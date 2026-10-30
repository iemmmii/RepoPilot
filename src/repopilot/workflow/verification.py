import hashlib
import shutil
import tempfile
from pathlib import Path

from pydantic import ValidationError

from repopilot.domain.errors import RepoPilotError
from repopilot.domain.evidence import EvidenceGraph, EvidenceNode
from repopilot.domain.models import Issue, Usage
from repopilot.domain.verification import Oracle, fingerprint
from repopilot.reporting.verification import render_verification
from repopilot.repository.materialize import (
    directory_digest,
    freeze_suite,
    materialize_repository,
)
from repopilot.repository.snapshot import _origin_slug
from repopilot.sandbox import harness
from repopilot.sandbox.docker import DockerRunner
from repopilot.storage.runs import RunStore, read_status
from repopilot.verification.gate import assess
from repopilot.verification.observations import observe


def _graph(store: RunStore, candidate: bool) -> EvidenceGraph:
    artifacts = {artifact.path: artifact.sha256 for artifact in store.manifest.artifacts}
    nodes = []

    def add(node_id, kind, artifact_path, dependencies=()):
        nodes.append(
            EvidenceNode(
                node_id=node_id,
                kind=kind,
                artifact_path=artifact_path,
                artifact_digest=artifacts[artifact_path],
                dependencies=list(dependencies),
            )
        )

    add("requirement", "requirement", "issue.json")
    add("suite", "suite", "suite.json")
    add("environment", "environment", "environment.json")
    add("oracle", "oracle", "oracle.json", ["requirement", "suite"])
    for name in ["base"] + (["candidate"] if candidate else []):
        add(name + "-source", "source", name + "-snapshot.json")
        add(
            name + "-command",
            "command",
            name + "-command.json",
            [name + "-source", "suite", "environment"],
        )
        add(
            name + "-observation",
            "observation",
            name + "-observation.json",
            [name + "-command", "oracle"],
        )
    add(
        "assessment",
        "assessment",
        "assessment.json",
        ["oracle", "base-observation"] + (["candidate-observation"] if candidate else []),
    )
    return EvidenceGraph(run_id=store.manifest.run_id, nodes=nodes)


def verify(
    *,
    issue: Issue,
    repository: Path,
    base_ref: str,
    candidate_ref: str | None,
    suite_path: Path,
    oracle_path: Path,
    output_root: Path,
    runner: DockerRunner,
) -> Path:
    scope = "verify_candidate" if candidate_ref is not None else "reproduce"
    store = RunStore(output_root, Usage(provider="none", requests=0), scope=scope)
    try:
        store.add("issue.json", issue)
        if oracle_path.stat().st_size > 32_000:
            raise RepoPilotError("invalid_oracle", "Oracle exceeds the input size limit.")
        try:
            oracle = Oracle.model_validate_json(oracle_path.read_bytes())
        except ValidationError as error:
            raise RepoPilotError(
                "invalid_oracle", "Oracle does not match the required schema."
            ) from error
        if oracle.issue_url != issue.url:
            raise RepoPilotError("oracle_issue_mismatch", "Oracle belongs to a different Issue.")
        origin = _origin_slug(repository)
        if origin and issue.repository and origin.casefold() != issue.repository.casefold():
            raise RepoPilotError(
                "repository_mismatch", "Issue repository and local origin disagree."
            )
        store.add("oracle.json", oracle)
        store.add("policy.json", runner.policy)
        # Only controller-generated files are created here. No target code runs on the host.
        with tempfile.TemporaryDirectory(prefix="execution-", dir=store.root) as temporary:
            work = Path(temporary)
            suite_root = work / "suite"
            suite = freeze_suite(suite_path, suite_root)
            if suite.suite_hash != oracle.suite_hash:
                raise RepoPilotError(
                    "suite_hash_mismatch", "Oracle does not bind these frozen test bytes."
                )
            store.add("suite.json", suite)
            runner_root = work / "runner"
            runner_root.mkdir()
            runner_root.chmod(0o755)
            harness_path = runner_root / "harness.py"
            shutil.copyfile(Path(harness.__file__), harness_path)
            harness_path.chmod(0o644)
            environment = runner.prepare(harness_path)
            store.add("environment.json", environment)
            snapshots = {}
            results = {}
            observations = {}
            for name, ref in [("base", base_ref)] + (
                [("candidate", candidate_ref)] if candidate_ref is not None else []
            ):
                source_root = work / name
                snapshot = materialize_repository(repository, ref, source_root)
                snapshots[name] = snapshot
                if name == "base":
                    store.manifest.base_commit = snapshot.commit
                store.add(name + "-snapshot.json", snapshot)
                before_suite = directory_digest(suite_root)
                if directory_digest(source_root) != snapshot.source_digest:
                    raise RepoPilotError(
                        "snapshot_changed", "Source changed before command execution."
                    )
                result = runner.run(
                    run_id=store.manifest.run_id,
                    source_digest=snapshot.source_digest,
                    suite_hash=suite.suite_hash,
                    environment=environment,
                    mounts={
                        "/workspace": source_root,
                        "/suite": suite_root,
                        "/runner": runner_root,
                    },
                    argv=["/usr/local/bin/python", "-I", "-B", "/runner/harness.py"],
                )
                store.manifest.tests_executed |= result.evidence.exit_code is not None
                result.evidence.stdout_artifact = name + "-stdout.log"
                result.evidence.stderr_artifact = name + "-stderr.log"
                result.evidence.stdout_sha256 = hashlib.sha256(result.stdout).hexdigest()
                result.evidence.stderr_sha256 = hashlib.sha256(result.stderr).hexdigest()
                store.add(name + "-stdout.log", result.stdout)
                store.add(name + "-stderr.log", result.stderr)
                store.add(name + "-command.json", result.evidence)
                observation = observe(result)
                if (
                    directory_digest(source_root) != snapshot.source_digest
                    or directory_digest(suite_root) != before_suite
                    or fingerprint(
                        {
                            path: (suite_root / path).read_bytes().decode("utf-8")
                            for path in suite.files
                        }
                    )
                    != suite.suite_hash
                ):
                    observation.protocol_valid = False
                    observation.problems.append("Execution input bytes changed during the command.")
                store.add(name + "-observation.json", observation)
                results[name] = result
                observations[name] = observation
                store.checkpoint()
                if result.evidence.termination == "interrupted":
                    raise RepoPilotError(
                        "verification_interrupted",
                        "Verification was interrupted; committed command evidence was retained.",
                    )
            if read_status(store.root)["artifact_integrity"] != "valid":
                raise RepoPilotError(
                    "evidence_corrupted", "Committed execution artifacts failed integrity checks."
                )
            assessment = assess(
                oracle=oracle,
                base=observations["base"],
                base_command=results["base"].evidence,
                candidate=observations.get("candidate"),
                candidate_command=results["candidate"].evidence if "candidate" in results else None,
                expected_base_digest=snapshots["base"].source_digest,
                expected_candidate_digest=snapshots["candidate"].source_digest
                if "candidate" in snapshots
                else None,
                suite_hash=suite.suite_hash,
                environment_digest=environment.environment_digest,
                requirement_digest=next(
                    artifact.sha256
                    for artifact in store.manifest.artifacts
                    if artifact.path == "issue.json"
                ),
            )
            store.add("assessment.json", assessment)
            store.add("graph.json", _graph(store, "candidate" in snapshots))
            store.add(
                "verification.md", render_verification(issue, snapshots, observations, assessment)
            )
            store.finish(outcome=assessment.outcome)
        return store.root
    except RepoPilotError as error:
        blocked = error.code.startswith("docker_") or error.code in {
            "image_digest_mismatch",
            "invalid_docker_metadata",
            "unsupported_engine",
            "remote_docker_rejected",
            "snapshot_changed",
        }
        store.finish(error=error, outcome="environment_blocked" if blocked else None)
        raise RepoPilotError(error.code, f"{error} Run: {store.root}") from error
    except KeyboardInterrupt as error:
        safe = RepoPilotError(
            "verification_interrupted", "Verification was interrupted before a complete assessment."
        )
        store.finish(error=safe)
        raise RepoPilotError(safe.code, f"{safe} Run: {store.root}") from error
    except Exception as error:
        safe = RepoPilotError(
            "verification_failed", "Verification stopped before a trustworthy assessment."
        )
        store.finish(error=safe)
        raise RepoPilotError(safe.code, f"{safe} Run: {store.root}") from error

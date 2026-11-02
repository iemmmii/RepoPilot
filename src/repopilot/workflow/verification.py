import hashlib
import json
import math
import shutil
import tempfile
from pathlib import Path

from pydantic import ValidationError

from repopilot.domain.errors import RepoPilotError
from repopilot.domain.evidence import EvidenceGraph, EvidenceNode
from repopilot.domain.models import Issue, Usage
from repopilot.domain.verification import (
    CommandEvidence,
    Oracle,
    TestObservation,
    VerificationAssessment,
    VerificationRequest,
    fingerprint,
)
from repopilot.reporting.verification import render_verification
from repopilot.repository.materialize import directory_digest, freeze_suite, materialize_repository
from repopilot.repository.snapshot import _origin_slug
from repopilot.sandbox import harness
from repopilot.sandbox.docker import DEFAULT_IMAGE, DockerRunner
from repopilot.storage.runs import read_status
from repopilot.storage.stages import VerificationStore
from repopilot.verification.gate import assess
from repopilot.verification.observations import observe


def _graph(store, candidate):
    artifacts = {artifact.path: artifact.sha256 for artifact in store.available_artifacts}
    nodes = []

    def add(identifier, kind, logical, dependencies=()):
        actual = store.artifact_name(logical)
        nodes.append(
            EvidenceNode(
                node_id=identifier,
                kind=kind,
                artifact_path=actual,
                artifact_digest=artifacts[actual],
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
    max_commands=6,
    _fault=None,
) -> Path:
    request = VerificationRequest(
        issue=issue,
        repository=str(repository.resolve()),
        base_ref=base_ref,
        candidate_ref=candidate_ref,
        suite_path=str(suite_path.resolve()),
        oracle_path=str(oracle_path.resolve()),
        image=getattr(runner, "image", DEFAULT_IMAGE),
        context=getattr(runner, "context", None),
        policy=runner.policy,
        max_commands=max_commands,
    )
    store = VerificationStore(
        output_root,
        Usage(provider="none", requests=0),
        "verify_candidate" if candidate_ref is not None else "reproduce",
    )
    try:
        store.manifest.command_limit = max_commands
        store.add("request.json", request)
        return _execute(store, request, runner, False, _fault)
    finally:
        store.release()


def resume(root: Path, *, runner=None, _fault=None) -> Path:
    store = VerificationStore(None, None, None, resume_root=root)
    try:
        request = VerificationRequest.model_validate_json(store.read("request.json"))
        command_stages = sum(stage.name in {"base", "candidate"} for stage in store.manifest.stages)
        if (
            store.manifest.command_limit != request.max_commands
            or store.manifest.command_attempts != command_stages
            or not math.isclose(
                store.manifest.reserved_seconds, command_stages * request.policy.timeout_seconds
            )
        ):
            raise RepoPilotError(
                "budget_checkpoint_invalid", "Saved budget and stage reservations disagree."
            )
        runner = runner or DockerRunner(
            image=request.image, policy=request.policy, context=request.context
        )
        if runner.policy != request.policy:
            raise RepoPilotError(
                "resume_inputs_changed", "Runner policy differs from the saved request."
            )
        return _execute(store, request, runner, True, _fault)
    finally:
        store.release()


def _execute(store, request, runner, resuming, fault):
    resumed_started = False

    def inject(point):
        if fault:
            fault(point)

    try:
        repository = Path(request.repository)
        path = Path(request.oracle_path)
        if path.stat().st_size > 32_000:
            raise RepoPilotError("invalid_oracle", "Oracle exceeds the input size limit.")
        try:
            oracle = Oracle.model_validate_json(path.read_bytes())
        except ValidationError as error:
            raise RepoPilotError("invalid_oracle", "Oracle does not match the schema.") from error
        if oracle.issue_url != request.issue.url:
            raise RepoPilotError("oracle_issue_mismatch", "Oracle belongs to another Issue.")
        origin = _origin_slug(repository)
        if (
            origin
            and request.issue.repository
            and origin.casefold() != request.issue.repository.casefold()
        ):
            raise RepoPilotError(
                "repository_mismatch", "Issue repository and local origin disagree."
            )
        with tempfile.TemporaryDirectory(prefix="execution-", dir=store.root) as temporary:
            work = Path(temporary)
            suite_root = work / "suite"
            suite = freeze_suite(Path(request.suite_path), suite_root)
            if suite.suite_hash != oracle.suite_hash:
                raise RepoPilotError(
                    "suite_hash_mismatch", "Oracle does not bind these frozen test bytes."
                )
            runner_root = work / "runner"
            runner_root.mkdir()
            runner_root.chmod(0o755)
            adapter = runner_root / "harness.py"
            shutil.copyfile(harness.__file__, adapter)
            adapter.chmod(0o644)
            environment = runner.prepare(adapter)
            snapshots = {}
            for name, ref in [("base", request.base_ref)] + (
                [("candidate", request.candidate_ref)] if request.candidate_ref is not None else []
            ):
                snapshots[name] = materialize_repository(repository, ref, work / name)
            inputs = {
                "issue": request.issue.model_dump(mode="json"),
                "oracle": oracle.model_dump(),
                "suite": suite.suite_hash,
                "environment": environment.environment_digest,
                "policy": runner.policy.model_dump(),
                "sources": {name: snapshot.model_dump() for name, snapshot in snapshots.items()},
            }
            digest = fingerprint(inputs)
            if resuming:
                previous = [
                    stage
                    for stage in store.manifest.stages
                    if stage.name == "inputs" and stage.status == "succeeded"
                ]
                if previous and previous[-1].input_fingerprint != digest:
                    raise RepoPilotError(
                        "resume_inputs_changed",
                        "Current inputs differ; old evidence is historical and a new Run is required.",
                    )
                store.recover(runner)
                resumed_started = True
            if not store.reusable("inputs", digest):
                store.begin("inputs", digest)
                for name, value in (
                    ("issue.json", request.issue),
                    ("oracle.json", oracle),
                    ("policy.json", runner.policy),
                    ("suite.json", suite),
                    ("environment.json", environment),
                ):
                    store.add(name, value)
                store.add("inputs.json", json.dumps(inputs, sort_keys=True, indent=2))
                store.commit_stage()
            observations, commands = {}, {}
            for name, snapshot in snapshots.items():
                stage_digest = fingerprint(
                    {"inputs": digest, "stage": name, "source": snapshot.source_digest}
                )
                if store.reusable(name, stage_digest):
                    commands[name] = CommandEvidence.model_validate_json(
                        store.read(name + "-command.json")
                    )
                    observations[name] = TestObservation.model_validate_json(
                        store.read(name + "-observation.json")
                    )
                    continue
                store.begin(name, stage_digest, command_seconds=runner.policy.timeout_seconds)
                store.add(name + "-snapshot.json", snapshot)
                if name == "base":
                    store.manifest.base_commit = snapshot.commit
                source = work / name
                before_suite = directory_digest(suite_root)
                if directory_digest(source) != snapshot.source_digest:
                    raise RepoPilotError("snapshot_changed", "Source changed before execution.")
                result = runner.run(
                    run_id=store.manifest.run_id,
                    source_digest=snapshot.source_digest,
                    suite_hash=suite.suite_hash,
                    environment=environment,
                    mounts={"/workspace": source, "/suite": suite_root, "/runner": runner_root},
                    argv=["/usr/local/bin/python", "-I", "-B", "/runner/harness.py"],
                    container_registered=store.register_container,
                )
                inject(name + ":after_command")
                store.manifest.tests_executed |= result.evidence.exit_code is not None
                for stream in ("stdout", "stderr"):
                    raw = getattr(result, stream)
                    logical = name + "-" + stream + ".log"
                    setattr(result.evidence, stream + "_artifact", store.target_name(logical))
                    setattr(result.evidence, stream + "_sha256", hashlib.sha256(raw).hexdigest())
                    store.add(logical, raw)
                store.add(name + "-command.json", result.evidence)
                observation = observe(result)
                if (
                    directory_digest(source) != snapshot.source_digest
                    or directory_digest(suite_root) != before_suite
                ):
                    observation.protocol_valid = False
                    observation.problems.append("Execution inputs changed during the command.")
                store.add(name + "-observation.json", observation)
                inject(name + ":before_commit")
                store.commit_stage(
                    succeeded=result.evidence.termination == "exited"
                    and result.evidence.cleanup_succeeded
                )
                inject(name + ":after_commit")
                commands[name], observations[name] = result.evidence, observation
                if result.evidence.termination == "interrupted":
                    raise RepoPilotError(
                        "verification_interrupted", "Command interrupted; evidence retained."
                    )
            if read_status(store.root)["artifact_integrity"] != "valid":
                raise RepoPilotError(
                    "evidence_corrupted", "Committed artifacts failed integrity checks."
                )
            assessment_digest = fingerprint(
                {
                    "inputs": digest,
                    "commands": {
                        name: cmd.model_dump(mode="json") for name, cmd in commands.items()
                    },
                }
            )
            if store.reusable("assess", assessment_digest):
                assessment = VerificationAssessment.model_validate_json(
                    store.read("assessment.json")
                )
            else:
                store.begin("assess", assessment_digest)
                assessment = assess(
                    oracle=oracle,
                    base=observations["base"],
                    base_command=commands["base"],
                    candidate=observations.get("candidate"),
                    candidate_command=commands.get("candidate"),
                    expected_base_digest=snapshots["base"].source_digest,
                    expected_candidate_digest=snapshots["candidate"].source_digest
                    if "candidate" in snapshots
                    else None,
                    suite_hash=suite.suite_hash,
                    environment_digest=environment.environment_digest,
                    requirement_digest=next(
                        a.sha256
                        for a in store.available_artifacts
                        if a.path == store.artifact_name("issue.json")
                    ),
                )
                store.add("assessment.json", assessment)
                store.add("graph.json", _graph(store, "candidate" in snapshots))
                store.add(
                    "verification.md",
                    render_verification(request.issue, snapshots, observations, assessment),
                )
                inject("assess:before_commit")
                store.commit_stage()
                inject("assess:after_commit")
            store.finish(outcome=assessment.outcome)
        return store.root
    except RepoPilotError as error:
        if resuming and not resumed_started:
            raise
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
            "verification_interrupted", "Verification interrupted before a complete assessment."
        )
        store.finish(error=safe)
        raise RepoPilotError(safe.code, f"{safe} Run: {store.root}") from error
    except Exception as error:
        safe = RepoPilotError(
            "verification_failed", "Verification stopped before a trustworthy assessment."
        )
        store.finish(error=safe)
        raise RepoPilotError(safe.code, f"{safe} Run: {store.root}") from error

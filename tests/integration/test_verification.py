import json
import subprocess
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from repopilot.cli import main
from repopilot.domain.errors import RepoPilotError
from repopilot.domain.models import Issue
from repopilot.domain.verification import (
    CommandEvidence,
    ExecutionEnvironment,
    SandboxPolicy,
    fingerprint,
)
from repopilot.sandbox.docker import DEFAULT_IMAGE, CommandResult
from repopilot.storage.runs import read_status
from repopilot.workflow.verification import verify


class ControlledRunner:
    policy = SandboxPolicy()

    def prepare(self, harness):
        return ExecutionEnvironment(
            image_ref=DEFAULT_IMAGE,
            image_id="sha256:fixture",
            os="linux",
            architecture="amd64",
            engine_version="controlled",
            kernel_version="controlled",
            policy_digest="policy",
            harness_digest="harness",
            runner_digest="runner",
            environment_digest="environment",
        )

    def run(self, **kwargs):
        root = kwargs["mounts"]["/workspace"]
        assert not (root / ".env").exists() and not (root / ".git").exists()
        assert set(kwargs["mounts"]) == {"/workspace", "/suite", "/runner"}
        failed = "return 500" in (root / "auth.py").read_text(encoding="utf-8")
        payload = {
            "protocol": "repopilot-unittest-v1",
            "tests_run": 2,
            "tests": [
                {
                    "test_id": "test_auth.Repro.test_expired",
                    "status": "failed" if failed else "passed",
                },
                {"test_id": "test_auth.Repro.test_current", "status": "passed"},
            ],
        }
        stdout = json.dumps(payload).encode()
        now = datetime.now(UTC)
        evidence = CommandEvidence(
            evidence_id=uuid4().hex,
            run_id=kwargs["run_id"],
            argv=kwargs["argv"],
            source_digest=kwargs["source_digest"],
            suite_hash=kwargs["suite_hash"],
            environment_digest=kwargs["environment"].environment_digest,
            started_at=now,
            ended_at=now,
            exit_code=1 if failed else 0,
            termination="exited",
            stdout_bytes=len(stdout),
            stderr_bytes=0,
            logs_truncated=False,
            cleanup_succeeded=True,
        )
        return CommandResult(evidence, stdout, b"")


@pytest.fixture
def verification_case(repository, tmp_path):
    def git(*args):
        return subprocess.check_output(
            [
                "git",
                "-c",
                "core.hooksPath=",
                "-c",
                "commit.gpgsign=false",
                "-C",
                str(repository),
                *args,
            ],
            text=True,
        ).strip()

    base = git("rev-parse", "HEAD")
    path = repository / "auth.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace("return 500", "return 401"), encoding="utf-8"
    )
    git("add", "auth.py")
    git("commit", "-m", "controlled candidate")
    candidate = git("rev-parse", "HEAD")
    suite = tmp_path / "oracle-suite"
    suite.mkdir()
    files = {"test_auth.py": "# controlled transport fixture; never imported on host\n"}
    (suite / "test_auth.py").write_bytes(files["test_auth.py"].encode("utf-8"))
    issue = Issue(
        title="Expired credentials return 500",
        repository="example/demo",
        url="https://github.com/example/demo/issues/1",
    )
    oracle = tmp_path / "oracle.json"
    oracle.write_text(
        json.dumps(
            {
                "criterion_id": "AC-1",
                "requirement": "Reject expired credentials with 401.",
                "issue_url": issue.url,
                "source_refs": ["controlled independent protocol"],
                "suite_hash": fingerprint(files),
                "target_tests": ["test_auth.Repro.test_expired"],
                "regression_tests": ["test_auth.Repro.test_current"],
                "assessment_status": "accepted",
                "assessed_by": "controlled protocol fixture",
                "assessment_basis": "Fixed independent expected response; not inferred from candidate output.",
            }
        ),
        encoding="utf-8",
    )
    return dict(
        issue=issue,
        repository=repository,
        base_ref=base,
        candidate_ref=candidate,
        suite_path=suite,
        oracle_path=oracle,
        output_root=tmp_path / "runs",
        runner=ControlledRunner(),
    )


def test_fixed_ref_verification_commits_bound_evidence_and_graph(verification_case):
    root = verify(**verification_case)
    status = read_status(root)
    assert status["outcome"] == "candidate_verified"
    assert status["requested_scope"] == "verify_candidate" and status["schema_version"] == "0.2"
    assert status["artifact_integrity"] == status["graph_integrity"] == "valid"
    assert status["usage"]["requests"] == 0 and status["tests_executed"] is True
    assert not (verification_case["repository"] / "IMPORT_MUST_NOT_RUN").exists()
    assert not list(root.glob("execution-*"))
    assert not (root / ".writer.lock").exists()
    assert "not model-generated repair" in (root / "verification.md").read_text(encoding="utf-8")


def test_provisional_oracle_does_not_gain_acceptance_from_success(verification_case):
    path = verification_case["oracle_path"]
    data = json.loads(path.read_bytes())
    data["assessment_status"] = "provisional"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert read_status(verify(**verification_case))["outcome"] == "needs_human"


def test_suite_edits_require_a_new_oracle_revision(verification_case):
    (verification_case["suite_path"] / "test_auth.py").write_text("changed\n", encoding="utf-8")
    with pytest.raises(RepoPilotError) as caught:
        verify(**verification_case)
    assert caught.value.code == "suite_hash_mismatch"
    manifest = next(verification_case["output_root"].glob("*/manifest.json"))
    saved = json.loads(manifest.read_bytes())
    assert saved["execution_status"] == "failed" and saved["tests_executed"] is False


def test_environment_failure_is_persisted_without_success(verification_case):
    class Unavailable(ControlledRunner):
        def prepare(self, harness):
            raise RepoPilotError("docker_unavailable", "Controlled unavailable runtime.")

    verification_case["runner"] = Unavailable()
    with pytest.raises(RepoPilotError):
        verify(**verification_case)
    root = next(verification_case["output_root"].iterdir())
    status = read_status(root)
    assert status["outcome"] == "environment_blocked"
    assert status["execution_status"] == "failed"
    assert not (root / "assessment.json").exists()


def test_source_changed_during_execution_is_rejected(verification_case):
    class Changed(ControlledRunner):
        def run(self, **kwargs):
            result = super().run(**kwargs)
            (kwargs["mounts"]["/workspace"] / "unexpected.py").write_text(
                "changed", encoding="utf-8"
            )
            return result

    verification_case["runner"] = Changed()
    assert read_status(verify(**verification_case))["outcome"] == "environment_blocked"


def test_reproduction_does_not_run_candidate(verification_case):
    verification_case["candidate_ref"] = None
    root = verify(**verification_case)
    assert read_status(root)["outcome"] == "reproduced"
    assert not (root / "candidate-command.json").exists()


def test_unchanged_source_with_conflicting_observations_is_unstable(verification_case):
    selected = verification_case["runner"]
    real_run = selected.run
    calls = []

    def inconsistent(**kwargs):
        result = real_run(**kwargs)
        if calls:
            payload = json.loads(result.stdout)
            payload["tests"][0]["status"] = "passed"
            result.stdout = json.dumps(payload).encode()
            result.evidence.exit_code = 0
        calls.append(True)
        return result

    selected.run = inconsistent
    verification_case["candidate_ref"] = verification_case["base_ref"]
    root = verify(**verification_case)
    assessment = json.loads((root / "assessment.json").read_bytes())
    assert assessment["outcome"] == "needs_human" and assessment["stability"] == "unstable"


def test_status_rejects_a_rehashed_cross_run_graph(verification_case):
    import hashlib

    root = verify(**verification_case)
    graph_path = root / "graph.json"
    graph = json.loads(graph_path.read_bytes())
    graph["run_id"] = "another-run"
    raw = json.dumps(graph).encode()
    graph_path.write_bytes(raw)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for artifact in manifest["artifacts"]:
        if artifact["path"] == "graph.json":
            artifact.update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert read_status(root)["artifact_integrity"] == "unverifiable"


def test_cli_has_explicit_execution_scope(verification_case, monkeypatch, capsys):
    import repopilot.cli as cli

    issue_file = verification_case["oracle_path"].parent / "issue.json"
    issue_file.write_text(verification_case["issue"].model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(cli, "DockerRunner", lambda **kwargs: verification_case["runner"])
    assert (
        main(
            [
                "verify-candidate",
                "--issue-file",
                str(issue_file),
                "--repo",
                str(verification_case["repository"]),
                "--base-ref",
                verification_case["base_ref"],
                "--candidate-ref",
                verification_case["candidate_ref"],
                "--suite",
                str(verification_case["suite_path"]),
                "--oracle",
                str(verification_case["oracle_path"]),
                "--output-dir",
                str(verification_case["output_root"]),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["outcome"] == "candidate_verified"

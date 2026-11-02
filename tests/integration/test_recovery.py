import json
import subprocess
import sys
from pathlib import Path

import pytest
import test_verification as helpers

from repopilot.domain.errors import RepoPilotError
from repopilot.storage.lease import RunLease
from repopilot.storage.runs import read_status
from repopilot.workflow.verification import resume, verify

ControlledRunner = helpers.ControlledRunner


@pytest.fixture
def verification_case(repository, tmp_path):
    return helpers.verification_case.__wrapped__(repository, tmp_path)


@pytest.mark.parametrize(
    "point,commands",
    [
        ("base:after_command", 3),
        ("base:before_commit", 3),
        ("base:after_commit", 2),
        ("assess:after_commit", 2),
    ],
)
def test_real_process_exit_respects_stage_commit(verification_case, point, commands, tmp_path):
    options = {
        key: (
            value.model_dump(mode="json")
            if key == "issue"
            else str(value)
            if isinstance(value, Path)
            else value
        )
        for key, value in verification_case.items()
        if key != "runner"
    }
    source = tmp_path / "options.json"
    source.write_text(json.dumps(options), encoding="utf-8")
    script = """
import json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'tests/integration'))
from test_verification import ControlledRunner
from repopilot.domain.models import Issue
from repopilot.workflow.verification import verify
options=json.loads(Path(sys.argv[1]).read_bytes())
options['issue']=Issue.model_validate(options['issue'])
for key in ('repository','suite_path','oracle_path','output_root'):
    options[key]=Path(options[key])
options['runner']=ControlledRunner()
verify(**options,_fault=lambda point: os._exit(91) if point==sys.argv[2] else None)
"""
    stopped = subprocess.run(
        [sys.executable, "-c", script, str(source), point], capture_output=True, timeout=30
    )
    assert stopped.returncode == 91, stopped.stderr.decode(errors="replace")
    root = next(verification_case["output_root"].iterdir())
    before = read_status(root)
    assert before["execution_status"] == "running"
    if point == "base:before_commit":
        assert "base-command.json" in before["orphan_artifacts"]
        assert not any(a["path"] == "base-command.json" for a in before["artifacts"])
    resume(root, runner=ControlledRunner())
    status = read_status(root)
    assert status["outcome"] == "candidate_verified" and status["graph_integrity"] == "valid"
    assert status["command_attempts"] == commands
    assert status["reserved_seconds"] == commands * 60
    command_ids = [a["path"] for a in status["artifacts"] if a["path"].endswith("-command.json")]
    assert len(command_ids) == 2
    assert all(s["status"] != "running" for s in status["stages"])


def test_completed_resume_does_not_execute_or_spend_budget(verification_case):
    root = verify(**verification_case)
    old = read_status(root)

    class NoCommands(ControlledRunner):
        def run(self, **kwargs):
            raise AssertionError("Committed commands must not run again")

    resume(root, runner=NoCommands())
    current = read_status(root)
    assert current["command_attempts"] == old["command_attempts"] == 2
    assert current["artifacts"] == old["artifacts"]


def test_resume_rejects_changed_inputs_without_rewriting_history(verification_case):
    root = verify(**verification_case)
    before = (root / "manifest.json").read_bytes()
    source = verification_case["oracle_path"]
    value = json.loads(source.read_bytes())
    value["assessment_basis"] += " changed requirement review"
    source.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RepoPilotError) as caught:
        resume(root, runner=ControlledRunner())
    assert caught.value.code == "resume_inputs_changed"
    assert (root / "manifest.json").read_bytes() == before


def test_resume_refuses_corrupt_artifact(verification_case):
    root = verify(**verification_case)
    (root / "base-stdout.log").write_bytes(b"tampered")
    with pytest.raises(RepoPilotError) as caught:
        resume(root, runner=ControlledRunner())
    assert caught.value.code == "evidence_corrupted"
    assert read_status(root)["artifact_integrity"] == "unverifiable"


def test_command_budget_is_persistent_and_not_reset_by_resume(verification_case):
    with pytest.raises(RepoPilotError):
        verify(**verification_case, max_commands=1)
    root = next(verification_case["output_root"].iterdir())
    assert read_status(root)["execution_status"] == "budget_exhausted"
    with pytest.raises(RepoPilotError) as caught:
        resume(root, runner=ControlledRunner())
    assert caught.value.code == "budget_exhausted"
    assert read_status(root)["command_attempts"] == 1


def test_kernel_lease_is_not_stolen_or_unlinked(tmp_path):
    lease = RunLease(tmp_path)
    try:
        with pytest.raises(RepoPilotError) as caught:
            RunLease(tmp_path)
        assert caught.value.code == "run_locked"
        assert (tmp_path / ".run.lock").exists()
    finally:
        lease.close()
    replacement = RunLease(tmp_path)
    replacement.close()


def test_failed_attempt_cleanup_precedes_retry_and_new_graph(verification_case):
    class Leaking(ControlledRunner):
        calls = 0
        cleaned = []
        retrying = False

        def cleanup_registered(self, name):
            self.cleaned.append(name)

        def run(self, **kwargs):
            if self.retrying:
                assert self.cleaned
            result = super().run(**kwargs)
            if self.calls == 0:
                kwargs["container_registered"]("repopilot-command-" + "a" * 32)
                result.evidence.cleanup_succeeded = False
            self.calls += 1
            return result

    selected = Leaking()
    verification_case["runner"] = selected
    root = verify(**verification_case)
    assert read_status(root)["outcome"] == "environment_blocked"
    selected.retrying = True
    resume(root, runner=selected)
    status = read_status(root)
    assert status["outcome"] == "candidate_verified" and status["graph_integrity"] == "valid"
    assert status["command_attempts"] == 3
    assert status["graph_artifact"] != "graph.json"

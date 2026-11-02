"""Real Docker crash points, separate from offline stage recovery tests."""

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from repopilot.evaluation.controlled import build_case
from repopilot.sandbox.docker import DockerRunner
from repopilot.storage.runs import read_status
from repopilot.workflow.verification import resume

pytestmark = pytest.mark.skipif(
    os.environ.get("REPOPILOT_DOCKER_TESTS") != "1",
    reason="Requires the pinned Docker image and local engine.",
)


@pytest.mark.parametrize(
    "point,expected_commands",
    [("base:after_command", 3), ("base:before_commit", 3), ("base:after_commit", 2)],
)
def test_real_docker_process_crash_and_resume(tmp_path, point, expected_commands):
    fixture = build_case(tmp_path / "case", "C01")
    options = {
        key: value.model_dump(mode="json")
        if key == "issue"
        else str(value)
        if isinstance(value, Path)
        else value
        for key, value in fixture["options"].items()
    }
    config = tmp_path / "options.json"
    config.write_bytes(json.dumps(options).encode())
    script = """
import json,os,sys
from pathlib import Path
from repopilot.domain.models import Issue
from repopilot.sandbox.docker import DockerRunner
from repopilot.workflow.verification import verify
options=json.loads(Path(sys.argv[1]).read_bytes())
options['issue']=Issue.model_validate(options['issue'])
for key in ('repository','suite_path','oracle_path','output_root'):
    options[key]=Path(options[key])
verify(**options,runner=DockerRunner(),_fault=lambda p:os._exit(91) if p==sys.argv[2] else None)
"""
    stopped = subprocess.run(
        [sys.executable, "-c", script, str(config), point], capture_output=True, timeout=45
    )
    assert stopped.returncode == 91, stopped.stderr.decode(errors="replace")
    root = next(fixture["options"]["output_root"].iterdir())
    before = read_status(root)
    assert before["execution_status"] == "running"
    resume(root)
    after = read_status(root)
    assert after["outcome"] == "candidate_verified" and after["graph_integrity"] == "valid"
    assert after["command_attempts"] == expected_commands
    assert after["stages"][1]["container_name"].startswith("repopilot-command-")
    if point == "base:before_commit":
        assert "base-command.json" in after["orphan_artifacts"]


def test_registered_running_container_cleanup_checks_owner(tmp_path):
    runner = DockerRunner()
    mounts = {}
    for name in ("workspace", "suite", "runner"):
        path = tmp_path / name
        path.mkdir()
        path.chmod(0o755)
        mounts["/" + name] = path
    name = "repopilot-command-" + uuid4().hex
    try:
        runner._control(
            *runner.create_arguments(
                name, mounts, ["/usr/local/bin/python", "-c", "import time; time.sleep(60)"]
            )
        )
        runner._control("start", name)
        runner.cleanup_registered(name)
        assert not runner._control(
            "ps", "--all", "--filter", "name=" + name, "--format", "{{.Names}}"
        ).strip()
    finally:
        runner._control("rm", "--force", name)

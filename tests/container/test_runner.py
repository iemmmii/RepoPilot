"""Opt-in real Docker tests; image preparation is explicit and outside the runner."""

import json
import os
import shutil
from pathlib import Path

import pytest

from repopilot.domain.errors import RepoPilotError
from repopilot.domain.verification import SandboxPolicy
from repopilot.sandbox import harness
from repopilot.sandbox.docker import DockerRunner
from repopilot.verification.observations import observe

pytestmark = pytest.mark.skipif(
    os.environ.get("REPOPILOT_DOCKER_TESTS") != "1",
    reason="Set REPOPILOT_DOCKER_TESTS=1 with the pinned image cached to run real containers.",
)


@pytest.fixture
def execution(tmp_path):
    mounts = {}
    for name in ("workspace", "suite", "runner"):
        path = tmp_path / name
        path.mkdir()
        path.chmod(0o755)
        mounts["/" + name] = path
    adapter = mounts["/runner"] / "harness.py"
    shutil.copyfile(harness.__file__, adapter)
    adapter.chmod(0o644)
    return mounts


def run(execution, code, *, policy=None):
    runner = DockerRunner(policy=policy)
    environment = runner.prepare(execution["/runner"] / "harness.py")
    result = runner.run(
        run_id="controlled-container-test",
        source_digest="controlled-source",
        suite_hash="controlled-suite",
        environment=environment,
        mounts=execution,
        argv=["/usr/local/bin/python", "-I", "-B", "-c", code],
    )
    return runner, result


def test_real_restrictions_and_controller_input_mounts(execution, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "controlled-sentinel-never-forward")
    code = """
import errno,json,os,socket
from pathlib import Path
assert os.getuid()==65534
for root in ('/workspace','/suite','/runner',''):
    try:
        Path(root+'/must-not-write').write_text('no')
    except OSError as error:
        assert error.errno==errno.EROFS
    else:
        raise AssertionError('input was writable')
assert not os.environ.get('DEEPSEEK_API_KEY')
for path in ('/mnt/c','/mnt/d','/var/run/docker.sock','/run/desktop/mnt/host'):
    assert not Path(path).exists()
assert {name for _,name in socket.if_nameindex()}=={'lo'}
fields=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
assert int(fields['CapEff'].strip(),16)==int(fields['CapBnd'].strip(),16)==0
assert fields['NoNewPrivs'].strip()=='1' and fields['Seccomp'].strip()=='2'
assert int(Path('/sys/fs/cgroup/memory.max').read_text())==268435456
assert int(Path('/sys/fs/cgroup/pids.max').read_text())==64
quota,period=Path('/sys/fs/cgroup/cpu.max').read_text().split()
assert quota==period
print(json.dumps({'restrictions':'passed'}))
"""
    _, result = run(execution, code)
    assert result.evidence.termination == "exited" and result.evidence.exit_code == 0
    assert result.evidence.cleanup_succeeded
    assert json.loads(result.stdout) == {"restrictions": "passed"}


def test_real_timeout_removes_container_and_child(execution):
    code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); time.sleep(60)"
    _, result = run(execution, code, policy=SandboxPolicy(timeout_seconds=1.5))
    assert result.evidence.termination == "timed_out"
    assert result.evidence.exit_code != 0 and result.evidence.cleanup_succeeded


def test_real_output_limit_keeps_bounded_logs(execution):
    _, result = run(
        execution,
        "import os,time; os.write(1,b'x'*65536); time.sleep(30)",
        policy=SandboxPolicy(output_limit_bytes=4096),
    )
    assert result.evidence.termination == "output_limit"
    assert result.evidence.logs_truncated and result.evidence.stdout_bytes > 4096
    assert len(result.stdout) + len(result.stderr) <= 4096
    assert result.evidence.cleanup_succeeded


@pytest.mark.parametrize(
    "test_source,expected",
    [
        ("import dependency_that_does_not_exist\n", "error"),
        (
            "import unittest\n@unittest.skip('controlled skip')\nclass Repro(unittest.TestCase):\n def test_target(self): pass\n",
            "skipped",
        ),
    ],
)
def test_real_adapter_does_not_turn_import_errors_or_skips_into_failures(
    execution, test_source, expected
):
    (execution["/suite"] / "test_bad.py").write_text(test_source, encoding="utf-8")
    (execution["/suite"] / "test_bad.py").chmod(0o644)
    runner = DockerRunner()
    environment = runner.prepare(execution["/runner"] / "harness.py")
    result = runner.run(
        run_id="controlled-adapter-test",
        source_digest="source",
        suite_hash="suite",
        environment=environment,
        mounts=execution,
        argv=["/usr/local/bin/python", "-I", "-B", "/runner/harness.py"],
    )
    observation = observe(result)
    assert observation.protocol_valid and observation.tests[0].status == expected
    assert result.evidence.cleanup_succeeded


def test_real_empty_adapter_result_is_explicit(execution):
    runner = DockerRunner()
    environment = runner.prepare(execution["/runner"] / "harness.py")
    result = runner.run(
        run_id="controlled-empty-test",
        source_digest="source",
        suite_hash="suite",
        environment=environment,
        mounts=execution,
        argv=["/usr/local/bin/python", "-I", "-B", "/runner/harness.py"],
    )
    observation = observe(result)
    assert observation.protocol_valid and observation.tests == []
    assert result.evidence.cleanup_succeeded


def test_real_interrupt_is_recorded_and_cleaned(execution, monkeypatch):
    from repopilot.sandbox import docker

    original_capture = docker._Capture

    class InterruptCapture(original_capture):
        def __init__(self, limit):
            super().__init__(limit)

            def interrupt(timeout=None):
                raise KeyboardInterrupt

            self.exceeded.wait = interrupt

    monkeypatch.setattr(docker, "_Capture", InterruptCapture)
    _, result = run(execution, "import time; time.sleep(30)")
    assert result.evidence.termination == "interrupted" and result.evidence.cleanup_succeeded


def test_suite_has_no_host_mount_escape(execution):
    # Mount policy is checked again by the product, even for an internal caller.
    runner = DockerRunner()
    with pytest.raises(RepoPilotError):
        runner.create_arguments("controlled", {**execution, "/host": Path.cwd()}, ["/bin/sh"])

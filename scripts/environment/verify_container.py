"""Verify a local Linux container runtime with a controlled, restricted Python probe."""

import argparse
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

PROBE = """
import errno, json, os, socket
from pathlib import Path
assert os.getuid() != 0, 'container must run as a non-root user'
assert Path('/workspace/probe.txt').read_text() == 'repopilot-environment-probe'
try:
    Path('/workspace/not-allowed').write_text('no')
except OSError as error:
    assert error.errno == errno.EROFS, 'workspace must be a read-only mount'
else:
    raise AssertionError('workspace must be read-only')
try:
    Path('/rootfs-write-probe').write_text('no')
except OSError as error:
    assert error.errno == errno.EROFS, 'root filesystem must be a read-only mount'
else:
    raise AssertionError('root filesystem must be read-only')
assert not Path('/var/run/docker.sock').exists(), 'Docker socket must not be mounted'
assert not Path('/mnt/c').exists() and not Path('/mnt/d').exists(), 'host drives must not be mounted'
assert not any(os.environ.get(k) for k in ('DEEPSEEK_API_KEY', 'OPENAI_API_KEY', 'GITHUB_TOKEN'))
status = Path('/proc/self/status').read_text()
fields = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
assert int(fields['CapEff'].strip(), 16) == 0, 'capabilities must be dropped'
assert int(fields['CapBnd'].strip(), 16) == 0, 'capability bounding set must be empty'
assert fields['NoNewPrivs'].strip() == '1', 'no-new-privileges must be enabled'
assert fields['Seccomp'].strip() == '2', 'seccomp filtering must be active'
cgroup = Path('/sys/fs/cgroup')
assert int((cgroup / 'memory.max').read_text()) == 268435456, 'memory limit must be active'
assert int((cgroup / 'pids.max').read_text()) == 64, 'PID limit must be active'
quota, period = (cgroup / 'cpu.max').read_text().split()
assert int(quota) == int(period), 'CPU quota must be one CPU'
assert {name for _, name in socket.if_nameindex()} == {'lo'}, 'only loopback may be present'
sock = socket.socket()
sock.settimeout(1)
try:
    sock.connect(('1.1.1.1', 443))
except OSError:
    pass
else:
    raise AssertionError('network must be disabled')
finally:
    sock.close()
print(json.dumps({'uid': os.getuid(), 'workspace_read_only': True, 'rootfs_read_only': True,
    'network_disabled': True, 'capabilities_dropped': True, 'no_new_privileges': True,
    'host_credentials_absent': True, 'docker_socket_absent': True, 'host_drives_absent': True,
    'capability_bounding_set_empty': True, 'seccomp_active': True,
    'cgroup_limits_verified': True, 'only_loopback': True}))
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", default=shutil.which("docker"))
    parser.add_argument("--context", default="desktop-linux")
    parser.add_argument(
        "--output", type=Path, default=Path(".repopilot/environment/container-verification.json")
    )
    args = parser.parse_args()
    if not args.docker:
        parser.error("Docker CLI not found; provide --docker with the installed executable path.")
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    fixture = output.parent / ("smoke-fixture-" + uuid4().hex)
    fixture.mkdir()
    (fixture / "probe.txt").write_text("repopilot-environment-probe", encoding="utf-8")
    name = "repopilot-env-smoke-" + uuid4().hex
    result = {"checked_at": datetime.now(UTC).isoformat(), "status": "failed"}
    command_prefix = [args.docker, "--context", args.context]
    child_environment = os.environ.copy()
    child_environment["PATH"] = (
        str(Path(args.docker).resolve().parent) + os.pathsep + child_environment.get("PATH", "")
    )
    result["context"] = args.context

    def call(*arguments: str, timeout: int = 30):
        result["step"] = arguments[0]
        return subprocess.run(
            [*command_prefix, *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=True,
            env=child_environment,
        ).stdout

    try:
        server = json.loads(call("version", "--format", "{{json .Server}}"))
        if server.get("Os") != "linux":
            raise RuntimeError("A Linux container backend is required.")
        result["server"] = {key: server.get(key) for key in ("Version", "Os", "Arch")}
        image = "python:3.13-slim"
        call("pull", image, timeout=300)
        digests = json.loads(call("image", "inspect", image, "--format", "{{json .RepoDigests}}"))
        if not digests or not digests[0].startswith("python@sha256:"):
            raise RuntimeError("The Python image did not resolve to a pinned digest.")
        result["image"] = digests[0]
        command = [
            "run",
            "--rm",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--user",
            "65534:65534",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--cpus",
            "1",
            "--memory",
            "256m",
            "--memory-swap",
            "256m",
            "--pids-limit",
            "64",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=32m",
            "--mount",
            f"type=bind,source={fixture},target=/workspace,readonly",
            "--workdir",
            "/workspace",
            digests[0],
            "python",
            "-c",
            PROBE,
        ]
        result["checks"] = json.loads(call(*command, timeout=30))
        result["limits"] = {"cpus": 1, "memory_bytes": 268435456, "pids": 64}
        result["status"] = "passed"
        result["step"] = "complete"
    except (subprocess.SubprocessError, OSError, ValueError, RuntimeError) as error:
        result["error_type"] = type(error).__name__
        result["error"] = "Container verification did not complete; inspect the local runtime."
    finally:
        try:
            cleanup = subprocess.run(
                [*command_prefix, "rm", "--force", name],
                capture_output=True,
                timeout=30,
                check=False,
                env=child_environment,
            )
            result["cleanup_exit_code"] = cleanup.returncode
        except (subprocess.SubprocessError, OSError) as error:
            result["cleanup_error_type"] = type(error).__name__
            result["status"] = "failed"
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

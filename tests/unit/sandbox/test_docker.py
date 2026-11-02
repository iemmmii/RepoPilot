import io
import json

import pytest

from repopilot.domain.errors import RepoPilotError
from repopilot.domain.verification import SandboxPolicy
from repopilot.sandbox.docker import DEFAULT_IMAGE, DockerRunner, _Capture


def runner(**options):
    return DockerRunner(executable="docker", context="default", **options)


def test_mutable_tags_cannot_execute():
    with pytest.raises(RepoPilotError, match="pinned"):
        runner(image="python:latest")


def test_policy_fingerprint_survives_json_roundtrip():
    from repopilot.domain.verification import fingerprint

    original = SandboxPolicy()
    restored = SandboxPolicy.model_validate_json(original.model_dump_json())
    assert fingerprint(original.model_dump()) == fingerprint(restored.model_dump())


def test_container_arguments_enforce_policy_and_only_three_mounts(tmp_path):
    mounts = {}
    for name in ("workspace", "suite", "runner"):
        path = tmp_path / name
        path.mkdir()
        mounts["/" + name] = path
    args = runner().create_arguments(
        "own-container", mounts, ["/usr/local/bin/python", "-I", "-B", "/runner/harness.py"]
    )
    for option, value in {
        "--network": "none",
        "--cap-drop": "ALL",
        "--security-opt": "no-new-privileges",
        "--user": "65534:65534",
        "--pull": "never",
        "--pids-limit": "64",
    }.items():
        assert args[args.index(option) + 1] == value
    assert "--read-only" in args and "--no-healthcheck" in args
    assert args.count("--mount") == 3
    assert all(item.endswith(",readonly") for item in args if item.startswith("type=bind"))
    assert not any("docker.sock" in item or "/.git" in item for item in args)
    with pytest.raises(RepoPilotError):
        runner().create_arguments("own-container", {"/workspace": tmp_path}, ["/bin/sh"])


def test_output_capture_keeps_a_bounded_prefix_and_actual_counts():
    capture = _Capture(1024)
    capture.read(io.BytesIO(b"x" * 5000), 0)
    capture.read(io.BytesIO(b"y" * 1000), 1)
    assert sum(map(len, capture.buffers)) == 1024
    assert capture.sizes == [5000, 1000]
    assert capture.exceeded.is_set()


def test_docker_cli_does_not_inherit_model_keys_or_remote_endpoint_override(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-key")
    monkeypatch.setenv("DOCKER_HOST", "tcp://untrusted.invalid:2375")
    selected = runner()
    assert "DEEPSEEK_API_KEY" not in selected.env
    assert "DOCKER_HOST" not in selected.env


@pytest.mark.parametrize(
    "host", ["ssh://remote", "tcp://remote:2375", "npipe:////remote/pipe/docker_engine"]
)
def test_remote_context_is_rejected_before_any_target_execution(tmp_path, monkeypatch, host):
    selected = runner()
    monkeypatch.setattr(
        selected,
        "_control",
        lambda *args: json.dumps([{"Endpoints": {"docker": {"Host": host}}}]).encode(),
    )
    with pytest.raises(RepoPilotError) as caught:
        selected.prepare(tmp_path / "harness.py")
    assert caught.value.code == "remote_docker_rejected"


def test_cached_linux_image_metadata_is_fingerprinted(tmp_path, monkeypatch):
    selected = runner()
    harness = tmp_path / "harness.py"
    harness.write_text("# trusted adapter", encoding="utf-8")

    def control(*args):
        if args[0] == "context":
            return json.dumps(
                [{"Endpoints": {"docker": {"Host": "unix:///var/run/docker.sock"}}}]
            ).encode()
        if args[0] == "version":
            return json.dumps(
                {"Os": "linux", "Version": "29-test", "KernelVersion": "test"}
            ).encode()
        return json.dumps(
            [
                {
                    "Os": "linux",
                    "Id": "sha256:image",
                    "Architecture": "amd64",
                    "RepoDigests": [DEFAULT_IMAGE],
                }
            ]
        ).encode()

    monkeypatch.setattr(selected, "_control", control)
    first = selected.prepare(harness)
    harness.write_text("# changed adapter", encoding="utf-8")
    assert selected.prepare(harness).environment_digest != first.environment_digest


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan"), 301])
def test_execution_timeout_is_finite_and_bounded(value):
    with pytest.raises(ValueError):
        SandboxPolicy(timeout_seconds=value)

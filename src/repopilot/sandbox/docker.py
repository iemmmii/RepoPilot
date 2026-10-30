import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from repopilot.domain.errors import RepoPilotError
from repopilot.domain.verification import (
    CommandEvidence,
    ExecutionEnvironment,
    SandboxPolicy,
    fingerprint,
)

DEFAULT_IMAGE = "python@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb"


def find_docker() -> str:
    path = shutil.which("docker")
    if not path and os.name == "nt":
        for directory in (
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/DockerDesktop/resources/bin",
            Path(os.environ.get("ProgramFiles", "C:/Program Files"))
            / "Docker/Docker/resources/bin",
        ):
            if (directory / "docker.exe").is_file():
                path = str(directory / "docker.exe")
                break
    if not path:
        raise RepoPilotError(
            "docker_missing", "Docker CLI is not available; no host fallback is allowed."
        )
    return path


@dataclass
class CommandResult:
    evidence: CommandEvidence
    stdout: bytes
    stderr: bytes


class _Capture:
    def __init__(self, limit: int):
        self.limit = limit
        self.buffers = [bytearray(), bytearray()]
        self.sizes = [0, 0]
        self.exceeded = threading.Event()
        self.lock = threading.Lock()

    def read(self, stream, index: int):
        try:
            while chunk := stream.read1(4096):
                with self.lock:
                    remaining = max(0, self.limit - sum(len(buf) for buf in self.buffers))
                    self.buffers[index].extend(chunk[:remaining])
                    self.sizes[index] += len(chunk)
                    if sum(self.sizes) > self.limit:
                        self.exceeded.set()
        except (OSError, ValueError):
            self.exceeded.set()


class DockerRunner:
    """No target code is run outside Docker; all mounts and options are controller-owned."""

    def __init__(
        self,
        *,
        image: str = DEFAULT_IMAGE,
        policy: SandboxPolicy | None = None,
        context: str | None = None,
        executable: str | None = None,
    ):
        if not re.fullmatch(r"[a-zA-Z0-9._/-]+@sha256:[a-f0-9]{64}", image):
            raise RepoPilotError(
                "unpinned_image", "Execution requires an image reference pinned by SHA-256."
            )
        self.image = image
        self.policy = policy or SandboxPolicy()
        self.context = context or ("desktop-linux" if os.name == "nt" else "default")
        self.executable = executable or find_docker()
        self.prefix = [self.executable, "--context", self.context]
        self.env = os.environ.copy()
        for name in (
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
            "DEEPSEEK_API_KEY",
            "OPENAI_API_KEY",
            "GITHUB_TOKEN",
            "GH_TOKEN",
        ):
            self.env.pop(name, None)
        self.env["PATH"] = (
            str(Path(self.executable).resolve().parent) + os.pathsep + self.env.get("PATH", "")
        )

    def _control(self, *arguments: str, timeout: float = 15) -> bytes:
        try:
            result = subprocess.run(
                [*self.prefix, *arguments], capture_output=True, timeout=timeout, env=self.env
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RepoPilotError(
                "docker_unavailable", "Docker control operation could not complete."
            ) from error
        if result.returncode or len(result.stdout) > 2_000_000:
            raise RepoPilotError(
                "docker_control_failed",
                "Docker control operation failed; no target result is inferred.",
            )
        return result.stdout

    def prepare(self, harness: Path) -> ExecutionEnvironment:
        try:
            contexts = json.loads(self._control("context", "inspect", self.context))
            host = contexts[0]["Endpoints"]["docker"]["Host"]
            if not host.startswith(("unix:///", "npipe:////./pipe/")):
                raise RepoPilotError(
                    "remote_docker_rejected",
                    "This runner requires a local Docker endpoint for bind mounts.",
                )
            server = json.loads(self._control("version", "--format", "{{json .Server}}"))
            image = json.loads(self._control("image", "inspect", self.image))[0]
            if server["Os"] != "linux" or image["Os"] != "linux":
                raise RepoPilotError(
                    "unsupported_engine", "A local Linux Docker engine and image are required."
                )
            if self.image not in image.get("RepoDigests", []):
                raise RepoPilotError(
                    "image_digest_mismatch", "The cached image does not match the requested digest."
                )
            values = {
                "image_ref": self.image,
                "image_id": image["Id"],
                "os": "linux",
                "architecture": image["Architecture"],
                "engine_version": server["Version"],
                "kernel_version": server["KernelVersion"],
                "policy_digest": fingerprint(self.policy.model_dump()),
                "harness_digest": hashlib.sha256(harness.read_bytes()).hexdigest(),
                "runner_digest": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            }
            return ExecutionEnvironment(**values, environment_digest=fingerprint(values))
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise RepoPilotError(
                "invalid_docker_metadata", "Docker returned incomplete environment metadata."
            ) from error

    def create_arguments(self, name: str, mounts: dict[str, Path], argv: list[str]) -> list[str]:
        if not argv or not argv[0].startswith("/"):
            raise RepoPilotError(
                "invalid_command", "Container entrypoint must be an explicit absolute path."
            )
        if set(mounts) != {"/workspace", "/suite", "/runner"}:
            raise RepoPilotError(
                "invalid_mounts", "Runner requires exactly the three isolated input mounts."
            )
        policy = self.policy
        args = [
            "create",
            "--name",
            name,
            "--label",
            "repopilot.managed=true",
            "--pull",
            "never",
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
            str(policy.cpus),
            "--memory",
            str(policy.memory_bytes),
            "--memory-swap",
            str(policy.memory_bytes),
            "--pids-limit",
            str(policy.pids),
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,nodev,size={policy.tmpfs_bytes}",
            "--workdir",
            "/workspace",
            "--no-healthcheck",
            "--init",
            "--log-driver",
            "local",
            "--log-opt",
            "max-size=1m",
            "--log-opt",
            "max-file=2",
            "--env",
            "HOME=/tmp",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
        ]
        for target, source in sorted(mounts.items()):
            resolved = source.resolve()
            if not resolved.is_dir() or any(char in str(resolved) for char in ",\r\n"):
                raise RepoPilotError(
                    "invalid_mounts",
                    "Mount source must be a supported controller-created directory.",
                )
            args.extend(["--mount", f"type=bind,source={resolved},target={target},readonly"])
        return [*args, "--entrypoint", argv[0], self.image, *argv[1:]]

    def run(
        self,
        *,
        run_id: str,
        source_digest: str,
        suite_hash: str,
        environment: ExecutionEnvironment,
        mounts: dict[str, Path],
        argv: list[str],
    ) -> CommandResult:
        name = "repopilot-command-" + uuid4().hex
        evidence_id = uuid4().hex
        started = datetime.now(UTC)
        capture = _Capture(self.policy.output_limit_bytes)
        termination = "environment_blocked"
        exit_code = None
        error_code = None
        cleanup = False
        process = None
        threads = []
        state = {}
        try:
            if environment.image_ref != self.image or environment.policy_digest != fingerprint(
                self.policy.model_dump()
            ):
                raise RepoPilotError(
                    "environment_changed",
                    "Runner policy or image changed after environment preparation.",
                )
            self._control(*self.create_arguments(name, mounts, argv))
            process = subprocess.Popen(
                [*self.prefix, "start", "--attach", name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.env,
            )
            for index, stream in enumerate((process.stdout, process.stderr)):
                thread = threading.Thread(target=capture.read, args=(stream, index), daemon=True)
                thread.start()
                threads.append(thread)
            deadline = time.monotonic() + self.policy.timeout_seconds
            termination = "exited"
            while process.poll() is None:
                if capture.exceeded.wait(0.02):
                    termination = "output_limit"
                    break
                if time.monotonic() >= deadline:
                    termination = "timed_out"
                    break
            if termination != "exited":
                self._control("kill", name, timeout=5)
            process.wait(timeout=5)
            for thread in threads:
                thread.join(timeout=2)
            state = json.loads(self._control("inspect", "--format", "{{json .State}}", name))
            if state["Running"] or state.get("Error"):
                raise RepoPilotError(
                    "container_state_invalid", "Container has no trustworthy finished state."
                )
            exit_code = state["ExitCode"]
            if capture.exceeded.is_set():
                termination = "output_limit"
            elif state.get("OOMKilled"):
                termination = "oom_killed"
            elif process.returncode and exit_code == 0:
                raise RepoPilotError(
                    "attach_failed",
                    "Docker attachment failed before a complete result was captured.",
                )
        except KeyboardInterrupt:
            termination = "interrupted"
        except (RepoPilotError, OSError, subprocess.SubprocessError, ValueError, KeyError) as error:
            termination = "environment_blocked"
            error_code = (
                error.code if isinstance(error, RepoPilotError) else "container_execution_failed"
            )
        finally:
            try:
                self._control("rm", "--force", name, timeout=10)
                cleanup = True
            except RepoPilotError:
                error_code = "container_cleanup_failed"
            if process:
                if process.poll() is None:
                    process.kill()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
                for thread in threads:
                    thread.join(timeout=1)
                for stream in (process.stdout, process.stderr):
                    stream.close()
        evidence = CommandEvidence(
            evidence_id=evidence_id,
            run_id=run_id,
            argv=argv,
            source_digest=source_digest,
            suite_hash=suite_hash,
            environment_digest=environment.environment_digest,
            started_at=started,
            ended_at=datetime.now(UTC),
            exit_code=exit_code,
            termination=termination,
            stdout_bytes=capture.sizes[0],
            stderr_bytes=capture.sizes[1],
            logs_truncated=capture.exceeded.is_set(),
            cleanup_succeeded=cleanup,
            error_code=error_code,
            container_name=name,
            container_started_at=state.get("StartedAt"),
            container_finished_at=state.get("FinishedAt"),
            stdout_sha256=hashlib.sha256(capture.buffers[0]).hexdigest(),
            stderr_sha256=hashlib.sha256(capture.buffers[1]).hexdigest(),
        )
        return CommandResult(
            evidence=evidence, stdout=bytes(capture.buffers[0]), stderr=bytes(capture.buffers[1])
        )

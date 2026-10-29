import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from pydantic import ValidationError

from repopilot.domain.errors import RepoPilotError
from repopilot.domain.models import Artifact, Manifest, Record, Usage


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp-" + uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class RunStore:
    """A new-run-only checkpoint store; stage resume is intentionally not implemented yet."""

    def __init__(self, output_root: Path, usage: Usage):
        now = datetime.now(UTC)
        run_id = uuid4().hex
        self.root = output_root.resolve() / run_id
        self.root.mkdir(parents=True, exist_ok=False)
        self._lock = self.root / ".writer.lock"
        self._lock.touch(exist_ok=False)
        self.manifest = Manifest(
            run_id=run_id,
            created_at=now,
            updated_at=now,
            execution_status="running",
            usage=usage,
        )
        self.checkpoint()

    def checkpoint(self) -> None:
        self.manifest.updated_at = datetime.now(UTC)
        _atomic_write(self.root / "manifest.json", self.manifest.model_dump_json(indent=2).encode())

    def add(self, name: str, content: str | Record) -> None:
        if Path(name).name != name or any(char in name for char in "/\\:") or name.startswith("."):
            raise RepoPilotError("invalid_artifact_path", "Artifact must have a simple filename.")
        if any(artifact.path == name for artifact in self.manifest.artifacts):
            raise RepoPilotError("artifact_exists", "Committed artifacts cannot be overwritten.")
        data = (
            content.model_dump_json(indent=2) if isinstance(content, Record) else content
        ).encode()
        _atomic_write(self.root / name, data)
        self.manifest.artifacts.append(
            Artifact(
                path=name,
                sha256=hashlib.sha256(data).hexdigest(),
                size_bytes=len(data),
            )
        )
        self.checkpoint()

    def finish(self, *, error: RepoPilotError | None = None) -> None:
        self.manifest.execution_status = "failed" if error else "completed"
        self.manifest.outcome = None if error else "investigated"
        self.manifest.error_code = error.code if error else None
        self.manifest.error_message = str(error) if error else None
        self.checkpoint()
        self._lock.unlink(missing_ok=True)


def read_status(root: Path) -> dict:
    root = root.resolve()
    try:
        manifest = Manifest.model_validate_json((root / "manifest.json").read_bytes())
    except (OSError, ValidationError) as error:
        raise RepoPilotError("invalid_manifest", "Cannot read a valid Run manifest.") from error
    problems = []
    for artifact in manifest.artifacts:
        relative = PurePosixPath(artifact.path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "\\" in artifact.path
            or ":" in artifact.path
        ):
            problems.append("invalid artifact path")
            continue
        path = (root / artifact.path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            problems.append("missing or out-of-root artifact")
            continue
        if path.stat().st_size != artifact.size_bytes:
            problems.append("artifact size mismatch")
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != artifact.sha256:
            problems.append("artifact digest mismatch")
    return {
        **manifest.model_dump(mode="json"),
        "artifact_integrity": "unverifiable" if problems else "valid",
        "integrity_problems": problems,
        "scope_note": "Integrity is relative to this manifest; no repair or live-worktree claim.",
    }

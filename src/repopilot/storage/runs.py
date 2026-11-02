import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from pydantic import ValidationError

from repopilot.domain.errors import RepoPilotError
from repopilot.domain.evidence import EvidenceGraph
from repopilot.domain.models import Artifact, Manifest, Record, Usage
from repopilot.domain.verification import CommandEvidence


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

    def __init__(self, output_root: Path, usage: Usage, scope="investigate"):
        now = datetime.now(UTC)
        run_id = uuid4().hex
        self.root = output_root.resolve() / run_id
        self.root.mkdir(parents=True, exist_ok=False)
        self._lock = self.root / ".writer.lock"
        self._lock.touch(exist_ok=False)
        self.manifest = Manifest(
            schema_version="0.1" if scope == "investigate" else "0.2",
            requested_scope=scope,
            run_id=run_id,
            created_at=now,
            updated_at=now,
            execution_status="running",
            usage=usage,
        )
        self.checkpoint()

    def checkpoint(self) -> None:
        self.manifest.updated_at = datetime.now(UTC)
        recovery_fields = {
            "stages",
            "command_attempts",
            "command_limit",
            "reserved_seconds",
            "wall_budget_seconds",
            "graph_artifact",
            "report_artifact",
        }
        excluded = recovery_fields if self.manifest.schema_version != "0.3" else set()
        _atomic_write(
            self.root / "manifest.json",
            self.manifest.model_dump_json(indent=2, exclude=excluded).encode(),
        )

    def add(self, name: str, content: str | bytes | Record) -> None:
        if (
            Path(name).name != name
            or any(char in name for char in "/\\:")
            or name.startswith(".")
            or name == "manifest.json"
        ):
            raise RepoPilotError("invalid_artifact_path", "Artifact must have a simple filename.")
        if any(artifact.path == name for artifact in self.manifest.artifacts):
            raise RepoPilotError("artifact_exists", "Committed artifacts cannot be overwritten.")
        data = (
            content
            if isinstance(content, bytes)
            else (
                content.model_dump_json(indent=2) if isinstance(content, Record) else content
            ).encode()
        )
        _atomic_write(self.root / name, data)
        self.manifest.artifacts.append(
            Artifact(
                path=name,
                sha256=hashlib.sha256(data).hexdigest(),
                size_bytes=len(data),
            )
        )
        self.checkpoint()

    def finish(self, *, error: RepoPilotError | None = None, outcome=None) -> None:
        self.manifest.execution_status = "failed" if error else "completed"
        if error and error.code == "verification_interrupted":
            self.manifest.execution_status = "interrupted"
        self.manifest.outcome = (
            outcome if outcome is not None else (None if error else "investigated")
        )
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
    graph_integrity = "not_assessed"
    artifacts = {artifact.path: artifact.sha256 for artifact in manifest.artifacts}
    attempts = set()
    for stage in manifest.stages:
        key = (stage.name, stage.attempt)
        if (
            key in attempts
            or any(path not in artifacts for path in stage.artifacts.values())
            or (stage.status == "running" and stage.artifacts)
        ):
            problems.append("invalid stage checkpoint or artifact binding")
        attempts.add(key)
    graph_path = manifest.graph_artifact or "graph.json"
    if graph_path in artifacts and not problems:
        try:
            graph = EvidenceGraph.model_validate_json((root / graph_path).read_bytes())
            if graph.run_id != manifest.run_id or any(
                artifacts.get(node.artifact_path) != node.artifact_digest for node in graph.nodes
            ):
                raise ValueError("Graph references another Run or artifact revision")
            for node in graph.nodes:
                if node.kind == "command":
                    command = CommandEvidence.model_validate_json(
                        (root / node.artifact_path).read_bytes()
                    )
                    if command.run_id != manifest.run_id or any(
                        path not in artifacts or artifacts[path] != digest
                        for path, digest in (
                            (command.stdout_artifact, command.stdout_sha256),
                            (command.stderr_artifact, command.stderr_sha256),
                        )
                    ):
                        raise ValueError("Command does not bind its Run and log artifacts")
            graph_integrity = "valid"
        except (OSError, ValueError):
            graph_integrity = "unverifiable"
            problems.append("invalid evidence graph or artifact binding")
    elif manifest.requested_scope != "investigate" and manifest.execution_status == "completed":
        graph_integrity = "unverifiable"
        problems.append("completed verification has no valid evidence graph")
    return {
        **manifest.model_dump(mode="json"),
        "artifact_integrity": "unverifiable" if problems else "valid",
        "integrity_problems": problems,
        "graph_integrity": graph_integrity,
        "orphan_artifacts": sorted(
            path.name
            for path in root.iterdir()
            if path.is_file()
            and not path.name.startswith(".")
            and path.name != "manifest.json"
            and path.name not in artifacts
        ),
        "scope_note": "Integrity is relative to this manifest; no repair or live-worktree claim.",
    }

import hashlib
from pathlib import Path

from pydantic import ValidationError

from repopilot.domain.errors import RepoPilotError
from repopilot.domain.models import Artifact, Manifest, Record, StageAttempt
from repopilot.storage.lease import RunLease
from repopilot.storage.runs import RunStore, _atomic_write, read_status


class VerificationStore(RunStore):
    def __init__(self, output_root, usage, scope, *, resume_root: Path | None = None):
        self.lease = None
        self.active = None
        self.pending = []
        self.pending_names = {}
        if resume_root is None:
            super().__init__(output_root, usage, scope)
            self.lease = RunLease(self.root)
            self.manifest.schema_version = "0.3"
            self.checkpoint()
        else:
            self.root = resume_root.resolve()
            self._lock = self.root / ".writer.lock"
            self.lease = RunLease(self.root)
            try:
                self.manifest = Manifest.model_validate_json(
                    (self.root / "manifest.json").read_bytes()
                )
                if (
                    self.manifest.schema_version != "0.3"
                    or self.manifest.requested_scope == "investigate"
                ):
                    raise RepoPilotError(
                        "resume_unsupported", "Only 0.3 verification Runs support stage resume."
                    )
                if read_status(self.root)["artifact_integrity"] != "valid":
                    raise RepoPilotError(
                        "evidence_corrupted", "Committed artifacts are corrupt; resume refused."
                    )
            except (OSError, ValidationError) as error:
                self.release()
                raise RepoPilotError(
                    "invalid_manifest", "Cannot resume an invalid Run manifest."
                ) from error
            except BaseException:
                self.release()
                raise

    @property
    def names(self):
        values = {artifact.path: artifact.path for artifact in self.manifest.artifacts}
        for stage in self.manifest.stages:
            if stage.status != "running":
                values.update(stage.artifacts)
        return {**values, **self.pending_names}

    @property
    def available_artifacts(self):
        return [*self.manifest.artifacts, *self.pending]

    def artifact_name(self, logical):
        return self.names.get(logical, logical)

    def target_name(self, logical):
        return (
            logical
            if self.active is None or self.active.attempt == 1
            else f"{self.active.name}-a{self.active.attempt:03d}-{logical}"
        )

    def read(self, logical):
        actual = self.names.get(logical)
        if actual not in {artifact.path for artifact in self.manifest.artifacts}:
            raise RepoPilotError(
                "uncommitted_artifact", "Uncommitted files cannot be resumed as evidence."
            )
        return (self.root / actual).read_bytes()

    def reusable(self, name, digest):
        attempts = [stage for stage in self.manifest.stages if stage.name == name]
        return bool(
            attempts
            and attempts[-1].status == "succeeded"
            and attempts[-1].input_fingerprint == digest
        )

    def recover(self, runner):
        for stage in self.manifest.stages:
            if stage.status in {"running", "failed", "interrupted"} and stage.container_name:
                runner.cleanup_registered(stage.container_name)
            if stage.status == "running":
                stage.status = "interrupted"
        self.manifest.execution_status = "running"
        self.manifest.outcome = None
        self.manifest.error_code = self.manifest.error_message = None
        self._lock.touch(exist_ok=True)
        self.checkpoint()

    def begin(self, name, digest, *, command_seconds=0):
        if command_seconds:
            if (
                self.manifest.command_attempts >= self.manifest.command_limit
                or self.manifest.reserved_seconds + command_seconds
                > self.manifest.wall_budget_seconds
            ):
                raise RepoPilotError(
                    "budget_exhausted", "Persistent command/time reservation budget is exhausted."
                )
            self.manifest.command_attempts += 1
            self.manifest.reserved_seconds += command_seconds
        attempt = 1 + max(
            (stage.attempt for stage in self.manifest.stages if stage.name == name), default=0
        )
        self.active = StageAttempt(
            name=name, attempt=attempt, input_fingerprint=digest, status="running"
        )
        self.manifest.stages.append(self.active)
        self.pending, self.pending_names = [], {}
        self.manifest.execution_status = "running"
        self.manifest.outcome = None
        self.checkpoint()

    def register_container(self, name):
        self.active.container_name = name
        self.checkpoint()

    def add(self, name: str, content: str | bytes | Record):
        if self.active is None:
            return super().add(name, content)
        if (
            Path(name).name != name
            or name.startswith(".")
            or any(c in name for c in "/\\:")
            or name == "manifest.json"
        ):
            raise RepoPilotError("invalid_artifact_path", "Stage artifact requires a simple name.")
        actual = self.target_name(name)
        if (self.root / actual).exists():
            raise RepoPilotError("artifact_exists", "An attempt artifact cannot be overwritten.")
        data = (
            content
            if isinstance(content, bytes)
            else (
                content.model_dump_json(indent=2) if isinstance(content, Record) else content
            ).encode()
        )
        _atomic_write(self.root / actual, data)
        self.pending.append(
            Artifact(path=actual, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
        )
        self.pending_names[name] = actual

    def commit_stage(self, *, succeeded=True):
        self.active.status = "succeeded" if succeeded else "failed"
        self.active.artifacts = dict(self.pending_names)
        self.manifest.artifacts.extend(self.pending)
        if "graph.json" in self.pending_names:
            self.manifest.graph_artifact = self.pending_names["graph.json"]
            self.manifest.report_artifact = self.pending_names["verification.md"]
        self.checkpoint()
        self.active, self.pending, self.pending_names = None, [], {}

    def finish(self, *, error=None, outcome=None):
        if self.active is not None:
            self.active.status = (
                "interrupted" if error and error.code == "verification_interrupted" else "failed"
            )
            self.active = None
            self.pending, self.pending_names = [], {}
        if error and error.code == "budget_exhausted":
            self.manifest.execution_status = "budget_exhausted"
            self.manifest.outcome = None
            self.manifest.error_code, self.manifest.error_message = error.code, str(error)
            self.checkpoint()
            self._lock.unlink(missing_ok=True)
        else:
            super().finish(error=error, outcome=outcome)

    def release(self):
        if self.lease is not None:
            self.lease.close()
            self.lease = None

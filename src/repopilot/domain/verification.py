import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from repopilot.domain.models import Record


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


class FileEntry(Record):
    path: str
    sha256: str
    size_bytes: int = Field(ge=0)


class SourceSnapshot(Record):
    commit: str
    source_digest: str
    files: list[FileEntry]
    excluded_paths: list[str]


class FrozenSuite(Record):
    suite_hash: str
    files: dict[str, str]


class Oracle(Record):
    criterion_id: str = Field(min_length=1, max_length=200)
    requirement: str = Field(min_length=1, max_length=4000)
    issue_url: str = Field(min_length=1, max_length=2000)
    source_refs: list[str] = Field(min_length=1, max_length=20)
    suite_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    target_tests: list[str] = Field(min_length=1, max_length=100)
    regression_tests: list[str] = Field(min_length=1, max_length=100)
    assessment_status: Literal["accepted", "provisional", "rejected"] = "provisional"
    assessment_basis: str = Field(min_length=1, max_length=4000)
    assessed_by: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def explicit_selection(self):
        selection = self.target_tests + self.regression_tests
        if len(set(selection)) != len(selection) or any(not item.strip() for item in selection):
            raise ValueError("Test IDs must be nonempty and unique across both groups")
        if self.assessment_status == "accepted" and not self.assessed_by:
            raise ValueError("Accepted Oracle requires an assessor and independent basis")
        return self


class SandboxPolicy(Record):
    version: Literal["docker-readonly-v1"] = "docker-readonly-v1"
    cpus: int = Field(default=1, ge=1, le=4)
    memory_bytes: int = Field(default=268435456, ge=67108864, le=2147483648)
    pids: int = Field(default=64, ge=16, le=256)
    timeout_seconds: float = Field(default=60, gt=0, le=300, allow_inf_nan=False)
    output_limit_bytes: int = Field(default=131072, ge=1024, le=1048576)
    tmpfs_bytes: int = Field(default=33554432, ge=1048576, le=134217728)


class ExecutionEnvironment(Record):
    image_ref: str
    image_id: str
    os: Literal["linux"]
    architecture: str
    engine_version: str
    kernel_version: str
    policy_digest: str
    harness_digest: str
    runner_digest: str
    environment_digest: str


class CommandEvidence(Record):
    evidence_id: str
    run_id: str
    argv: list[str]
    cwd: Literal["/workspace"] = "/workspace"
    source_digest: str
    suite_hash: str
    environment_digest: str
    started_at: datetime
    ended_at: datetime
    exit_code: int | None = None
    termination: Literal[
        "exited", "timed_out", "output_limit", "interrupted", "oom_killed", "environment_blocked"
    ]
    stdout_bytes: int = Field(ge=0)
    stderr_bytes: int = Field(ge=0)
    logs_truncated: bool
    cleanup_succeeded: bool
    error_code: str | None = None
    container_name: str | None = None
    container_started_at: str | None = None
    container_finished_at: str | None = None
    stdout_artifact: str | None = None
    stderr_artifact: str | None = None
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None


class TestCaseObservation(Record):
    test_id: str = Field(min_length=1, max_length=2000)
    status: Literal["passed", "failed", "error", "skipped", "xfailed", "unexpected_success"]


class TestObservation(Record):
    command_evidence_id: str
    source_digest: str
    suite_hash: str
    environment_digest: str
    protocol_valid: bool
    tests: list[TestCaseObservation] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)
    stability: Literal["not_checked"] = "not_checked"


class VerificationAssessment(Record):
    requested_scope: Literal["reproduce", "verify_candidate"]
    outcome: Literal[
        "reproduced", "not_reproduced", "environment_blocked", "needs_human", "candidate_verified"
    ]
    reproduction_status: Literal[
        "reproduced", "not_reproduced", "environment_blocked", "needs_human"
    ]
    input_fingerprint: str
    oracle_status: Literal["accepted", "provisional", "rejected"]
    reasons: list[str]
    limitations: list[str]
    command_evidence_ids: list[str]
    stability: Literal["not_checked", "unstable"] = "not_checked"

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Issue(Record):
    title: str = Field(min_length=1, max_length=1000)
    body: str = Field(default="", max_length=100_000)
    url: str | None = None
    repository: str | None = None
    number: int | None = Field(default=None, gt=0)
    body_kind: Literal["original", "curated_summary"] = "original"


class CodeExcerpt(Record):
    path: str
    blob_oid: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    content: str
    symbols: list[str]
    retrieval_score: int = Field(ge=0)


class RepositoryContext(Record):
    base_commit: str
    tree_oid: str
    tree_manifest_sha256: str
    snapshot_scope: Literal["git_commit_only"] = "git_commit_only"
    total_regular_files: int
    scanned_files: int
    excerpts: list[CodeExcerpt]
    candidate_test_commands: list[list[str]]
    limitations: list[str]


class Finding(Record):
    path: str
    start_line: int = Field(gt=0, strict=True)
    end_line: int = Field(gt=0, strict=True)
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def ordered_lines(self):
        if self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line")
        return self


class Analysis(Record):
    summary: str = Field(min_length=1, max_length=5000)
    findings: list[Finding] = Field(min_length=1, max_length=10)
    hypotheses: list[str] = Field(default_factory=list, max_length=10)
    limitations: list[str] = Field(default_factory=list, max_length=20)


class Usage(Record):
    provider: str
    model: str | None = None
    requests: int = Field(default=0, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = None


class Artifact(Record):
    path: str
    sha256: str
    size_bytes: int = Field(ge=0)


class StageAttempt(Record):
    name: Literal["inputs", "base", "candidate", "assess"]
    attempt: int = Field(ge=1)
    input_fingerprint: str
    status: Literal["running", "succeeded", "failed", "interrupted"]
    artifacts: dict[str, str] = Field(default_factory=dict)
    container_name: str | None = None


class Manifest(Record):
    schema_version: Literal["0.1", "0.2", "0.3"] = "0.1"
    run_id: str
    requested_scope: Literal["investigate", "reproduce", "verify_candidate"] = "investigate"
    created_at: datetime
    updated_at: datetime
    execution_status: Literal["running", "completed", "failed", "interrupted", "budget_exhausted"]
    outcome: (
        Literal[
            "investigated",
            "reproduced",
            "not_reproduced",
            "environment_blocked",
            "needs_human",
            "candidate_verified",
        ]
        | None
    ) = None
    base_commit: str | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    usage: Usage
    error_code: str | None = None
    error_message: str | None = None
    tests_executed: bool = False
    stages: list[StageAttempt] = Field(default_factory=list)
    command_attempts: int = Field(default=0, ge=0)
    command_limit: int = Field(default=6, ge=1, le=20)
    reserved_seconds: float = Field(default=0, ge=0)
    wall_budget_seconds: float = Field(default=1200, gt=0)
    graph_artifact: str | None = None
    report_artifact: str | None = None

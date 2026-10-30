from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from repopilot.domain.models import Record
from repopilot.domain.verification import SourceSnapshot


class FileReplacement(Record):
    path: str = Field(min_length=1, max_length=500)
    before_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    content: str = Field(max_length=64_000)


class PatchProposal(Record):
    """Data only: no shell commands, tests, executable tools, or permission changes."""

    explanation: str = Field(min_length=1, max_length=4000)
    replacements: list[FileReplacement] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def unique_paths(self):
        paths = [item.path.casefold() for item in self.replacements]
        if len(paths) != len(set(paths)):
            raise ValueError("Replacement paths must be unique")
        if sum(len(item.content.encode("utf-8")) for item in self.replacements) > 256_000:
            raise ValueError("Replacement batch exceeds its byte limit")
        return self


class CandidateRevision(Record):
    revision_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    created_at: datetime
    snapshot: SourceSnapshot
    git_marker_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    patch_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    proposal_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class CandidateManifest(Record):
    schema_version: Literal["candidate-0.1"] = "candidate-0.1"
    candidate_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    repository: str
    base: SourceSnapshot
    revisions: list[CandidateRevision] = Field(min_length=1, max_length=11)
    retired: bool = False
    released_revisions: list[str] = Field(default_factory=list, max_length=11)

    @model_validator(mode="after")
    def unique_revisions(self):
        ids = [item.revision_id for item in self.revisions]
        if (
            len(ids) != len(set(ids))
            or self.revisions[0].snapshot != self.base
            or len(set(self.released_revisions)) != len(self.released_revisions)
            or not set(self.released_revisions) <= set(ids)
            or (self.released_revisions and not self.retired)
        ):
            raise ValueError("Candidate history must start with its fixed base")
        return self


class CandidateExport(Record):
    schema_version: Literal["candidate-export-0.1"] = "candidate-export-0.1"
    candidate_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    revision: str = Field(pattern=r"^[a-f0-9]{32}$")
    repository: str
    base_ref: str = Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    candidate_ref: str = Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    patch_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    changed_paths: list[str] = Field(min_length=1, max_length=500)
    outcome: Literal["unverified"] = "unverified"
    tests_executed: Literal[False] = False

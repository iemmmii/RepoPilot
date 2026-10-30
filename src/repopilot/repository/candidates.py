"""Controller-owned immutable candidate revisions; target code never executes here."""

import ast
import difflib
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from repopilot.domain.errors import RepoPilotError
from repopilot.domain.patches import (
    CandidateExport,
    CandidateManifest,
    CandidateRevision,
    PatchProposal,
)
from repopilot.domain.verification import fingerprint
from repopilot.repository.materialize import (
    MAX_FILES,
    MAX_TOTAL_BYTES,
    excluded,
    is_link,
    read_repository,
    safe_relative,
    validate_paths,
    write_files,
)
from repopilot.storage.lease import RunLease
from repopilot.storage.runs import _atomic_write

MAX_REVISIONS = 11


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def editable(path: str) -> bool:
    relative = safe_relative(path)
    parts = [part.casefold() for part in relative.parts]
    return (
        relative.suffix == ".py"
        and not excluded(relative)
        and not set(parts[:-1]) & {"test", "tests", "testing", "fixtures"}
        and parts[-1] not in {"conftest.py", "setup.py"}
        and not parts[-1].startswith("test_")
        and not parts[-1].endswith(("_test.py", "_tests.py"))
    )


def _regular(path: Path) -> None:
    if is_link(path):
        raise RepoPilotError("candidate_changed", "Candidate contains an unsupported link.")


def _git(repository: Path, *args: str, data=None, index: Path | None = None) -> str:
    # Raw object/index operations only. Never checkout, diff, status, add, or apply.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_AUTHOR_NAME="RepoPilot Candidate",
        GIT_AUTHOR_EMAIL="candidate@repopilot.invalid",
        GIT_COMMITTER_NAME="RepoPilot Candidate",
        GIT_COMMITTER_EMAIL="candidate@repopilot.invalid",
    )
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index.resolve())
    try:
        result = subprocess.run(
            [
                "git",
                "--no-optional-locks",
                "-c",
                "core.fsmonitor=false",
                "-c",
                f"core.hooksPath={os.devnull}",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "gc.auto=0",
                "-c",
                "maintenance.auto=false",
                "-C",
                str(repository),
                *args,
            ],
            input=data,
            capture_output=True,
            timeout=30,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RepoPilotError(
            "candidate_git_failed", "Candidate Git operation did not complete."
        ) from error
    if result.returncode or len(result.stdout) > 1_000_000:
        raise RepoPilotError("candidate_git_failed", "Candidate Git operation failed.")
    return result.stdout.decode("utf-8").strip()


def _oid(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", value):
        raise RepoPilotError("candidate_git_failed", "Git returned an invalid object identifier.")
    return value


def _read_manifest(root: Path) -> CandidateManifest:
    _regular(root)
    path = root / "candidate.json"
    _regular(path)
    try:
        if path.stat().st_size > 2_000_000:
            raise ValueError("Oversized manifest")
        return CandidateManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise RepoPilotError(
            "invalid_candidate", "Cannot read a valid candidate manifest."
        ) from error


def read_proposal(path: Path) -> PatchProposal:
    try:
        _regular(path)
        if path.stat().st_size > 512_000:
            raise ValueError("Oversized proposal")
        return PatchProposal.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise RepoPilotError(
            "invalid_patch_proposal", "Proposal must match the bounded JSON schema."
        ) from error


def _revision_dir(root: Path, revision: CandidateRevision) -> Path:
    revisions = root / "revisions"
    _regular(revisions)
    path = revisions / revision.revision_id
    _regular(path)
    return path


def _check_revision(root: Path, revision: CandidateRevision, *, released=False) -> dict[str, bytes]:
    folder = _revision_dir(root, revision)
    workspace = folder / "workspace"
    _regular(workspace)
    expected = {entry.path: entry for entry in revision.snapshot.files}
    validate_paths(expected)
    if (
        len(expected) != len(revision.snapshot.files)
        or len(expected) > MAX_FILES
        or sum(entry.size_bytes for entry in expected.values()) > MAX_TOTAL_BYTES
        or fingerprint([entry.model_dump() for entry in revision.snapshot.files])
        != revision.snapshot.source_digest
    ):
        raise RepoPilotError("candidate_changed", "Candidate snapshot binding is invalid.")
    files = {}
    for path in () if released else workspace.rglob("*"):
        _regular(path)
        name = path.relative_to(workspace).as_posix()
        if path.is_dir():
            continue
        if name == ".git":
            if (
                path.stat().st_size > 4096
                or _digest(path.read_bytes()) != revision.git_marker_sha256
            ):
                raise RepoPilotError("candidate_changed", "Managed worktree registration changed.")
            continue
        entry = expected.get(name)
        if entry is None or path.stat().st_size != entry.size_bytes:
            raise RepoPilotError("candidate_changed", "Managed candidate file selection changed.")
        content = path.read_bytes()
        if _digest(content) != entry.sha256:
            raise RepoPilotError("candidate_changed", "Managed candidate content changed.")
        files[name] = content
    if not released and (files.keys() != expected.keys() or not (workspace / ".git").is_file()):
        raise RepoPilotError("candidate_changed", "Managed candidate files are missing.")
    for name, digest in (
        ("patch.diff", revision.patch_sha256),
        ("proposal.json", revision.proposal_sha256),
    ):
        if digest is None:
            continue
        path = folder / name
        _regular(path)
        if (
            not path.is_file()
            or path.stat().st_size > 1_000_000
            or _digest(path.read_bytes()) != digest
        ):
            raise RepoPilotError("candidate_changed", "Candidate audit artifact changed.")
    return files


def _patch(base: dict[str, bytes], candidate: dict[str, bytes]) -> bytes:
    chunks = []
    for path in sorted(base):
        if base[path] == candidate[path]:
            continue
        old, new = base[path].decode("utf-8"), candidate[path].decode("utf-8")
        a, b = (
            json.dumps("a/" + path, ensure_ascii=False),
            json.dumps("b/" + path, ensure_ascii=False),
        )
        chunks.append(f"diff --git {a} {b}\n")
        for line in difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True), fromfile=a, tofile=b
        ):
            chunks.append(line)
            if not line.endswith("\n"):
                chunks.append("\n\\ No newline at end of file\n")
    return "".join(chunks).encode("utf-8")


def _commit(
    repository: Path, base: str, original: dict[str, bytes], files: dict[str, bytes], root: Path
) -> str:
    with tempfile.TemporaryDirectory(prefix="index-", dir=root) as temp:
        index = Path(temp) / "index"
        _git(repository, "read-tree", base, index=index)
        for name in sorted(files):
            if files[name] == original[name]:
                continue
            oid = _oid(_git(repository, "hash-object", "-w", "--stdin", data=files[name]))
            # Preserve executable bits from the fixed base; no worktree/stat/filter lookup.
            record = _git(repository, "ls-tree", base, "--", name)
            mode = record.split(" ", 1)[0]
            if mode not in {"100644", "100755"}:
                raise RepoPilotError("candidate_git_failed", "Unsupported candidate file mode.")
            _git(
                repository,
                "update-index",
                "-z",
                "--index-info",
                index=index,
                data=f"{mode} {oid}\t{name}\0".encode(),
            )
        tree = _oid(_git(repository, "write-tree", index=index))
    return _oid(
        _git(repository, "commit-tree", tree, "-p", base, data=b"RepoPilot bounded candidate\n")
    )


def _new_revision(root, repository, snapshot, files, patch, proposal=None):
    folder = root / "revisions" / uuid4().hex
    folder.mkdir(parents=True, exist_ok=False)
    workspace = folder / "workspace"
    _git(
        repository, "worktree", "add", "--detach", "--no-checkout", str(workspace), snapshot.commit
    )
    # No checkout has occurred. Only the controller's already bounded raw blobs are written.
    if {item.name for item in workspace.iterdir()} != {".git"}:
        raise RepoPilotError("candidate_git_failed", "New worktree is not empty.")
    for name, data in files.items():
        target = workspace.joinpath(*safe_relative(name).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o644)
    _atomic_write(folder / "patch.diff", patch)
    proposal_bytes = proposal.model_dump_json(indent=2).encode() if proposal else None
    if proposal_bytes is not None:
        _atomic_write(folder / "proposal.json", proposal_bytes)
    return CandidateRevision(
        revision_id=folder.name,
        created_at=datetime.now(UTC),
        snapshot=snapshot,
        git_marker_sha256=_digest((workspace / ".git").read_bytes()),
        patch_sha256=_digest(patch),
        proposal_sha256=_digest(proposal_bytes) if proposal_bytes is not None else None,
    )


def create_candidate(repository: Path, base_ref: str, output_root: Path) -> Path:
    repository = repository.resolve()
    snapshot, files = read_repository(repository, base_ref)
    root = output_root.resolve() / uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    with RunLease(root):
        revision = _new_revision(root, repository, snapshot, files, b"")
        manifest = CandidateManifest(
            candidate_id=root.name, repository=str(repository), base=snapshot, revisions=[revision]
        )
        _atomic_write(root / "candidate.json", manifest.model_dump_json(indent=2).encode())
    return root


def apply_proposal(root: Path, proposal: PatchProposal) -> dict:
    root = root.absolute()
    _regular(root)
    with RunLease(root):
        manifest = _read_manifest(root)
        if manifest.retired:
            raise RepoPilotError("candidate_retired", "Retired candidates cannot accept proposals.")
        if len(list((root / "revisions").iterdir())) >= MAX_REVISIONS:
            raise RepoPilotError("candidate_budget_exhausted", "Candidate revision limit reached.")
        # Revalidate models constructed through Python as well as JSON callers.
        try:
            proposal = PatchProposal.model_validate_json(proposal.model_dump_json())
        except ValidationError as error:
            raise RepoPilotError("invalid_patch_proposal", "Invalid replacement batch.") from error
        current = _check_revision(root, manifest.revisions[-1])
        original = _check_revision(root, manifest.revisions[0])
        for revision in manifest.revisions[1:-1]:
            _check_revision(root, revision)
        updated = dict(current)
        for replacement in proposal.replacements:
            name = replacement.path
            if not editable(name) or name not in current:
                raise RepoPilotError(
                    "patch_scope_rejected",
                    "Patch must replace an existing implementation Python file.",
                )
            if len(current[name]) > 64_000 or _digest(current[name]) != replacement.before_sha256:
                raise RepoPilotError(
                    "stale_patch", "Replacement does not match current candidate bytes."
                )
            try:
                current[name].decode("utf-8")
                data = replacement.content.encode("utf-8")
                if len(data) > 64_000:
                    raise ValueError("Oversized file")
                ast.parse(replacement.content, filename=name)
            except (UnicodeError, SyntaxError, ValueError, RecursionError) as error:
                raise RepoPilotError(
                    "invalid_python_patch", "Replacement must be bounded UTF-8 Python syntax."
                ) from error
            updated[name] = data
        if updated == current:
            raise RepoPilotError("empty_patch", "Proposal does not change the candidate.")
        repository = Path(manifest.repository)
        patch = _patch(original, updated)
        if len(patch) > 1_000_000:
            raise RepoPilotError("patch_too_large", "Cumulative patch exceeds one million bytes.")
        commit = _commit(repository, manifest.base.commit, original, updated, root)
        snapshot, committed = read_repository(repository, commit)
        if committed != updated:
            raise RepoPilotError(
                "candidate_git_failed", "Committed bytes differ from the validated proposal."
            )
        revision = _new_revision(root, repository, snapshot, updated, patch, proposal)
        # This atomic manifest update is the sole publication point; incomplete directories are orphans.
        manifest.revisions.append(revision)
        _atomic_write(root / "candidate.json", manifest.model_dump_json(indent=2).encode())
    return candidate_status(root)


def candidate_status(root: Path) -> dict:
    root = root.absolute()
    manifest = _read_manifest(root)
    problems = []
    try:
        for revision in manifest.revisions:
            _check_revision(
                root, revision, released=revision.revision_id in manifest.released_revisions
            )
    except (RepoPilotError, OSError):
        problems.append("managed revision or audit artifact changed")
    current = manifest.revisions[-1]
    registered = {revision.revision_id for revision in manifest.revisions}
    return {
        "candidate_dir": str(root),
        "candidate_id": manifest.candidate_id,
        "base_ref": manifest.base.commit,
        "candidate_ref": current.snapshot.commit,
        "source_digest": current.snapshot.source_digest,
        "revision": current.revision_id,
        "revision_count": len(manifest.revisions),
        "retired": manifest.retired,
        "released_revisions": manifest.released_revisions,
        "integrity": "unverifiable" if problems else "valid",
        "problems": problems,
        "orphan_revisions": sorted(
            path.name for path in (root / "revisions").iterdir() if path.name not in registered
        ),
        "outcome": "unverified",
        "tests_executed": False,
    }


def export_candidate(root: Path, destination: Path) -> dict:
    root = root.absolute()
    _regular(root)
    with RunLease(root):
        manifest = _read_manifest(root)
        if manifest.retired:
            raise RepoPilotError(
                "candidate_retired", "Export the patch before retiring the candidate."
            )
        original = _check_revision(root, manifest.revisions[0])
        for revision in manifest.revisions[1:-1]:
            _check_revision(root, revision)
        current = manifest.revisions[-1]
        files = _check_revision(root, current)
        patch = _patch(original, files)
        if not patch:
            raise RepoPilotError(
                "empty_patch", "Candidate has no implementation changes to export."
            )
        # Git objects may have been pruned or replaced externally; verify the exact export binding.
        snapshot, committed = read_repository(Path(manifest.repository), current.snapshot.commit)
        if snapshot != current.snapshot or committed != files:
            raise RepoPilotError(
                "candidate_changed", "Candidate Git objects no longer match the revision."
            )
        result = CandidateExport(
            candidate_id=manifest.candidate_id,
            revision=current.revision_id,
            repository=manifest.repository,
            base_ref=manifest.base.commit,
            candidate_ref=current.snapshot.commit,
            source_digest=current.snapshot.source_digest,
            patch_sha256=_digest(patch),
            changed_paths=sorted(name for name in original if original[name] != files[name]),
        ).model_dump(mode="json")
        write_files(
            destination,
            {"patch.diff": patch, "candidate.json": json.dumps(result, indent=2).encode()},
        )
    return result


def check_export(root: Path, exported: Path) -> dict:
    """Check whether a historical export still describes this candidate revision."""
    _regular(exported)
    try:
        path = exported / "candidate.json"
        _regular(path)
        _regular(exported / "patch.diff")
        if path.stat().st_size > 64_000 or (exported / "patch.diff").stat().st_size > 1_000_000:
            raise ValueError("Oversized export")
        saved = CandidateExport.model_validate_json(path.read_bytes())
        patch = (exported / "patch.diff").read_bytes()
        if _digest(patch) != saved.patch_sha256:
            raise ValueError("Patch digest mismatch")
    except (OSError, ValueError) as error:
        raise RepoPilotError(
            "invalid_candidate_export", "Export metadata or patch is invalid."
        ) from error
    root = root.absolute()
    _regular(root)
    with RunLease(root):
        manifest = _read_manifest(root)
        if (
            saved.candidate_id != manifest.candidate_id
            or saved.repository != manifest.repository
            or saved.base_ref != manifest.base.commit
        ):
            raise RepoPilotError(
                "candidate_export_mismatch", "Export belongs to another candidate session."
            )
        revision = next(
            (item for item in manifest.revisions if item.revision_id == saved.revision), None
        )
        if (
            revision is None
            or revision.snapshot.commit != saved.candidate_ref
            or revision.snapshot.source_digest != saved.source_digest
            or revision.patch_sha256 != saved.patch_sha256
        ):
            raise RepoPilotError(
                "candidate_export_mismatch", "Export does not bind a committed candidate revision."
            )
        base_hashes = {entry.path: entry.sha256 for entry in manifest.base.files}
        changed_paths = sorted(
            entry.path
            for entry in revision.snapshot.files
            if base_hashes.get(entry.path) != entry.sha256
        )
        if saved.changed_paths != changed_paths:
            raise RepoPilotError(
                "candidate_export_mismatch", "Export changed-file list does not match its revision."
            )
        status = candidate_status(root)
        applicability = (
            "unverifiable"
            if status["integrity"] != "valid"
            else "retired"
            if manifest.retired
            else "current"
            if manifest.revisions[-1].revision_id == saved.revision
            else "superseded"
        )
        return {
            "applicability": applicability,
            "candidate_id": manifest.candidate_id,
            "exported_ref": saved.candidate_ref,
            "current_ref": status["candidate_ref"],
            "historical_export_integrity": "valid",
            "candidate_integrity": status["integrity"],
            "outcome": "unverified",
            "tests_executed": False,
        }


def release_candidate(root: Path) -> dict:
    """Retire a session and remove only its verified, registered worktree paths.

    Audit files and the kernel lock remain. Orphans are reported for operator review;
    they never authorize deleting an arbitrary Git worktree or running prune.
    """
    root = root.absolute()
    _regular(root)
    with RunLease(root):
        manifest = _read_manifest(root)
        repository = Path(manifest.repository)
        # Publish retirement before deletion so a crash cannot leave an active partial session.
        manifest.retired = True
        _atomic_write(root / "candidate.json", manifest.model_dump_json(indent=2).encode())
        for revision in manifest.revisions:
            if revision.revision_id in manifest.released_revisions:
                continue
            folder = _revision_dir(root, revision)
            workspace = folder / "workspace"
            _regular(workspace)
            resolved = workspace.resolve()
            if (
                not resolved.is_relative_to(root.resolve())
                or resolved != root.resolve() / "revisions" / revision.revision_id / "workspace"
            ):
                raise RepoPilotError(
                    "candidate_changed", "Cleanup path is outside its managed revision."
                )
            records = _git(repository, "worktree", "list", "--porcelain", "-z").split("\0\0")
            registration = None
            for record in records:
                fields = record.split("\0")
                if fields[0].startswith("worktree ") and Path(fields[0][9:]).resolve() == resolved:
                    registration = fields
                    break
            if workspace.exists():
                _check_revision(root, revision)
                if registration is None or "HEAD " + revision.snapshot.commit not in registration:
                    raise RepoPilotError(
                        "candidate_changed",
                        "Worktree registration does not match the managed revision.",
                    )
                # Git removes recursively: the absolute, bounded, link-free target was checked above.
                _git(repository, "worktree", "remove", "--force", str(resolved))
            elif registration is not None:
                raise RepoPilotError(
                    "candidate_changed",
                    "Missing workspace still has a Git registration; inspect manually.",
                )
            manifest.released_revisions.append(revision.revision_id)
            _atomic_write(root / "candidate.json", manifest.model_dump_json(indent=2).encode())
    return candidate_status(root)

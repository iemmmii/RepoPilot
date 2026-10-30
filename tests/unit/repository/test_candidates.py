import hashlib
import json
import subprocess
import sys

import pytest
from conftest import git

from repopilot.domain.errors import RepoPilotError
from repopilot.domain.patches import FileReplacement, PatchProposal
from repopilot.repository.candidates import (
    apply_proposal,
    candidate_status,
    check_export,
    create_candidate,
    export_candidate,
    release_candidate,
)
from repopilot.repository.materialize import read_repository
from repopilot.storage.lease import RunLease


def proposal(content, path="auth.py", original=None):
    return PatchProposal(
        explanation="Return the required expired-token status.",
        replacements=[
            FileReplacement(
                path=path, before_sha256=hashlib.sha256(original).hexdigest(), content=content
            )
        ],
    )


def workspace(root, revision=-1):
    manifest = json.loads((root / "candidate.json").read_bytes())
    return root / "revisions" / manifest["revisions"][revision]["revision_id"] / "workspace"


def test_candidate_isolates_dirty_worktree_index_and_private_files(repository, tmp_path):
    before = read_repository(repository, "HEAD")[1]["auth.py"]
    (repository / "auth.py").write_bytes(before + b"# staged user edit\n")
    git(repository, "add", "auth.py")
    index = (repository / ".git/index").read_bytes()
    (repository / "auth.py").write_bytes(before + b"# unstaged user edit\n")
    working = (repository / "auth.py").read_bytes()
    root = create_candidate(repository, "HEAD", tmp_path / "candidates")
    assert (workspace(root) / "auth.py").read_bytes() == before
    assert not (workspace(root) / ".env").exists()
    result = apply_proposal(root, proposal(before.decode().replace("500", "401"), original=before))
    assert result["outcome"] == "unverified" and result["integrity"] == "valid"
    assert result["revision_count"] == 2 and not result["tests_executed"]
    assert (repository / ".git/index").read_bytes() == index
    assert (repository / "auth.py").read_bytes() == working
    assert not (repository / "IMPORT_MUST_NOT_RUN").exists()
    exported = export_candidate(root, tmp_path / "export")
    assert exported["changed_paths"] == ["auth.py"]
    _, files = read_repository(repository, exported["candidate_ref"])
    assert b"401" in files["auth.py"]
    assert git(repository, "rev-parse", exported["candidate_ref"] + "^") == exported["base_ref"]
    assert (
        git(repository, "show", exported["candidate_ref"] + ":.env")
        == "PRIVATE_TEST_VALUE=must-not-enter-context"
    )
    assert (workspace(root, 0) / "auth.py").read_bytes() == before


@pytest.mark.parametrize(
    "path",
    [
        "../outside.py",
        "/outside.py",
        "C:/evil.py",
        "tests/test_auth.py",
        "test_auth.py",
        "setup.py",
        "new.py",
        ".git/config",
        "auth.py:stream",
        "AUTH.py",
    ],
)
def test_patch_rejects_scope_without_partial_writes(repository, tmp_path, path):
    root = create_candidate(repository, "HEAD", tmp_path / "candidates")
    original = (workspace(root) / "auth.py").read_bytes()
    before = (root / "candidate.json").read_bytes()
    valid = proposal(original.decode().replace("500", "401"), original=original)
    invalid = FileReplacement(path=path, before_sha256="0" * 64, content="x=1\n")
    valid.replacements.append(invalid)
    with pytest.raises(RepoPilotError):
        apply_proposal(root, valid)
    assert (root / "candidate.json").read_bytes() == before
    assert (workspace(root) / "auth.py").read_bytes() == original
    assert candidate_status(root)["orphan_revisions"] == []


@pytest.mark.parametrize("change", ["syntax", "stale", "noop"])
def test_invalid_or_stale_proposals_are_atomic(repository, tmp_path, change):
    root = create_candidate(repository, "HEAD", tmp_path / "candidates")
    original = (workspace(root) / "auth.py").read_bytes()
    content = (
        original.decode() if change == "noop" else "def bad(:\n" if change == "syntax" else "x=1\n"
    )
    item = proposal(content, original=original)
    if change == "stale":
        item.replacements[0].before_sha256 = "0" * 64
    before = (root / "candidate.json").read_bytes()
    with pytest.raises(RepoPilotError) as caught:
        apply_proposal(root, item)
    assert (
        caught.value.code
        == {"syntax": "invalid_python_patch", "stale": "stale_patch", "noop": "empty_patch"}[change]
    )
    assert (root / "candidate.json").read_bytes() == before


def test_hooks_filters_and_user_git_environment_never_run(repository, tmp_path, monkeypatch):
    marker = tmp_path / "MUST_NOT_RUN"
    hook = repository / ".git/hooks/post-checkout"
    hook.write_text('#!/bin/sh\necho executed > "' + marker.as_posix() + '"\n', encoding="utf-8")
    hook.chmod(0o755)
    (repository / ".gitattributes").write_text("*.py filter=trap\n", encoding="utf-8")
    git(repository, "add", ".gitattributes")
    git(repository, "commit", "-m", "add trap attributes")
    for kind in ("clean", "smudge"):
        git(
            repository,
            "config",
            f"filter.trap.{kind}",
            'echo executed > "' + marker.as_posix() + '"',
        )
    git(repository, "config", "filter.trap.required", "true")
    root = create_candidate(repository, "HEAD", tmp_path / "candidates")
    original = (workspace(root) / "auth.py").read_bytes()
    # External index/worktree overrides must not affect controller writes.
    foreign_index = tmp_path / "foreign-index"
    foreign_index.write_bytes(b"must remain unchanged")
    monkeypatch.setenv("GIT_INDEX_FILE", str(foreign_index))
    apply_proposal(root, proposal(original.decode().replace("500", "401"), original=original))
    export_candidate(root, tmp_path / "export")
    assert foreign_index.read_bytes() == b"must remain unchanged"
    assert not marker.exists()


def test_changed_worktree_and_artifacts_revoke_candidate_integrity(repository, tmp_path):
    root = create_candidate(repository, "HEAD", tmp_path / "candidates")
    original = (workspace(root) / "auth.py").read_bytes()
    apply_proposal(root, proposal(original.decode().replace("500", "401"), original=original))
    (workspace(root) / "auth.py").write_text("x=1\n", encoding="utf-8")
    assert candidate_status(root)["integrity"] == "unverifiable"
    with pytest.raises(RepoPilotError) as caught:
        export_candidate(root, tmp_path / "export")
    assert caught.value.code == "candidate_changed"


def test_lock_contention_and_orphan_revision_not_promoted(repository, tmp_path):
    root = create_candidate(repository, "HEAD", tmp_path / "candidates")
    original = (workspace(root) / "auth.py").read_bytes()
    item = proposal(original.decode().replace("500", "401"), original=original)
    with RunLease(root), pytest.raises(RepoPilotError) as caught:
        apply_proposal(root, item)
    assert caught.value.code == "run_locked"
    orphan = root / "revisions" / ("a" * 32)
    orphan.mkdir()
    assert candidate_status(root)["orphan_revisions"] == [orphan.name]
    assert candidate_status(root)["revision_count"] == 1


def test_exported_patch_applies_exact_bytes_without_final_newline(repository, tmp_path):
    original = b"answer = 500"
    (repository / "no newline.py").write_bytes(original)
    git(repository, "add", "no newline.py")
    git(repository, "commit", "-m", "no final newline")
    root = create_candidate(repository, "HEAD", tmp_path / "candidates")
    apply_proposal(root, proposal("answer = 401", "no newline.py", original))
    export_candidate(root, tmp_path / "export")
    # Apply only in this disposable fixture; production candidate construction uses raw blobs.
    subprocess.run(
        ["git", "-C", str(repository), "apply", "--check", str(tmp_path / "export/patch.diff")],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "apply", str(tmp_path / "export/patch.diff")],
        check=True,
        capture_output=True,
    )
    assert (repository / "no newline.py").read_bytes() == b"answer = 401"


def test_process_exit_before_publication_keeps_old_revision_and_counts_orphan(repository, tmp_path):
    root = create_candidate(repository, "HEAD", tmp_path / "candidates")
    original = (workspace(root) / "auth.py").read_bytes()
    item = proposal(original.decode().replace("500", "401"), original=original)
    payload = tmp_path / "proposal.json"
    payload.write_bytes(item.model_dump_json().encode())
    before = (root / "candidate.json").read_bytes()
    script = """
import os,sys
from pathlib import Path
import repopilot.repository.candidates as module
write=module._atomic_write
def stop(path,data):
    if path.name=='candidate.json': os._exit(91)
    write(path,data)
module._atomic_write=stop
module.apply_proposal(Path(sys.argv[1]),module.read_proposal(Path(sys.argv[2])))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(root), str(payload)], capture_output=True, timeout=30
    )
    assert result.returncode == 91, result.stderr.decode(errors="replace")
    assert (root / "candidate.json").read_bytes() == before
    interrupted = candidate_status(root)
    assert interrupted["integrity"] == "valid" and len(interrupted["orphan_revisions"]) == 1
    assert interrupted["revision_count"] == 1
    resumed = apply_proposal(root, item)
    assert (
        resumed["revision_count"] == 2
        and resumed["orphan_revisions"] == interrupted["orphan_revisions"]
    )


def test_release_only_managed_worktrees_preserves_repository_and_audit(repository, tmp_path):
    head = git(repository, "rev-parse", "HEAD")
    root = create_candidate(repository, "HEAD", tmp_path / "candidates")
    original = (workspace(root) / "auth.py").read_bytes()
    apply_proposal(root, proposal(original.decode().replace("500", "401"), original=original))
    paths = [workspace(root, index) for index in (0, 1)]
    result = release_candidate(root)
    assert result["retired"] and result["integrity"] == "valid"
    assert len(result["released_revisions"]) == 2
    assert all(not path.exists() for path in paths)
    assert git(repository, "rev-parse", "HEAD") == head
    assert (repository / "auth.py").is_file()
    assert (paths[1].parent / "patch.diff").is_file()
    assert release_candidate(root) == result
    with pytest.raises(RepoPilotError) as caught:
        apply_proposal(root, proposal("x=1\n", original=original))
    assert caught.value.code == "candidate_retired"


def test_symlink_or_junction_in_candidate_refuses_cleanup(repository, tmp_path):
    root = create_candidate(repository, "HEAD", tmp_path / "candidates")
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "important.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    link = workspace(root) / "foreign"
    if sys.platform == "win32":
        import _winapi

        try:
            _winapi.CreateJunction(str(outside), str(link))
        except PermissionError:
            pytest.skip("Host policy prevents creating a test junction; Linux CI covers symlinks.")
    else:
        link.symlink_to(outside, target_is_directory=True)
    assert candidate_status(root)["integrity"] == "unverifiable"
    with pytest.raises(RepoPilotError) as caught:
        release_candidate(root)
    assert caught.value.code == "candidate_changed"
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_case_colliding_directory_names_rejected_before_worktree(repository, tmp_path):
    from repopilot.repository.materialize import validate_paths

    for names in (["Pkg/a.py", "pkg/b.py"], ["a", "a/b.py"]):
        with pytest.raises(RepoPilotError) as caught:
            validate_paths(names)
        assert caught.value.code == "snapshot_path_collision"


def test_old_export_is_historical_after_next_revision(repository, tmp_path):
    root = create_candidate(repository, "HEAD", tmp_path / "candidates")
    original = (workspace(root) / "auth.py").read_bytes()
    first = original.decode().replace("500", "401")
    apply_proposal(root, proposal(first, original=original))
    export_candidate(root, tmp_path / "export")
    before = (tmp_path / "export/patch.diff").read_bytes()
    assert check_export(root, tmp_path / "export")["applicability"] == "current"
    apply_proposal(root, proposal(first.replace("401", "402"), original=first.encode()))
    result = check_export(root, tmp_path / "export")
    assert (
        result["applicability"] == "superseded" and result["exported_ref"] != result["current_ref"]
    )
    assert result["historical_export_integrity"] == "valid"
    assert (tmp_path / "export/patch.diff").read_bytes() == before
    metadata_path = tmp_path / "export/candidate.json"
    metadata = metadata_path.read_bytes()
    changed = json.loads(metadata)
    changed["changed_paths"] = ["wrong.py"]
    metadata_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(RepoPilotError) as caught:
        check_export(root, tmp_path / "export")
    assert caught.value.code == "candidate_export_mismatch"
    metadata_path.write_bytes(metadata)
    (tmp_path / "export/patch.diff").write_bytes(b"tampered")
    with pytest.raises(RepoPilotError) as caught:
        check_export(root, tmp_path / "export")
    assert caught.value.code == "invalid_candidate_export"


def test_corrupted_middle_revision_refuses_new_publication(repository, tmp_path):
    root = create_candidate(repository, "HEAD", tmp_path / "candidates")
    content = (workspace(root) / "auth.py").read_bytes()
    for value in (b"401", b"402"):
        updated = (
            content.replace(b"500", value) if value == b"401" else content.replace(b"401", value)
        )
        apply_proposal(root, proposal(updated.decode(), original=content))
        content = updated
    before = (root / "candidate.json").read_bytes()
    (workspace(root, 1).parent / "proposal.json").write_bytes(b"tampered")
    with pytest.raises(RepoPilotError) as caught:
        apply_proposal(root, proposal(content.decode().replace("402", "403"), original=content))
    assert caught.value.code == "candidate_changed"
    assert (root / "candidate.json").read_bytes() == before
    with pytest.raises(RepoPilotError):
        export_candidate(root, tmp_path / "export")


def test_orphans_consume_revision_budget_without_becoming_current(repository, tmp_path):
    root = create_candidate(repository, "HEAD", tmp_path / "candidates")
    content = (workspace(root) / "auth.py").read_bytes()
    for index in range(10):
        (root / "revisions" / f"{index:032x}").mkdir()
    with pytest.raises(RepoPilotError) as caught:
        apply_proposal(root, proposal(content.decode().replace("500", "401"), original=content))
    assert caught.value.code == "candidate_budget_exhausted"
    assert candidate_status(root)["revision_count"] == 1


def test_release_can_continue_after_removal_before_checkpoint(repository, tmp_path, monkeypatch):
    import repopilot.repository.candidates as module

    root = create_candidate(repository, "HEAD", tmp_path / "candidates")
    content = (workspace(root) / "auth.py").read_bytes()
    apply_proposal(root, proposal(content.decode().replace("500", "401"), original=content))
    call = module._git

    def stop_after_removal(repo, *args, **kwargs):
        result = call(repo, *args, **kwargs)
        if args[:2] == ("worktree", "remove"):
            raise RuntimeError("simulated process interruption after Git removal")
        return result

    monkeypatch.setattr(module, "_git", stop_after_removal)
    with pytest.raises(RuntimeError):
        release_candidate(root)
    assert json.loads((root / "candidate.json").read_bytes())["retired"]
    assert not workspace(root, 0).exists()
    monkeypatch.setattr(module, "_git", call)
    result = release_candidate(root)
    assert result["retired"] and result["integrity"] == "valid"
    assert len(result["released_revisions"]) == 2

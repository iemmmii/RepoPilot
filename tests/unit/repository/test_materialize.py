from pathlib import Path

import pytest

from repopilot.domain.errors import RepoPilotError
from repopilot.repository.materialize import (
    directory_digest,
    freeze_suite,
    materialize_repository,
    safe_relative,
    write_files,
)


@pytest.mark.parametrize(
    "name",
    ["../x", "/x", "a/../x", "a//x", "a\\x", "C:/x", "a:x", "a,bc", "NUL.txt", "a. ", "a\nx"],
)
def test_rejects_cross_platform_unsafe_paths(name):
    with pytest.raises(RepoPilotError):
        safe_relative(name)


def test_materialization_reads_commit_without_import_or_dirty_files(repository, tmp_path):
    (repository / "auth.py").write_text("raise RuntimeError('dirty')", encoding="utf-8")
    (repository / "untracked.py").write_text("private", encoding="utf-8")
    destination = tmp_path / "snapshot"
    snapshot = materialize_repository(repository, "HEAD", destination)
    assert "def expired_token" in (destination / "auth.py").read_text(encoding="utf-8")
    assert not (destination / ".env").exists()
    assert not (destination / ".git").exists()
    assert not (destination / "untracked.py").exists()
    assert not (repository / "IMPORT_MUST_NOT_RUN").exists()
    assert snapshot.source_digest == directory_digest(destination)
    assert ".env" in snapshot.excluded_paths


def test_case_collision_is_rejected_before_second_write(tmp_path):
    with pytest.raises(RepoPilotError, match="collide"):
        write_files(tmp_path / "output", {"A.py": b"one", "a.py": b"two"})


def test_materialization_rejects_git_symlink(repository, tmp_path):
    import subprocess

    blob = subprocess.check_output(
        ["git", "-C", str(repository), "hash-object", "-w", "--stdin"], input=b"../private"
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "update-index",
            "--add",
            "--cacheinfo",
            "120000," + blob.decode().strip() + ",outside",
        ],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "core.hooksPath=",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            "add symlink object",
        ],
        check=True,
        capture_output=True,
    )
    with pytest.raises(RepoPilotError, match="Symlinks"):
        materialize_repository(repository, "HEAD", tmp_path / "snapshot")


def test_freezing_preserves_crlf_and_digest(tmp_path):
    source = tmp_path / "tests"
    source.mkdir()
    (source / "test_clock.py").write_bytes(b"import unittest\r\n")
    suite = freeze_suite(source, tmp_path / "frozen")
    assert suite.files["test_clock.py"] == "import unittest\r\n"
    assert (tmp_path / "frozen/test_clock.py").read_bytes() == b"import unittest\r\n"
    (source / "test_clock.py").write_text("changed", encoding="utf-8")
    assert (tmp_path / "frozen/test_clock.py").read_bytes() != (
        source / "test_clock.py"
    ).read_bytes()


@pytest.mark.parametrize(
    "name,content",
    [("secret.key", b"no"), ("test_bad.py", b"\xff"), ("test_big.py", b"x" * 128001)],
)
def test_invalid_suite_stops_before_execution(tmp_path, name, content):
    source = tmp_path / "tests"
    source.mkdir()
    (source / name).write_bytes(content)
    with pytest.raises(RepoPilotError):
        freeze_suite(source, tmp_path / "frozen")


def test_directory_digest_is_portable_over_mixed_case_paths(tmp_path):
    entries = write_files(
        tmp_path / "input", {"Zoo.py": b"z", "alpha.py": b"a", "a/b.py": b"nested"}
    )
    from repopilot.domain.verification import fingerprint

    assert directory_digest(tmp_path / "input") == fingerprint(
        [entry.model_dump() for entry in entries]
    )
    assert Path(tmp_path / "input/a/b.py").is_file()

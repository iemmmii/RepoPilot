from pathlib import Path

import pytest
from conftest import git

from repopilot.domain.errors import RepoPilotError
from repopilot.domain.models import Issue
from repopilot.repository.snapshot import inspect_repository


def issue():
    return Issue(
        title="expired token returns 500", body="Expected status 401.", repository="example/demo"
    )


def test_snapshot_ignores_dirty_files_and_never_imports(repository, tmp_path):
    before = git(repository, "rev-parse", "HEAD")
    (repository / "auth.py").write_text("DIRTY_NOT_IN_SNAPSHOT = True\n", encoding="utf-8")
    (repository / "untracked.py").write_text("UNTRACKED = True\n", encoding="utf-8")
    context = inspect_repository(repository, issue())
    rendered = context.model_dump_json()
    assert context.base_commit == before
    assert "expired_token" in rendered
    assert "DIRTY_NOT_IN_SNAPSHOT" not in rendered
    assert "untracked.py" not in rendered
    assert "PRIVATE_TEST_VALUE" not in rendered
    assert not (repository / "IMPORT_MUST_NOT_RUN").exists()
    assert not (Path.cwd() / "IMPORT_MUST_NOT_RUN").exists()


def test_issue_repository_mismatch_is_rejected(repository):
    with pytest.raises(RepoPilotError, match="origin disagree"):
        inspect_repository(repository, Issue(title="issue", repository="other/project"))


def test_short_file_keeps_related_checks_outside_the_strongest_match(repository):
    content = "def original_check():\n    return 'age < max_age'\n" + "# spacing\n" * 100
    content += "def expired_token():\n    return 'expired token 500 status'\n"
    (repository / "auth.py").write_text(content, encoding="utf-8")
    git(repository, "add", "auth.py")
    git(repository, "commit", "-m", "separate related checks")
    context = inspect_repository(repository, issue())
    excerpt = next(value for value in context.excerpts if value.path == "auth.py")
    assert "original_check" in excerpt.content and "expired_token" in excerpt.content
    assert excerpt.start_line == 1 and excerpt.end_line == len(content.splitlines())

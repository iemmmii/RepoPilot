import socket
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def no_test_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("Unit tests must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", deny)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        [
            "git",
            "-c",
            "core.hooksPath=",
            "-c",
            "commit.gpgsign=false",
            "-C",
            str(root),
            *args,
        ],
        text=True,
    ).strip()


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "--initial-branch=main")
    git(root, "config", "user.name", "RepoPilot Test")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "remote", "add", "origin", "https://github.com/example/demo.git")
    (root / "auth.py").write_text(
        "from pathlib import Path\n"
        "Path('IMPORT_MUST_NOT_RUN').touch()\n\n"
        "def expired_token(age):\n"
        "    return 500 if age > 10 else 200\n",
        encoding="utf-8",
    )
    (root / "tests").mkdir()
    (root / "tests/test_auth.py").write_text(
        "def test_expired_token():\n    assert False\n",
        encoding="utf-8",
    )
    (root / ".env").write_text("PRIVATE_TEST_VALUE=must-not-enter-context\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "test fixture")
    return root

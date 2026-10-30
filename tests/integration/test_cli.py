import hashlib
import json
from pathlib import Path

from repopilot.cli import main
from repopilot.domain.models import Issue
from repopilot.repository.materialize import read_repository


def issue():
    return Issue(
        title="expired token returns 500", body="Expected status 401.", repository="example/demo"
    )


def test_cli_offline_entry_point(repository, tmp_path, capsys):
    issue_file = tmp_path / "issue.json"
    issue_file.write_text(issue().model_dump_json(), encoding="utf-8")
    assert (
        main(
            [
                "investigate",
                "--issue-file",
                str(issue_file),
                "--repo",
                str(repository),
                "--provider",
                "lexical",
                "--output-dir",
                str(tmp_path / "runs"),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert Path(result["report"]).is_file()
    assert result["tests_executed"] is False


def test_cli_missing_credentials_is_explicit(repository, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    issue_file = tmp_path / "issue.json"
    issue_file.write_text(issue().model_dump_json(), encoding="utf-8")
    assert main(["investigate", "--issue-file", str(issue_file), "--repo", str(repository)]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "missing_api_key"


def test_candidate_cli_create_apply_export(repository, tmp_path, capsys):
    assert (
        main(
            [
                "candidate",
                "create",
                "--repo",
                str(repository),
                "--base-ref",
                "HEAD",
                "--output-dir",
                str(tmp_path / "candidates"),
            ]
        )
        == 0
    )
    created = json.loads(capsys.readouterr().out)
    original = read_repository(repository, "HEAD")[1]["auth.py"]
    proposal = tmp_path / "proposal.json"
    proposal.write_text(
        json.dumps(
            {
                "explanation": "controlled CLI patch",
                "replacements": [
                    {
                        "path": "auth.py",
                        "before_sha256": hashlib.sha256(original).hexdigest(),
                        "content": original.decode().replace("500", "401"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert main(["candidate", "apply", created["candidate_dir"], "--proposal", str(proposal)]) == 0
    changed = json.loads(capsys.readouterr().out)
    assert changed["revision_count"] == 2
    assert (
        main(
            [
                "candidate",
                "export",
                created["candidate_dir"],
                "--output-dir",
                str(tmp_path / "export"),
            ]
        )
        == 0
    )
    exported = json.loads(capsys.readouterr().out)
    assert exported["candidate_ref"] == changed["candidate_ref"]
    assert exported["outcome"] == "unverified"

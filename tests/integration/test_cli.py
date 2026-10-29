import json
from pathlib import Path

from repopilot.cli import main
from repopilot.domain.models import Issue


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

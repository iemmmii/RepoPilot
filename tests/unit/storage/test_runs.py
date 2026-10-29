import json

from repopilot.domain.models import Issue
from repopilot.providers.lexical import LexicalProvider
from repopilot.storage.runs import read_status
from repopilot.workflow.investigation import investigate


def issue():
    return Issue(
        title="expired token returns 500", body="Expected status 401.", repository="example/demo"
    )


def test_offline_report_is_versioned_and_checks_artifacts(repository, tmp_path):
    run = investigate(issue(), repository, tmp_path / "runs", LexicalProvider())
    status = read_status(run)
    assert status["outcome"] == "investigated"
    assert status["tests_executed"] is False
    assert status["usage"]["requests"] == 0
    assert status["artifact_integrity"] == "valid"
    assert len(status["artifacts"]) == 4
    report = (run / "investigation.md").read_text(encoding="utf-8")
    assert "not executed" in report
    (run / "analysis.json").write_text("{}", encoding="utf-8")
    assert read_status(run)["artifact_integrity"] == "unverifiable"


def test_status_rejects_out_of_root_artifact(repository, tmp_path):
    run = investigate(issue(), repository, tmp_path / "runs", LexicalProvider())
    manifest = run / "manifest.json"
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    saved["artifacts"][0]["path"] = "../outside.json"
    manifest.write_text(json.dumps(saved), encoding="utf-8")
    assert read_status(run)["artifact_integrity"] == "unverifiable"

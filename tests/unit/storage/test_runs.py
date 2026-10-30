import json

import pytest

from repopilot.domain.errors import RepoPilotError
from repopilot.domain.models import Issue, Usage
from repopilot.providers.lexical import LexicalProvider
from repopilot.storage.runs import RunStore, read_status
from repopilot.workflow.investigation import investigate


def issue():
    return Issue(
        title="expired token returns 500", body="Expected status 401.", repository="example/demo"
    )


def test_original_investigation_wire_schema_is_preserved(tmp_path):
    store = RunStore(tmp_path / "runs", Usage(provider="test"))
    store.finish()
    wire = json.loads((store.root / "manifest.json").read_bytes())
    assert wire["schema_version"] == "0.1"
    assert "stages" not in wire and "command_attempts" not in wire


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


def test_artifact_cannot_overwrite_the_run_checkpoint(tmp_path):
    store = RunStore(tmp_path / "runs", Usage(provider="test"))
    original = (store.root / "manifest.json").read_bytes()
    with pytest.raises(RepoPilotError) as caught:
        store.add("manifest.json", "{}")
    assert caught.value.code == "invalid_artifact_path"
    assert (store.root / "manifest.json").read_bytes() == original

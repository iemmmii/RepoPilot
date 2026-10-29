import json

import pytest

from repopilot.domain.errors import RepoPilotError
from repopilot.domain.models import Analysis, Finding, Issue, Usage
from repopilot.workflow.investigation import investigate


def issue():
    return Issue(
        title="expired token returns 500", body="Expected status 401.", repository="example/demo"
    )


def test_invalid_model_reference_leaves_failed_run(repository, tmp_path):
    class InvalidProvider:
        usage = Usage(provider="test")

        def analyze(self, issue, context):
            return Analysis(
                summary="hypothesis",
                findings=[
                    Finding(
                        path="../../secret.py",
                        start_line=1,
                        end_line=2,
                        reason="invalid reference",
                    )
                ],
            )

    with pytest.raises(RepoPilotError) as caught:
        investigate(issue(), repository, tmp_path / "runs", InvalidProvider())
    assert caught.value.code == "invalid_code_reference"
    manifests = list((tmp_path / "runs").glob("*/manifest.json"))
    assert len(manifests) == 1
    saved = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert saved["execution_status"] == "failed"
    assert saved["outcome"] is None
    assert saved["error_code"] == "invalid_code_reference"
    assert {a["path"] for a in saved["artifacts"]} == {"issue.json", "repo_context.json"}

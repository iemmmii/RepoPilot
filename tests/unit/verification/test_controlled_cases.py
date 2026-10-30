import ast

from repopilot.domain.verification import Oracle, fingerprint
from repopilot.evaluation.controlled import CASES, build_case


def test_controlled_protocol_is_frozen_and_expected_cases_not_dropped(tmp_path):
    assert [case[0] for case in CASES] == ["C01", "C02", "C03"]
    for case in CASES:
        fixture = build_case(tmp_path / case[0], case[0])
        options = fixture["options"]
        oracle = Oracle.model_validate_json(options["oracle_path"].read_bytes())
        source = (options["suite_path"] / "test_contract.py").read_bytes().decode()
        ast.parse(source)  # Syntax validation only; no target import on the host.
        assert oracle.suite_hash == fingerprint({"test_contract.py": source})
        assert fixture["expected"] == case[-1]


def test_evaluation_retains_failed_cases_and_run_references(tmp_path):
    import json

    from repopilot.domain.errors import RepoPilotError
    from repopilot.domain.verification import SandboxPolicy
    from repopilot.evaluation.controlled import evaluate

    class Unavailable:
        policy = SandboxPolicy()

        def prepare(self, harness):
            raise RepoPilotError("docker_unavailable", "Controlled unavailable runtime.")

    root = evaluate(tmp_path / "evaluations", runner=Unavailable())
    summary = json.loads((root / "summary.json").read_bytes())
    assert summary["matched"] == 0 and summary["total"] == 3
    assert all(
        case["observed"] == "evaluation_error" and len(case["retained_run_dirs"]) == 1
        for case in summary["cases"]
    )

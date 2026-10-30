import json

from pydantic import ValidationError

from repopilot.domain.verification import TestCaseObservation, TestObservation
from repopilot.sandbox.docker import CommandResult


def observe(result: CommandResult) -> TestObservation:
    command = result.evidence
    observation = TestObservation(
        command_evidence_id=command.evidence_id,
        source_digest=command.source_digest,
        suite_hash=command.suite_hash,
        environment_digest=command.environment_digest,
        protocol_valid=False,
    )
    if command.termination != "exited" or not command.cleanup_succeeded or command.logs_truncated:
        observation.problems.append(
            "Command did not complete with bounded logs and confirmed cleanup."
        )
        return observation
    try:
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict) or payload.get("protocol") != "repopilot-unittest-v1":
            raise ValueError("Invalid adapter protocol")
        tests = [TestCaseObservation.model_validate(item) for item in payload["tests"]]
        if type(payload["tests_run"]) is not int or payload["tests_run"] != len(tests):
            raise ValueError("Run count disagrees with observations")
        ids = [test.test_id for test in tests]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate test IDs")
        expected_exit = (
            1
            if any(test.status in {"failed", "error", "unexpected_success"} for test in tests)
            else 0
        )
        if command.exit_code != expected_exit:
            raise ValueError("Process exit disagrees with observations")
        observation.tests = tests
        observation.protocol_valid = True
    except (ValueError, TypeError, KeyError, ValidationError, UnicodeDecodeError):
        observation.problems.append(
            "Frozen-suite adapter output is missing, malformed or inconsistent."
        )
    return observation

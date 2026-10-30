import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from repopilot.domain.verification import (
    CommandEvidence,
    Oracle,
)
from repopilot.domain.verification import (
    TestCaseObservation as CaseObservation,
)
from repopilot.domain.verification import (
    TestObservation as Observation,
)
from repopilot.sandbox.docker import CommandResult
from repopilot.verification.gate import assess
from repopilot.verification.observations import observe


def command(source="base", code=1, **changes):
    now = datetime.now(UTC)
    return CommandEvidence(
        evidence_id=uuid4().hex,
        run_id="run",
        argv=["python"],
        source_digest=source,
        suite_hash="a" * 64,
        environment_digest="environment",
        started_at=now,
        ended_at=now,
        exit_code=code,
        termination="exited",
        stdout_bytes=100,
        stderr_bytes=0,
        logs_truncated=False,
        cleanup_succeeded=True,
    ).model_copy(update=changes)


def oracle(**changes):
    return Oracle(
        criterion_id="AC-1",
        requirement="Expired credentials must be rejected.",
        issue_url="https://example.invalid/issues/1",
        source_refs=["controlled-protocol-v1"],
        suite_hash="a" * 64,
        target_tests=["test_auth.Repro.test_expired"],
        regression_tests=["test_auth.Repro.test_current"],
        assessment_status="accepted",
        assessed_by="controlled fixture protocol",
        assessment_basis="Independent frozen expected status protocol.",
    ).model_copy(update=changes)


def observation(cmd, target="failed", regression="passed"):
    return Observation(
        command_evidence_id=cmd.evidence_id,
        source_digest=cmd.source_digest,
        suite_hash=cmd.suite_hash,
        environment_digest=cmd.environment_digest,
        protocol_valid=True,
        tests=[
            CaseObservation(test_id="test_auth.Repro.test_expired", status=target),
            CaseObservation(test_id="test_auth.Repro.test_current", status=regression),
        ],
    )


def evaluate(
    base=None, candidate=None, base_command=None, candidate_command=None, selected_oracle=None
):
    base_command = base_command or command()
    candidate_command = candidate_command or command("candidate", 0)
    return assess(
        oracle=selected_oracle or oracle(),
        base=base or observation(base_command),
        base_command=base_command,
        candidate=candidate or observation(candidate_command, target="passed"),
        candidate_command=candidate_command,
        expected_base_digest="base",
        expected_candidate_digest="candidate",
        requirement_digest="requirement-v1",
        suite_hash="a" * 64,
        environment_digest="environment",
    )


def test_matching_fail_pass_can_only_support_limited_candidate_scope():
    result = evaluate()
    assert result.outcome == "candidate_verified"
    assert result.reproduction_status == "reproduced"
    assert result.requested_scope == "verify_candidate"
    assert any("not_checked" in limit for limit in result.limitations)


@pytest.mark.parametrize("status", ["provisional", "rejected"])
def test_fail_pass_does_not_upgrade_an_unaccepted_oracle(status):
    assert evaluate(selected_oracle=oracle(assessment_status=status)).outcome == "needs_human"


@pytest.mark.parametrize("status", ["skipped", "error", "xfailed", "unexpected_success"])
def test_skip_import_errors_and_expected_failures_are_not_reproduction(status):
    cmd = command()
    assert (
        evaluate(base=observation(cmd, target=status), base_command=cmd).outcome
        == "environment_blocked"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"source_digest": "old-candidate"},
        {"suite_hash": "b" * 64},
        {"environment_digest": "old-env"},
        {"command_evidence_id": "unknown"},
        {"protocol_valid": False},
        {"tests": []},
    ],
)
def test_stale_or_missing_observations_cannot_support_candidate(change):
    cmd = command("candidate", 0)
    candidate = observation(cmd, target="passed").model_copy(update=change)
    assert evaluate(candidate=candidate, candidate_command=cmd).outcome == "environment_blocked"


@pytest.mark.parametrize(
    "change",
    [
        {"termination": "timed_out"},
        {"termination": "output_limit"},
        {"termination": "oom_killed"},
        {"cleanup_succeeded": False},
        {"logs_truncated": True},
        {"run_id": "another-run"},
        {"exit_code": 1},
    ],
)
def test_bad_command_results_do_not_produce_success(change):
    cmd = command("candidate", 0, **change)
    assert (
        evaluate(candidate=observation(cmd, target="passed"), candidate_command=cmd).outcome
        == "environment_blocked"
    )


def test_no_base_failure_is_not_reproduced():
    cmd = command(exit_code=0)
    assert (
        evaluate(base=observation(cmd, target="passed"), base_command=cmd).outcome
        == "not_reproduced"
    )


def test_regression_failure_on_base_is_not_the_target_bug():
    cmd = command()
    assert (
        evaluate(base=observation(cmd, regression="failed"), base_command=cmd).outcome
        == "environment_blocked"
    )


def test_actual_container_exit_is_checked_again_at_gate():
    cmd = command(exit_code=0)
    assert evaluate(base=observation(cmd), base_command=cmd).outcome == "environment_blocked"


@pytest.mark.parametrize(
    "stdout,exit_code",
    [
        (b"{}", 0),
        (b"[]", 0),
        (b"not json", 0),
        (b'{"protocol":"repopilot-unittest-v1","tests_run":0,"tests":[]}', 1),
    ],
)
def test_malformed_adapter_result_is_not_a_business_observation(stdout, exit_code):
    assert not observe(CommandResult(command(exit_code=exit_code), stdout, b"")).protocol_valid


def test_adapter_checks_count_and_duplicate_ids():
    cmd = command(exit_code=0)
    tests = [{"test_id": "test_x", "status": "passed"}] * 2
    for count in (1, 2):
        raw = json.dumps(
            {"protocol": "repopilot-unittest-v1", "tests_run": count, "tests": tests}
        ).encode()
        assert not observe(CommandResult(cmd, raw, b"")).protocol_valid


def test_accepted_oracle_cannot_omit_assessment_provenance():
    data = oracle().model_dump()
    data["assessed_by"] = None
    with pytest.raises(ValidationError):
        Oracle.model_validate(data)

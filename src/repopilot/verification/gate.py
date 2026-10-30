from repopilot.domain.verification import (
    CommandEvidence,
    Oracle,
    TestObservation,
    VerificationAssessment,
    fingerprint,
)


def assess(
    *,
    oracle: Oracle,
    base: TestObservation,
    base_command: CommandEvidence,
    candidate: TestObservation | None = None,
    candidate_command: CommandEvidence | None = None,
    expected_base_digest: str,
    expected_candidate_digest: str | None,
    suite_hash: str,
    environment_digest: str,
    requirement_digest: str,
) -> VerificationAssessment:
    scope = "verify_candidate" if expected_candidate_digest is not None else "reproduce"
    reasons = []
    stability = "not_checked"
    commands = [base_command] + ([candidate_command] if candidate_command else [])
    input_hash = fingerprint(
        {
            "oracle": oracle.model_dump(),
            "requirement": requirement_digest,
            "base": expected_base_digest,
            "candidate": expected_candidate_digest,
            "suite": suite_hash,
            "environment": environment_digest,
            "gate_policy": "frozen-unittest-v1",
        }
    )

    def finish(outcome, reproduction):
        return VerificationAssessment(
            requested_scope=scope,
            outcome=outcome,
            reproduction_status=reproduction,
            input_fingerprint=input_hash,
            oracle_status=oracle.assessment_status,
            reasons=reasons,
            command_evidence_ids=[item.evidence_id for item in commands],
            stability=stability,
            limitations=[
                "Only the frozen target and regression IDs are assessed; this is not full project regression.",
                "No independent patch review or complete repair verdict; resolved_verified is unavailable.",
                f"Stability: {stability}; no general flakiness guarantee.",
                "The adapter supports controlled repositories, not hostile Python manipulating its test interpreter.",
            ],
        )

    if oracle.suite_hash != suite_hash:
        reasons.append("Oracle does not bind the executed frozen suite.")
        return finish("environment_blocked", "environment_blocked")
    pairs = [(base, base_command, expected_base_digest)]
    if scope == "verify_candidate":
        if candidate is None or candidate_command is None:
            reasons.append("Candidate command evidence is missing.")
            return finish("environment_blocked", "environment_blocked")
        pairs.append((candidate, candidate_command, expected_candidate_digest))
    selection = set(oracle.target_tests + oracle.regression_tests)
    for observation, command, digest in pairs:
        if (
            not observation.protocol_valid
            or command.termination != "exited"
            or command.logs_truncated
            or not command.cleanup_succeeded
            or observation.command_evidence_id != command.evidence_id
            or observation.source_digest != digest
            or command.source_digest != digest
            or observation.suite_hash != suite_hash
            or command.suite_hash != suite_hash
            or observation.environment_digest != environment_digest
            or command.environment_digest != environment_digest
            or command.run_id != base_command.run_id
        ):
            reasons.append("Command evidence is incomplete or bound to different inputs.")
            return finish("environment_blocked", "environment_blocked")
        tests = {test.test_id: test.status for test in observation.tests}
        if len(tests) != len(observation.tests) or set(tests) != selection:
            reasons.append("Selected test IDs were missing, duplicated, empty or unexpected.")
            return finish("environment_blocked", "environment_blocked")
        if any(
            value in {"error", "skipped", "xfailed", "unexpected_success"}
            for value in tests.values()
        ):
            reasons.append(
                "Required tests errored or were skipped; this is not a target assertion result."
            )
            return finish("environment_blocked", "environment_blocked")
        if command.exit_code != (1 if "failed" in tests.values() else 0):
            reasons.append("Actual container exit code disagrees with the test observations.")
            return finish("environment_blocked", "environment_blocked")
    baseline = {test.test_id: test.status for test in base.tests}
    if (
        candidate is not None
        and expected_candidate_digest == expected_base_digest
        and {test.test_id: test.status for test in candidate.tests} != baseline
    ):
        stability = "unstable"
        reasons.append(
            "Identical controlled source/suite/environment inputs produced conflicting observations."
        )
        return finish("needs_human", "needs_human")
    if any(baseline[test] != "passed" for test in oracle.regression_tests):
        reasons.append("Base regression checks failed; target behavior was not isolated.")
        return finish("environment_blocked", "environment_blocked")
    if any(baseline[test] != "failed" for test in oracle.target_tests):
        reasons.append("Not all required target assertions failed on the fixed base.")
        return finish("not_reproduced", "not_reproduced")
    if oracle.assessment_status != "accepted":
        reasons.append("Observed fail/pass cannot replace an accepted independent Oracle.")
        return finish("needs_human", "needs_human")
    if candidate is not None and any(test.status != "passed" for test in candidate.tests):
        reasons.append(
            "Base target failure was reproduced, but candidate assertions did not all pass."
        )
        return finish("reproduced", "reproduced")
    reasons.append(
        "Fixed base target assertions failed while the frozen regression selection passed."
    )
    if candidate is not None:
        reasons.append("The same frozen selection passed on the specified candidate snapshot.")
        return finish("candidate_verified", "reproduced")
    return finish("reproduced", "reproduced")

from collections import Counter

from repopilot.domain.models import Issue
from repopilot.domain.verification import SourceSnapshot, TestObservation, VerificationAssessment
from repopilot.reporting.investigation import _plain


def render_verification(
    issue: Issue,
    snapshots: dict[str, SourceSnapshot],
    observations: dict[str, TestObservation],
    assessment: VerificationAssessment,
) -> str:
    lines = [
        "# RepoPilot controlled verification",
        "",
        f"Issue: {_plain(issue.title)}",
        "",
        f"Requested scope: `{assessment.requested_scope}`",
        f"Outcome: **{assessment.outcome}**",
        f"Reproduction: `{assessment.reproduction_status}`",
        f"Oracle: `{assessment.oracle_status}`",
        f"Input fingerprint: `{assessment.input_fingerprint}`",
        "",
        "| Snapshot | Commit | Source digest | Test observations |",
        "| --- | --- | --- | --- |",
    ]
    for name, snapshot in snapshots.items():
        counts = Counter(test.status for test in observations[name].tests)
        lines.append(f"| {name} | {snapshot.commit} | {snapshot.source_digest} | {dict(counts)} |")
    lines.extend(["", "## Assessment", ""])
    lines.extend("- " + _plain(reason) for reason in assessment.reasons)
    lines.extend(["", "## Limits", ""])
    lines.extend("- " + _plain(limit) for limit in assessment.limitations)
    lines.extend(
        [
            "",
            "Model requests: 0. This is a fixed-ref verification, not model-generated repair.",
            "Command IDs: " + ", ".join(assessment.command_evidence_ids),
            "",
            "Saved artifacts describe these historical inputs. No live-worktree or repair success claim.",
            "",
        ]
    )
    return "\n".join(lines)

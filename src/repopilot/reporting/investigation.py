import html
import re

from repopilot.domain.models import Analysis, Issue, RepositoryContext, Usage


def _plain(value: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()#!|])", r"\\\1", html.escape(value))


def render_report(
    issue: Issue, context: RepositoryContext, analysis: Analysis, usage: Usage
) -> str:
    lines = [
        "# RepoPilot investigation",
        "",
        f"Issue: {_plain(issue.title)}",
        "",
        f"Base commit: `{context.base_commit}`",
        f"Tree: `{context.tree_oid}`",
        f"Provider: `{usage.provider}`",
        "",
        "**Outcome: investigated. No target code or tests were executed.**",
        "",
        "This report describes the pinned Git commit, excluding working-tree changes.",
        "",
        "## Investigation summary (unverified)",
        "",
        _plain(analysis.summary),
        "",
        "## Code references",
        "",
    ]
    for finding in analysis.findings:
        lines.extend(
            [
                f"- {_plain(finding.path)}:{finding.start_line}-{finding.end_line}: {_plain(finding.reason)}",
            ]
        )
    lines.extend(["", "## Hypotheses (not reproduced)", ""])
    lines.extend("- " + _plain(value) for value in analysis.hypotheses)
    if not analysis.hypotheses:
        lines.append("No root cause established.")
    lines.extend(["", "## Candidate test commands (not executed)", ""])
    lines.extend("- `" + " ".join(command) + "`" for command in context.candidate_test_commands)
    if not context.candidate_test_commands:
        lines.append("No test command inferred from the selected metadata.")
    lines.extend(["", "## Limits", ""])
    lines.extend("- " + _plain(value) for value in context.limitations + analysis.limitations)
    lines.extend(
        [
            "",
            "## Usage",
            "",
            f"Model requests: {usage.requests}",
            f"Prompt tokens: {usage.prompt_tokens if usage.prompt_tokens is not None else 'unknown'}",
            f"Completion tokens: {usage.completion_tokens if usage.completion_tokens is not None else 'unknown'}",
            "Cost: unknown; no price or successful repair is inferred.",
            "",
        ]
    )
    return "\n".join(lines)

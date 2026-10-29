from typing import Protocol

from repopilot.domain.errors import RepoPilotError
from repopilot.domain.models import Analysis, Issue, RepositoryContext, Usage


class Provider(Protocol):
    usage: Usage

    def analyze(self, issue: Issue, context: RepositoryContext) -> Analysis: ...


def validate_references(analysis: Analysis, context: RepositoryContext) -> Analysis:
    available = {excerpt.path: excerpt for excerpt in context.excerpts}
    for finding in analysis.findings:
        excerpt = available.get(finding.path)
        if (
            excerpt is None
            or finding.start_line < excerpt.start_line
            or finding.end_line > excerpt.end_line
        ):
            raise RepoPilotError(
                "invalid_code_reference",
                "Analysis cites a file or line outside the supplied context.",
            )
    return analysis

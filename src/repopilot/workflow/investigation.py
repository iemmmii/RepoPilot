from pathlib import Path

from repopilot.domain.errors import RepoPilotError
from repopilot.domain.models import Issue
from repopilot.providers.base import Provider, validate_references
from repopilot.reporting.investigation import render_report
from repopilot.repository.snapshot import inspect_repository
from repopilot.storage.runs import RunStore


def investigate(
    issue: Issue, repository: Path, output_root: Path, provider: Provider, ref: str = "HEAD"
) -> Path:
    store = RunStore(output_root, provider.usage)
    try:
        store.add("issue.json", issue)
        context = inspect_repository(repository, issue, ref)
        store.manifest.base_commit = context.base_commit
        store.add("repo_context.json", context)
        analysis = validate_references(provider.analyze(issue, context), context)
        store.add("analysis.json", analysis)
        store.add("investigation.md", render_report(issue, context, analysis, provider.usage))
        store.manifest.usage = provider.usage
        store.finish()
        return store.root
    except RepoPilotError as error:
        store.manifest.usage = provider.usage
        store.finish(error=error)
        raise RepoPilotError(error.code, f"{error} Run: {store.root}") from error
    except Exception as error:
        safe = RepoPilotError("investigation_failed", "Investigation stopped before completion.")
        store.manifest.usage = provider.usage
        store.finish(error=safe)
        raise RepoPilotError(safe.code, f"{safe} Run: {store.root}") from error

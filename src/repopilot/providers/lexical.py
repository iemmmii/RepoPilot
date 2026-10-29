from repopilot.domain.models import Analysis, Finding, Issue, RepositoryContext, Usage


class LexicalProvider:
    """An explicit offline retrieval baseline, not a simulated successful LLM call."""

    def __init__(self):
        self.usage = Usage(provider="lexical", prompt_tokens=0, completion_tokens=0)

    def analyze(self, issue: Issue, context: RepositoryContext) -> Analysis:
        return Analysis(
            summary="Offline lexical/AST retrieval only; no model or target test was called.",
            findings=[
                Finding(
                    path=excerpt.path,
                    start_line=excerpt.start_line,
                    end_line=excerpt.end_line,
                    reason=f"Lexical retrieval score {excerpt.retrieval_score}; inspect this excerpt.",
                )
                for excerpt in context.excerpts[:5]
            ],
            limitations=["Root cause and behavior have not been established by this baseline."],
        )

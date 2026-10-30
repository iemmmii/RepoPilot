import pytest
from pydantic import ValidationError

from repopilot.domain.evidence import EvidenceGraph, EvidenceNode


def node(identifier, kind, dependencies=()):
    return EvidenceNode(
        node_id=identifier,
        kind=kind,
        artifact_path=identifier + ".json",
        artifact_digest="a" * 64,
        dependencies=list(dependencies),
    )


@pytest.mark.parametrize(
    "nodes",
    [
        [],
        [node("a", "source", ["missing"])],
        [node("a", "source"), node("a", "source")],
        [node("a", "source", ["b"]), node("b", "source", ["a"])],
        [node("source", "source"), node("oracle", "oracle", ["source"])],
        [node("requirement", "requirement"), node("oracle", "oracle", ["requirement"])],
    ],
)
def test_graph_rejects_missing_cyclic_illegal_or_incomplete_dependencies(nodes):
    with pytest.raises(ValidationError):
        EvidenceGraph(run_id="run", nodes=nodes)

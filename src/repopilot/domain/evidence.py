from typing import Literal

from pydantic import model_validator

from repopilot.domain.models import Record

NodeKind = Literal[
    "requirement",
    "source",
    "suite",
    "environment",
    "oracle",
    "command",
    "observation",
    "assessment",
]
ALLOWED = {
    "requirement": set(),
    "source": set(),
    "suite": set(),
    "environment": set(),
    "oracle": {"requirement", "suite"},
    "command": {"source", "suite", "environment"},
    "observation": {"command", "oracle"},
    "assessment": {"oracle", "observation"},
}


class EvidenceNode(Record):
    node_id: str
    kind: NodeKind
    artifact_path: str
    artifact_digest: str
    dependencies: list[str]


class EvidenceGraph(Record):
    run_id: str
    nodes: list[EvidenceNode]

    @model_validator(mode="after")
    def valid_dependencies(self):
        known = {}
        for node in self.nodes:
            if not node.node_id or node.node_id in known:
                raise ValueError("Evidence node IDs must be unique")
            if len(set(node.dependencies)) != len(node.dependencies):
                raise ValueError("Duplicate dependency")
            for dependency in node.dependencies:
                if dependency not in known or known[dependency] not in ALLOWED[node.kind]:
                    raise ValueError("Missing, cyclic, unordered or illegal evidence dependency")
            expected = ALLOWED[node.kind]
            if {known[dependency] for dependency in node.dependencies} != expected:
                raise ValueError("A required dependency kind is missing")
            known[node.node_id] = node.kind
        if set(known.values()) != set(ALLOWED):
            raise ValueError("A completed evidence graph requires all input and assessment kinds")
        return self

"""A managed patch must earn its outcome from the existing real verification gate."""

import hashlib
import os

import pytest

from repopilot.domain.patches import FileReplacement, PatchProposal
from repopilot.evaluation.controlled import build_case
from repopilot.repository.candidates import apply_proposal, create_candidate, export_candidate
from repopilot.repository.materialize import read_repository
from repopilot.sandbox.docker import DockerRunner
from repopilot.storage.runs import read_status
from repopilot.workflow.verification import verify

pytestmark = pytest.mark.skipif(
    os.environ.get("REPOPILOT_DOCKER_TESTS") != "1",
    reason="Opt-in real Docker verification with the pinned image cached.",
)


def test_managed_patch_passes_frozen_base_candidate_comparison(tmp_path):
    options = build_case(tmp_path / "case", "C01")["options"]
    root = create_candidate(options["repository"], options["base_ref"], tmp_path / "candidates")
    _, files = read_repository(options["repository"], options["base_ref"])
    original = files["auth.py"]
    generated = apply_proposal(
        root,
        PatchProposal(
            explanation="Controlled manually authored patch; not model-generated.",
            replacements=[
                FileReplacement(
                    path="auth.py",
                    before_sha256=hashlib.sha256(original).hexdigest(),
                    content=original.decode().replace("500", "401"),
                )
            ],
        ),
    )
    assert generated["outcome"] == "unverified"
    exported = export_candidate(root, tmp_path / "export")
    options["candidate_ref"] = exported["candidate_ref"]
    run = verify(**options, runner=DockerRunner())
    status = read_status(run)
    assert status["outcome"] == "candidate_verified"
    assert status["artifact_integrity"] == status["graph_integrity"] == "valid"
    assert status["command_attempts"] == 2 and status["usage"]["requests"] == 0

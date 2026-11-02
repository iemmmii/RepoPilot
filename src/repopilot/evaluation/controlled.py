import json
import subprocess
from pathlib import Path
from uuid import uuid4

from repopilot.domain.models import Issue
from repopilot.domain.verification import Oracle, fingerprint
from repopilot.sandbox.docker import DockerRunner
from repopilot.storage.runs import read_status
from repopilot.workflow.verification import verify

PROTOCOL = "repopilot-controlled-cases-v1"
CASES = (
    (
        "C01",
        "Expired credentials return the wrong status",
        "auth",
        "def status(age):\n    return 500 if age > 10 else 200\n",
        "def status(age):\n    return 401 if age > 10 else 200\n",
        "self.assertEqual(subject.status(11),401)",
        "self.assertEqual(subject.status(0),200)",
        "candidate_verified",
    ),
    (
        "C02",
        "Empty input has no defined average",
        "averages",
        "def average(values):\n    return sum(values)/len(values)\n",
        "def average(values):\n    return sum(values)/len(values) if values else 0\n",
        "try:\n            result=subject.average([])\n        except ZeroDivisionError:\n            self.fail('Protocol requires zero for empty input')\n        self.assertEqual(result,0)",
        "self.assertEqual(subject.average([2,4]),3)",
        "candidate_verified",
    ),
    (
        "C03",
        "Required dependency is unavailable",
        "missing",
        "import repopilot_c03_dependency_unavailable_7c93\ndef result(): return 1\n",
        None,
        "self.assertEqual(subject.result(),1)",
        "self.assertTrue(callable(subject.result))",
        "environment_blocked",
    ),
)


def build_case(root: Path, case_id: str) -> dict:
    case = next(item for item in CASES if item[0] == case_id)
    identifier, title, module, base, candidate, target, regression, expected = case
    root.mkdir(parents=True, exist_ok=False)
    repo = root / "repository"
    repo.mkdir()

    def git(*args):
        return subprocess.check_output(
            [
                "git",
                "-c",
                "core.hooksPath=",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "user.name=RepoPilot Controlled Fixture",
                "-c",
                "user.email=fixture@repopilot.invalid",
                "-C",
                str(repo),
                *args,
            ],
            text=True,
            stderr=subprocess.PIPE,
        ).strip()

    git("init", "--initial-branch=main")
    git("remote", "add", "origin", "https://github.com/repopilot-fixtures/controlled.git")
    path = repo / (module + ".py")
    path.write_bytes(base.encode())
    git("add", ".")
    git("commit", "-m", identifier + " controlled base")
    base_ref = git("rev-parse", "HEAD")
    candidate_ref = None
    if candidate is not None:
        path.write_bytes(candidate.encode())
        git("add", ".")
        git("commit", "-m", identifier + " known candidate")
        candidate_ref = git("rev-parse", "HEAD")
    suite = root / "suite"
    suite.mkdir()
    text = f"import unittest\nimport {module} as subject\n\nclass Contract(unittest.TestCase):\n    def test_target(self):\n        {target}\n\n    def test_regression(self):\n        {regression}\n"
    files = {"test_contract.py": text}
    (suite / "test_contract.py").write_bytes(text.encode())
    issue = Issue(
        title=title,
        body="Controlled tuning protocol: " + PROTOCOL,
        repository="repopilot-fixtures/controlled",
        url="https://github.com/repopilot-fixtures/controlled/issues/" + str(int(identifier[1:])),
    )
    oracle = Oracle(
        criterion_id=identifier,
        requirement=title + "; target and regression expectations are fixed by " + PROTOCOL,
        issue_url=issue.url,
        source_refs=[PROTOCOL + ":" + identifier],
        suite_hash=fingerprint(files),
        target_tests=["test_contract.Contract.test_target"],
        regression_tests=["test_contract.Contract.test_regression"],
        assessment_status="accepted",
        assessed_by="Versioned controlled evaluation protocol; synthetic fixture, not maintainer/user approval",
        assessment_basis="The expected behavior is declared before running this controlled case. C01 requires 401 for expired credentials; C02 requires 0 for empty input and treats the specified ZeroDivisionError as a target assertion failure; C03 must classify missing imports as environment_blocked. No generated patch supplies its own truth.",
    )
    oracle_path = root / "oracle.json"
    oracle_path.write_bytes(oracle.model_dump_json(indent=2).encode())
    options = dict(
        issue=issue,
        repository=repo,
        base_ref=base_ref,
        candidate_ref=candidate_ref,
        suite_path=suite,
        oracle_path=oracle_path,
        output_root=root / "runs",
    )
    return {"options": options, "expected": expected, "protocol": PROTOCOL}


def evaluate(output_root: Path, *, runner=None) -> Path:
    root = output_root.resolve() / uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    results = []
    for case in CASES:
        fixture = build_case(root / case[0], case[0])
        try:
            run = verify(**fixture["options"], runner=runner or DockerRunner())
            status = read_status(run)
            result = {
                "case": case[0],
                "expected": fixture["expected"],
                "observed": status["outcome"],
                "run_dir": str(run),
                "artifact_integrity": status["artifact_integrity"],
                "command_attempts": status["command_attempts"],
                "model_requests": status["usage"]["requests"],
            }
        except Exception as error:
            result = {
                "case": case[0],
                "expected": fixture["expected"],
                "observed": "evaluation_error",
                "error_type": type(error).__name__,
                "retained_run_dirs": [
                    str(path.parent) for path in (root / case[0] / "runs").glob("*/manifest.json")
                ],
            }
        result["matches_protocol"] = (
            result["observed"] == result["expected"] and result.get("artifact_integrity") == "valid"
        )
        results.append(result)
    summary = {
        "protocol": PROTOCOL,
        "case_kind": "controlled_tuning",
        "cases": results,
        "matched": sum(item["matches_protocol"] for item in results),
        "total": len(results),
        "limitations": [
            "Known candidates, no model repair.",
            "Three controlled tuning cases; not a general success-rate estimate.",
            "No resolved_verified claims; false full-success rate is N/A.",
        ],
    }
    (root / "summary.json").write_bytes(json.dumps(summary, indent=2).encode())
    return root

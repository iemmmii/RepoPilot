import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from repopilot import __version__
from repopilot.diagnostics.environment import inspect_environment
from repopilot.domain.errors import RepoPilotError
from repopilot.domain.verification import SandboxPolicy
from repopilot.evaluation.controlled import evaluate
from repopilot.github.issues import fetch_issue, read_issue_file
from repopilot.providers.deepseek import DeepSeekProvider
from repopilot.providers.lexical import LexicalProvider
from repopilot.repository.candidates import (
    apply_proposal,
    candidate_status,
    check_export,
    create_candidate,
    export_candidate,
    read_proposal,
    release_candidate,
)
from repopilot.sandbox.docker import DEFAULT_IMAGE, DockerRunner
from repopilot.storage.runs import read_status
from repopilot.workflow.investigation import investigate
from repopilot.workflow.verification import resume, verify


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path.cwd() / ".env", override=False)
    parser = argparse.ArgumentParser(prog="repopilot")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Inspect prerequisites without exposing credentials.")
    investigation = commands.add_parser(
        "investigate", help="Read a pinned Git snapshot; run no target code."
    )
    source = investigation.add_mutually_exclusive_group(required=True)
    source.add_argument("--issue-url")
    source.add_argument("--issue-file", type=Path)
    investigation.add_argument("--repo", type=Path, required=True)
    investigation.add_argument("--ref", default="HEAD")
    investigation.add_argument("--provider", choices=["deepseek", "lexical"], default="deepseek")
    investigation.add_argument("--output-dir", type=Path, default=Path(".repopilot/runs"))
    for name in ("reproduce", "verify-candidate"):
        verification = commands.add_parser(
            name, help="Execute a frozen unittest suite in a restricted Linux container."
        )
        issue_source = verification.add_mutually_exclusive_group(required=True)
        issue_source.add_argument("--issue-url")
        issue_source.add_argument("--issue-file", type=Path)
        verification.add_argument("--repo", type=Path, required=True)
        verification.add_argument("--base-ref", required=True)
        if name == "verify-candidate":
            verification.add_argument("--candidate-ref", required=True)
        verification.add_argument("--suite", type=Path, required=True)
        verification.add_argument("--oracle", type=Path, required=True)
        verification.add_argument("--image", default=DEFAULT_IMAGE)
        verification.add_argument("--docker-context")
        verification.add_argument("--timeout", type=float, default=60)
        verification.add_argument("--max-commands", type=int, choices=range(1, 21), default=6)
        verification.add_argument("--output-dir", type=Path, default=Path(".repopilot/runs"))
    status = commands.add_parser("status", help="Check saved artifacts against their manifest.")
    status.add_argument("run_dir", type=Path)
    recovery = commands.add_parser(
        "resume", help="Resume a 0.3 verification Run after input and integrity checks."
    )
    recovery.add_argument("run_dir", type=Path)
    evaluation = commands.add_parser(
        "evaluate", help="Run the three controlled tuning cases without model requests."
    )
    evaluation.add_argument("--output-dir", type=Path, default=Path(".repopilot/evaluations"))
    candidates = commands.add_parser("candidate", help="Manage bounded implementation patches.")
    candidate_commands = candidates.add_subparsers(dest="candidate_command", required=True)
    create = candidate_commands.add_parser("create", help="Create a detached managed candidate.")
    create.add_argument("--repo", type=Path, required=True)
    create.add_argument("--base-ref", required=True)
    create.add_argument("--output-dir", type=Path, default=Path(".repopilot/candidates"))
    for name in ("status", "apply", "export", "check-export", "release"):
        command = candidate_commands.add_parser(name)
        command.add_argument("candidate_dir", type=Path)
        if name == "apply":
            command.add_argument("--proposal", type=Path, required=True)
        if name == "export":
            command.add_argument("--output-dir", type=Path, required=True)
        if name == "check-export":
            command.add_argument("--export-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = inspect_environment()
        elif args.command == "candidate":
            if args.candidate_command == "create":
                root = create_candidate(args.repo, args.base_ref, args.output_dir)
                result = candidate_status(root)
            elif args.candidate_command == "status":
                result = candidate_status(args.candidate_dir)
            elif args.candidate_command == "apply":
                result = apply_proposal(args.candidate_dir, read_proposal(args.proposal))
            elif args.candidate_command == "release":
                result = release_candidate(args.candidate_dir)
            elif args.candidate_command == "check-export":
                result = check_export(args.candidate_dir, args.export_dir)
            else:
                result = export_candidate(args.candidate_dir, args.output_dir)
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return (
                0
                if result.get("integrity", "valid") == "valid"
                and result.get("applicability", "current") == "current"
                else 1
            )
        elif args.command == "evaluate":
            root = evaluate(args.output_dir)
            summary = json.loads((root / "summary.json").read_bytes())
            print(
                json.dumps(
                    {
                        "evaluation_dir": str(root),
                        "matched": summary["matched"],
                        "total": summary["total"],
                        "case_kind": summary["case_kind"],
                    },
                    indent=2,
                )
            )
            return 0 if summary["matched"] == summary["total"] else 1
        elif args.command == "status":
            result = read_status(args.run_dir)
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return 0 if result["artifact_integrity"] == "valid" else 1
        elif args.command == "resume":
            root = resume(args.run_dir)
            saved = read_status(root)
            result = {
                "run_dir": str(root),
                "report": str(root / (saved["report_artifact"] or "verification.md")),
                "outcome": saved["outcome"],
                "command_attempts": saved["command_attempts"],
            }
            print(json.dumps(result, ensure_ascii=True, indent=2))
            expected = (
                "candidate_verified"
                if saved["requested_scope"] == "verify_candidate"
                else "reproduced"
            )
            return 0 if saved["outcome"] == expected else 1
        elif args.command in {"reproduce", "verify-candidate"}:
            from pydantic import ValidationError

            try:
                policy = SandboxPolicy(timeout_seconds=args.timeout)
            except ValidationError as error:
                raise RepoPilotError(
                    "invalid_policy", "Timeout must be finite, positive and at most 300 seconds."
                ) from error
            issue = (
                read_issue_file(args.issue_file) if args.issue_file else fetch_issue(args.issue_url)
            )
            root = verify(
                issue=issue,
                repository=args.repo,
                base_ref=args.base_ref,
                candidate_ref=getattr(args, "candidate_ref", None),
                suite_path=args.suite,
                oracle_path=args.oracle,
                output_root=args.output_dir,
                runner=DockerRunner(image=args.image, policy=policy, context=args.docker_context),
                max_commands=args.max_commands,
            )
            saved = read_status(root)
            result = {
                "run_dir": str(root),
                "report": str(root / "verification.md"),
                "outcome": saved["outcome"],
                "tests_executed": saved["tests_executed"],
            }
            print(json.dumps(result, ensure_ascii=True, indent=2))
            expected = "candidate_verified" if args.command == "verify-candidate" else "reproduced"
            return 0 if result["outcome"] == expected else 1
        else:
            issue = (
                read_issue_file(args.issue_file) if args.issue_file else fetch_issue(args.issue_url)
            )
            provider = (
                DeepSeekProvider.from_environment()
                if args.provider == "deepseek"
                else LexicalProvider()
            )
            root = investigate(issue, args.repo, args.output_dir, provider, args.ref)
            result = {
                "run_dir": str(root),
                "report": str(root / "investigation.md"),
                "outcome": "investigated",
                "tests_executed": False,
            }
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except RepoPilotError as error:
        print(
            json.dumps({"error": error.code, "message": str(error)}, ensure_ascii=True),
            file=sys.stderr,
        )
        return 2
    except OSError:
        print(
            json.dumps(
                {"error": "io_error", "message": "Could not access the requested local files."}
            ),
            file=sys.stderr,
        )
        return 2

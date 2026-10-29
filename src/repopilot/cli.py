import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from repopilot import __version__
from repopilot.diagnostics.environment import inspect_environment
from repopilot.domain.errors import RepoPilotError
from repopilot.github.issues import fetch_issue, read_issue_file
from repopilot.providers.deepseek import DeepSeekProvider
from repopilot.providers.lexical import LexicalProvider
from repopilot.storage.runs import read_status
from repopilot.workflow.investigation import investigate


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
    status = commands.add_parser("status", help="Check saved artifacts against their manifest.")
    status.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = inspect_environment()
        elif args.command == "status":
            result = read_status(args.run_dir)
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return 0 if result["artifact_integrity"] == "valid" else 1
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

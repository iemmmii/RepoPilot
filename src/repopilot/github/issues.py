import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from repopilot.domain.errors import RepoPilotError
from repopilot.domain.models import Issue


def parse_issue_url(url: str) -> tuple[str, str, int]:
    if len(url) > 2048:
        raise RepoPilotError("invalid_issue_url", "GitHub Issue URL exceeds the length limit.")
    try:
        parsed = urlsplit(url)
    except ValueError as error:
        raise RepoPilotError("invalid_issue_url", "Malformed GitHub Issue URL.") from error
    match = re.fullmatch(r"/([\w.-]+)/([\w.-]+)/issues/([1-9][0-9]*)/?", parsed.path, re.ASCII)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "github.com"
        or parsed.query
        or not match
    ):
        raise RepoPilotError("invalid_issue_url", "Expected an HTTPS github.com Issue URL.")
    owner, repo, number = match.groups()
    if owner in {".", ".."} or repo in {".", ".."}:
        raise RepoPilotError("invalid_issue_url", "Invalid repository path.")
    return owner, repo, int(number)


def read_issue_file(path: Path) -> Issue:
    try:
        if path.stat().st_size > 1_000_000:
            raise RepoPilotError("issue_too_large", "Issue JSON exceeds the size limit.")
        issue = Issue.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        raise RepoPilotError(
            "invalid_issue_file", "Cannot read a valid Issue JSON file."
        ) from error
    if issue.url:
        owner, repo, number = parse_issue_url(issue.url)
        if issue.repository and issue.repository.casefold() != f"{owner}/{repo}".casefold():
            raise RepoPilotError("issue_identity_mismatch", "Issue URL and repository disagree.")
        if issue.number is not None and issue.number != number:
            raise RepoPilotError("issue_identity_mismatch", "Issue URL and number disagree.")
        issue = issue.model_copy(update={"repository": f"{owner}/{repo}", "number": number})
    return issue


def fetch_issue(url: str, client: httpx.Client | None = None) -> Issue:
    owner, repo, number = parse_issue_url(url)
    owned = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=False)
    try:
        response = client.get(
            f"https://api.github.com/repos/{owner}/{repo}/issues/{number}",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "RepoPilot"},
        )
        if response.status_code != 200:
            code = {
                403: "github_access_or_rate_limit",
                404: "issue_not_found",
                429: "github_rate_limit",
            }.get(response.status_code, "github_http_error")
            raise RepoPilotError(code, f"GitHub Issue read failed (HTTP {response.status_code}).")
        if len(response.content) > 1_000_000:
            raise RepoPilotError("issue_too_large", "GitHub Issue response exceeds the limit.")
        data = response.json()
        if not isinstance(data, dict):
            raise TypeError("Expected an Issue response object")
        if "pull_request" in data:
            raise RepoPilotError("not_an_issue", "The URL identifies a pull request, not an Issue.")
        if data.get("number") != number:
            raise RepoPilotError("issue_identity_mismatch", "GitHub returned a different Issue.")
        return Issue(
            title=data["title"],
            body=data.get("body") or "",
            url=f"https://github.com/{owner}/{repo}/issues/{number}",
            repository=f"{owner}/{repo}",
            number=number,
        )
    except httpx.HTTPError as error:
        raise RepoPilotError(
            "github_transport_error", "GitHub request did not complete."
        ) from error
    except (ValueError, KeyError, TypeError, ValidationError) as error:
        raise RepoPilotError(
            "invalid_github_response", "GitHub returned invalid Issue data."
        ) from error
    finally:
        if owned:
            client.close()


def issue_json(issue: Issue) -> str:
    return json.dumps(issue.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"

import httpx
import pytest

from repopilot.domain.errors import RepoPilotError
from repopilot.github.issues import fetch_issue, parse_issue_url


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a/b/issues/1",
        "https://evil.test/a/b/issues/1",
        "https://github.com@evil.test/a/b/issues/1",
        "https://github.com/a/b/pull/1",
        "https://github.com/a/b/issues/0",
        "https://github.com/a/b/issues/1?redirect=evil",
    ],
)
def test_invalid_issue_url(url):
    with pytest.raises(RepoPilotError):
        parse_issue_url(url)


def test_github_reader_maps_rate_limit():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(429))) as client:
        with pytest.raises(RepoPilotError) as caught:
            fetch_issue("https://github.com/example/demo/issues/1", client)
    assert caught.value.code == "github_rate_limit"


def test_github_reader_rejects_pull_request():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "number": 1,
                "title": "PR",
                "pull_request": {},
            },
        )
    )
    with httpx.Client(transport=transport) as client, pytest.raises(RepoPilotError) as caught:
        fetch_issue("https://github.com/example/demo/issues/1", client)
    assert caught.value.code == "not_an_issue"


@pytest.mark.parametrize("url", ["https://[bad", "https://github.com/a/b/issues/" + "9" * 3000])
def test_malformed_and_oversized_urls_have_safe_errors(url):
    with pytest.raises(RepoPilotError) as caught:
        parse_issue_url(url)
    assert caught.value.code == "invalid_issue_url"

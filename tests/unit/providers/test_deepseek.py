import json

import httpx
import pytest
from pydantic import SecretStr

from repopilot.domain.errors import RepoPilotError
from repopilot.domain.models import Issue
from repopilot.providers.deepseek import DeepSeekProvider
from repopilot.repository.snapshot import inspect_repository


def test_deepseek_json_request_usage_and_reference_validation(repository):
    issue = Issue(title="expired token")
    context = inspect_repository(repository, issue)
    excerpt = context.excerpts[0]
    answer = {
        "summary": "investigation only",
        "findings": [
            {
                "path": excerpt.path,
                "start_line": excerpt.start_line,
                "end_line": excerpt.start_line,
                "reason": "related code",
            }
        ],
    }
    requests = []

    def respond(request):
        requests.append(request)
        body = json.loads(request.content)
        assert request.url == "https://api.deepseek.com/chat/completions"
        assert request.headers["authorization"] == "Bearer test-secret"
        assert body["response_format"] == {"type": "json_object"}
        assert body["thinking"] == {"type": "disabled"}
        assert "json" in body["messages"][0]["content"].lower()
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 30},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        provider = DeepSeekProvider(SecretStr("test-secret"), client=client)
        result = provider.analyze(issue, context)
        assert result.findings[0].path == excerpt.path
        assert provider.usage.prompt_tokens == 100
        assert provider.usage.cost_usd is None
        with pytest.raises(RepoPilotError) as caught:
            provider.analyze(issue, context)
    assert caught.value.code == "model_budget_exhausted"
    assert len(requests) == 1


@pytest.mark.parametrize(
    "status,choices,expected",
    [
        (401, None, "deepseek_http_error"),
        (
            200,
            [{"finish_reason": "length", "message": {"content": "{}"}}],
            "model_output_incomplete",
        ),
        (200, [{"finish_reason": "stop", "message": {"content": ""}}], "empty_model_output"),
        (200, [{"finish_reason": "stop", "message": {"content": "{}"}}], "invalid_model_output"),
    ],
)
def test_deepseek_failures_do_not_leak_response_or_secret(repository, status, choices, expected):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status,
            json={
                "choices": choices,
                "error": "test-secret must not be printed",
            },
        )
    )
    with httpx.Client(transport=transport) as client:
        provider = DeepSeekProvider(SecretStr("test-secret"), client=client)
        with pytest.raises(RepoPilotError) as caught:
            provider.analyze(
                Issue(title="expired token"),
                inspect_repository(repository, Issue(title="expired token")),
            )
    assert caught.value.code == expected
    assert "test-secret" not in str(caught.value)


@pytest.mark.parametrize(
    "url", ["http://api.deepseek.com", "https://evil.test", "https://api.deepseek.com@evil.test"]
)
def test_provider_rejects_credential_forwarding_to_untrusted_hosts(url):
    with pytest.raises(RepoPilotError) as caught:
        DeepSeekProvider(SecretStr("test-secret"), base_url=url)
    assert caught.value.code == "invalid_provider_url"


def test_model_cannot_reference_lines_outside_the_supplied_excerpt(repository):
    context = inspect_repository(repository, Issue(title="expired token"))
    excerpt = context.excerpts[0]
    content = json.dumps(
        {
            "summary": "unverified",
            "findings": [
                {
                    "path": excerpt.path,
                    "start_line": excerpt.end_line + 1,
                    "end_line": excerpt.end_line + 1,
                    "reason": "invented line",
                }
            ],
        }
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": content}}],
            },
        )
    )
    with httpx.Client(transport=transport) as client:
        provider = DeepSeekProvider(SecretStr("test-secret"), client=client)
        with pytest.raises(RepoPilotError) as caught:
            provider.analyze(Issue(title="expired token"), context)
    assert caught.value.code == "invalid_code_reference"

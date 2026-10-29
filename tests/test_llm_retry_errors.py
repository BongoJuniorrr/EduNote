import asyncio
import pytest
from src.services.llm import factory
from src.services.llm.exceptions import LLMRateLimitError


def test_exhausted_retry_preserves_provider_error(monkeypatch):
    async def rate_limited(**kwargs):
        raise LLMRateLimitError('quota reached', provider='local')

    monkeypatch.setattr(factory.local_provider, 'complete', rate_limited)
    with pytest.raises(LLMRateLimitError):
        asyncio.run(factory.complete(prompt='test', model='local', binding='vllm',
                                     base_url='http://localhost:8000/v1', max_retries=0))


def test_cloudflare_failure_is_actionable_and_does_not_echo_html():
    from src.services.llm.exceptions import LLMAPIError
    error = LLMAPIError('<html>visitor IP and diagnostic page</html>', status_code=524, provider='openai')
    text = str(error)
    assert 'HTTP 524' in text and '300 seconds' in text and 'upstream' in text
    assert '<html>' not in text and 'visitor IP' not in text


def test_html_provider_failure_does_not_echo_proxy_page():
    from src.services.llm.exceptions import LLMAPIError
    error = LLMAPIError('API error <!DOCTYPE html><html>private diagnostics</html>', status_code=502)
    assert 'HTML error page' in str(error)
    assert 'private diagnostics' not in str(error)


def test_cloudflare_timeout_keeps_status_and_identity_when_mapped():
    from src.services.llm.error_mapping import map_error
    from src.services.llm.exceptions import LLMAPIError
    error = LLMAPIError('origin timed out', status_code=524, provider='openai')
    assert map_error(error, provider='openai') is error
    assert error.status_code == 524
    assert str(error).count('[openai]') == 1


def test_separate_limit_is_not_a_rate_limit_error():
    from src.services.llm.error_mapping import map_error
    from src.services.llm.exceptions import LLMAPIError
    error = map_error(Exception('The upstream proxy has a separate limit.'))
    assert type(error) is LLMAPIError
    assert error.status_code is None


def test_unclassified_rate_limit_still_maps_to_429():
    from src.services.llm.error_mapping import map_error
    assert isinstance(map_error(Exception('Provider rate limit exceeded')), LLMRateLimitError)


def test_underscored_quota_error_still_maps_to_429():
    from src.services.llm.error_mapping import map_error
    assert isinstance(map_error(Exception('insufficient_quota')), LLMRateLimitError)


def test_mapping_preserves_rate_limit_retry_after():
    from src.services.llm.error_mapping import map_error
    error = LLMRateLimitError('Too many requests', retry_after=42, provider='local')
    assert map_error(error) is error
    assert error.retry_after == 42

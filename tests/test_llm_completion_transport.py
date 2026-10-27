"""A buffered API return value may use SSE transport through an idle-timeout proxy."""
import asyncio
import pytest
from src.services.llm import factory


def test_stream_transport_preserves_messages_and_returns_complete_text(monkeypatch):
    seen = {}
    async def stream(**kwargs):
        seen.update(kwargs)
        yield 'Hello'
        yield ' world'
    monkeypatch.setattr(factory.cloud_provider, 'stream', stream)
    messages = [{'role':'user','content':'first'}, {'role':'assistant','content':'reply'}, {'role':'user','content':'second'}]
    answer = asyncio.run(factory.complete(prompt='second', model='local', base_url='https://example.org/v1', api_key='test', binding='openai', messages=messages, transport_stream=True, max_retries=0))
    assert answer == 'Hello world'
    assert seen['messages'] == messages
    assert seen['timeout'] == 300
    assert 'transport_stream' not in seen


def test_stream_transport_enforces_whole_request_timeout(monkeypatch):
    async def stream(**kwargs):
        yield 'partial'
        await asyncio.sleep(1)
        yield 'late'
    monkeypatch.setattr(factory.cloud_provider, 'stream', stream)
    with pytest.raises(Exception, match='(?i)timeout|timed out'):
        asyncio.run(factory.complete(prompt='test', model='local', base_url='https://example.org/v1', binding='openai', transport_stream=True, timeout=.01, max_retries=0))


def test_environment_opt_in_uses_local_sse(monkeypatch):
    monkeypatch.setenv('LLM_COMPLETION_TRANSPORT', 'stream')
    async def stream(**kwargs):
        yield 'local answer'
    monkeypatch.setattr(factory.local_provider, 'stream', stream)
    assert asyncio.run(factory.complete(prompt='test', model='local', base_url='http://localhost:9000/v1', binding='vllm', max_retries=0)) == 'local answer'

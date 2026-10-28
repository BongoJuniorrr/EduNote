"""RAG and multi-turn chat must work with strict single-system templates."""
import asyncio
from copy import deepcopy

import pytest

from src.services.llm import factory
from src.services.llm.utils import normalize_system_messages


def conversation():
    return [
        {"role": "system", "content": "Tutor instructions"},
        {"role": "system", "content": "Reference context: computer history"},
        {"role": "user", "content": "Explain computers"},
        {"role": "assistant", "content": "For which audience?"},
        {"role": "user", "content": "University lecturer"},
    ]


@pytest.mark.parametrize("binding", ["openai", "vllm"])
@pytest.mark.parametrize("mode", ["buffered", "aggregated", "stream"])
def test_requests_have_one_leading_system_and_keep_history(monkeypatch, binding, mode):
    messages = conversation()
    original = deepcopy(messages)
    provider = factory.cloud_provider if binding == "openai" else factory.local_provider

    def check(kwargs):
        sent = kwargs["messages"]
        assert sent[0] == {
            "role": "system",
            "content": "Tutor instructions\n\nReference context: computer history",
        }
        assert sent[1:] == original[2:]

    async def complete(**kwargs):
        check(kwargs)
        return "Answer"

    async def stream(**kwargs):
        check(kwargs)
        yield "Answer"

    monkeypatch.setattr(provider, "complete", complete)
    monkeypatch.setattr(provider, "stream", stream)

    async def run():
        kwargs = dict(prompt="University lecturer", messages=messages, model="qwen",
                      base_url="https://example.org/v1", binding=binding, max_retries=0)
        if mode == "stream":
            return "".join([part async for part in factory.stream(**kwargs)])
        return await factory.complete(**kwargs, transport_stream=mode == "aggregated")

    assert asyncio.run(run()) == "Answer"
    assert messages == original


def test_late_system_keeps_tool_and_multimodal_payloads():
    messages = [
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "example"}}]},
        {"role": "system", "content": "Instructions"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call1"}]},
        {"role": "tool", "tool_call_id": "call1", "content": "Result"},
    ]
    assert normalize_system_messages(messages) == [messages[1], messages[0], *messages[2:]]


def test_system_text_blocks_are_preserved():
    assert normalize_system_messages([
        {"role": "system", "content": "Instructions"},
        {"role": "system", "content": [{"type": "text", "text": "Reference"}]},
    ]) == [{"role": "system", "content": [
        {"type": "text", "text": "Instructions"},
        {"type": "text", "text": "Reference"},
    ]}]


def test_chat_context_is_part_of_first_system_message():
    from src.agents.chat.chat_agent import ChatAgent

    class Prompts:
        def get_prompt(self, name, default):
            return {"system": "Tutor", "context_template": "Reference: {context}"}[name]

    messages = ChatAgent.build_messages(Prompts(), "Question", [], "Document")
    assert messages == [
        {"role": "system", "content": "Tutor\n\nReference: Document"},
        {"role": "user", "content": "Question"},
    ]

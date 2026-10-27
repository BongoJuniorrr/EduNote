import asyncio

from src.agents.question.agents.retrieve_agent import RetrieveAgent


def test_retrieve_agent_treats_content_as_knowledge(monkeypatch):
    agent = RetrieveAgent(kb_name="dummy")

    async def fake_generate_queries(_requirement_text, _num_queries):
        return ["query-1"]

    async def fake_execute_searches(_queries):
        return [
            {
                "query": "query-1",
                "answer": "",
                "content": "context available from provider",
                "mode": "hybrid",
            }
        ]

    monkeypatch.setattr(agent, "_generate_queries", fake_generate_queries)
    monkeypatch.setattr(agent, "_execute_searches", fake_execute_searches)

    result = asyncio.run(
        agent.process(requirement={"knowledge_point": "Recent Trends in CS"}, num_queries=1)
    )

    assert result["has_content"] is True
    assert "context available from provider" in result["summary"]

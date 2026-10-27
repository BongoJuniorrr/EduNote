import unittest
from types import SimpleNamespace
import sys
import types
from unittest.mock import AsyncMock

# Optional dependency used by paper tool; stub for isolated unit test import.
sys.modules.setdefault("arxiv", types.ModuleType("arxiv"))

from src.agents.research.agents.reporting_agent import ReportingAgent
from src.agents.research.research_pipeline import ResearchPipeline


class TestReportingAgentJsonResilience(unittest.IsolatedAsyncioTestCase):
    def _build_agent(self, retries: int = 1) -> ReportingAgent:
        agent = ReportingAgent.__new__(ReportingAgent)
        agent.reporting_config = {"json_repair_retries": retries}
        agent.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
        return agent

    async def test_parse_json_field_success(self):
        agent = self._build_agent()
        agent.call_llm = AsyncMock()

        result = await agent._parse_json_field_with_repair(
            raw_response='{"section_content":"Structured output"}',
            required_key="section_content",
            stage="write_section_body",
            system_prompt="system",
            fallback_to_raw_markdown=True,
        )

        self.assertEqual(result, "Structured output")
        agent.call_llm.assert_not_awaited()

    async def test_parse_json_field_repair_success(self):
        agent = self._build_agent(retries=1)
        agent.call_llm = AsyncMock(return_value='{"section_content":"Recovered output"}')

        result = await agent._parse_json_field_with_repair(
            raw_response="not a json payload",
            required_key="section_content",
            stage="write_section_body",
            system_prompt="system",
            fallback_to_raw_markdown=True,
        )

        self.assertEqual(result, "Recovered output")
        agent.call_llm.assert_awaited_once()

    async def test_parse_json_field_raw_fallback_for_section(self):
        agent = self._build_agent(retries=1)
        agent.call_llm = AsyncMock(return_value="```markdown\n## Raw Section\n\nFallback body\n```")

        result = await agent._parse_json_field_with_repair(
            raw_response="still malformed",
            required_key="section_content",
            stage="write_section_body",
            system_prompt="system",
            fallback_to_raw_markdown=True,
        )

        self.assertEqual(result, "## Raw Section\n\nFallback body")
        agent.call_llm.assert_awaited_once()

    async def test_parse_json_field_raises_when_no_fallback(self):
        agent = self._build_agent(retries=1)
        agent.call_llm = AsyncMock(return_value="{}")

        with self.assertRaises(ValueError):
            await agent._parse_json_field_with_repair(
                raw_response="invalid",
                required_key="conclusion",
                stage="write_conclusion",
                system_prompt="system",
                fallback_to_raw_markdown=False,
            )


class TestResearchPipelineReportingFailure(unittest.IsolatedAsyncioTestCase):
    async def test_phase3_reporting_emits_reporting_failed_event(self):
        class DummyReporting:
            def set_citation_manager(self, citation_manager):
                self.citation_manager = citation_manager

            async def process(self, queue, topic, progress_callback=None):
                raise ValueError("simulated report failure")

        pipeline = ResearchPipeline.__new__(ResearchPipeline)
        pipeline.agents = {"reporting": DummyReporting()}
        pipeline.citation_manager = object()
        pipeline.queue = object()
        pipeline.logger = SimpleNamespace(
            success=lambda *args, **kwargs: None,
            info=lambda *args, **kwargs: None,
        )

        emitted_events = []
        pipeline._log_progress = lambda stage, status, **payload: emitted_events.append(
            {"stage": stage, "status": status, "payload": payload}
        )

        with self.assertRaisesRegex(ValueError, "simulated report failure"):
            await ResearchPipeline._phase3_reporting(pipeline, "test topic")

        self.assertEqual(len(emitted_events), 1)
        self.assertEqual(emitted_events[0]["stage"], "reporting")
        self.assertEqual(emitted_events[0]["status"], "reporting_failed")
        self.assertIn("simulated report failure", emitted_events[0]["payload"]["error"])


def test_dynamic_research_topic_budget_is_finite():
    from src.agents.research.research_pipeline import research_topic_budget
    assert research_topic_budget({}) == 16
    assert research_topic_budget({'queue': {'max_length': None}}) == 16
    assert research_topic_budget({'queue': {'max_length': 2}}) == 2
    assert research_topic_budget({'queue': {'max_length': 100000}}) == 32


def test_manager_stops_expansion_at_topic_budget():
    from src.agents.research.agents.manager_agent import ManagerAgent
    from src.agents.research.data_structures import DynamicTopicQueue
    manager=ManagerAgent.__new__(ManagerAgent)
    manager.queue=DynamicTopicQueue('budget-test',max_length=1)
    manager.queue.add_block('First topic','Already planned')
    assert manager.add_new_topic('Another topic','Outside the selected budget') is None
    assert len(manager.queue.blocks)==1

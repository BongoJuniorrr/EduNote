import asyncio
import json

from src.agents.edu_studio.workflow_agent import EduStudioWorkflowAgent


def test_workflow_agent_dry_run_returns_structured_payload():
    agent = EduStudioWorkflowAgent(
        api_key="test-key",
        base_url="http://localhost:8000/v1",
        model="test-model",
        binding="openai",
        language="en",
    )

    result = asyncio.run(
        agent.run_workflow(
            "slide_deck",
            {
                "title": "Fractions Basics",
                "language": "en",
                "settings": {"slide_count": 12, "duration_minutes": 45},
                "source_text": "Fractions represent equal parts of a whole.",
                "dry_run": True,
            },
        )
    )

    assert result["workflow"] == "slide_deck"
    assert result["title"] == "Fractions Basics"
    assert isinstance(result["deliverable_markdown"], str)
    assert len(result["deliverable_markdown"]) > 10
    assert isinstance(result["structured_data"], dict)
    assert isinstance(result["quality_checks"], list)
    assert result["metadata"]["model"] == "test-model"


def test_workflow_agent_exam_blueprint_warns_when_matrix_missing():
    agent = EduStudioWorkflowAgent(
        api_key="test-key",
        base_url="http://localhost:8000/v1",
        model="test-model",
        binding="openai",
        language="en",
    )

    result = asyncio.run(
        agent.run_workflow(
            "exam_blueprint",
            {
                "title": "Midterm exam",
                "language": "en",
                "settings": {},
                "source_text": "Algebra and geometry chapters.",
                "dry_run": True,
            },
        )
    )

    names = [check.get("name") for check in result["quality_checks"]]
    assert "matrix_definition" in names


def test_workflow_agent_backfills_slide_theme_and_slide_fields():
    agent = EduStudioWorkflowAgent(
        api_key="test-key",
        base_url="http://localhost:8000/v1",
        model="test-model",
        binding="openai",
        language="en",
    )

    async def fake_call_llm(*args, **kwargs):
        return json.dumps(
            {
                "title": "Deck",
                "summary": "Summary",
                "deliverable_markdown": "# Deck",
                "structured_data": {
                    "slides": [
                        {
                            "title": "S1",
                            "objective": "Obj",
                            "key_points": ["Point A"],
                            "activity": "Discuss",
                            "speaker_notes": "Notes",
                        }
                    ],
                    "design_guidelines": [],
                    "assessment_checkpoints": [],
                },
                "quality_checks": [{"name": "llm", "status": "Pass", "detail": "ok"}],
                "next_actions": ["next"],
            }
        )

    agent.call_llm = fake_call_llm  # type: ignore[method-assign]

    result = asyncio.run(
        agent.run_workflow(
            "slide_deck",
            {
                "title": "Deck",
                "language": "en",
                "settings": {"slide_count": 3, "style": "clean-academic"},
                "source_text": "Source",
            },
        )
    )

    structured = result["structured_data"]
    assert "deck_theme" in structured
    assert structured["deck_theme"]["ratio"] == "16:9"
    assert len(structured["slides"]) == 3
    assert "layout_hint" in structured["slides"][0]
    assert "visual_hint" in structured["slides"][0]
    assert "visual_prompt" in structured["slides"][0]
    assert isinstance(structured["slides"][0]["visual_prompt"], str)
    assert structured["slides"][0]["visual_prompt"]

    checks = result["quality_checks"]
    assert any(c.get("name") == "structured_schema_backfill" for c in checks)
    assert any(c.get("status") == "warn" for c in checks)


def test_workflow_agent_backfills_missing_workflow_keys_without_raising():
    agent = EduStudioWorkflowAgent(
        api_key="test-key",
        base_url="http://localhost:8000/v1",
        model="test-model",
        binding="openai",
        language="en",
    )

    async def fake_call_llm(*args, **kwargs):
        return json.dumps(
            {
                "title": "Exam",
                "summary": "Summary",
                "deliverable_markdown": "# Exam",
                "structured_data": {
                    "exam_variants": [{"variant": "A", "questions": []}],
                },
                "quality_checks": [],
                "next_actions": [],
            }
        )

    agent.call_llm = fake_call_llm  # type: ignore[method-assign]

    result = asyncio.run(
        agent.run_workflow(
            "exam_blueprint",
            {
                "title": "Exam",
                "language": "en",
                "settings": {},
                "source_text": "Source",
            },
        )
    )

    structured = result["structured_data"]
    assert "matrix_validation" in structured
    assert "exam_variants" in structured
    assert "rubric" in structured
    assert isinstance(structured["rubric"], list)
    assert any(
        c.get("name") == "structured_schema_backfill" and c.get("status") == "warn"
        for c in result["quality_checks"]
    )


def test_empty_model_output_is_not_a_successful_template(monkeypatch):
    import asyncio
    import pytest
    from src.agents.edu_studio.workflow_agent import EduStudioWorkflowAgent

    agent = EduStudioWorkflowAgent()

    async def empty(**kwargs):
        return '{}'

    monkeypatch.setattr(agent, 'call_llm', empty)
    with pytest.raises(ValueError, match='valid Edu Studio JSON'):
        asyncio.run(agent.run_workflow('lesson_plan', {'source_text': 'Orchids are plants.'}))

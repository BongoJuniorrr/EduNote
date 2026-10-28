import asyncio
import copy
import re

import pytest

from src.services.slide_pro.engine import (
    LAYOUT_VARIANTS,
    SlideComposerAgent,
    SlideInstructionAgent,
    SlideLayoutAgent,
    SlideProEngine,
    _boxes_overlap,
    _chart_data_for_slide,
    _default_theme,
    _extract_metric_values,
    _instruction_max_loops,
)


@pytest.fixture(autouse=True)
def offline_image_generation(monkeypatch):
    # Unit tests must not call a provider configured in the developer's .env.
    monkeypatch.setenv("IMAGE_MODEL", "")


def _layout_spec(layout_id: str, slide_id: str = "s1") -> dict:
    spec = next(item for item in LAYOUT_VARIANTS if item["id"] == layout_id)
    return {
        "slide_id": slide_id,
        "slide_index": 0,
        "layout_id": spec["id"],
        "description": spec["description"],
        "slots": copy.deepcopy(spec["slots"]),
        "chart_type": spec.get("chart_type", "bar"),
        "svg_variant": spec.get("svg_variant", "default"),
        "metric_cards": spec.get("metric_cards", 0),
        "constraints": copy.deepcopy(spec.get("constraints", {})),
        "asset_specs": [],
        "attempt": 0,
    }


class _RetryOnceInstructionAgent(SlideInstructionAgent):
    def __init__(self) -> None:
        self.calls = 0

    def run(self, *, deck: dict, layout_plan: list[dict], template_id: str) -> dict:  # type: ignore[override]
        self.calls += 1
        if self.calls == 1:
            issue = {
                "slide_id": "s1",
                "reasons": ["readability"],
                "major_reasons": ["readability"],
                "minor_reasons": [],
                "severity": 10,
            }
            return {
                "approved": False,
                "issues": [issue],
                "slides_to_retry": [{"slide_id": "s1", "reasons": ["readability"]}],
                "unresolved_major": [{"slide_id": "s1", "reasons": ["readability"]}],
                "unresolved_minor": [],
            }
        return {
            "approved": True,
            "issues": [],
            "slides_to_retry": [],
            "unresolved_major": [],
            "unresolved_minor": [],
        }


class _ApproveInstructionAgent(SlideInstructionAgent):
    def run(self, *, deck: dict, layout_plan: list[dict], template_id: str) -> dict:  # type: ignore[override]
        return {
            "approved": True,
            "issues": [],
            "slides_to_retry": [],
            "unresolved_major": [],
            "unresolved_minor": [],
        }


def test_retry_keeps_slide_citations_attached(monkeypatch):
    engine = SlideProEngine()
    engine.instruction_agent = _RetryOnceInstructionAgent()

    async def fake_research(**kwargs):
        return {
            "source_text": "Benchmark improved by 42% in controlled tests.",
            "evidence_catalog": [
                {
                    "id": "S1",
                    "source_type": "web",
                    "title": "Benchmark Report",
                    "short_ref": "Benchmark 2026",
                    "snippet": "Improvement reached 42% across runs.",
                    "url": "https://example.com/benchmark",
                }
            ],
            "warnings": [],
            "research_notes": [],
        }

    async def fake_content(**kwargs):
        return {
            "learning_goals": ["Understand observed gains"],
            "source": "fallback",
            "slides": [
                {
                    "title": "Observed Gain",
                    "objective": "Evidence shows 42% gain in outcome quality.",
                    "key_points": [
                        "Claim: Performance improved by 42%.",
                        "Evidence: Controlled benchmark runs report 42% uplift.",
                        "Implication: Adopt the method in production rollout.",
                    ],
                    "speaker_notes": "Keep discussion anchored to cited benchmark evidence.",
                    "asset_focus": "Benchmark comparison visual",
                }
            ],
        }

    monkeypatch.setattr(engine.research_agent, "run", fake_research)
    monkeypatch.setattr(engine.content_agent, "run", fake_content)

    result = asyncio.run(
        engine.generate(
            title="Retry Citation",
            language="en",
            source_text="",
            source_records=None,
            instructions="",
            settings={
                "slide_count": 1,
                "template_id": "academic_evidence",
                "max_instruction_loops": 2,
            },
        )
    )

    slide = result["deck_json"]["slides"][0]
    assert slide["citations"], "Slide citations should remain after retry recomposition."
    claim_elements = [
        element
        for element in slide["elements"]
        if element.get("id", "").endswith("_objective")
        or element.get("type") in {"bullets", "chart", "table"}
        or (
            element.get("type") == "shape"
            and isinstance(element.get("style"), dict)
            and element["style"].get("purpose") == "chart_fallback"
        )
    ]
    assert any(element.get("evidence_refs") for element in claim_elements)
    assert result["instruction_report"]["attempts_by_slide"]["s1"] >= 1


def test_geometry_detects_text_overflow():
    agent = SlideInstructionAgent()
    slide = {
        "id": "s1",
        "elements": [
            {
                "id": "s1_bg",
                "type": "shape",
                "box": {"x": 0, "y": 0, "w": 1600, "h": 900, "rot": 0},
                "style": {"fill": "#FFFFFF", "purpose": "background", "locked": True, "zIndex": 0},
                "content": "",
            },
            {
                "id": "s1_objective",
                "type": "text",
                "box": {"x": 80, "y": 120, "w": 260, "h": 42, "rot": 0},
                "style": {"fontSize": 28, "lineHeight": 1.22, "color": "#0F172A", "zIndex": 5},
                "content": " ".join(["overflow"] * 120),
                "evidence_refs": ["S1"],
            },
        ],
    }

    geometry = agent._geometry_and_contrast_issues(slide)
    assert geometry["overflow"] >= 1


def test_layout_guards_remove_invalid_overlap_after_replan(monkeypatch):
    layout_agent = SlideLayoutAgent()
    monkeypatch.setattr(layout_agent, "_pool", lambda template_id: ["comparison_dual"])

    replanned = layout_agent.replan_slide(
        current_layout=_layout_spec("comparison_dual"),
        template_id="academic_evidence",
        slide_payload={
            "title": "Overlap check",
            "objective": "Validate spacing",
            "key_points": [
                "Claim: Layout should avoid overlap.",
                "Evidence: Geometry checks enforce separation.",
                "Implication: Exported slide stays readable.",
            ],
        },
        reasons=["layout_overlap"],
        attempt=1,
    )
    chart_box = replanned["slots"]["chart"]
    callout_box = replanned["slots"]["callout"]
    assert chart_box["h"] >= replanned["constraints"]["min_chart_h"]
    assert not _boxes_overlap(callout_box, chart_box)


def test_chart_policy_avoids_synthetic_values_without_numeric_evidence():
    chart = _chart_data_for_slide(
        title="Qualitative Slide",
        key_points=[
            "Claim: Team confidence improved.",
            "Evidence: Stakeholder interviews indicate better alignment.",
            "Implication: Continue iterative validation.",
        ],
        seed=13,
        citations=[{"snippet": "No quantitative metric present in this excerpt."}],
        allow_synthetic=False,
    )
    assert chart["series"] == []
    assert chart["grounded"] is False
    assert chart["reason"] == "insufficient_numeric_evidence"

    composer = SlideComposerAgent()
    slide = composer.compose_slide(
        slide_id="s1",
        slide_payload={
            "title": "Qualitative Summary",
            "objective": "Summarize source-backed findings.",
            "key_points": [
                "Claim: Team confidence improved.",
                "Evidence: Interviews show better coordination.",
                "Implication: Maintain current operating model.",
            ],
            "speaker_notes": "No numeric evidence was provided.",
            "asset_focus": "Evidence card",
        },
        layout_spec=_layout_spec("hero_split_left"),
        theme=_default_theme("academic_evidence"),
        template_id="academic_evidence",
        slide_citations=[
            {
                "id": "S1",
                "source_type": "web",
                "title": "Interview Summary",
                "short_ref": "Interview Summary 2026",
                "snippet": "Findings remain qualitative without explicit numeric values.",
            }
        ],
    )
    assert not any(element.get("type") == "chart" for element in slide["elements"])
    assert any(element.get("type") == "image" for element in slide["elements"])


def test_citation_coverage_quality_check_passes_with_grounded_evidence(monkeypatch):
    engine = SlideProEngine()
    engine.instruction_agent = _ApproveInstructionAgent()

    async def fake_research(**kwargs):
        return {
            "source_text": "Completion increased to 72% and latency dropped to 18%.",
            "evidence_catalog": [
                {
                    "id": "S1",
                    "source_type": "web",
                    "title": "Program Metrics 2026",
                    "short_ref": "Program Metrics 2026",
                    "snippet": "Completion increased to 72% and latency dropped to 18%.",
                    "url": "https://example.com/metrics-2026",
                }
            ],
            "warnings": [],
            "research_notes": [],
        }

    async def fake_content(**kwargs):
        return {
            "learning_goals": ["Interpret grounded metrics"],
            "source": "fallback",
            "slides": [
                {
                    "title": "Metric Snapshot",
                    "objective": "Completion reached 72% with latency at 18%.",
                    "key_points": [
                        "Claim: Completion reached 72%.",
                        "Evidence: Source reports latency at 18%.",
                        "Implication: Scale the intervention to similar cohorts.",
                    ],
                    "speaker_notes": "Keep quantitative claims tied to citation [S1].",
                    "asset_focus": "Metric trend card",
                }
            ],
        }

    def fake_layout_run(**kwargs):
        return [_layout_spec("hero_split_left")]

    monkeypatch.setattr(engine.research_agent, "run", fake_research)
    monkeypatch.setattr(engine.content_agent, "run", fake_content)
    monkeypatch.setattr(engine.layout_agent, "run", fake_layout_run)

    result = asyncio.run(
        engine.generate(
            title="Citation Coverage",
            language="en",
            source_text="",
            source_records=None,
            instructions="",
            settings={
                "slide_count": 1,
                "template_id": "academic_evidence",
                "max_instruction_loops": 1,
            },
        )
    )
    checks = {item["name"]: item for item in result["quality_checks"]}
    assert checks["citation_coverage"]["status"] == "pass"
    assert checks["chart_grounding"]["status"] == "pass"


def test_instruction_max_loops_allows_user_setting_above_five():
    assert _instruction_max_loops({"max_instruction_loops": 8}) == 8
    assert _instruction_max_loops({"max_instruction_loops": 99}) == 20
    assert _instruction_max_loops({"max_instruction_loops": 0}) == 1


def test_composer_uses_rgb_fill_for_callout_and_metric_cards():
    composer = SlideComposerAgent()
    slide = composer.compose_slide(
        slide_id="s1",
        slide_payload={
            "title": "Fill Color Test",
            "objective": "Check fills",
            "key_points": [
                "Claim: Accuracy reached 82% in internal evaluation.",
                "Evidence: Latency dropped to 34 ms after optimization.",
                "Implication: Throughput improved by 27% week-over-week.",
            ],
            "speaker_notes": "notes",
            "asset_focus": "visual",
        },
        layout_spec=_layout_spec("timeline_flow"),
        theme=_default_theme("academic_evidence"),
        template_id="academic_evidence",
        slide_citations=[
            {
                "id": "S1",
                "source_type": "web",
                "title": "Benchmark Source",
                "short_ref": "Benchmark Source",
                "snippet": "Accuracy reached 82% in controlled evaluation.",
            }
        ],
    )
    shapes = [
        element
        for element in slide["elements"]
        if element.get("type") == "shape"
        and isinstance(element.get("style"), dict)
        and (
            "callout" in str(element.get("id"))
            or "metric_" in str(element.get("id"))
            or element["style"].get("purpose") == "chart_fallback"
        )
    ]
    assert shapes
    for shape in shapes:
        fill = shape["style"].get("fill")
        assert isinstance(fill, str)
        assert re.fullmatch(r"#[0-9A-F]{6}", fill), f"Expected RGB fill, got: {fill}"


def test_metric_extractor_rejects_page_and_lecture_indices():
    text = "ExploringCS. Lecture 6. pp.5-10. Chapter 2 introduces concepts."
    assert _extract_metric_values(text, max_values=8) == []

    metric_text = "Model accuracy reached 82% and latency dropped to 34 ms in benchmark runs."
    values = _extract_metric_values(metric_text, max_values=8)
    assert values[:2] == [82.0, 34.0]


def test_composer_avoids_callout_for_academic_hero_layout():
    composer = SlideComposerAgent()
    slide = composer.compose_slide(
        slide_id="s1",
        slide_payload={
            "title": "No Forced Callout",
            "objective": "Use cleaner composition for readability.",
            "key_points": [
                "Claim: Core concept summary.",
                "Evidence: Citation-backed detail.",
                "Implication: Next teaching action.",
            ],
            "speaker_notes": "notes",
            "asset_focus": "visual",
        },
        layout_spec=_layout_spec("hero_split_left"),
        theme=_default_theme("academic_evidence"),
        template_id="academic_evidence",
        slide_citations=[
            {
                "id": "S1",
                "source_type": "web",
                "title": "Source",
                "short_ref": "Source",
                "snippet": "Accuracy reached 82% and latency was 34 ms.",
            }
        ],
    )
    assert not any("callout" in str(element.get("id")) for element in slide["elements"])

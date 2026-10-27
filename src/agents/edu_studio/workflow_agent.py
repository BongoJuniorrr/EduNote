# -*- coding: utf-8 -*-
"""
Edu Studio workflow agent.

Implements education-focused agentic workflows with structured JSON outputs.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
from typing import Any

from src.agents.base_agent import BaseAgent
from src.utils.json_parser import parse_json_response

SLIDE_LAYOUT_HINTS = {
    "title",
    "bullets",
    "comparison",
    "timeline",
    "equation",
    "summary",
}
SLIDE_LAYOUT_SEQUENCE = ["title", "bullets", "comparison", "timeline", "equation", "summary"]

WORKFLOW_SPECS: dict[str, dict[str, Any]] = {
    "slide_deck": {
        "name": "Lecture Slide Generator",
        "description": (
            "Generate a professional presentation-ready slide deck from lesson materials "
            "with coherent story arc, polished speaker notes, and actionable classroom activities."
        ),
        "setting_hints": {
            "template": "professional_lecture | workshop_active | keynote_executive | data_story",
            "target_grade": "e.g. Grade 7",
            "duration_minutes": 45,
            "slide_count": 15,
            "style": "clean-academic",
            "style_directives": (
                "Detailed style instructions (tone, visual motif, icon style, spacing, "
                "title voice, chart preferences, do/don't list)"
            ),
            "storyline_structure": "problem_to_solution | timeline | compare_contrast | pyramid",
            "audience_persona": "undergraduate beginners, educators, executives, etc.",
            "depth_mode": "overview | standard | deep",
            "language": "vi or en",
        },
        "output_shape": {
            "deck_theme": {
                "palette": {
                    "background": "#F8FAFC",
                    "foreground": "#0F172A",
                    "accent": "#0EA5E9",
                    "muted": "#475569",
                },
                "typography": {
                    "font_family": "Inter, Segoe UI, sans-serif",
                    "title_scale": "2rem",
                    "body_scale": "1rem",
                },
                "visual_style": "clean-academic",
                "ratio": "16:9",
            },
            "slides": [
                {
                    "title": "string",
                    "objective": "string",
                    "key_points": ["string"],
                    "activity": "string",
                    "speaker_notes": "string",
                    "layout_hint": "title|bullets|comparison|timeline|equation|summary",
                    "visual_hint": "icon-set or simple diagram intent",
                    "visual_prompt": "detailed illustration brief (composition + focus + labels)",
                }
            ],
            "design_guidelines": ["string"],
            "assessment_checkpoints": ["string"],
        },
    },
    "exam_blueprint": {
        "name": "Exam Matrix Builder",
        "description": (
            "Generate exam papers aligned with an exam matrix and source materials."
        ),
        "setting_hints": {
            "matrix_definition": "JSON/CSV text of competency x difficulty matrix",
            "total_score": 10,
            "variants": 2,
            "question_types": ["mcq", "short_answer", "essay"],
            "language": "vi or en",
        },
        "output_shape": {
            "matrix_validation": ["string"],
            "exam_variants": [
                {
                    "variant": "A",
                    "questions": [
                        {
                            "id": "Q1",
                            "type": "mcq",
                            "difficulty": "understand",
                            "prompt": "string",
                            "options": ["A", "B", "C", "D"],
                            "answer": "string",
                            "rationale": "string",
                            "source_alignment": "string",
                        }
                    ],
                }
            ],
            "rubric": ["string"],
        },
    },
    "lesson_plan": {
        "name": "Lesson Plan Generator",
        "description": (
            "Generate lesson plans that follow a provided sample template and "
            "curriculum constraints."
        ),
        "setting_hints": {
            "target_grade": "e.g. Grade 10",
            "duration_minutes": 45,
            "teaching_methods": ["discussion", "project-based"],
            "template_requirements": "Required section names and format",
            "language": "vi or en",
        },
        "output_shape": {
            "lesson_plan_sections": [
                {"section": "string", "content": "string", "duration": "string"}
            ],
            "assessment": ["string"],
            "differentiation": ["string"],
            "homework": ["string"],
        },
    },
    "learning_outcome_mapper": {
        "name": "Learning Outcome Mapper",
        "description": "Map materials to CLO/PLO outcomes and identify coverage gaps.",
        "setting_hints": {"framework": "CLO/PLO or custom", "language": "vi or en"},
        "output_shape": {
            "outcome_map": [
                {
                    "outcome": "string",
                    "evidence": ["string"],
                    "coverage": "high/medium/low",
                    "gap_actions": ["string"],
                }
            ]
        },
    },
    "rubric_builder": {
        "name": "Rubric Builder",
        "description": "Generate rubric criteria, performance levels, and scoring notes.",
        "setting_hints": {
            "assessment_type": "essay/project/presentation",
            "levels": 4,
            "language": "vi or en",
        },
        "output_shape": {
            "rubric": [
                {
                    "criterion": "string",
                    "weight": "string",
                    "levels": [
                        {"level": "Excellent", "descriptor": "string", "score_band": "string"}
                    ],
                }
            ]
        },
    },
    "misconception_detector": {
        "name": "Misconception Detector",
        "description": "Identify likely misconceptions and corrective teaching interventions.",
        "setting_hints": {"language": "vi or en"},
        "output_shape": {
            "misconceptions": [
                {
                    "pattern": "string",
                    "evidence": "string",
                    "root_cause": "string",
                    "intervention": "string",
                }
            ]
        },
    },
    "adaptive_quiz_coach": {
        "name": "Adaptive Quiz Coach",
        "description": "Generate adaptive quiz sequences with remediation paths.",
        "setting_hints": {
            "question_count": 8,
            "start_level": "medium",
            "language": "vi or en",
        },
        "output_shape": {
            "quiz_sequence": [
                {
                    "id": "Q1",
                    "difficulty": "easy/medium/hard",
                    "prompt": "string",
                    "answer": "string",
                    "hint": "string",
                    "remediation_if_wrong": "string",
                }
            ]
        },
    },
    "curriculum_alignment": {
        "name": "Curriculum Alignment Checker",
        "description": "Check alignment between generated materials and curriculum standards.",
        "setting_hints": {
            "curriculum_standard": "VN framework/Common Core/custom",
            "language": "vi or en",
        },
        "output_shape": {
            "alignment_report": [
                {
                    "standard": "string",
                    "status": "aligned/partial/missing",
                    "evidence": "string",
                    "recommendation": "string",
                }
            ]
        },
    },
    "content_safety_fact_check": {
        "name": "Content Safety & Fact Checker",
        "description": "Check factual grounding, safety risk, and citation coverage.",
        "setting_hints": {"language": "vi or en"},
        "output_shape": {
            "safety_findings": [
                {"severity": "low/medium/high", "issue": "string", "fix": "string"}
            ],
            "fact_check": [
                {"claim": "string", "status": "grounded/unverified", "evidence": "string"}
            ],
        },
    },
}

WORKFLOW_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "slide_deck": [
        {
            "id": "professional_lecture",
            "name": "Professional Lecture",
            "description": "Balanced academic deck for classroom teaching.",
            "settings": {
                "target_grade": "University",
                "duration_minutes": 45,
                "slide_count": 12,
                "style": "clean-academic",
                "style_directives": (
                    "Professional lecture aesthetic; high contrast title hierarchy; "
                    "minimal icons; avoid clutter; favor clean visual metaphors."
                ),
                "include_activity": True,
                "storyline_structure": "problem_to_solution",
                "audience_persona": "undergraduate learners",
                "depth_mode": "standard",
                "include_case_study": True,
            },
        },
        {
            "id": "workshop_active",
            "name": "Workshop Active",
            "description": "Interactive workshop deck with more activities.",
            "settings": {
                "target_grade": "Professional Training",
                "duration_minutes": 90,
                "slide_count": 18,
                "style": "visual-storytelling",
                "style_directives": (
                    "Workshop style with energetic visuals, bold section dividers, "
                    "scenario cards, and practical callouts for interaction."
                ),
                "include_activity": True,
                "storyline_structure": "timeline",
                "audience_persona": "mixed-skill participants",
                "depth_mode": "deep",
                "include_case_study": True,
            },
        },
        {
            "id": "keynote_executive",
            "name": "Executive Keynote",
            "description": "High-impact narrative deck for leadership audience.",
            "settings": {
                "target_grade": "Executive",
                "duration_minutes": 30,
                "slide_count": 10,
                "style": "executive-impact",
                "style_directives": (
                    "Executive boardroom style; concise statements; premium typography; "
                    "strategic visuals; one insight per slide with clear business takeaway."
                ),
                "include_activity": False,
                "storyline_structure": "pyramid",
                "audience_persona": "decision makers",
                "depth_mode": "overview",
                "include_case_study": True,
            },
        },
        {
            "id": "data_story",
            "name": "Data Story",
            "description": "Data-driven storyline with evidence-focused slides.",
            "settings": {
                "target_grade": "University",
                "duration_minutes": 50,
                "slide_count": 14,
                "style": "data-briefing",
                "style_directives": (
                    "Data briefing style; chart-first storytelling; evidence captions; "
                    "balanced whitespace; technical but readable."
                ),
                "include_activity": True,
                "storyline_structure": "compare_contrast",
                "audience_persona": "analytical audience",
                "depth_mode": "deep",
                "include_case_study": True,
            },
        },
    ],
    "exam_blueprint": [
        {
            "id": "standard_midterm",
            "name": "Standard Midterm",
            "description": "Balanced midterm matrix with mixed question types.",
            "settings": {
                "matrix_definition": (
                    "Topic,Difficulty,Question Count\n"
                    "Fractions,Understand,4\n"
                    "Fractions,Apply,2"
                ),
                "total_score": 10,
                "variants": 2,
                "question_types": ["mcq", "short_answer"],
            },
        },
        {
            "id": "competency_deep",
            "name": "Competency Deep",
            "description": "Higher-rigor variant with stronger application emphasis.",
            "settings": {
                "matrix_definition": (
                    "Topic,Difficulty,Question Count\n"
                    "Core Theory,Understand,3\n"
                    "Applied Tasks,Apply,4\n"
                    "Analysis,Analyze,2"
                ),
                "total_score": 100,
                "variants": 3,
                "question_types": ["mcq", "short_answer", "essay"],
            },
        },
    ],
    "lesson_plan": [
        {
            "id": "compact_45m",
            "name": "Compact 45m",
            "description": "Single-period lesson plan for standard classroom sessions.",
            "settings": {
                "target_grade": "Grade 10",
                "duration_minutes": 45,
                "template_requirements": (
                    "Sections: Objectives, Materials, Procedure, Assessment, Homework"
                ),
                "teaching_methods": ["discussion", "guided practice"],
            },
        },
        {
            "id": "project_based",
            "name": "Project-Based",
            "description": "Longer plan with collaboration and reflection activities.",
            "settings": {
                "target_grade": "University",
                "duration_minutes": 90,
                "template_requirements": (
                    "Sections: Warm-up, Exploration, Group Task, Presentation, Reflection"
                ),
                "teaching_methods": ["project-based", "peer review", "presentation"],
            },
        },
    ],
    "learning_outcome_mapper": [
        {
            "id": "clo_plo",
            "name": "CLO/PLO Standard",
            "description": "Default mapping aligned to CLO/PLO format.",
            "settings": {"framework": "CLO/PLO"},
        },
        {
            "id": "accreditation_gap",
            "name": "Accreditation Gap",
            "description": "Focus on gap detection and remediation planning.",
            "settings": {"framework": "ABET-style outcomes"},
        },
    ],
    "rubric_builder": [
        {
            "id": "presentation_rubric",
            "name": "Presentation Rubric",
            "description": "Rubric for oral presentation and slide quality.",
            "settings": {"assessment_type": "presentation", "levels": 4},
        },
        {
            "id": "project_rubric",
            "name": "Project Rubric",
            "description": "Rubric for end-to-end project deliverables.",
            "settings": {"assessment_type": "project", "levels": 5},
        },
    ],
    "misconception_detector": [
        {
            "id": "foundation_scan",
            "name": "Foundation Scan",
            "description": "Identify misconceptions at foundational concept level.",
            "settings": {"focus_scope": "core concepts", "confidence_threshold": "medium"},
        },
        {
            "id": "exam_focus",
            "name": "Exam Focus",
            "description": "Prioritize misconceptions that affect test performance.",
            "settings": {"focus_scope": "exam misconceptions", "confidence_threshold": "high"},
        },
    ],
    "adaptive_quiz_coach": [
        {
            "id": "mastery_path",
            "name": "Mastery Path",
            "description": "Stepped adaptive quiz to build concept mastery.",
            "settings": {"question_count": 8, "start_level": "medium"},
        },
        {
            "id": "remediation_first",
            "name": "Remediation First",
            "description": "Starts easy and branches aggressively when errors occur.",
            "settings": {"question_count": 10, "start_level": "easy"},
        },
    ],
    "curriculum_alignment": [
        {
            "id": "viet_moet",
            "name": "Vietnam MOET",
            "description": "Alignment profile for Vietnam MOET standards.",
            "settings": {"curriculum_standard": "Vietnam MOET"},
        },
        {
            "id": "outcome_based",
            "name": "Outcome-Based",
            "description": "Alignment profile for OBE and competency frameworks.",
            "settings": {"curriculum_standard": "OBE / competency framework"},
        },
    ],
    "content_safety_fact_check": [
        {
            "id": "strict_audit",
            "name": "Strict Audit",
            "description": "Comprehensive safety and factual coverage scan.",
            "settings": {"strictness": "high", "require_citations": True},
        },
        {
            "id": "fast_screen",
            "name": "Fast Screen",
            "description": "Quick pass for obvious factual or safety issues.",
            "settings": {"strictness": "medium", "require_citations": False},
        },
    ],
}


class EduStudioWorkflowAgent(BaseAgent):
    """Edu Studio orchestration agent."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        model: str | None = None,
        binding: str = "openai",
        language: str = "en",
    ):
        super().__init__(
            module_name="edu_studio",
            agent_name="workflow_agent",
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            model=model,
            binding=binding,
            language=language,
        )

    @classmethod
    def get_workflow_specs(cls) -> dict[str, dict[str, Any]]:
        return WORKFLOW_SPECS

    @classmethod
    def get_workflow_catalog(cls) -> list[dict[str, Any]]:
        catalog: list[dict[str, Any]] = []
        for workflow, spec in WORKFLOW_SPECS.items():
            catalog.append(
                {
                    "id": workflow,
                    "name": spec.get("name", workflow),
                    "description": spec.get("description", ""),
                    "templates": deepcopy(WORKFLOW_TEMPLATES.get(workflow, [])),
                }
            )
        return catalog

    async def process(self, workflow: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.run_workflow(workflow, payload)

    async def run_workflow(self, workflow: str, payload: dict[str, Any]) -> dict[str, Any]:
        if workflow not in WORKFLOW_SPECS:
            raise ValueError(f"Unsupported workflow: {workflow}")

        spec = WORKFLOW_SPECS[workflow]
        title = (payload.get("title") or "").strip()
        language = (payload.get("language") or "vi").strip().lower()
        instructions = (payload.get("instructions") or "").strip()
        settings = payload.get("settings") or {}
        if not isinstance(settings, dict):
            settings = {}
        settings_template = str(payload.get("settings_template") or "").strip()
        context_enrichment = payload.get("context_enrichment")
        if not isinstance(context_enrichment, dict):
            context_enrichment = {}
        source_context = (payload.get("combined_context") or payload.get("source_text") or "").strip()
        dry_run = bool(payload.get("dry_run", False))

        if not source_context:
            source_context = "No source material was provided. Use reasonable educational assumptions."

        if dry_run:
            result = self._build_fallback_result(workflow, title, language, settings, source_context)
            result["quality_checks"] = self._post_validate(
                workflow,
                settings,
                result.get("quality_checks", []),
                schema_warnings=[],
            )
            return result

        if workflow == "slide_deck":
            system_prompt, user_prompt = self._build_slide_deck_prompts(
                spec=spec,
                title=title,
                language=language,
                settings=settings,
                settings_template=settings_template,
                instructions=instructions,
                source_context=source_context,
                context_enrichment=context_enrichment,
            )
        else:
            system_prompt, user_prompt = self._build_generic_prompts(
                workflow=workflow,
                spec=spec,
                title=title,
                language=language,
                settings=settings,
                settings_template=settings_template,
                instructions=instructions,
                source_context=source_context,
                context_enrichment=context_enrichment,
            )

        response = await self.call_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            response_format={"type": "json_object"},
            stage=f"edu_studio:{workflow}",
        )

        parsed = parse_json_response(response, logger_instance=self.logger, fallback={})
        if not isinstance(parsed, dict) or not parsed:
            raise ValueError("The model did not return a valid Edu Studio JSON result. Retry with a model that supports structured output.")

        normalized, schema_warnings = self._normalize_result(
            workflow,
            title,
            language,
            settings,
            parsed,
            source_context,
        )
        normalized["quality_checks"] = self._post_validate(
            workflow,
            settings,
            normalized.get("quality_checks", []),
            schema_warnings=schema_warnings,
        )
        return normalized

    def _build_generic_prompts(
        self,
        workflow: str,
        spec: dict[str, Any],
        title: str,
        language: str,
        settings: dict[str, Any],
        settings_template: str,
        instructions: str,
        source_context: str,
        context_enrichment: dict[str, Any],
    ) -> tuple[str, str]:
        system_prompt = (
            "You are Edu Studio, a precise instructional design assistant.\n"
            "Always return STRICT JSON object only.\n"
            "Do not include markdown code fences.\n"
            "Use concise but actionable educational outputs.\n"
            "Ground every major section in the provided source context."
        )

        user_prompt = (
            f"Workflow: {workflow}\n"
            f"Workflow Name: {spec['name']}\n"
            f"Workflow Description: {spec['description']}\n\n"
            f"Language: {language}\n"
            f"Title: {title or spec['name']}\n"
            f"Settings Template: {settings_template or '(not specified)'}\n"
            f"Settings JSON:\n{json.dumps(settings, ensure_ascii=False, indent=2)}\n\n"
            f"Context enrichment metadata:\n"
            f"{json.dumps(context_enrichment, ensure_ascii=False, indent=2)}\n\n"
            f"Output JSON shape guidance:\n"
            f"{json.dumps(spec['output_shape'], ensure_ascii=False, indent=2)}\n\n"
            "Return a JSON object with keys:\n"
            "- title: string\n"
            "- summary: string\n"
            "- deliverable_markdown: string\n"
            "- structured_data: object\n"
            "- quality_checks: array of {name,status,detail}\n"
            "- next_actions: string[]\n\n"
            f"Additional user instructions:\n{instructions or '(none)'}\n\n"
            f"Source context:\n{source_context}"
        )
        return system_prompt, user_prompt

    def _build_slide_deck_prompts(
        self,
        spec: dict[str, Any],
        title: str,
        language: str,
        settings: dict[str, Any],
        settings_template: str,
        instructions: str,
        source_context: str,
        context_enrichment: dict[str, Any],
    ) -> tuple[str, str]:
        structure_request = (
            str(
                settings.get("storyline_structure")
                or settings.get("structure_template")
                or settings.get("template_requirements")
                or ""
            ).strip()
            or "(not specified)"
        )
        target_grade = str(settings.get("target_grade") or "(not specified)")
        duration_minutes = str(settings.get("duration_minutes") or "(not specified)")
        slide_count = self._resolve_slide_count(settings)
        style_directives = (
            str(
                settings.get("style_directives")
                or settings.get("visual_directives")
                or settings.get("design_directives")
                or ""
            ).strip()
            or "(not specified)"
        )

        system_prompt = (
            "You are Edu Studio's senior presentation strategist and instructional designer.\n"
            "Always return STRICT JSON object only, without markdown code fences.\n"
            "Build a professional presentation that is boardroom-ready and classroom-usable.\n"
            "Expand the content depth using the available source context and enrichment context.\n"
            "Avoid generic filler text. Every slide must contain concrete insights, examples, or evidence.\n"
            "Keep a single coherent narrative arc across the full deck.\n"
            "Use varied slide layouts (title, bullets, comparison, timeline, equation, summary) across the deck.\n"
            "For each slide, provide a vivid visual direction that can be rendered as an illustration.\n"
            "Honor style directives strictly unless they conflict with factual clarity.\n"
            "If formulas are relevant, write LaTeX with $...$ for inline and $$...$$ for block equations.\n"
            "Speaker notes should be practical, transition-aware, and execution-ready."
        )

        user_prompt = (
            f"Workflow: slide_deck\n"
            f"Workflow Name: {spec['name']}\n"
            f"Workflow Description: {spec['description']}\n\n"
            f"Language: {language}\n"
            f"Presentation Title: {title or spec['name']}\n"
            f"Target grade/audience level: {target_grade}\n"
            f"Duration (minutes): {duration_minutes}\n"
            f"Expected slide count: {slide_count}\n"
            f"Settings template: {settings_template or '(not specified)'}\n"
            f"Requested structure: {structure_request}\n\n"
            f"Slide style directives: {style_directives}\n\n"
            "Requirements:\n"
            "1. Generate a polished professional deck narrative from opening context to final takeaway.\n"
            "2. Each slide must include: title, objective, 3-6 key_points, activity, speaker_notes, layout_hint, visual_hint, visual_prompt.\n"
            "3. speaker_notes should include delivery guidance and transitions to the next slide.\n"
            "4. Maintain visual consistency through deck_theme while varying content layouts.\n"
            "5. Expand and enrich content with contextual examples, concise data points, and realistic applications.\n"
            "6. visual_prompt must be specific (foreground/midground/background, labels, chart/diagram intent, style cues) instead of generic.\n"
            "7. Respect additional structure and constraints from user settings/instructions.\n\n"
            f"Settings JSON:\n{json.dumps(settings, ensure_ascii=False, indent=2)}\n\n"
            f"Context enrichment metadata:\n"
            f"{json.dumps(context_enrichment, ensure_ascii=False, indent=2)}\n\n"
            f"Output JSON shape guidance:\n"
            f"{json.dumps(spec['output_shape'], ensure_ascii=False, indent=2)}\n\n"
            "Return a JSON object with keys:\n"
            "- title: string\n"
            "- summary: string\n"
            "- deliverable_markdown: string\n"
            "- structured_data: object\n"
            "- quality_checks: array of {name,status,detail}\n"
            "- next_actions: string[]\n\n"
            f"Additional user instructions:\n{instructions or '(none)'}\n\n"
            f"Source context:\n{source_context}"
        )
        return system_prompt, user_prompt

    def _normalize_result(
        self,
        workflow: str,
        title: str,
        language: str,
        settings: dict[str, Any],
        parsed: dict[str, Any],
        source_context: str,
    ) -> tuple[dict[str, Any], list[str]]:
        default = self._build_fallback_result(workflow, title, language, settings, source_context)

        structured_raw = parsed.get("structured_data")
        structured_data, schema_warnings = self._coerce_structured_data(
            workflow,
            structured_raw,
            settings,
        )

        next_actions_raw = parsed.get("next_actions")
        next_actions = self._to_string_list(next_actions_raw)
        if not next_actions:
            next_actions = default["next_actions"]

        result = {
            "workflow": workflow,
            "title": str(parsed.get("title") or default["title"]),
            "summary": str(parsed.get("summary") or default["summary"]),
            "deliverable_markdown": str(
                parsed.get("deliverable_markdown") or default["deliverable_markdown"]
            ),
            "structured_data": structured_data,
            "quality_checks": parsed.get("quality_checks") or default["quality_checks"],
            "next_actions": next_actions,
            "metadata": {
                "model": self.get_model(),
                "provider": self.binding,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "language": language,
            },
        }
        return result, schema_warnings

    def _coerce_structured_data(
        self,
        workflow: str,
        structured_data: Any,
        settings: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        defaults = self._build_structured_defaults(workflow, settings)
        warnings: list[str] = []

        if not isinstance(structured_data, dict):
            warnings.append("structured_data missing or invalid; fallback template applied")
            return defaults, warnings

        normalized = deepcopy(defaults)
        for key, default_value in defaults.items():
            if key not in structured_data:
                warnings.append(f"structured_data.{key} missing; fallback applied")
                continue

            candidate = structured_data[key]
            if not self._compatible_value_type(candidate, default_value):
                warnings.append(f"structured_data.{key} invalid type; fallback applied")
                continue

            normalized[key] = candidate

        for key, value in structured_data.items():
            if key not in normalized:
                normalized[key] = value

        if workflow == "slide_deck":
            normalized, slide_warnings = self._normalize_slide_deck_structured_data(
                normalized,
                settings,
            )
            warnings.extend(slide_warnings)

        return normalized, warnings

    def _normalize_slide_deck_structured_data(
        self,
        structured_data: dict[str, Any],
        settings: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        warnings: list[str] = []
        expected_count = self._resolve_slide_count(settings)

        theme = structured_data.get("deck_theme")
        requested_style = str(settings.get("style") or "").strip().lower()
        if not isinstance(theme, dict):
            warnings.append("slide_deck.deck_theme missing; default theme applied")
            theme = self._build_deck_theme(str(settings.get("style") or "clean-academic"))
            structured_data["deck_theme"] = theme
        elif requested_style:
            current_style = str(theme.get("visual_style") or "").strip().lower()
            if current_style != requested_style:
                warnings.append(
                    "slide_deck.deck_theme.visual_style mismatched requested style; adjusted"
                )
                structured_data["deck_theme"] = self._build_deck_theme(requested_style)

        slides_raw = structured_data.get("slides")
        if not isinstance(slides_raw, list) or not slides_raw:
            warnings.append("slide_deck.slides missing; default slide outline applied")
            slides_raw = []

        normalized_slides: list[dict[str, Any]] = []
        for index, slide in enumerate(slides_raw, start=1):
            normalized_slides.append(self._normalize_slide(slide, index, warnings))

        if len(normalized_slides) < expected_count:
            warnings.append(
                f"slide_deck.slides had {len(normalized_slides)} items; filled to {expected_count}"
            )
            for slide_index in range(len(normalized_slides) + 1, expected_count + 1):
                normalized_slides.append(self._build_slide_item(slide_index))

        if len(normalized_slides) > expected_count:
            warnings.append(
                f"slide_deck.slides had {len(normalized_slides)} items; trimmed to {expected_count}"
            )
            normalized_slides = normalized_slides[:expected_count]

        normalized_slides = self._rebalance_layout_hints(normalized_slides, warnings)

        structured_data["slides"] = normalized_slides
        if not isinstance(structured_data.get("design_guidelines"), list):
            warnings.append("slide_deck.design_guidelines invalid; fallback applied")
            structured_data["design_guidelines"] = [
                "Use high contrast headings and concise bullet points.",
                "Keep one core concept per slide.",
            ]

        if not isinstance(structured_data.get("assessment_checkpoints"), list):
            warnings.append("slide_deck.assessment_checkpoints invalid; fallback applied")
            structured_data["assessment_checkpoints"] = [
                "Check comprehension with one quick question every 2 slides.",
            ]

        return structured_data, warnings

    def _normalize_slide(
        self,
        slide: Any,
        index: int,
        warnings: list[str],
    ) -> dict[str, Any]:
        if not isinstance(slide, dict):
            warnings.append(f"slide[{index}] invalid type; fallback slide applied")
            return self._build_slide_item(index)

        fallback = self._build_slide_item(index)

        title = str(slide.get("title") or fallback["title"]).strip() or fallback["title"]
        objective = str(slide.get("objective") or fallback["objective"]).strip() or fallback["objective"]

        key_points = self._to_string_list(slide.get("key_points"))
        if not key_points:
            key_points = fallback["key_points"]
            warnings.append(f"slide[{index}].key_points missing; fallback applied")
        elif len(key_points) < 3:
            warnings.append(f"slide[{index}].key_points too short; expanded with fallback points")
            for fallback_point in fallback["key_points"]:
                if len(key_points) >= 3:
                    break
                if fallback_point not in key_points:
                    key_points.append(fallback_point)

        activity = str(slide.get("activity") or fallback["activity"]).strip() or fallback["activity"]
        speaker_notes = (
            str(slide.get("speaker_notes") or fallback["speaker_notes"]).strip()
            or fallback["speaker_notes"]
        )
        if len(speaker_notes) < 35:
            warnings.append(f"slide[{index}].speaker_notes too brief; fallback guidance applied")
            speaker_notes = fallback["speaker_notes"]

        layout_hint = str(slide.get("layout_hint") or fallback["layout_hint"]).strip().lower()
        if layout_hint not in SLIDE_LAYOUT_HINTS:
            layout_hint = fallback["layout_hint"]
            warnings.append(f"slide[{index}].layout_hint invalid; fallback '{layout_hint}' applied")

        visual_hint = str(slide.get("visual_hint") or fallback["visual_hint"]).strip()
        if not visual_hint:
            visual_hint = fallback["visual_hint"]

        visual_prompt = (
            str(
                slide.get("visual_prompt")
                or slide.get("illustration_prompt")
                or fallback["visual_prompt"]
            ).strip()
            or fallback["visual_prompt"]
        )

        return {
            "title": title,
            "objective": objective,
            "key_points": key_points,
            "activity": activity,
            "speaker_notes": speaker_notes,
            "layout_hint": layout_hint,
            "visual_hint": visual_hint,
            "visual_prompt": visual_prompt,
        }

    def _rebalance_layout_hints(
        self,
        slides: list[dict[str, Any]],
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        if len(slides) < 4:
            return slides

        unique_hints = {str(slide.get("layout_hint") or "").lower() for slide in slides}
        unique_hints.discard("")
        if len(unique_hints) >= 3:
            return slides

        warnings.append("slide_deck.layout_hint lacked diversity; auto-distributed layout hints")
        for idx, slide in enumerate(slides):
            slide["layout_hint"] = SLIDE_LAYOUT_SEQUENCE[idx % len(SLIDE_LAYOUT_SEQUENCE)]
        return slides

    def _build_structured_defaults(self, workflow: str, settings: dict[str, Any]) -> dict[str, Any]:
        defaults = deepcopy(WORKFLOW_SPECS[workflow]["output_shape"])

        if workflow == "slide_deck":
            slide_count = self._resolve_slide_count(settings)
            defaults["deck_theme"] = self._build_deck_theme(
                style=str(settings.get("style") or "clean-academic")
            )
            defaults["slides"] = [self._build_slide_item(index) for index in range(1, slide_count + 1)]
            defaults["design_guidelines"] = [
                "Use a consistent visual rhythm across all slides.",
                "Favor concise bullets with one idea per line.",
                "Keep color accents for emphasis only.",
            ]
            defaults["assessment_checkpoints"] = [
                "Quick check-in question after each major concept block.",
                "Reserve final slide for recap and formative assessment.",
            ]

        return defaults

    @staticmethod
    def _compatible_value_type(candidate: Any, default_value: Any) -> bool:
        if isinstance(default_value, list):
            return isinstance(candidate, list)
        if isinstance(default_value, dict):
            return isinstance(candidate, dict)
        if isinstance(default_value, str):
            return isinstance(candidate, str)
        if isinstance(default_value, int):
            return isinstance(candidate, int)
        if isinstance(default_value, float):
            return isinstance(candidate, (int, float))
        if isinstance(default_value, bool):
            return isinstance(candidate, bool)
        return True

    @staticmethod
    def _resolve_slide_count(settings: dict[str, Any]) -> int:
        raw = settings.get("slide_count")
        if isinstance(raw, bool):
            return 10
        if isinstance(raw, (int, float)):
            return max(3, min(int(raw), 40))
        if isinstance(raw, str):
            try:
                return max(3, min(int(raw.strip()), 40))
            except ValueError:
                return 10
        return 10

    def _build_slide_theme(self, style: str) -> dict[str, Any]:
        normalized = style.strip().lower()

        themes = {
            "clean-academic": {
                "palette": {
                    "background": "#F8FAFC",
                    "foreground": "#0F172A",
                    "accent": "#0EA5E9",
                    "muted": "#475569",
                },
                "typography": {
                    "font_family": "Inter, Segoe UI, sans-serif",
                    "title_scale": "2rem",
                    "body_scale": "1rem",
                },
                "visual_style": "clean-academic",
                "ratio": "16:9",
            },
            "modern-grid": {
                "palette": {
                    "background": "#F5F3FF",
                    "foreground": "#1E1B4B",
                    "accent": "#2563EB",
                    "muted": "#4C1D95",
                },
                "typography": {
                    "font_family": "Inter, Segoe UI, sans-serif",
                    "title_scale": "2.1rem",
                    "body_scale": "1rem",
                },
                "visual_style": "modern-grid",
                "ratio": "16:9",
            },
            "executive-impact": {
                "palette": {
                    "background": "#F8FAFC",
                    "foreground": "#0B1324",
                    "accent": "#0D9488",
                    "muted": "#1E293B",
                },
                "typography": {
                    "font_family": "Inter, Segoe UI, sans-serif",
                    "title_scale": "2.15rem",
                    "body_scale": "1.02rem",
                },
                "visual_style": "executive-impact",
                "ratio": "16:9",
            },
            "visual-storytelling": {
                "palette": {
                    "background": "#FFFBEB",
                    "foreground": "#3F2A10",
                    "accent": "#D97706",
                    "muted": "#92400E",
                },
                "typography": {
                    "font_family": "Nunito Sans, Segoe UI, sans-serif",
                    "title_scale": "2.2rem",
                    "body_scale": "1.02rem",
                },
                "visual_style": "visual-storytelling",
                "ratio": "16:9",
            },
            "data-briefing": {
                "palette": {
                    "background": "#F1F5F9",
                    "foreground": "#0F172A",
                    "accent": "#2563EB",
                    "muted": "#334155",
                },
                "typography": {
                    "font_family": "Inter, Segoe UI, sans-serif",
                    "title_scale": "2rem",
                    "body_scale": "0.98rem",
                },
                "visual_style": "data-briefing",
                "ratio": "16:9",
            },
            "chalkboard": {
                "palette": {
                    "background": "#0F172A",
                    "foreground": "#E2E8F0",
                    "accent": "#22D3EE",
                    "muted": "#94A3B8",
                },
                "typography": {
                    "font_family": "Nunito Sans, Segoe UI, sans-serif",
                    "title_scale": "2rem",
                    "body_scale": "1rem",
                },
                "visual_style": "chalkboard",
                "ratio": "16:9",
            },
        }

        return deepcopy(themes.get(normalized, themes["clean-academic"]))

    def _build_deck_theme(self, style: str) -> dict[str, Any]:
        return self._build_slide_theme(style)

    def _build_slide_item(self, index: int) -> dict[str, Any]:
        return {
            "title": f"Slide {index}",
            "objective": "State one concrete takeaway the audience should remember.",
            "key_points": [
                "Explain the core concept with concise evidence.",
                "Add a practical example tied to real classroom or industry usage.",
                "Bridge this insight to the next section of the narrative.",
            ],
            "activity": "Prompt a 60-second reflection or mini discussion to verify understanding.",
            "speaker_notes": (
                "Open with context, emphasize one key claim, and transition clearly to the next slide "
                "using a short connective sentence."
            ),
            "layout_hint": "bullets",
            "visual_hint": "diagram intent: concept flow with 2-3 labeled elements",
            "visual_prompt": (
                "Create a clean academic illustration with one focal element in the center, "
                "two supporting labeled callouts, and subtle background shapes for depth."
            ),
        }

    @staticmethod
    def _to_string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []

        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                normalized.append(text)
        return normalized

    def _build_fallback_result(
        self,
        workflow: str,
        title: str,
        language: str,
        settings: dict[str, Any],
        source_context: str,
    ) -> dict[str, Any]:
        wf_name = WORKFLOW_SPECS[workflow]["name"]
        normalized_title = title or wf_name
        context_preview = source_context[:1200]

        return {
            "workflow": workflow,
            "title": normalized_title,
            "summary": (
                f"Draft generated for {wf_name}. This result is a deterministic fallback "
                "template and should be refined with full LLM generation."
            ),
            "deliverable_markdown": (
                f"# {normalized_title}\n\n"
                f"## Workflow\n{wf_name}\n\n"
                f"## Language\n{language}\n\n"
                "## Settings\n"
                f"```json\n{json.dumps(settings, ensure_ascii=False, indent=2)}\n```\n\n"
                "## Draft Deliverable\n"
                "1. Define objective and expected outcomes.\n"
                "2. Align content with source materials.\n"
                "3. Build assessment checkpoints.\n"
                "4. Add adaptation for mixed-level learners.\n\n"
                "## Source Preview\n"
                f"{context_preview}"
            ),
            "structured_data": self._build_structured_defaults(workflow, settings),
            "quality_checks": [
                {"name": "source_context_present", "status": "pass", "detail": "Source was provided."},
                {
                    "name": "fallback_mode",
                    "status": "warn",
                    "detail": "LLM output unavailable or dry_run mode enabled.",
                },
            ],
            "next_actions": [
                "Review settings and constraints.",
                "Regenerate with richer source materials for higher quality.",
                "Run curriculum alignment and safety checks before publishing.",
            ],
            "metadata": {
                "model": self.get_model(),
                "provider": self.binding,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "language": language,
            },
        }

    def _post_validate(
        self,
        workflow: str,
        settings: dict[str, Any],
        checks: list[dict[str, Any]] | None,
        schema_warnings: list[str] | None,
    ) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for item in checks or []:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", "info")).strip().lower() or "info"
            if status not in {"pass", "warn", "info", "error", "fail"}:
                status = "info"
            normalized.append(
                {
                    "name": str(item.get("name", "check")),
                    "status": status,
                    "detail": str(item.get("detail", "")),
                }
            )

        for warning in schema_warnings or []:
            normalized.append(
                {
                    "name": "structured_schema_backfill",
                    "status": "warn",
                    "detail": warning,
                }
            )

        if workflow == "exam_blueprint":
            matrix = settings.get("matrix_definition")
            if not matrix:
                normalized.append(
                    {
                        "name": "matrix_definition",
                        "status": "warn",
                        "detail": "Exam matrix is missing; alignment quality may be low.",
                    }
                )
        if workflow == "slide_deck":
            if not settings.get("slide_count"):
                normalized.append(
                    {
                        "name": "slide_count",
                        "status": "warn",
                        "detail": "No slide count provided. Deck length may be inconsistent.",
                    }
                )
        if workflow == "lesson_plan":
            if not settings.get("template_requirements"):
                normalized.append(
                    {
                        "name": "template_requirements",
                        "status": "warn",
                        "detail": "Lesson template requirements were not provided.",
                    }
                )

        if not normalized:
            normalized.append(
                {
                    "name": "basic_validation",
                    "status": "pass",
                    "detail": "No blocking validation issues detected.",
                }
            )
        return normalized

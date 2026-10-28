from __future__ import annotations

import json
from typing import Any

from src.agents.base_agent import BaseAgent
from src.agents.research.utils.json_utils import extract_json_from_text

from ..schemas import MissionBrief, MissionPlanRequest


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        parts = [part.strip("-• \t") for part in value.splitlines()]
        return [part for part in parts if part]
    return []


class ClarifierAgent(BaseAgent):
    def __init__(self, language: str = "en"):
        super().__init__(
            module_name="mission",
            agent_name="clarifier_agent",
            language=language,
        )

    async def process(
        self,
        request: MissionPlanRequest,
        *,
        notebook_context: list[dict[str, Any]],
        preset_defaults: dict[str, Any],
    ) -> MissionBrief:
        system_prompt = self.get_prompt(
            "system",
            "You turn ambiguous goals into structured, execution-ready mission briefs.",
        )
        user_template = self.get_prompt(
            "user_template",
            (
                "Goal: {goal}\nPreset: {preset}\nDesired outputs: {desired_outputs}\n"
                "Constraints: {constraints}\nSuccess criteria: {success_criteria}\n"
                "Primary KB: {primary_kb_name}\nNotebook context:\n{notebook_context}"
            ),
        )

        notebook_lines = []
        for notebook in notebook_context:
            notebook_lines.append(
                f"- {notebook.get('name', notebook.get('id', 'Notebook'))}: "
                f"{notebook.get('record_count', 0)} records"
            )

        user_prompt = user_template.format(
            goal=request.goal.strip(),
            preset=request.preset,
            desired_outputs=", ".join(request.desired_outputs) or "(use preset defaults)",
            constraints=request.constraints.strip() or "(none provided)",
            success_criteria=request.success_criteria.strip() or "(none provided)",
            primary_kb_name=request.primary_kb_name or "(none selected)",
            notebook_context="\n".join(notebook_lines) or "- No notebooks selected",
        )

        response = await self.call_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            response_format={"type": "json_object"},
            stage="clarify_mission",
        )

        data = extract_json_from_text(response)
        if isinstance(data, dict):
            return MissionBrief(
                working_title=str(data.get("working_title") or preset_defaults["label"]).strip()
                or preset_defaults["label"],
                objective=str(data.get("objective") or request.goal).strip() or request.goal,
                rationale=str(data.get("rationale") or "").strip(),
                deliverables=_as_list(data.get("deliverables")) or list(request.desired_outputs),
                success_criteria=_as_list(data.get("success_criteria"))
                or _as_list(request.success_criteria)
                or list(preset_defaults.get("default_success_criteria", [])),
                constraints=_as_list(data.get("constraints"))
                or _as_list(request.constraints)
                or list(preset_defaults.get("default_constraints", [])),
                assumptions=_as_list(data.get("assumptions")),
                required_resources=_as_list(data.get("required_resources")),
                execution_notes=_as_list(data.get("execution_notes")),
                key_questions=_as_list(data.get("key_questions")),
            )

        fallback_outputs = request.desired_outputs or list(preset_defaults.get("default_outputs", []))
        fallback_criteria = _as_list(request.success_criteria) or list(
            preset_defaults.get("default_success_criteria", [])
        )
        fallback_constraints = _as_list(request.constraints) or list(
            preset_defaults.get("default_constraints", [])
        )

        return MissionBrief(
            working_title=preset_defaults["label"],
            objective=request.goal.strip(),
            rationale="Fallback brief generated because structured clarification failed.",
            deliverables=fallback_outputs,
            success_criteria=fallback_criteria,
            constraints=fallback_constraints,
            assumptions=["Use only the selected notebooks and knowledge base unless the user broadens scope."],
            required_resources=[
                *([f"Primary KB: {request.primary_kb_name}"] if request.primary_kb_name else []),
                *([f"Notebook count: {len(request.notebook_ids)}"] if request.notebook_ids else []),
            ],
            execution_notes=[
                f"Preset: {request.preset}",
                f"Research depth: {request.research_depth}",
                "Prioritize grounded outputs over stylistic flourishes.",
            ],
            key_questions=[
                "What evidence is needed to support the final report?",
                "Which artifacts are essential for the requested deliverables?",
            ],
        )

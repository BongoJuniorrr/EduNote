from __future__ import annotations

import json
from typing import Any

from src.agents.base_agent import BaseAgent
from src.agents.research.utils.json_utils import extract_json_from_text

from ..schemas import MissionBrief, MissionPlanRequest, MissionStep

ALLOWED_STEP_TYPES = {
    "knowledge_map",
    "idea_board",
    "research_brief",
    "final_dossier",
    "review",
}


class PlannerAgent(BaseAgent):
    def __init__(self, language: str = "en"):
        super().__init__(
            module_name="mission",
            agent_name="planner_agent",
            language=language,
        )

    def _fallback_plan(
        self,
        brief: MissionBrief,
        request: MissionPlanRequest,
        capabilities: dict[str, bool],
    ) -> list[MissionStep]:
        steps: list[MissionStep] = []

        def add_step(step_type: str, title: str, rationale: str, outputs: list[str]) -> None:
            steps.append(
                MissionStep(
                    step_id=f"step_{len(steps) + 1}",
                    title=title,
                    step_type=step_type,  # type: ignore[arg-type]
                    rationale=rationale,
                    depends_on=[steps[-1].step_id] if steps else [],
                    outputs=outputs,
                )
            )

        wants_idea_board = any(
            item in brief.deliverables for item in ["idea_board", "scope_options", "risk_register"]
        )
        wants_knowledge_map = any(
            item in brief.deliverables for item in ["knowledge_map", "study_plan", "weakness_audit"]
        )

        if capabilities.get("has_notebooks") and wants_knowledge_map:
            add_step(
                "knowledge_map",
                "Build a grounded knowledge map",
                "Extract learning blocks and friction points from notebook records.",
                ["knowledge_map"],
            )

        if wants_idea_board or request.preset == "capstone_prep":
            add_step(
                "idea_board",
                "Generate and filter mission options",
                "Use notebook evidence or mission intent to surface actionable directions.",
                ["idea_board"],
            )

        if capabilities.get("has_primary_kb"):
            add_step(
                "research_brief",
                "Run evidence-grounded research",
                "Use the primary knowledge base to gather citations and supporting arguments.",
                ["research_brief"],
            )

        add_step(
            "final_dossier",
            "Synthesize final dossier",
            "Combine all artifacts into one concise, reviewable deliverable.",
            ["final_dossier"],
        )
        add_step(
            "review",
            "Review and stress-test dossier",
            "Score the dossier against the mission brief and trigger one revision pass if needed.",
            ["review"],
        )

        return steps

    async def process(
        self,
        brief: MissionBrief,
        request: MissionPlanRequest,
        *,
        capabilities: dict[str, bool],
    ) -> list[MissionStep]:
        system_prompt = self.get_prompt(
            "system",
            "You create minimal plans that maximize grounded outputs and minimize unnecessary steps.",
        )
        user_template = self.get_prompt(
            "user_template",
            (
                "Mission brief JSON:\n{brief_json}\n\n"
                "Mission request JSON:\n{request_json}\n\n"
                "Capabilities JSON:\n{capabilities_json}\n\n"
                "Return JSON with a `steps` array."
            ),
        )

        user_prompt = user_template.format(
            brief_json=json.dumps(brief.model_dump(), ensure_ascii=False, indent=2),
            request_json=json.dumps(request.model_dump(), ensure_ascii=False, indent=2),
            capabilities_json=json.dumps(capabilities, ensure_ascii=False, indent=2),
        )

        response = await self.call_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            response_format={"type": "json_object"},
            stage="plan_mission",
        )

        data = extract_json_from_text(response)
        if isinstance(data, dict) and isinstance(data.get("steps"), list):
            steps: list[MissionStep] = []
            for index, raw_step in enumerate(data["steps"], start=1):
                if not isinstance(raw_step, dict):
                    continue
                step_type = str(raw_step.get("step_type") or "").strip()
                if step_type not in ALLOWED_STEP_TYPES:
                    continue
                if step_type == "research_brief" and not capabilities.get("has_primary_kb"):
                    continue
                if step_type == "knowledge_map" and not capabilities.get("has_notebooks"):
                    continue
                steps.append(
                    MissionStep(
                        step_id=str(raw_step.get("step_id") or f"step_{index}"),
                        title=str(raw_step.get("title") or step_type.replace("_", " ").title()),
                        step_type=step_type,  # type: ignore[arg-type]
                        rationale=str(raw_step.get("rationale") or "").strip(),
                        depends_on=[
                            str(dep).strip() for dep in raw_step.get("depends_on", []) if str(dep).strip()
                        ],
                        outputs=[
                            str(item).strip()
                            for item in raw_step.get("outputs", [])
                            if str(item).strip()
                        ],
                        approval_required=bool(raw_step.get("approval_required", False)),
                        metadata=raw_step.get("metadata", {})
                        if isinstance(raw_step.get("metadata"), dict)
                        else {},
                    )
                )

            if steps:
                if steps[-1].step_type != "review":
                    steps.append(
                        MissionStep(
                            step_id=f"step_{len(steps) + 1}",
                            title="Review and stress-test dossier",
                            step_type="review",
                            rationale="Always end with a quality gate.",
                            depends_on=[steps[-1].step_id],
                            outputs=["review"],
                        )
                    )

                has_dossier = any(step.step_type == "final_dossier" for step in steps)
                if not has_dossier:
                    insert_at = max(len(steps) - 1, 0)
                    depends_on = [steps[insert_at - 1].step_id] if insert_at > 0 else []
                    dossier_step = MissionStep(
                        step_id=f"step_{insert_at + 1}",
                        title="Synthesize final dossier",
                        step_type="final_dossier",
                        rationale="Mission needs a single consolidated deliverable before review.",
                        depends_on=depends_on,
                        outputs=["final_dossier"],
                    )
                    steps.insert(insert_at, dossier_step)
                    for idx, step in enumerate(steps, start=1):
                        step.step_id = f"step_{idx}"
                        if idx > 1 and not step.depends_on:
                            step.depends_on = [steps[idx - 2].step_id]
                # Execution is sequential. Normalize IDs/dependencies after
                # filtering unavailable capabilities or inserting required steps.
                for index, step in enumerate(steps, 1):
                    step.step_id = f"step_{index}"
                    step.depends_on = [f"step_{index - 1}"] if index > 1 else []
                return steps

        return self._fallback_plan(brief, request, capabilities)

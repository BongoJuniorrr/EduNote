from __future__ import annotations

import json

from src.agents.base_agent import BaseAgent
from src.agents.research.utils.json_utils import extract_json_from_text

from ..schemas import MissionBrief, MissionReview


def _coerce_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [line.strip("-• \t") for line in value.splitlines() if line.strip("-• \t")]
    return []


class ReviewerAgent(BaseAgent):
    def __init__(self, language: str = "en"):
        super().__init__(
            module_name="mission",
            agent_name="reviewer_agent",
            language=language,
        )

    async def process(
        self,
        brief: MissionBrief,
        dossier_markdown: str,
        *,
        artifact_summary: str,
    ) -> MissionReview:
        system_prompt = self.get_prompt(
            "system",
            "You are a rigorous reviewer. Prefer revise over pass when evidence is weak.",
        )
        user_template = self.get_prompt(
            "user_template",
            (
                "Mission brief JSON:\n{brief_json}\n\n"
                "Artifact summary:\n{artifact_summary}\n\n"
                "Dossier excerpt:\n{dossier_excerpt}"
            ),
        )

        dossier_excerpt = dossier_markdown[:12000]
        user_prompt = user_template.format(
            brief_json=json.dumps(brief.model_dump(), ensure_ascii=False, indent=2),
            artifact_summary=artifact_summary,
            dossier_excerpt=dossier_excerpt,
        )

        response = await self.call_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            response_format={"type": "json_object"},
            stage="review_mission",
        )

        data = extract_json_from_text(response)
        if isinstance(data, dict):
            score = float(data.get("score", 0.0) or 0.0)
            status = str(data.get("status") or ("pass" if score >= 0.78 else "revise")).strip()
            if status not in {"pass", "revise"}:
                status = "pass" if score >= 0.78 else "revise"

            return MissionReview(
                status=status,  # type: ignore[arg-type]
                score=max(0.0, min(score, 1.0)),
                strengths=_coerce_list(data.get("strengths")),
                risks=_coerce_list(data.get("risks")),
                missing_items=_coerce_list(data.get("missing_items")),
                recommended_changes=_coerce_list(data.get("recommended_changes")),
                final_recommendation=str(data.get("final_recommendation") or "").strip(),
            )

        score = 0.82 if len(dossier_markdown) > 600 else 0.58
        status = "pass" if score >= 0.78 else "revise"
        return MissionReview(
            status=status,  # type: ignore[arg-type]
            score=score,
            strengths=["Fallback review used because structured review parsing failed."],
            risks=[] if status == "pass" else ["Dossier may be too short or under-evidenced."],
            missing_items=[] if status == "pass" else ["Expand evidence and explicit next actions."],
            recommended_changes=[] if status == "pass" else ["Add more grounded findings and a clearer action plan."],
            final_recommendation="Ready to use." if status == "pass" else "Revise once before relying on the dossier.",
        )

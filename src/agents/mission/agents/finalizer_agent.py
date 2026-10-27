from __future__ import annotations

import json
from typing import Any

from src.agents.base_agent import BaseAgent

from ..schemas import MissionArtifact, MissionBrief, MissionReview


class FinalizerAgent(BaseAgent):
    def __init__(self, language: str = "en"):
        super().__init__(
            module_name="mission",
            agent_name="finalizer_agent",
            language=language,
        )

    def _format_artifacts(self, artifacts: list[MissionArtifact], *, max_chars: int = 4500) -> str:
        chunks: list[str] = []
        for artifact in artifacts:
            preview = artifact.preview[:max_chars].strip()
            chunks.append(
                f"### {artifact.title} [{artifact.kind}]\n"
                f"Summary: {artifact.summary}\n"
                f"Preview:\n{preview}\n"
            )
        return "\n\n".join(chunks)

    async def process(
        self,
        brief: MissionBrief,
        artifacts: list[MissionArtifact],
        *,
        preset: str,
        desired_outputs: list[str],
    ) -> str:
        system_prompt = self.get_prompt(
            "system",
            "You synthesize grounded multi-step artifacts into one polished markdown dossier.",
        )
        user_template = self.get_prompt(
            "user_template",
            (
                "Mission brief JSON:\n{brief_json}\n\n"
                "Preset: {preset}\nDesired outputs: {desired_outputs}\n\n"
                "Artifacts:\n{artifact_bundle}"
            ),
        )
        artifact_bundle = self._format_artifacts(artifacts)
        user_prompt = user_template.format(
            brief_json=json.dumps(brief.model_dump(), ensure_ascii=False, indent=2),
            preset=preset,
            desired_outputs=", ".join(desired_outputs),
            artifact_bundle=artifact_bundle or "No upstream artifacts available.",
        )

        try:
            return await self.call_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                stage="finalize_mission",
            )
        except Exception:
            lines = [
                f"# {brief.working_title}",
                "",
                "## Mission Objective",
                brief.objective,
                "",
                "## Deliverables",
            ]
            for item in brief.deliverables:
                lines.append(f"- {item}")
            lines.extend(["", "## Artifact Digest"])
            for artifact in artifacts:
                lines.extend(
                    [
                        f"### {artifact.title}",
                        artifact.summary or artifact.preview[:400],
                        "",
                    ]
                )
            lines.extend(["## Next Actions", "- Review the synthesized artifacts and close remaining gaps."])
            return "\n".join(lines).strip()

    async def revise(
        self,
        brief: MissionBrief,
        current_dossier: str,
        review: MissionReview,
    ) -> str:
        system_prompt = self.get_prompt(
            "revision_system",
            "You revise the dossier to address reviewer objections without bloating the output.",
        )
        revision_template = self.get_prompt(
            "revision_template",
            (
                "Mission brief JSON:\n{brief_json}\n\n"
                "Current dossier:\n{current_dossier}\n\n"
                "Review feedback JSON:\n{review_json}"
            ),
        )
        user_prompt = revision_template.format(
            brief_json=json.dumps(brief.model_dump(), ensure_ascii=False, indent=2),
            current_dossier=current_dossier[:16000],
            review_json=json.dumps(review.model_dump(), ensure_ascii=False, indent=2),
        )

        try:
            return await self.call_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                stage="revise_mission",
            )
        except Exception:
            recommendations = "\n".join(
                f"- {item}" for item in review.recommended_changes or ["Clarify missing evidence."]
            )
            return (
                f"{current_dossier}\n\n"
                "## Revision Notes\n"
                f"{recommendations}\n"
            ).strip()

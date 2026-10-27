from __future__ import annotations

from typing import Any

from src.agents.guide.agents.locate_agent import LocateAgent

from ..schemas import MissionBrief


class KnowledgeMapAdapter:
    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str | None,
        api_version: str | None,
        binding: str,
        language: str,
    ):
        self.locate_agent = LocateAgent(
            api_key=api_key or "",
            base_url=base_url or "",
            api_version=api_version,
            binding=binding,
            language=language,
        )

    def _fallback_points(self, brief: MissionBrief) -> list[dict[str, str]]:
        seeds = brief.key_questions or brief.success_criteria or [brief.objective]
        points: list[dict[str, str]] = []
        for index, item in enumerate(seeds[:4], start=1):
            points.append(
                {
                    "knowledge_title": f"Focus {index}",
                    "knowledge_summary": item,
                    "user_difficulty": "Clarify assumptions, evidence, and dependencies.",
                }
            )
        if not points:
            points.append(
                {
                    "knowledge_title": "Mission Core",
                    "knowledge_summary": brief.objective,
                    "user_difficulty": "Identify missing evidence and unresolved assumptions.",
                }
            )
        return points

    def _to_markdown(self, points: list[dict[str, Any]], notebook_names: list[str]) -> str:
        lines = [
            "# Knowledge Map",
            "",
            f"Source notebooks: {', '.join(notebook_names) if notebook_names else 'Mission goal only'}",
            "",
        ]
        for index, point in enumerate(points, start=1):
            lines.extend(
                [
                    f"## {index}. {point.get('knowledge_title', 'Untitled knowledge block')}",
                    point.get("knowledge_summary", "").strip() or "No summary available.",
                    "",
                    f"Potential friction: {point.get('user_difficulty', '').strip() or 'Not specified.'}",
                    "",
                ]
            )
        return "\n".join(lines).strip()

    async def run(
        self,
        *,
        brief: MissionBrief,
        records: list[dict[str, Any]],
        notebook_names: list[str],
    ) -> dict[str, Any]:
        points: list[dict[str, Any]] = []
        if records:
            result = await self.locate_agent.process(
                notebook_id="mission_workspace",
                notebook_name=", ".join(notebook_names) or "Mission Workspace",
                records=records,
            )
            if result.get("success"):
                points = result.get("knowledge_points", [])

        if not points:
            points = self._fallback_points(brief)

        return {
            "markdown": self._to_markdown(points, notebook_names),
            "data": {"knowledge_points": points},
            "summary": f"Mapped {len(points)} knowledge blocks from mission context.",
            "metadata": {"knowledge_point_count": len(points), "source_notebooks": notebook_names},
        }

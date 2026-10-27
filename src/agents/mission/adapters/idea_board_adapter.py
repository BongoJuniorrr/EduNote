from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from src.agents.ideagen.idea_generation_workflow import IdeaGenerationWorkflow
from src.agents.ideagen.material_organizer_agent import MaterialOrganizerAgent

from ..schemas import MissionBrief

ProgressCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]


class IdeaBoardAdapter:
    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str | None,
        api_version: str | None,
        language: str,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.api_version = api_version
        self.language = language

    async def run(
        self,
        *,
        brief: MissionBrief,
        records: list[dict[str, Any]],
        user_thoughts: str,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        knowledge_points: list[dict[str, Any]]

        if records:
            organizer = MaterialOrganizerAgent(
                api_key=self.api_key,
                base_url=self.base_url,
                api_version=self.api_version,
                language=self.language,
            )
            knowledge_points = await organizer.process(records, user_thoughts=user_thoughts)
        else:
            knowledge_points = [
                {
                    "knowledge_point": brief.working_title,
                    "description": brief.objective,
                }
            ]

        if not knowledge_points:
            knowledge_points = [
                {
                    "knowledge_point": brief.working_title,
                    "description": brief.objective,
                }
            ]

        workflow = IdeaGenerationWorkflow(
            api_key=self.api_key,
            base_url=self.base_url,
            api_version=self.api_version,
            language=self.language,
            progress_callback=progress_callback,
        )
        markdown = await workflow.process(knowledge_points)

        return {
            "markdown": markdown,
            "data": {"knowledge_points": knowledge_points},
            "summary": f"Generated idea board from {len(knowledge_points)} knowledge points.",
            "metadata": {
                "knowledge_point_count": len(knowledge_points),
                "record_count": len(records),
            },
        }

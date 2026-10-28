from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from typing import Any

from ..schemas import MissionBrief


class ResearchBriefAdapter:
    def __init__(
        self,
        *,
        config: dict[str, Any],
        api_key: str | None,
        base_url: str | None,
        api_version: str | None,
        language: str,
    ):
        self.base_config = config
        self.api_key = api_key
        self.base_url = base_url
        self.api_version = api_version
        self.language = language

    def _apply_depth(self, config: dict[str, Any], depth: str) -> None:
        config.setdefault("planning", {})
        config.setdefault("researching", {})
        config.setdefault("reporting", {})
        config["queue"] = {**config.get("queue", {}), "max_length": {"quick": 2, "medium": 8, "deep": 12}.get(depth, 8)}

        config["planning"].setdefault("rephrase", {})
        config["planning"]["rephrase"]["enabled"] = False

        if depth == "quick":
            config["planning"]["decompose"] = {"mode": "manual", "initial_subtopics": 2}
            config["researching"]["max_iterations"] = 2
            config["researching"]["iteration_mode"] = "fixed"
            config["reporting"]["min_section_length"] = 250
        elif depth == "deep":
            config["planning"]["decompose"] = {"mode": "manual", "initial_subtopics": 6}
            config["researching"]["max_iterations"] = 6
            config["researching"]["iteration_mode"] = "fixed"
            config["reporting"]["min_section_length"] = 700
        else:
            config["planning"]["decompose"] = {"mode": "manual", "initial_subtopics": 4}
            config["researching"]["max_iterations"] = 4
            config["researching"]["iteration_mode"] = "fixed"
            config["reporting"]["min_section_length"] = 450

    async def run(
        self,
        *,
        run_id: str,
        brief: MissionBrief,
        kb_name: str,
        depth: str,
        progress_callback,
    ) -> dict[str, Any]:
        config = copy.deepcopy(self.base_config)
        config.setdefault("system", {})
        config["system"]["language"] = self.language
        self._apply_depth(config, depth)

        def report_progress(event: dict[str, Any]) -> None:
            if not progress_callback:
                return
            result = progress_callback("research_pipeline", event)
            if result is not None and hasattr(result, "__await__"):
                asyncio.create_task(result)

        from src.agents.research.research_pipeline import ResearchPipeline

        pipeline = ResearchPipeline(
            config=config,
            api_key=self.api_key or "",
            base_url=self.base_url or "",
            api_version=self.api_version,
            research_id=f"{run_id}_research",
            kb_name=kb_name,
            progress_callback=report_progress,
        )
        result = await pipeline.run(topic=brief.objective)
        report_path = Path(result["final_report_path"])
        report_markdown = report_path.read_text(encoding="utf-8")

        return {
            "markdown": report_markdown,
            "summary": "Completed evidence-grounded research brief.",
            "metadata": result.get("metadata", {}),
            "data": {
                "research_id": result.get("research_id"),
                "final_report_path": result.get("final_report_path"),
                "metadata": result.get("metadata", {}),
            },
        }

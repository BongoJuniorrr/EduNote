from __future__ import annotations

from collections.abc import Awaitable, Callable
import json
from pathlib import Path
from typing import Any

from src.services.config import load_config_with_main
from src.services.llm import get_llm_config
from src.services.settings.interface_settings import get_ui_language

from src.api.utils.notebook_manager import NotebookManager

from .adapters import IdeaBoardAdapter, KnowledgeMapAdapter, ResearchBriefAdapter
from .agents import ClarifierAgent, FinalizerAgent, PlannerAgent, ReviewerAgent
from .schemas import MissionArtifact, MissionPlanRequest, MissionReview, MissionRun, MissionTemplate
from .state_store import MissionStateStore

EventCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]

PRESET_DEFAULTS: dict[str, dict[str, Any]] = {
    "learn_topic": {
        "label": "Learn Topic Mission",
        "description": "Turn notebook evidence and KB context into a study-ready learning dossier.",
        "default_outputs": ["knowledge_map", "research_brief", "study_plan", "next_actions"],
        "recommended_when": [
            "Need a structured study path from notebooks and KB evidence.",
            "Want grounded notes before entering Guided Learning or Solver.",
        ],
        "default_success_criteria": [
            "Explains the topic structure clearly.",
            "Surfaces likely learning bottlenecks.",
            "Ends with a concrete next-step plan.",
        ],
        "default_constraints": [
            "Prefer grounded content over stylistic expansion.",
        ],
    },
    "capstone_prep": {
        "label": "Capstone Prep Mission",
        "description": "Explore options, gather evidence, and shape a defensible project direction.",
        "default_outputs": [
            "idea_board",
            "research_brief",
            "scope_options",
            "risk_register",
            "execution_roadmap",
        ],
        "recommended_when": [
            "Need multiple project directions before committing.",
            "Need a short list of risks, scope tradeoffs, and roadmap decisions.",
        ],
        "default_success_criteria": [
            "Produces multiple viable directions.",
            "Identifies scope and evidence gaps.",
            "Ends with an executable roadmap.",
        ],
        "default_constraints": [
            "Avoid generic startup-style ideation; keep outputs grounded in available materials.",
        ],
    },
    "defense_prep": {
        "label": "Defense Prep Mission",
        "description": "Stress-test current material and produce a defense-oriented preparation brief.",
        "default_outputs": [
            "knowledge_map",
            "research_brief",
            "weakness_audit",
            "qa_bank",
            "defense_strategy",
        ],
        "recommended_when": [
            "Need likely examiner questions and weak-point analysis.",
            "Need a concise defense prep pack from current notes and KB evidence.",
        ],
        "default_success_criteria": [
            "Identifies weaknesses and unsupported claims.",
            "Produces likely challenge questions.",
            "Ends with a defense strategy and next fixes.",
        ],
        "default_constraints": [
            "Focus on critique readiness, not marketing tone.",
        ],
    },
    "custom": {
        "label": "Custom Mission",
        "description": "Flexible mission orchestration from a free-form goal.",
        "default_outputs": ["research_brief", "final_dossier", "next_actions"],
        "recommended_when": [
            "Need a custom agentic workflow without forcing a preset.",
        ],
        "default_success_criteria": [
            "Delivers a usable final dossier aligned to the goal.",
        ],
        "default_constraints": [
            "Keep the mission plan short and justified.",
        ],
    },
}


class MissionOrchestrator:
    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        store: MissionStateStore | None = None,
        notebook_manager: NotebookManager | None = None,
    ):
        self.config = config or load_config_with_main("main.yaml")
        self.store = store or MissionStateStore()
        self.notebook_manager = notebook_manager or NotebookManager()

        try:
            llm_config = get_llm_config()
            self.api_key = llm_config.api_key
            self.base_url = llm_config.base_url
            self.api_version = getattr(llm_config, "api_version", None)
            self.binding = getattr(llm_config, "binding", "openai")
        except Exception:
            self.api_key = None
            self.base_url = None
            self.api_version = None
            self.binding = "openai"

        self.language = get_ui_language(default=self.config.get("system", {}).get("language", "en"))

        self.clarifier = ClarifierAgent(language=self.language)
        self.planner = PlannerAgent(language=self.language)
        self.finalizer = FinalizerAgent(language=self.language)
        self.reviewer = ReviewerAgent(language=self.language)
        self.knowledge_map_adapter = KnowledgeMapAdapter(
            api_key=self.api_key,
            base_url=self.base_url,
            api_version=self.api_version,
            binding=self.binding,
            language=self.language,
        )
        self.idea_board_adapter = IdeaBoardAdapter(
            api_key=self.api_key,
            base_url=self.base_url,
            api_version=self.api_version,
            language=self.language,
        )
        self.research_brief_adapter = ResearchBriefAdapter(
            config=self.config,
            api_key=self.api_key,
            base_url=self.base_url,
            api_version=self.api_version,
            language=self.language,
        )

    def get_templates(self) -> list[MissionTemplate]:
        templates: list[MissionTemplate] = []
        for preset_id, preset in PRESET_DEFAULTS.items():
            templates.append(
                MissionTemplate(
                    id=preset_id,  # type: ignore[arg-type]
                    label=preset["label"],
                    description=preset["description"],
                    default_outputs=list(preset.get("default_outputs", [])),
                    recommended_when=list(preset.get("recommended_when", [])),
                )
            )
        return templates

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.store.list_runs(limit=limit)

    def get_run(self, run_id: str) -> MissionRun | None:
        return self.store.get_run(run_id)

    def approve_run(self, run_id: str) -> MissionRun:
        run = self.store.get_run(run_id)
        if not run:
            raise FileNotFoundError(f"Mission run not found: {run_id}")
        if run.status == "approved":
            return run
        return self.store.set_status(run_id, "approved", error=None)

    def _preset_defaults(self, preset: str) -> dict[str, Any]:
        return PRESET_DEFAULTS.get(preset, PRESET_DEFAULTS["custom"])

    def _load_notebook_summaries(self, notebook_ids: list[str]) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for notebook_id in notebook_ids:
            notebook = self.notebook_manager.get_notebook(notebook_id)
            if not notebook:
                continue
            summaries.append(
                {
                    "id": notebook["id"],
                    "name": notebook.get("name", notebook_id),
                    "record_count": len(notebook.get("records", [])),
                }
            )
        return summaries

    def _load_records(self, notebook_ids: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        records: list[dict[str, Any]] = []
        notebook_names: list[str] = []
        for notebook_id in notebook_ids:
            notebook = self.notebook_manager.get_notebook(notebook_id)
            if not notebook:
                continue
            notebook_names.append(notebook.get("name", notebook_id))
            records.extend(notebook.get("records", []))
        return records, notebook_names

    async def plan_mission(self, request: MissionPlanRequest) -> MissionRun:
        preset_defaults = self._preset_defaults(request.preset)
        desired_outputs = request.desired_outputs or list(preset_defaults.get("default_outputs", []))
        normalized_request = request.model_copy(
            update={
                "goal": request.goal.strip(),
                "desired_outputs": desired_outputs,
            }
        )
        notebook_context = self._load_notebook_summaries(normalized_request.notebook_ids)

        brief = await self.clarifier.process(
            normalized_request,
            notebook_context=notebook_context,
            preset_defaults=preset_defaults,
        )
        if not brief.deliverables:
            brief.deliverables = desired_outputs

        plan = await self.planner.process(
            brief,
            normalized_request,
            capabilities={
                "has_notebooks": bool(notebook_context),
                "has_primary_kb": bool(normalized_request.primary_kb_name),
            },
        )
        status = "approved" if normalized_request.auto_approve_plan else "awaiting_approval"

        run = self.store.create_run(
            normalized_request,
            brief,
            plan,
            title=brief.working_title or preset_defaults["label"],
            status=status,
            context_summary={
                "selected_notebooks": notebook_context,
                "selected_primary_kb": normalized_request.primary_kb_name,
            },
        )
        self.store.append_event(
            run.run_id,
            "plan_ready",
            {
                "status": run.status,
                "step_count": len(run.plan),
            },
        )
        return self.store.get_run(run.run_id) or run

    async def _emit(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        callback: EventCallback | None,
    ) -> None:
        event = self.store.append_event(run_id, event_type, payload)
        if callback:
            result = callback(event_type, event)
            if result is not None and hasattr(result, "__await__"):
                await result

    def _latest_artifact(self, run: MissionRun, kind: str) -> MissionArtifact | None:
        for artifact in reversed(run.artifacts):
            if artifact.kind == kind:
                return artifact
        return None

    def _read_artifact_text(self, artifact: MissionArtifact | None) -> str:
        if not artifact or not artifact.file_path:
            return ""
        try:
            return Path(artifact.file_path).read_text(encoding="utf-8")
        except Exception:
            return artifact.preview or ""

    def _artifact_summary_for_review(self, run: MissionRun) -> str:
        lines: list[str] = []
        for artifact in run.artifacts:
            lines.append(f"- {artifact.title} [{artifact.kind}]: {artifact.summary}")
        return "\n".join(lines)

    async def _execute_step(
        self,
        run_id: str,
        run: MissionRun,
        step,
        records: list[dict[str, Any]],
        notebook_names: list[str],
        callback: EventCallback | None,
    ) -> dict[str, Any]:
        async def step_progress(adapter_event: str, payload: dict[str, Any]) -> None:
            await self._emit(
                run_id,
                "step_progress",
                {
                    "step_id": step.step_id,
                    "step_type": step.step_type,
                    "adapter_event": adapter_event,
                    "payload": payload,
                },
                callback,
            )

        if step.step_type == "knowledge_map":
            return await self.knowledge_map_adapter.run(
                brief=run.brief,
                records=records,
                notebook_names=notebook_names,
            )

        if step.step_type == "idea_board":
            return await self.idea_board_adapter.run(
                brief=run.brief,
                records=records,
                user_thoughts=run.goal,
                progress_callback=step_progress,
            )

        if step.step_type == "research_brief":
            if not run.primary_kb_name:
                raise ValueError("Research brief step requires a primary knowledge base.")
            return await self.research_brief_adapter.run(
                run_id=run_id,
                brief=run.brief,
                kb_name=run.primary_kb_name,
                depth=run.research_depth,
                progress_callback=lambda event: step_progress("research_pipeline", event),
            )

        if step.step_type == "final_dossier":
            dossier = await self.finalizer.process(
                run.brief,
                [artifact for artifact in run.artifacts if artifact.kind not in {"mission_plan", "mission_brief"}],
                preset=run.preset,
                desired_outputs=run.desired_outputs,
            )
            return {
                "markdown": dossier,
                "summary": "Synthesized final mission dossier.",
                "metadata": {"desired_outputs": run.desired_outputs, "preset": run.preset},
            }

        if step.step_type == "review":
            dossier_artifact = self._latest_artifact(run, "final_dossier")
            dossier_markdown = self._read_artifact_text(dossier_artifact)
            review = await self.reviewer.process(
                run.brief,
                dossier_markdown,
                artifact_summary=self._artifact_summary_for_review(run),
            )
            revision_count = 0
            revised_artifacts: list[dict[str, Any]] = []
            max_loops = int(self.config.get("mission", {}).get("execution", {}).get("review_loops", 1))

            while review.status == "revise" and revision_count < max_loops:
                revision_count += 1
                await self._emit(
                    run_id,
                    "review_feedback",
                    {
                        "step_id": step.step_id,
                        "status": review.status,
                        "score": review.score,
                        "recommended_changes": review.recommended_changes,
                        "revision_count": revision_count,
                    },
                    callback,
                )
                revised = await self.finalizer.revise(run.brief, dossier_markdown, review)
                revised_artifacts.append(
                    {
                        "kind": "final_dossier",
                        "title": f"{run.title} (Revised)",
                        "content": revised,
                        "file_name": f"final_dossier_revised_{revision_count}.md",
                        "summary": "Revised mission dossier after review feedback.",
                    }
                )
                dossier_markdown = revised
                review = await self.reviewer.process(
                    run.brief,
                    dossier_markdown,
                    artifact_summary=self._artifact_summary_for_review(run),
                )

            review_payload = review.model_dump()
            if revised_artifacts:
                review_payload["revised_artifacts"] = revised_artifacts
            return {
                "data": review_payload,
                "summary": f"Review completed with status `{review.status}` and score {review.score:.2f}.",
                "metadata": {"review_status": review.status, "review_score": review.score},
                "review": review,
                "revised_artifacts": revised_artifacts,
            }

        raise ValueError(f"Unsupported mission step type: {step.step_type}")

    async def execute_run(self, run_id: str, callback: EventCallback | None = None) -> MissionRun:
        run = self.store.get_run(run_id)
        if not run:
            raise FileNotFoundError(f"Mission run not found: {run_id}")
        if run.status == "awaiting_approval":
            raise PermissionError("Mission plan must be approved before execution.")

        run = self.store.set_status(run_id, "running", error=None)
        await self._emit(
            run_id,
            "run_started",
            {
                "run_id": run.run_id,
                "title": run.title,
                "step_count": len(run.plan),
            },
            callback,
        )

        records, notebook_names = self._load_records(run.notebook_ids)

        for step in run.plan:
            if step.status == "completed":
                continue

            run = self.store.update_step(run_id, step.step_id, status="running", summary="")
            await self._emit(
                run_id,
                "step_started",
                {
                    "run_id": run_id,
                    "step_id": step.step_id,
                    "step_type": step.step_type,
                    "title": step.title,
                },
                callback,
            )

            current_run = self.store.get_run(run_id) or run
            current_step = next(
                mission_step for mission_step in current_run.plan if mission_step.step_id == step.step_id
            )

            try:
                result = await self._execute_step(
                    run_id,
                    current_run,
                    current_step,
                    records,
                    notebook_names,
                    callback,
                )
            except Exception as exc:
                error_message = str(exc)
                run = self.store.update_step(
                    run_id,
                    step.step_id,
                    status="failed",
                    summary=error_message,
                )
                await self._emit(
                    run_id,
                    "step_failed",
                    {
                        "step_id": step.step_id,
                        "step_type": step.step_type,
                        "message": error_message,
                    },
                    callback,
                )

                if step.step_type in {"final_dossier", "review"}:
                    run = self.store.set_status(run_id, "failed", error=error_message)
                    await self._emit(
                        run_id,
                        "error",
                        {
                            "run_id": run_id,
                            "message": error_message,
                            "step_id": step.step_id,
                        },
                        callback,
                    )
                    return run
                continue

            artifact_ids: list[str] = []

            if isinstance(result.get("markdown"), str) and result["markdown"].strip():
                artifact = self.store.save_text_artifact(
                    run_id,
                    kind=current_step.step_type,
                    title=current_step.title,
                    content=result["markdown"],
                    source_step_id=current_step.step_id,
                    file_name=f"{current_step.step_type}.md",
                    summary=result.get("summary", ""),
                    metadata=result.get("metadata", {}),
                )
                artifact_ids.append(artifact.artifact_id)
                await self._emit(
                    run_id,
                    "artifact_created",
                    {
                        "step_id": current_step.step_id,
                        "artifact": artifact.model_dump(),
                    },
                    callback,
                )

            if result.get("data") is not None:
                artifact = self.store.save_json_artifact(
                    run_id,
                    kind=f"{current_step.step_type}_data",
                    title=f"{current_step.title} Data",
                    payload=result["data"],
                    source_step_id=current_step.step_id,
                    file_name=f"{current_step.step_type}_data.json",
                    summary=result.get("summary", ""),
                    metadata=result.get("metadata", {}),
                )
                artifact_ids.append(artifact.artifact_id)

            if current_step.step_type == "review" and result.get("review"):
                review: MissionReview = result["review"]
                run = self.store.set_review(run_id, review)
                for revised in result.get("revised_artifacts", []):
                    artifact = self.store.save_text_artifact(
                        run_id,
                        kind=revised["kind"],
                        title=revised["title"],
                        content=revised["content"],
                        source_step_id=current_step.step_id,
                        file_name=revised["file_name"],
                        summary=revised["summary"],
                    )
                    artifact_ids.append(artifact.artifact_id)
                await self._emit(
                    run_id,
                    "review_completed",
                    {
                        "step_id": current_step.step_id,
                        "review": review.model_dump(),
                    },
                    callback,
                )

            run = self.store.update_step(
                run_id,
                current_step.step_id,
                status="completed",
                summary=result.get("summary", ""),
                artifact_ids=artifact_ids,
                metadata=result.get("metadata", {}),
            )
            await self._emit(
                run_id,
                "step_completed",
                {
                    "step_id": current_step.step_id,
                    "step_type": current_step.step_type,
                    "summary": result.get("summary", ""),
                    "artifact_ids": artifact_ids,
                },
                callback,
            )

        run = self.store.get_run(run_id) or run
        failed_steps = [step for step in run.plan if step.status == "failed"]
        if failed_steps:
            message = "Mission has failed steps: " + ", ".join(step.title for step in failed_steps)
            run = self.store.set_status(run_id, "failed", error=message)
            await self._emit(run_id, "error", {"run_id": run_id, "message": message}, callback)
            return run
        result_summary = (
            run.review.final_recommendation
            if run.review and run.review.final_recommendation
            else f"Mission completed with {len(run.artifacts)} artifacts."
        )
        run = self.store.set_status(run_id, "completed", result_summary=result_summary, error=None)
        await self._emit(
            run_id,
            "run_completed",
            {
                "run_id": run.run_id,
                "artifact_count": len(run.artifacts),
                "result_summary": run.result_summary,
                "review": run.review.model_dump() if run.review else None,
            },
            callback,
        )
        return run

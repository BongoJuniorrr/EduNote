from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import threading
from typing import Any

from .schemas import MissionArtifact, MissionBrief, MissionPlanRequest, MissionReview, MissionRun
from .schemas import MissionStep


class MissionStateStore:
    """Persist Mission runs under data/user/mission without touching existing modules."""

    def __init__(self, base_dir: Path | None = None):
        if base_dir is None:
            env_dir = (os.getenv("MISSION_OUTPUT_DIR") or "").strip()
            if env_dir:
                base_dir = Path(env_dir)
            else:
                project_root = Path(__file__).resolve().parents[3]
                base_dir = project_root / "data" / "user" / "mission"

        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def generate_run_id() -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"mission_{timestamp}_{secrets.token_hex(3)}"

    @staticmethod
    def artifact_base_url(run_id: str) -> str:
        return f"/api/outputs/mission/{run_id}/artifacts"

    def _run_dir(self, run_id: str) -> Path:
        return self.base_dir / run_id

    def _run_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "run.json"

    def _artifact_dir(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "artifacts"

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _save_run(self, run: MissionRun) -> MissionRun:
        run.updated_at = self._now_iso()
        self._run_dir(run.run_id).mkdir(parents=True, exist_ok=True)
        self._artifact_dir(run.run_id).mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._write_json(self._run_path(run.run_id), run.model_dump())
        return run

    def get_run(self, run_id: str) -> MissionRun | None:
        payload = self._read_json(self._run_path(run_id), default=None)
        if not isinstance(payload, dict):
            return None
        try:
            return MissionRun.model_validate(payload)
        except Exception:
            return None

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        for run_dir in self.base_dir.iterdir():
            if not run_dir.is_dir():
                continue
            run = self.get_run(run_dir.name)
            if not run:
                continue
            runs.append(
                {
                    "run_id": run.run_id,
                    "title": run.title,
                    "status": run.status,
                    "preset": run.preset,
                    "goal": run.goal,
                    "created_at": run.created_at,
                    "updated_at": run.updated_at,
                    "artifact_count": len(run.artifacts),
                    "step_count": len(run.plan),
                    "review_status": run.review.status if run.review else None,
                }
            )

        runs.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return runs[:limit]

    def create_run(
        self,
        request: MissionPlanRequest,
        brief: MissionBrief,
        plan: list[MissionStep],
        *,
        title: str,
        status: str,
        context_summary: dict[str, Any] | None = None,
    ) -> MissionRun:
        now = self._now_iso()
        run = MissionRun(
            run_id=self.generate_run_id(),
            title=title,
            status=status,
            preset=request.preset,
            goal=request.goal,
            primary_kb_name=request.primary_kb_name,
            notebook_ids=request.notebook_ids,
            desired_outputs=request.desired_outputs,
            constraints=request.constraints,
            success_criteria=request.success_criteria,
            research_depth=request.research_depth,
            brief=brief,
            plan=plan,
            context_summary=context_summary or {},
            created_at=now,
            updated_at=now,
        )
        if status == "approved":
            run.approved_at = now
        self._save_run(run)
        self.save_json_artifact(
            run.run_id,
            kind="mission_brief",
            title="Mission Brief",
            payload=brief.model_dump(),
            source_step_id=None,
            file_name="mission_brief.json",
            summary="Structured mission brief used for planning.",
        )
        self.save_json_artifact(
            run.run_id,
            kind="mission_plan",
            title="Mission Plan",
            payload={"steps": [step.model_dump() for step in plan]},
            source_step_id=None,
            file_name="mission_plan.json",
            summary="Executable mission plan awaiting approval or execution.",
        )
        return self.get_run(run.run_id) or run

    def set_status(self, run_id: str, status: str, **updates: Any) -> MissionRun:
        run = self.get_run(run_id)
        if not run:
            raise FileNotFoundError(f"Mission run not found: {run_id}")
        run.status = status  # type: ignore[assignment]
        now = self._now_iso()
        if status == "approved":
            run.approved_at = now
        if status in {"completed", "failed"}:
            run.completed_at = now
        for key, value in updates.items():
            if hasattr(run, key):
                setattr(run, key, value)
        return self._save_run(run)

    def update_step(self, run_id: str, step_id: str, **updates: Any) -> MissionRun:
        run = self.get_run(run_id)
        if not run:
            raise FileNotFoundError(f"Mission run not found: {run_id}")

        changed = False
        for step in run.plan:
            if step.step_id != step_id:
                continue
            for key, value in updates.items():
                if hasattr(step, key):
                    setattr(step, key, value)
                    changed = True
            break

        if not changed:
            raise ValueError(f"Mission step not found: {step_id}")

        return self._save_run(run)

    def set_review(self, run_id: str, review: MissionReview) -> MissionRun:
        run = self.get_run(run_id)
        if not run:
            raise FileNotFoundError(f"Mission run not found: {run_id}")
        run.review = review
        return self._save_run(run)

    def append_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        run = self.get_run(run_id)
        if not run:
            raise FileNotFoundError(f"Mission run not found: {run_id}")

        event = {
            "type": event_type,
            "timestamp": self._now_iso(),
            **payload,
        }
        run.events = (run.events or [])[-199:] + [event]
        self._save_run(run)
        return event

    def _unique_filename(self, run_id: str, file_name: str) -> str:
        artifact_dir = self._artifact_dir(run_id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        target = artifact_dir / file_name
        if not target.exists():
            return file_name

        stem = target.stem
        suffix = target.suffix
        counter = 1
        while True:
            candidate = f"{stem}_{counter}{suffix}"
            if not (artifact_dir / candidate).exists():
                return candidate
            counter += 1

    def _safe_filename(self, base_name: str, extension: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (base_name or "").strip()).strip("._")
        if not cleaned:
            cleaned = f"artifact_{secrets.token_hex(3)}"
        ext = extension if extension.startswith(".") else f".{extension}"
        return f"{cleaned}{ext}"

    def _append_artifact(self, run: MissionRun, artifact: MissionArtifact) -> MissionRun:
        run.artifacts.append(artifact)
        return self._save_run(run)

    def save_text_artifact(
        self,
        run_id: str,
        *,
        kind: str,
        title: str,
        content: str,
        source_step_id: str | None,
        file_name: str | None = None,
        content_type: str = "text/markdown",
        summary: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> MissionArtifact:
        run = self.get_run(run_id)
        if not run:
            raise FileNotFoundError(f"Mission run not found: {run_id}")

        extension = ".md" if "markdown" in content_type else ".txt"
        safe_name = self._safe_filename(kind, extension) if not file_name else file_name
        safe_name = self._unique_filename(run_id, safe_name)
        target = self._artifact_dir(run_id) / safe_name
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)

        artifact = MissionArtifact(
            artifact_id=f"artifact_{secrets.token_hex(5)}",
            kind=kind,
            title=title,
            summary=summary or (content[:220].strip() if content else ""),
            source_step_id=source_step_id,
            file_name=safe_name,
            file_path=str(target),
            url=f"{self.artifact_base_url(run_id)}/{safe_name}",
            content_type=content_type,
            created_at=self._now_iso(),
            preview=content[:1200],
            metadata=metadata or {},
        )
        self._append_artifact(run, artifact)
        return artifact

    def save_json_artifact(
        self,
        run_id: str,
        *,
        kind: str,
        title: str,
        payload: Any,
        source_step_id: str | None,
        file_name: str | None = None,
        summary: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> MissionArtifact:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        safe_name = file_name or self._safe_filename(kind, ".json")
        return self.save_text_artifact(
            run_id,
            kind=kind,
            title=title,
            content=text,
            source_step_id=source_step_id,
            file_name=safe_name,
            content_type="application/json",
            summary=summary,
            metadata=metadata,
        )

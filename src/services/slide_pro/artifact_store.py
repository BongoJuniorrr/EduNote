# -*- coding: utf-8 -*-
"""Artifact persistence for Slide Generator Pro runs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
from typing import Any

from src.utils.document_validator import DocumentValidator


ALLOWED_ARTIFACT_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".pdf",
    ".pptx",
    ".json",
    ".zip",
}


class SlideProArtifactStore:
    """Persist run metadata and artifacts under data/user/slide-pro."""

    def __init__(self, base_dir: Path | None = None):
        if base_dir is None:
            env_dir = (os.getenv("SLIDE_PRO_OUTPUT_DIR") or "").strip()
            if env_dir:
                base_dir = Path(env_dir)
            else:
                project_root = Path(__file__).resolve().parents[3]
                base_dir = project_root / "data" / "user" / "slide-pro"
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def generate_run_id() -> str:
        now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        suffix = secrets.token_hex(3)
        return f"sp_{now}_{suffix}"

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def artifact_base_url(run_id: str) -> str:
        return f"/api/outputs/slide-pro/{run_id}/artifacts"

    def _run_dir(self, run_id: str) -> Path:
        return self.base_dir / run_id

    def _meta_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "run.json"

    def _result_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "result.json"

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

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def create_run(self, title: str = "", run_id: str | None = None) -> dict[str, Any]:
        resolved_run_id = run_id or self.generate_run_id()
        run_dir = self._run_dir(resolved_run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        self._artifact_dir(resolved_run_id).mkdir(parents=True, exist_ok=True)
        now = self._now_iso()
        metadata = {
            "run_id": resolved_run_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "artifacts": [],
        }
        self._write_json(self._meta_path(resolved_run_id), metadata)
        return metadata

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        payload = self._read_json(self._meta_path(run_id), default=None)
        if not isinstance(payload, dict):
            return None
        return payload

    def ensure_run(self, run_id: str) -> dict[str, Any]:
        run_meta = self.get_run(run_id)
        if not run_meta:
            raise FileNotFoundError(f"Run not found: {run_id}")
        return run_meta

    def save_result(self, run_id: str, result: dict[str, Any]) -> None:
        payload = {"saved_at": self._now_iso(), "result": result}
        self._write_json(self._result_path(run_id), payload)
        meta = self.get_run(run_id)
        if isinstance(meta, dict):
            meta["updated_at"] = self._now_iso()
            self._write_json(self._meta_path(run_id), meta)

    @staticmethod
    def _build_artifact_record(
        run_id: str,
        filename: str,
        size_bytes: int,
        content_type: str,
    ) -> dict[str, Any]:
        return {
            "file_name": filename,
            "size_bytes": size_bytes,
            "content_type": content_type,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "url": f"{SlideProArtifactStore.artifact_base_url(run_id)}/{filename}",
        }

    def save_artifacts(
        self,
        run_id: str,
        files: list[tuple[str, bytes, str]],
        manifest: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        run = self.ensure_run(run_id)
        artifact_dir = self._artifact_dir(run_id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        saved: list[dict[str, Any]] = []

        for original_name, raw, content_type in files:
            safe_name = DocumentValidator.validate_upload_safety(
                original_name,
                len(raw),
                allowed_extensions=ALLOWED_ARTIFACT_EXTENSIONS,
            )
            final_name = safe_name
            target = artifact_dir / final_name
            suffix = 1
            while target.exists():
                stem = target.stem
                ext = target.suffix
                final_name = f"{stem}_{suffix}{ext}"
                target = artifact_dir / final_name
                suffix += 1

            with open(target, "wb") as f:
                f.write(raw)
            saved.append(
                self._build_artifact_record(
                    run_id=run_id,
                    filename=final_name,
                    size_bytes=len(raw),
                    content_type=content_type or "application/octet-stream",
                )
            )

        if manifest is not None:
            manifest_path = artifact_dir / "manifest.json"
            self._write_json(manifest_path, manifest)
            with open(manifest_path, "rb") as f:
                manifest_raw = f.read()
            saved.append(
                self._build_artifact_record(
                    run_id=run_id,
                    filename="manifest.json",
                    size_bytes=len(manifest_raw),
                    content_type="application/json",
                )
            )

        artifacts = run.get("artifacts", [])
        if not isinstance(artifacts, list):
            artifacts = []
        run["artifacts"] = artifacts + saved
        run["updated_at"] = self._now_iso()
        self._write_json(self._meta_path(run_id), run)
        return saved


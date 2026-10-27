# -*- coding: utf-8 -*-
"""Slide Generator Pro API router."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from src.knowledge.manager import KnowledgeBaseManager
from src.services.config import get_kb_config_service
from src.services.search import get_current_config
from src.services.slide_pro import (
    ALLOWED_ARTIFACT_EXTENSIONS,
    SlideProArtifactStore,
    slide_pro_engine,
)


router = APIRouter()


class SlideProGenerateRequest(BaseModel):
    title: str = ""
    language: Literal["vi", "en"] = "vi"
    source_text: str = ""
    source_records: list[dict[str, Any]] = Field(default_factory=list)
    instructions: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)


class SlideProCriticRequest(BaseModel):
    deck_json: dict[str, Any]


class SlideProCriticResponse(BaseModel):
    deck_json: dict[str, Any]
    issues: list[dict[str, Any]]
    suggested_patches: list[dict[str, Any]]


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "slide_pro"}


@router.get("/templates")
async def get_templates():
    return {"templates": slide_pro_engine.templates()}


@router.get("/research-options")
async def get_research_options():
    try:
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        kb_manager = KnowledgeBaseManager(base_dir=str(project_root / "data" / "knowledge_bases"))
        kb_names = kb_manager.list_knowledge_bases()
        default_kb = kb_manager.get_default()
        kb_config_service = get_kb_config_service()

        knowledge_bases: list[dict[str, Any]] = []
        for kb_name in kb_names:
            kb_cfg = kb_config_service.get_kb_config(kb_name)
            knowledge_bases.append(
                {
                    "name": kb_name,
                    "is_default": kb_name == default_kb,
                    "rag_provider": kb_cfg.get("rag_provider", "unknown"),
                    "search_mode": kb_cfg.get("search_mode", "hybrid"),
                    "retrieval_profile": kb_cfg.get("retrieval_profile", "standard"),
                }
            )

        default_kb_names: list[str] = []
        if default_kb and default_kb in kb_names:
            default_kb_names = [default_kb]
        elif kb_names:
            default_kb_names = [kb_names[0]]

        search_cfg = get_current_config()
        search_providers = search_cfg.get("providers", [])
        search_default = search_cfg.get("provider", "perplexity")

        return {
            "knowledge_bases": knowledge_bases,
            "default_kb_names": default_kb_names,
            "search": {
                "default_provider": search_default,
                "providers": search_providers,
                "default_effort": "medium",
                "efforts": [
                    {
                        "id": "fast",
                        "label": "Fast",
                        "description": "Lower latency, lightweight retrieval depth.",
                    },
                    {
                        "id": "medium",
                        "label": "Medium",
                        "description": "Balanced depth and latency (recommended).",
                    },
                    {
                        "id": "high",
                        "label": "High",
                        "description": "Higher depth and broader retrieval for stronger grounding.",
                    },
                ],
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate")
async def generate_deck(request: SlideProGenerateRequest):
    try:
        result = await slide_pro_engine.generate(
            title=request.title,
            language=request.language,
            source_text=request.source_text,
            source_records=request.source_records,
            instructions=request.instructions,
            settings=request.settings,
        )
        artifact_store = SlideProArtifactStore()
        run_meta = artifact_store.create_run(title=request.title)
        run_id = run_meta["run_id"]
        result["deck_json"]["deck_id"] = run_id
        artifact_store.save_result(run_id, result)

        auto_files: list[tuple[str, bytes, str]] = []
        deck_payload = {
            "run_id": run_id,
            "deck_json": result.get("deck_json", {}),
            "layout_plan": result.get("layout_plan", []),
            "instruction_cycles": result.get("instruction_cycles", []),
            "quality_checks": result.get("quality_checks", []),
            "research_trace": result.get("research_trace", {}),
            "evidence_catalog": result.get("evidence_catalog", []),
            "slide_evidence": result.get("slide_evidence", {}),
            "instruction_report": result.get("instruction_report", {}),
            "warnings": result.get("warnings", []),
        }
        auto_files.append(
            (
                f"{run_id}.slidepro.json",
                json.dumps(deck_payload, ensure_ascii=False, indent=2).encode("utf-8"),
                "application/json",
            )
        )
        research_trace = result.get("research_trace") or {}
        if research_trace:
            auto_files.append(
                (
                    "research_trace.json",
                    json.dumps(research_trace, ensure_ascii=False, indent=2).encode("utf-8"),
                    "application/json",
                )
            )
        artifact_store.save_artifacts(
            run_id=run_id,
            files=auto_files,
            manifest={
                "kind": "slidepro_generated",
                "mode": "deck_json",
                "run_id": run_id,
            },
        )
        run_meta = artifact_store.get_run(run_id) or run_meta

        return {
            "success": True,
            "run_id": run_id,
            "artifact_base_url": SlideProArtifactStore.artifact_base_url(run_id),
            "artifacts": run_meta.get("artifacts", []),
            **result,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/critic", response_model=SlideProCriticResponse)
async def run_critic(request: SlideProCriticRequest):
    try:
        payload = slide_pro_engine.run_critic(request.deck_json)
        return SlideProCriticResponse(**payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/runs/{run_id}/artifacts")
async def upload_artifacts(
    run_id: str,
    manifest: str | None = Form(default=None),
    files: list[UploadFile] | None = File(default=None),
):
    try:
        artifact_store = SlideProArtifactStore()
        artifact_store.ensure_run(run_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    parsed_manifest = None
    if manifest:
        try:
            parsed_manifest = json.loads(manifest)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid manifest JSON: {e}") from e

    file_payloads: list[tuple[str, bytes, str]] = []
    for upload in files or []:
        raw = await upload.read()
        file_payloads.append(
            (
                upload.filename or "artifact.bin",
                raw,
                upload.content_type or "application/octet-stream",
            )
        )

    try:
        saved = artifact_store.save_artifacts(
            run_id=run_id,
            files=file_payloads,
            manifest=parsed_manifest,
        )
    except ValueError as e:
        allowed = ", ".join(sorted(ALLOWED_ARTIFACT_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"Invalid artifact payload: {e}. Allowed extensions: {allowed}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "success": True,
        "run_id": run_id,
        "artifact_base_url": SlideProArtifactStore.artifact_base_url(run_id),
        "artifacts": saved,
    }


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    artifact_store = SlideProArtifactStore()
    run = artifact_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return {
        "success": True,
        "run_id": run_id,
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "title": run.get("title"),
        "artifact_base_url": SlideProArtifactStore.artifact_base_url(run_id),
        "artifacts": run.get("artifacts", []),
    }

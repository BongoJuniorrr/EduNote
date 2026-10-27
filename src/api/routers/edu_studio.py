# -*- coding: utf-8 -*-
"""
Edu Studio API Router.

Provides a dedicated module for education-focused multi-agent workflows.
"""

import asyncio
import json
import os
from pathlib import Path as FsPath
import re
from typing import Any, Literal
from defusedxml import ElementTree as ET

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, UploadFile
from pydantic import BaseModel, Field

from src.agents.edu_studio import EduStudioWorkflowAgent
from src.knowledge.manager import KnowledgeBaseManager
from src.services.config import ConfigType, get_config_manager
from src.services.edu_studio import (
    ALLOWED_ARTIFACT_EXTENSIONS,
    EduStudioArtifactStore,
    ParsedMaterial,
    combine_materials_text,
    parse_uploaded_material,
)
from src.services.llm.exceptions import LLMAPIError, LLMAuthenticationError
from src.security.auth import AuthenticatedUser, get_optional_current_user
from src.tools.rag_tool import rag_search
from src.tools.web_search import web_search

router = APIRouter()
QWEN_TEACHER_CONFIG_ID = "qwen_teacher_env"

WorkflowName = Literal[
    "slide_deck",
    "exam_blueprint",
    "lesson_plan",
    "learning_outcome_mapper",
    "rubric_builder",
    "misconception_detector",
    "adaptive_quiz_coach",
    "curriculum_alignment",
    "content_safety_fact_check",
]
RAGMode = Literal["hybrid", "local", "global", "naive"]
SearchMode = Literal["quick", "balanced", "deep"]

SEARCH_QUERY_BUDGET: dict[SearchMode, int] = {
    "quick": 1,
    "balanced": 2,
    "deep": 3,
}
SEARCH_CITATION_BUDGET: dict[SearchMode, int] = {
    "quick": 3,
    "balanced": 5,
    "deep": 8,
}

_KB_BASE_DIR = FsPath(__file__).resolve().parent.parent.parent.parent / "data" / "knowledge_bases"
_QUERY_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "into",
    "about",
    "using",
    "use",
    "are",
    "was",
    "were",
    "have",
    "has",
    "had",
    "will",
    "your",
    "you",
    "và",
    "các",
    "những",
    "trong",
    "với",
    "cho",
    "một",
    "được",
    "từ",
    "này",
    "đó",
}



from src.security.paths import safe_child, safe_leaf, contained_path

class MaterialPayload(BaseModel):
    title: str
    content: str
    metadata: dict = Field(default_factory=dict)


class ContextEnrichmentPayload(BaseModel):
    enable_rag: bool = False
    kb_name: str = ""
    rag_mode: RAGMode = "hybrid"
    enable_web_search: bool = False
    search_mode: SearchMode = "balanced"
    search_provider: str = ""


class EduStudioRunRequest(BaseModel):
    workflow: WorkflowName
    title: str = ""
    language: Literal["vi", "en"] = "vi"
    source_text: str = ""
    instructions: str = ""
    settings: dict = Field(default_factory=dict)
    settings_template: str = ""
    context_enrichment: ContextEnrichmentPayload = Field(default_factory=ContextEnrichmentPayload)
    materials: list[MaterialPayload] = Field(default_factory=list)
    model_config_id: str | None = None
    dry_run: bool = False


def _get_first_env(keys: list[str], default: str = "") -> str:
    for key in keys:
        val = os.getenv(key)
        if val and val.strip():
            return val.strip()
    return default

def _build_qwen_teacher_env_config() -> dict | None:
    """Build a transient Qwen-Teacher config from .env values."""
    model = _get_first_env(["VNM_TEACHER_MODEL"])
    if not model:
        return None

    provider = _get_first_env(["VNM_TEACHER_PROVIDER"], "huggingface").lower()
    device = _get_first_env(["VNM_TEACHER_DEVICE"], "cuda:0")
    api_version = _get_first_env(["VNM_TEACHER_API_VERSION", "LLM_API_VERSION"])
    
    api_key_fallbacks = ["VNM_TEACHER_API_KEY", "HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN", "LLM_API_KEY"]
    api_key = _get_first_env(api_key_fallbacks)

    base_url_fallbacks = ["VNM_TEACHER_BASE_URL", "VNM_TEACHER_HOST"]
    if provider == "huggingface":
        base_url_fallbacks.extend(["HF_OPENAI_BASE_URL"])
        default_url = "https://router.huggingface.co/v1"
    else:
        base_url_fallbacks.extend(["LLM_HOST"])
        default_url = ""
    
    base_url = _get_first_env(base_url_fallbacks, default_url)

    return {
        "id": QWEN_TEACHER_CONFIG_ID,
        "name": "Qwen-Teacher (.env)",
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
        "api_version": api_version or None,
        "device": device,
    }


def _resolve_llm_config(model_config_id: str | None) -> dict:
    manager = get_config_manager()

    if model_config_id == QWEN_TEACHER_CONFIG_ID:
        config = _build_qwen_teacher_env_config()
        if not config:
            raise HTTPException(
                status_code=400,
                detail="Qwen-Teacher is not configured. Please set VNM_TEACHER_MODEL in .env.",
            )
    elif not model_config_id or model_config_id == "active":
        config = manager.get_active_config(ConfigType.LLM)
    elif model_config_id == "default":
        config = manager.get_default_config(ConfigType.LLM)
    else:
        config = manager.get_config(ConfigType.LLM, model_config_id)
        if not config:
            raise HTTPException(
                status_code=404, detail=f"LLM configuration not found: {model_config_id}"
            )
        config = manager.resolve_config_env_values(config)

    if not config:
        raise HTTPException(status_code=500, detail="No active LLM configuration found")

    model = config.get("model")
    base_url = config.get("base_url")
    if not model or not base_url:
        raise HTTPException(status_code=400, detail="Incomplete LLM configuration")

    return config


def _to_parsed_materials(materials: list[MaterialPayload]) -> list[ParsedMaterial]:
    parsed: list[ParsedMaterial] = []
    for material in materials:
        parsed.append(
            ParsedMaterial(
                filename=material.title,
                content=material.content,
                metadata=material.metadata,
            )
        )
    return parsed


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _truncate_text(text: str, max_chars: int) -> str:
    normalized = text.strip()
    if max_chars <= 0 or len(normalized) <= max_chars:
        return normalized
    return f"{normalized[: max_chars - 3].rstrip()}..."


def _tokenize_query(query: str) -> list[str]:
    terms = re.findall(r"[a-zA-Z0-9]{3,}", query.lower())
    return [term for term in terms if term not in _QUERY_STOPWORDS]


def _extract_item_text(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if not isinstance(item, dict):
        return ""

    parts: list[str] = []
    for key in ("title", "text", "content", "summary", "objective", "caption"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())

    for key in ("key_points", "img_caption", "bullet_points", "highlights"):
        value = item.get(key)
        if isinstance(value, list):
            for entry in value:
                entry_text = _normalize_text(entry)
                if entry_text:
                    parts.append(entry_text)

    return " ".join(parts).strip()


def _score_text_match(text: str, terms: list[str]) -> int:
    if not text:
        return 0
    text_lower = text.lower()
    score = 0
    for term in terms:
        if term in text_lower:
            score += 1
    if len(terms) >= 2:
        phrase = f"{terms[0]} {terms[1]}"
        if phrase in text_lower:
            score += 1
    return score


def _local_kb_context_search(kb_name: str, query: str, max_blocks: int = 2) -> str:
    kb_dir = safe_child(_KB_BASE_DIR, kb_name)
    content_list_dir = kb_dir / "content_list"
    if not content_list_dir.exists():
        return ""

    terms = _tokenize_query(query)
    if not terms:
        fallback_terms = [token.lower() for token in query.split() if token.strip()]
        terms = fallback_terms[:5]

    candidates: list[tuple[int, str]] = []
    scanned_items = 0
    max_scan_items = 1600

    for json_file in sorted(content_list_dir.glob("*.json")):
        if scanned_items >= max_scan_items:
            break
        try:
            with open(json_file, encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            continue

        items: list[Any]
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            items = [payload]
        else:
            continue

        for item in items:
            if scanned_items >= max_scan_items:
                break
            scanned_items += 1

            text = _extract_item_text(item)
            if len(text) < 32:
                continue

            score = _score_text_match(text, terms)
            if score <= 0:
                continue

            page_idx = item.get("page_idx") if isinstance(item, dict) else None
            page_text = ""
            if isinstance(page_idx, int) and page_idx >= 0:
                page_text = f" p.{page_idx + 1}"

            source_name = json_file.stem
            snippet = _truncate_text(" ".join(text.split()), 360)
            rendered = f"[{source_name}{page_text}] {snippet}"
            candidates.append((score, rendered))

    if not candidates:
        return ""

    candidates.sort(key=lambda item: item[0], reverse=True)
    deduped: list[str] = []
    seen: set[str] = set()
    for _, line in candidates:
        if line in seen:
            continue
        seen.add(line)
        deduped.append(line)
        if len(deduped) >= max_blocks:
            break

    if not deduped:
        return ""
    return "Local KB excerpts:\n" + "\n".join(f"- {line}" for line in deduped)


def _get_kb_runtime_status(kb_name: str) -> dict[str, Any]:
    graph_path = safe_child(_KB_BASE_DIR, kb_name) / "rag_storage" / "graph_chunk_entity_relation.graphml"
    rag_graph_valid: bool | None = None
    rag_graph_error = ""
    if graph_path.exists():
        try:
            ET.parse(graph_path)
            rag_graph_valid = True
        except Exception as e:
            rag_graph_valid = False
            rag_graph_error = str(e)

    manager = KnowledgeBaseManager(base_dir=str(_KB_BASE_DIR))
    try:
        kb_names = set(manager.list_knowledge_bases())
    except Exception:
        kb_names = set()

    exists = kb_name in kb_names
    if not exists:
        return {
            "exists": False,
            "status": "missing",
            "rag_initialized": False,
            "rag_provider": None,
            "rag_graph_valid": rag_graph_valid,
            "rag_graph_error": rag_graph_error,
        }

    try:
        info = manager.get_info(kb_name)
    except Exception:
        return {
            "exists": True,
            "status": "unknown",
            "rag_initialized": False,
            "rag_provider": None,
            "rag_graph_valid": rag_graph_valid,
            "rag_graph_error": rag_graph_error,
        }

    stats = info.get("statistics", {}) if isinstance(info, dict) else {}
    metadata = info.get("metadata", {}) if isinstance(info, dict) else {}
    return {
        "exists": True,
        "status": _normalize_text(info.get("status")) if isinstance(info, dict) else "unknown",
        "rag_initialized": bool(stats.get("rag_initialized", False)),
        "rag_provider": _normalize_text(
            stats.get("rag_provider") if isinstance(stats, dict) else None
        )
        or _normalize_text(metadata.get("rag_provider") if isinstance(metadata, dict) else None),
        "rag_graph_valid": rag_graph_valid,
        "rag_graph_error": rag_graph_error,
    }


def _is_rag_instance_error(exc: Exception) -> bool:
    message = str(exc).lower()
    patterns = (
        "no lightrag instance available",
        "process documents first",
        "not initialized",
        "rag storage not found",
    )
    return any(pattern in message for pattern in patterns)


def _build_enrichment_queries(request: EduStudioRunRequest, combined_context: str) -> list[str]:
    settings = request.settings if isinstance(request.settings, dict) else {}
    title = _normalize_text(request.title) or request.workflow.replace("_", " ")
    instructions = _truncate_text(_normalize_text(request.instructions), 220)

    structure_hints: list[str] = []
    for key in (
        "storyline_structure",
        "structure_template",
        "template_requirements",
        "audience_persona",
        "delivery_goal",
    ):
        value = _normalize_text(settings.get(key))
        if value:
            structure_hints.append(value)

    context_lines = [line.strip() for line in combined_context.splitlines() if line.strip()]
    context_hint = _truncate_text(" ".join(context_lines[:3]), 240)

    candidates = [
        title,
        " | ".join(part for part in [title, instructions] if part),
        " | ".join(part for part in [title, ", ".join(structure_hints[:2])] if part),
        " | ".join(part for part in [title, context_hint] if part),
    ]

    deduped: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        normalized = _truncate_text(item, 320)
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def _format_web_context(result: dict[str, Any], citation_limit: int) -> str:
    answer = _truncate_text(
        _normalize_text(result.get("answer") or result.get("content")),
        1800,
    )
    citations_raw = result.get("citations")
    citation_lines: list[str] = []

    if isinstance(citations_raw, list):
        for item in citations_raw[:citation_limit]:
            if not isinstance(item, dict):
                continue
            title = _normalize_text(item.get("title")) or "Source"
            url = _normalize_text(item.get("url"))
            snippet = _truncate_text(_normalize_text(item.get("snippet")), 220)
            line = f"- {title}"
            if url:
                line += f" ({url})"
            if snippet:
                line += f": {snippet}"
            citation_lines.append(line)

    blocks: list[str] = []
    if answer:
        blocks.append(answer)
    if citation_lines:
        blocks.append("Citations:\n" + "\n".join(citation_lines))
    return "\n\n".join(blocks)


async def _build_context_enrichment(
    request: EduStudioRunRequest,
    combined_context: str,
) -> tuple[str, dict[str, Any], list[str]]:
    cfg = request.context_enrichment
    details: dict[str, Any] = {
        "enabled": bool(cfg.enable_rag or cfg.enable_web_search),
        "applied": False,
        "rag": {
            "enabled": bool(cfg.enable_rag),
            "kb_name": _normalize_text(cfg.kb_name),
            "mode": cfg.rag_mode,
            "status": "disabled",
            "rag_initialized": None,
            "rag_provider": None,
            "rag_graph_valid": None,
            "query_count": 0,
            "hit_count": 0,
            "fallback_hit_count": 0,
            "generation_fallback_count": 0,
        },
        "search": {
            "enabled": bool(cfg.enable_web_search),
            "mode": cfg.search_mode,
            "provider": _normalize_text(cfg.search_provider) or "default",
            "query_count": 0,
            "hit_count": 0,
        },
    }

    if not details["enabled"]:
        return "", details, []

    warnings: list[str] = []
    queries = _build_enrichment_queries(request, combined_context)

    rag_blocks: list[str] = []
    if cfg.enable_rag:
        kb_name = _normalize_text(cfg.kb_name)
        if not kb_name:
            warnings.append("RAG enabled but no knowledge base selected, skipped RAG enrichment.")
        else:
            kb_runtime = _get_kb_runtime_status(kb_name)
            details["rag"]["status"] = kb_runtime.get("status") or "unknown"
            details["rag"]["rag_initialized"] = bool(kb_runtime.get("rag_initialized"))
            details["rag"]["rag_provider"] = kb_runtime.get("rag_provider")
            details["rag"]["rag_graph_valid"] = kb_runtime.get("rag_graph_valid")

            if not kb_runtime.get("exists"):
                warnings.append(
                    f"RAG skipped: knowledge base '{kb_name}' was not found in current server storage."
                )
            elif kb_runtime.get("rag_graph_valid") is False:
                graph_error = _normalize_text(kb_runtime.get("rag_graph_error"))
                details["rag"]["status"] = "graph_corrupted"
                warnings.append(
                    "RAG knowledge graph appears corrupted for KB "
                    f"'{kb_name}' (graphml parse error: {graph_error or 'unknown'}). "
                    "Retrieval fallback may be used until KB is repaired/re-indexed."
                )

            generation_fallback_queries: list[str] = []
            graph_skip_count = 0
            index_not_ready_reported = False
            for query in queries[:2]:
                details["rag"]["query_count"] += 1
                graph_corrupted = kb_runtime.get("rag_graph_valid") is False
                can_call_rag = (
                    bool(kb_runtime.get("exists"))
                    and bool(kb_runtime.get("rag_initialized"))
                    and not graph_corrupted
                )
                needs_fallback = not can_call_rag

                if can_call_rag:
                    try:
                        rag_result = await rag_search(query=query, kb_name=kb_name, mode=cfg.rag_mode)
                        content = _truncate_text(
                            _normalize_text(rag_result.get("content") or rag_result.get("answer")),
                            2200,
                        )
                        if content:
                            details["rag"]["hit_count"] += 1
                            answer_source = _normalize_text(
                                (
                                    rag_result.get("metadata")
                                    if isinstance(rag_result.get("metadata"), dict)
                                    else {}
                                ).get("answer_source")
                            )
                            if answer_source == "retrieval_fallback":
                                details["rag"]["generation_fallback_count"] += 1
                                generation_fallback_queries.append(query[:80])
                            rag_blocks.append(
                                (
                                    f"RAG Query: {query}\n"
                                    f"KB: {kb_name} | mode: {rag_result.get('mode', cfg.rag_mode)}\n"
                                    f"{content}"
                                )
                            )
                            continue
                        needs_fallback = True
                    except Exception as e:
                        if _is_rag_instance_error(e):
                            warnings.append(
                                "RAG runtime is not ready (LightRAG instance unavailable). "
                                "Using local KB fallback excerpts."
                            )
                        else:
                            warnings.append(f"RAG enrichment failed for query '{query[:80]}': {e}")
                        needs_fallback = True
                else:
                    if graph_corrupted:
                        graph_skip_count += 1
                    else:
                        if not index_not_ready_reported:
                            warnings.append(
                                f"RAG index for KB '{kb_name}' is not initialized yet. "
                                "Using local KB fallback excerpts."
                            )
                            index_not_ready_reported = True

                if needs_fallback:
                    fallback_context = _local_kb_context_search(kb_name=kb_name, query=query, max_blocks=2)
                    if fallback_context:
                        details["rag"]["fallback_hit_count"] += 1
                        rag_blocks.append(
                            (
                                f"RAG Fallback Query: {query}\n"
                                f"KB: {kb_name} | mode: local_file_fallback\n"
                                f"{fallback_context}"
                            )
                        )
                    else:
                        warnings.append(
                            f"RAG fallback found no matching local excerpts for query '{query[:80]}'."
                        )

            if graph_skip_count:
                warnings.append(
                    f"RAG generation skipped for {graph_skip_count} query(ies) because KB '{kb_name}' "
                    "knowledge graph is corrupted; using local fallback excerpts."
                )

            if generation_fallback_queries:
                warnings.append(
                    "RAG generation fallback triggered for "
                    f"{len(generation_fallback_queries)} query(ies) on KB '{kb_name}'. "
                    "Generation fallback was used. "
                    "Retrieved context is available, but the LightRAG generation layer "
                    "needs repair/re-index for best quality."
                )

    web_blocks: list[str] = []
    if cfg.enable_web_search:
        query_budget = SEARCH_QUERY_BUDGET[cfg.search_mode]
        citation_limit = SEARCH_CITATION_BUDGET[cfg.search_mode]
        provider = _normalize_text(cfg.search_provider) or None

        for query in queries[:query_budget]:
            details["search"]["query_count"] += 1
            try:
                result = await asyncio.to_thread(
                    web_search,
                    query=query,
                    provider=provider,
                    verbose=False,
                )
                if not isinstance(result, dict):
                    continue
                context = _format_web_context(result, citation_limit=citation_limit)
                if not context:
                    continue
                details["search"]["hit_count"] += 1
                web_blocks.append(
                    (
                        f"Web Query: {query}\n"
                        f"Provider: {result.get('provider') or provider or 'default'}\n"
                        f"{context}"
                    )
                )
            except Exception as e:
                warnings.append(f"Web search enrichment failed for query '{query[:80]}': {e}")

    sections: list[str] = []
    if rag_blocks:
        sections.append("## RAG Enrichment\n" + "\n\n".join(rag_blocks))
    if web_blocks:
        sections.append("## Web Enrichment\n" + "\n\n".join(web_blocks))

    enriched_context = _truncate_text("\n\n".join(sections), 12000)
    details["applied"] = bool(enriched_context)
    deduped_warnings = list(dict.fromkeys(warnings))
    return enriched_context, details, deduped_warnings


async def _run_workflow(
    request: EduStudioRunRequest,
    parsed_materials: list[ParsedMaterial],
    user: AuthenticatedUser | None = None,
):
    llm_config = _resolve_llm_config(request.model_config_id)
    agent = EduStudioWorkflowAgent(
        api_key=llm_config.get("api_key"),
        base_url=llm_config.get("base_url"),
        api_version=llm_config.get("api_version"),
        model=llm_config.get("model"),
        binding=llm_config.get("provider", "openai"),
        language=request.language,
    )

    all_materials = _to_parsed_materials(request.materials) + parsed_materials
    combined_context = combine_materials_text(
        source_text=request.source_text,
        materials=all_materials,
    )

    enriched_context, enrichment_details, enrichment_warnings = await _build_context_enrichment(
        request,
        combined_context,
    )
    if enriched_context:
        combined_context = (
            f"{combined_context}\n\n"
            "[External enrichment: prioritize this for factual expansion and examples]\n"
            f"{enriched_context}"
        )

    try:
        workflow_result = await agent.run_workflow(
            request.workflow,
            {
                "title": request.title,
                "language": request.language,
                "instructions": request.instructions,
                "settings": request.settings,
                "settings_template": request.settings_template,
                "context_enrichment": enrichment_details,
                "source_text": request.source_text,
                "combined_context": combined_context,
                "dry_run": request.dry_run,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=502, detail=f"Edu Studio generation failed: {e}") from e
    except LLMAuthenticationError as e:
        detail = "LLM authentication failed."
        if request.model_config_id == QWEN_TEACHER_CONFIG_ID:
            detail += " Please check your .env configuration (e.g., API keys like VNM_TEACHER_API_KEY)."
        else:
            detail += f" Details: {e}"
        raise HTTPException(status_code=401, detail=detail) from e
    except LLMAPIError as e:
        status = 429 if e.status_code == 429 else 502
        raise HTTPException(status_code=status, detail=f"LLM provider error: {e}") from e

    warnings: list[str] = []
    for material in parsed_materials:
        warnings.extend(material.warnings)
    warnings.extend(enrichment_warnings)

    artifact_store = EduStudioArtifactStore(owner_id=user.id if user else None)
    run_meta = artifact_store.create_run(
        workflow=request.workflow,
        title=request.title,
    )
    run_id = run_meta["run_id"]
    artifact_store.save_result(run_id, workflow_result)

    return {
        "success": True,
        "workflow": request.workflow,
        "run_id": run_id,
        "artifact_base_url": EduStudioArtifactStore.artifact_base_url(run_id),
        "artifacts": run_meta.get("artifacts", []),
        "result": workflow_result,
        "parsed_materials": [
            {
                "filename": m.filename,
                "content_type": m.content_type,
                "metadata": m.metadata,
                "warnings": m.warnings,
                "content_length": len(m.content),
            }
            for m in parsed_materials
        ],
        "warnings": warnings,
        "context_enrichment": enrichment_details,
    }


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "edu_studio"}


@router.get("/templates")
async def list_workflow_templates():
    return {
        "workflows": EduStudioWorkflowAgent.get_workflow_catalog(),
    }


@router.get("/features")
async def list_features():
    return {
        "features": EduStudioWorkflowAgent.get_workflow_specs(),
        "workflows": EduStudioWorkflowAgent.get_workflow_catalog(),
        "accepted_file_types": [
            ".txt",
            ".md",
            ".json",
            ".csv",
            ".tsv",
            ".pdf",
            ".docx",
        ],
    }


@router.get("/llm-options")
async def list_llm_options():
    manager = get_config_manager()
    configs = manager.list_configs(ConfigType.LLM)
    response_configs = [
        {
            "id": cfg.get("id", ""),
            "name": cfg.get("name", ""),
            "provider": cfg.get("provider", ""),
            "model": cfg.get("model", ""),
            "is_active": bool(cfg.get("is_active", False)),
        }
        for cfg in configs
    ]

    qwen_teacher = _build_qwen_teacher_env_config()
    if qwen_teacher:
        response_configs.insert(
            0,
            {
                "id": qwen_teacher["id"],
                "name": qwen_teacher["name"],
                "provider": qwen_teacher["provider"],
                "model": qwen_teacher["model"],
                "is_active": False,
                "metadata": {"device": qwen_teacher.get("device", "")},
            },
        )

    return {
        "configs": response_configs
    }


WORKFLOW_TIMEOUT_SECONDS = 300
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_UPLOAD_FILES = 10


async def _read_bounded_upload(upload):
    data = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Each Edu Studio file must be at most 20 MiB")
    return data


async def _run_with_deadline(request, parsed_materials, user):
    try:
        return await asyncio.wait_for(
            _run_workflow(request, parsed_materials=parsed_materials, user=user),
            timeout=WORKFLOW_TIMEOUT_SECONDS,
        )
    except TimeoutError as error:
        raise HTTPException(504, "Edu Studio generation timed out. Try a shorter source or check model capacity.") from error


@router.post("/run")
async def run_workflow(
    request: EduStudioRunRequest,
    user: AuthenticatedUser | None = Depends(get_optional_current_user),
):
    return await _run_with_deadline(request, [], user)


@router.post("/run-with-files")
async def run_workflow_with_files(
    payload: str = Form(...),
    files: list[UploadFile] | None = File(default=None),
    user: AuthenticatedUser | None = Depends(get_optional_current_user),
):
    try:
        data = json.loads(payload)
        request = EduStudioRunRequest(**data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}") from e

    parsed_materials: list[ParsedMaterial] = []
    if len(files or []) > MAX_UPLOAD_FILES:
        raise HTTPException(413, "At most 10 files are allowed per upload")
    for upload in files or []:
        raw = await _read_bounded_upload(upload)
        parsed = await asyncio.to_thread(
            parse_uploaded_material,
            upload.filename or "uploaded_file",
            raw,
            upload.content_type or "",
        )
        parsed_materials.append(parsed)

    return await _run_with_deadline(request, parsed_materials, user)


@router.post("/runs/{run_id}/artifacts")
async def upload_artifacts(
    run_id: str = Path(..., description="Edu Studio run identifier"),
    files: list[UploadFile] | None = File(default=None),
    manifest: str | None = Form(default=None),
    user: AuthenticatedUser | None = Depends(get_optional_current_user),
):
    artifact_store = EduStudioArtifactStore(owner_id=user.id if user else None)

    run = artifact_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    parsed_manifest: dict | None = None
    if manifest:
        try:
            parsed_manifest = json.loads(manifest)
            if not isinstance(parsed_manifest, dict):
                raise ValueError("manifest must be a JSON object")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid manifest JSON: {e}") from e

    prepared_files: list[tuple[str, bytes, str]] = []
    if len(files or []) > MAX_UPLOAD_FILES:
        raise HTTPException(413, "At most 10 files are allowed per upload")
    for upload in files or []:
        raw = await _read_bounded_upload(upload)
        if not raw:
            continue
        prepared_files.append(
            (
                upload.filename or "artifact.bin",
                raw,
                upload.content_type or "application/octet-stream",
            )
        )

    if not prepared_files and parsed_manifest is None:
        raise HTTPException(
            status_code=400,
            detail="No artifact files or manifest were provided",
        )

    try:
        saved = artifact_store.save_artifacts(
            run_id=run_id,
            files=prepared_files,
            manifest=parsed_manifest,
        )
    except ValueError as e:
        allowed = ", ".join(sorted(ALLOWED_ARTIFACT_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"Invalid artifact payload: {e}. Allowed extensions: {allowed}",
        ) from e

    updated_run = artifact_store.get_run(run_id) or run

    return {
        "success": True,
        "run_id": run_id,
        "workflow": updated_run.get("workflow"),
        "artifact_base_url": EduStudioArtifactStore.artifact_base_url(run_id),
        "artifacts": saved,
    }


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str = Path(..., description="Edu Studio run identifier"),
    user: AuthenticatedUser | None = Depends(get_optional_current_user),
):
    artifact_store = EduStudioArtifactStore(owner_id=user.id if user else None)
    run = artifact_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    return {
        "success": True,
        "run_id": run.get("run_id"),
        "workflow": run.get("workflow"),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "artifacts": run.get("artifacts", []),
        "artifact_base_url": EduStudioArtifactStore.artifact_base_url(run_id),
    }

# -*- coding: utf-8 -*-
"""
VGU Course API Router
=====================

REST API endpoints for VGU Course mode.

Features:
- Query with page-accurate citations
- Knowledge base management
- Search mode selection
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.agents.vgu_course import VGUCourseAgent, VGURAGTool
from src.logging import get_logger
from src.services.rag.factory import get_pipeline, list_pipelines

logger = get_logger("VGUCourseAPI")

router = APIRouter(prefix="/vgu", tags=["VGU Course"])


# =============================================================================
# Request/Response Models
# =============================================================================

class VGUQueryRequest(BaseModel):
    """Request model for VGU Course query."""
    question: str = Field(..., description="Question to answer")
    kb_name: str = Field(..., description="Knowledge base name")
    mode: str = Field(default="hybrid", description="Search mode: hybrid, local, global, naive")
    include_citations: bool = Field(default=True, description="Include page citations")
    verify_citations: bool = Field(default=False, description="Verify citation accuracy")


class VGUCitation(BaseModel):
    """Citation model with page information."""
    doc_id: str
    doc_name: str
    page_start: int
    page_end: int
    section_path: str = ""
    chunk_id: str = ""
    confidence: float = 1.0


class VGUQueryResponse(BaseModel):
    """Response model for VGU Course query."""
    question: str
    answer: str
    citations: List[VGUCitation] = []
    mode: str
    provider: str = "vgu_course"
    metadata: Dict[str, Any] = {}


class VGUContextRequest(BaseModel):
    """Request model for context-only retrieval."""
    query: str = Field(..., description="Search query")
    kb_name: str = Field(..., description="Knowledge base name")
    mode: str = Field(default="hybrid", description="Search mode")
    top_k: int = Field(default=5, description="Number of results")


class VGUContextResponse(BaseModel):
    """Response model for context retrieval."""
    query: str
    context: str
    chunks: List[Dict[str, Any]] = []
    citations: List[VGUCitation] = []


class VGUInitRequest(BaseModel):
    """Request for initializing a VGU Course KB."""
    kb_name: str = Field(..., description="Knowledge base name")
    file_paths: List[str] = Field(..., description="List of document paths")
    enable_reranker: bool = Field(default=True, description="Enable reranker")
    extract_numbered_items: bool = Field(default=True, description="Extract definitions, theorems, etc.")


class VGUInitResponse(BaseModel):
    """Response for KB initialization."""
    success: bool
    kb_name: str
    message: str
    stats: Dict[str, Any] = {}


# =============================================================================
# API Endpoints
# =============================================================================

@router.post("/query", response_model=VGUQueryResponse)
async def query_vgu_course(request: VGUQueryRequest):
    """
    Query VGU Course knowledge base with page-accurate citations.
    
    Features:
    - Two-tier retrieval (coarse sections → fine chunks)
    - Cross-encoder reranking
    - Page-accurate citations
    """
    try:
        agent = VGUCourseAgent(kb_name=request.kb_name)
        
        if request.verify_citations:
            result = await agent.answer_with_verification(
                question=request.question,
                mode=request.mode,
                verify_citations=True,
            )
        else:
            result = await agent.answer(
                question=request.question,
                mode=request.mode,
                include_citations=request.include_citations,
            )
        
        return VGUQueryResponse(
            question=result["question"],
            answer=result["answer"],
            citations=[VGUCitation(**c) for c in result.get("citations", [])],
            mode=result["mode"],
            provider=result["provider"],
            metadata=result.get("metadata", {}),
        )
        
    except Exception as e:
        logger.error(f"VGU query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/context", response_model=VGUContextResponse)
async def get_vgu_context(request: VGUContextRequest):
    """
    Get retrieval context without LLM generation.
    
    Useful for debugging or custom answer generation.
    """
    try:
        tool = VGURAGTool(kb_name=request.kb_name)
        result = await tool.search(
            query=request.query,
            mode=request.mode,
            only_need_context=True,
        )
        
        return VGUContextResponse(
            query=request.query,
            context=result.get("content", ""),
            chunks=[],  # Simplified - full chunks in result
            citations=[VGUCitation(**c) for c in result.get("citations", [])],
        )
        
    except Exception as e:
        logger.error(f"VGU context retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/init", response_model=VGUInitResponse)
async def init_vgu_kb(request: VGUInitRequest):
    """
    Initialize a new VGU Course knowledge base.
    
    This processes documents with:
    - Two-tier indexing (sections + chunks)
    - Page metadata extraction
    - Section summary generation
    - Numbered items extraction (definitions, theorems, etc.)
    """
    try:
        pipeline = get_pipeline(
            "vgu_course",
            enable_reranker=request.enable_reranker,
        )
        
        success = await pipeline.initialize(
            kb_name=request.kb_name,
            file_paths=request.file_paths,
            extract_numbered_items=request.extract_numbered_items,
        )
        
        return VGUInitResponse(
            success=success,
            kb_name=request.kb_name,
            message="Knowledge base initialized successfully" if success else "Initialization failed",
            stats={},
        )
        
    except Exception as e:
        logger.error(f"VGU KB init failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pipelines")
async def list_available_pipelines():
    """
    List all available RAG pipelines including VGU Course.
    """
    pipelines = list_pipelines()
    
    # Highlight VGU Course pipeline
    for p in pipelines:
        if p["id"] == "vgu_course":
            p["recommended"] = True
            p["features"] = [
                "Two-tier indexing",
                "Page-accurate citations",
                "Cross-encoder reranking",
                "Long document support",
                "Multimodal (images, tables, equations)",
            ]
    
    return {"pipelines": pipelines}


@router.get("/health")
async def health_check():
    """Health check for VGU Course API."""
    return {
        "status": "healthy",
        "service": "vgu_course",
        "features": [
            "two_tier_indexing",
            "page_citations",
            "reranking",
            "multimodal",
        ],
    }

# -*- coding: utf-8 -*-
"""
Pre-configured Pipelines
========================

Ready-to-use RAG pipelines for common use cases.
"""

from typing import Any

__all__ = [
    "RAGAnythingPipeline",
    "RAGAnythingDoclingPipeline",
    "LightRAGPipeline",
    "VGUCoursePipeline",
]

# NOTE:
# - Do NOT import heavy/optional backends at module import time.
# - Users may want `llamaindex` without `raganything`, or vice versa.
# - Accessing an attribute triggers a targeted import via __getattr__.


def __getattr__(name: str) -> Any:
    if name == "LightRAGPipeline":
        from .lightrag import LightRAGPipeline

        return LightRAGPipeline
    if name == "RAGAnythingPipeline":
        from .raganything import RAGAnythingPipeline

        return RAGAnythingPipeline
    if name == "RAGAnythingDoclingPipeline":
        from .raganything_docling import RAGAnythingDoclingPipeline

        return RAGAnythingDoclingPipeline
    if name == "LlamaIndexPipeline":
        # Optional dependency: llama_index
        from .llamaindex import LlamaIndexPipeline

        return LlamaIndexPipeline
    if name == "VGUCoursePipeline":
        # VGU Course: Two-tier indexing, page-accurate citations, reranker
        from .vgu_course import VGUCoursePipeline

        return VGUCoursePipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

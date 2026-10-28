# -*- coding: utf-8 -*-
"""
Services Layer
==============

Unified service layer for EduNote providing:
- LLM client and configuration
- Embedding client and configuration
- RAG pipelines and components
- Prompt management
- TTS configuration
- Web Search providers
- System setup utilities
- Configuration loading

Usage:
    from src.services.llm import get_llm_client
    from src.services.embedding import get_embedding_client
    from src.services.rag import get_pipeline
    from src.services.prompt import get_prompt_manager
    from src.services.tts import get_tts_config
    from src.services.search import web_search
    from src.services.setup import init_user_directories
    from src.services.config import load_config_with_main

    # LLM
    llm = get_llm_client()
    response = await llm.complete("Hello, world!")

    # Embedding
    embed = get_embedding_client()
    vectors = await embed.embed(["text1", "text2"])

    # RAG
    pipeline = get_pipeline("raganything")
    result = await pipeline.search("query", "kb_name")

    # Prompt
    pm = get_prompt_manager()
    prompts = pm.load_prompts("guide", "tutor_agent")

    # Search
    result = web_search("What is AI?")
"""

import importlib

# Note: rag and embedding modules are lazy-loaded via __getattr__
# to avoid importing heavy dependencies (lightrag, llama_index) at module load time

__all__ = [
    "llm",
    "embedding",
    "rag",
    "prompt",
    "tts",
    "search",
    "setup",
    "config",
    "edu_studio",
]


def __getattr__(name: str):
    """Lazy import for service submodules."""
    if name in {
        "llm",
        "embedding",
        "rag",
        "prompt",
        "tts",
        "search",
        "setup",
        "config",
        "edu_studio",
    }:
        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

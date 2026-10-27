# -*- coding: utf-8 -*-
"""
RAG Service
===========

Unified RAG service providing a single entry point for all RAG operations.
"""

import json
import os
from pathlib import Path
import shutil
import threading
from typing import Any, Dict, List, Optional

from src.logging import get_logger
from src.services.config import get_kb_config_service

from .factory import get_pipeline, has_pipeline, list_pipelines

# Default knowledge base directory
DEFAULT_KB_BASE_DIR = str(
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "knowledge_bases"
)

PROFILE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "vgu_course": {
        "mode": "hybrid",
        "enable_query_expansion": True,
        "enable_hybrid_search": True,
        "enable_reranker": True,
        "coarse_top_k": 15,
        "fine_top_k": 40,
        "final_top_k": 10,
    },
    "standard": {
        "mode": "hybrid",
    },
    "lightweight": {
        "mode": "naive",
        "top_k": 5,
        "enable_query_expansion": False,
        "enable_hybrid_search": False,
        "enable_reranker": False,
        "coarse_top_k": 8,
        "fine_top_k": 20,
        "final_top_k": 5,
    },
}


class RAGService:
    """
    Unified RAG service entry point.

    Provides a clean interface for RAG operations:
    - Knowledge base initialization
    - Search/retrieval
    - Knowledge base deletion

    Usage:
        # Default configuration
        service = RAGService()
        await service.initialize("my_kb", ["doc1.pdf"])
        result = await service.search("query", "my_kb")

        # Custom configuration for testing
        service = RAGService(kb_base_dir="/tmp/test_kb", provider="llamaindex")
        await service.initialize("test", ["test.txt"])
    """

    # Reuse heavy pipeline instances across service objects and requests.
    _PIPELINE_CACHE: Dict[tuple[str, str], Any] = {}
    _PIPELINE_CACHE_LOCK = threading.Lock()

    def __init__(
        self,
        kb_base_dir: Optional[str] = None,
        provider: Optional[str] = None,
    ):
        """
        Initialize RAG service.

        Args:
            kb_base_dir: Base directory for knowledge bases.
                         Defaults to data/knowledge_bases.
            provider: RAG pipeline provider to use.
                      Defaults to RAG_PROVIDER env var or "raganything".
        """
        self.logger = get_logger("RAGService")
        self.kb_base_dir = kb_base_dir or DEFAULT_KB_BASE_DIR
        self.provider = provider or os.getenv("RAG_PROVIDER", "raganything")
        self._pipeline = None

    def _get_pipeline(self):
        """Get or create pipeline instance."""
        self._pipeline = self._get_cached_pipeline(self.provider)
        return self._pipeline

    def _get_cached_pipeline(self, provider: str):
        """Get or create a cached pipeline for a provider and KB base directory."""
        import hashlib

        from src.services.config import ConfigType, get_config_manager

        manager = get_config_manager()
        signature = hashlib.sha256(
            json.dumps(
                {
                    kind.value: manager.get_active_config(kind)
                    for kind in (ConfigType.LLM, ConfigType.EMBEDDING)
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        cache_key = (provider, str(Path(self.kb_base_dir).resolve()), signature)

        with self._PIPELINE_CACHE_LOCK:
            pipeline = self._PIPELINE_CACHE.get(cache_key)
            if pipeline is None:
                pipeline = get_pipeline(provider, kb_base_dir=self.kb_base_dir)
                self._PIPELINE_CACHE[cache_key] = pipeline
        return pipeline

    async def initialize(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        """
        Initialize a knowledge base with documents.

        Args:
            kb_name: Knowledge base name
            file_paths: List of file paths to process
            **kwargs: Additional arguments passed to pipeline

        Returns:
            True if successful

        Example:
            service = RAGService()
            success = await service.initialize("my_kb", ["doc1.pdf", "doc2.txt"])
        """
        self.logger.info(f"Initializing KB '{kb_name}' with provider '{self.provider}'")
        pipeline = self._get_pipeline()
        return await pipeline.initialize(kb_name=kb_name, file_paths=file_paths, **kwargs)

    async def search(
        self, query: str, kb_name: str, mode: str = "hybrid", **kwargs
    ) -> Dict[str, Any]:
        """
        Search a knowledge base.

        Args:
            query: Search query
            kb_name: Knowledge base name
            mode: Search mode (hybrid, local, global, naive)
            **kwargs: Additional arguments passed to pipeline

        Returns:
            Search results dictionary with keys:
            - query: Original query
            - answer: Generated answer
            - content: Retrieved content
            - mode: Search mode used
            - provider: Pipeline provider used

        Example:
            service = RAGService()
            result = await service.search("What is ML?", "textbook")
            print(result["answer"])
        """
        # Get the provider from KB metadata, fallback to instance provider
        provider = self._get_provider_for_kb(kb_name)
        resolved_mode, resolved_kwargs = self._resolve_retrieval_options(
            kb_name=kb_name,
            provider=provider,
            mode=mode,
            request_kwargs=kwargs,
        )

        self.logger.info(
            f"Searching KB '{kb_name}' with provider '{provider}', mode '{resolved_mode}' "
            f"and query: {query[:50]}..."
        )

        # Get cached pipeline for the specific provider
        pipeline = self._get_cached_pipeline(provider)

        result = await pipeline.search(
            query=query,
            kb_name=kb_name,
            mode=resolved_mode,
            **resolved_kwargs,
        )

        # Ensure consistent return format
        if "query" not in result:
            result["query"] = query
        if "answer" not in result and "content" in result:
            result["answer"] = result["content"]
        if "content" not in result and "answer" in result:
            result["content"] = result["answer"]
        if "provider" not in result:
            result["provider"] = provider
        if "mode" not in result:
            result["mode"] = resolved_mode

        return result

    def _resolve_retrieval_options(
        self,
        kb_name: str,
        provider: str,
        mode: str,
        request_kwargs: Dict[str, Any],
    ) -> tuple[str, Dict[str, Any]]:
        """
        Resolve retrieval profile + overrides for a KB.

        Precedence (low -> high):
        1. Profile defaults
        2. KB retrieval_overrides
        3. Request kwargs
        """
        try:
            from src.services.config.knowledge_base_config import DEFAULT_CONFIG_PATH

            config_path = DEFAULT_CONFIG_PATH
            kb_cfg_service = get_kb_config_service(config_path=config_path)
            kb_cfg = kb_cfg_service.get_kb_config(kb_name)
        except Exception as e:
            self.logger.warning(f"Failed to load KB retrieval config for '{kb_name}': {e}")
            kb_cfg = {}

        profile = kb_cfg.get("retrieval_profile", "standard")
        profile_defaults = PROFILE_DEFAULTS.get(profile, PROFILE_DEFAULTS["standard"]).copy()

        # Provider-aware fallback for unset profile values.
        if provider == "vgu_course" and profile == "standard":
            profile_defaults.update(
                {
                    "enable_query_expansion": True,
                    "enable_hybrid_search": True,
                    "enable_reranker": True,
                    "coarse_top_k": 15,
                    "fine_top_k": 40,
                    "final_top_k": 10,
                }
            )

        overrides = kb_cfg.get("retrieval_overrides", {}) or {}

        resolved_kwargs = {}
        resolved_kwargs.update(profile_defaults)
        resolved_kwargs.update(overrides)
        resolved_kwargs.update(request_kwargs)

        resolved_mode = resolved_kwargs.pop("mode", mode)
        self.logger.debug(
            f"Resolved retrieval config for KB '{kb_name}': profile={profile}, "
            f"mode={resolved_mode}, overrides={list(overrides.keys())}, "
            f"kwargs={list(resolved_kwargs.keys())}"
        )
        return resolved_mode, resolved_kwargs

    def _get_provider_for_kb(self, kb_name: str) -> str:
        """
        Get the RAG provider for a specific knowledge base from its metadata.
        Falls back to instance provider or env var if not found in metadata.

        Args:
            kb_name: Knowledge base name

        Returns:
            Provider name (e.g., 'llamaindex', 'lightrag', 'raganything')
        """
        try:
            metadata_file = Path(self.kb_base_dir) / kb_name / "metadata.json"

            if metadata_file.exists():
                with open(metadata_file, encoding="utf-8") as f:
                    metadata = json.load(f)
                    provider = metadata.get("rag_provider")
                    if provider:
                        self.logger.info(f"Using provider '{provider}' from KB metadata")
                        return provider

            # Fallback to instance provider
            self.logger.info(f"No provider in metadata, using instance provider: {self.provider}")
            return self.provider

        except Exception as e:
            self.logger.warning(
                f"Error reading provider from metadata: {e}, using instance provider"
            )
            return self.provider

    async def delete(self, kb_name: str) -> bool:
        """
        Delete a knowledge base.

        Args:
            kb_name: Knowledge base name

        Returns:
            True if successful

        Example:
            service = RAGService()
            success = await service.delete("old_kb")
        """
        self.logger.info(f"Deleting KB '{kb_name}'")
        pipeline = self._get_pipeline()

        if hasattr(pipeline, "delete"):
            return await pipeline.delete(kb_name=kb_name)

        # Fallback: delete directory manually
        kb_dir = Path(self.kb_base_dir) / kb_name
        if kb_dir.exists():
            shutil.rmtree(kb_dir)
            self.logger.info(f"Deleted KB directory: {kb_dir}")
            return True
        return False

    @staticmethod
    def list_providers() -> List[Dict[str, str]]:
        """
        List available RAG pipeline providers.

        Returns:
            List of provider info dictionaries

        Example:
            providers = RAGService.list_providers()
            for p in providers:
                print(f"{p['id']}: {p['description']}")
        """
        return list_pipelines()

    @staticmethod
    def get_current_provider() -> str:
        """
        Get the currently configured default provider.

        Returns:
            Provider name from RAG_PROVIDER env var or default
        """
        return os.getenv("RAG_PROVIDER", "raganything")

    @staticmethod
    def has_provider(name: str) -> bool:
        """
        Check if a provider is available.

        Args:
            name: Provider name

        Returns:
            True if provider exists
        """
        return has_pipeline(name)

# -*- coding: utf-8 -*-
"""
Embedding Client
================

Unified embedding client for all EduNote services.
Now supports multiple providers through adapters.
Includes automatic batching to avoid API rate limits and manage GPU memory.
"""

import os
from typing import List, Optional

from src.logging import get_logger

from .adapters.base import EmbeddingRequest
from .config import EmbeddingConfig, get_embedding_config
from .provider import EmbeddingProviderManager, get_embedding_provider_manager

# Default batch sizes per provider
_DEFAULT_BATCH_SIZES = {
    "huggingface": 128,  # Local GPU - large batches are efficient
    "ollama": 64,  # Local CPU/GPU
    "lm_studio": 64,  # Local
    "openai": 2048,  # OpenAI allows large batches
    "azure_openai": 2048,
    "google": 80,  # Google Gemini: max 100 per batch, use 80 for safety
    "cohere": 96,  # Cohere default
    "jina": 128,  # Jina default
}


class EmbeddingClient:
    """
    Unified embedding client for all services.

    Delegates to provider-specific adapters based on configuration.
    Supports: OpenAI, Azure OpenAI, Cohere, Ollama, Jina, HuggingFace (local), Google.

    Includes automatic batching:
    - For API providers: avoids rate limits (e.g., Google's 100/batch limit)
    - For local models: manages GPU memory efficiently
    """

    def __init__(self, config: Optional[EmbeddingConfig] = None):
        """
        Initialize embedding client.

        Args:
            config: Embedding configuration. If None, loads from environment.
        """
        self.config = config or get_embedding_config()
        self.logger = get_logger("EmbeddingClient")
        self.manager: EmbeddingProviderManager = get_embedding_provider_manager()
        self.adapter = None

        # Determine batch size
        env_batch = os.environ.get("EMBEDDING_BATCH_SIZE")
        if env_batch:
            self.batch_size = int(env_batch)
        else:
            self.batch_size = _DEFAULT_BATCH_SIZES.get(self.config.binding, 100)

        # Initialize adapter based on binding configuration
        try:
            adapter = self.manager.get_adapter(
                self.config.binding,
                {
                    "api_key": self.config.api_key,
                    "base_url": self.config.base_url,
                    "api_version": getattr(self.config, "api_version", None),
                    "model": self.config.model,
                    "dimensions": self.config.dim,
                    "request_timeout": self.config.request_timeout,
                    "batch_size": self.batch_size,
                },
            )
            self.adapter = adapter
            self.manager.set_adapter(adapter)

            self.logger.info(
                f"Initialized embedding client with {self.config.binding} adapter "
                f"(model: {self.config.model}, dim: {self.config.dim}, "
                f"batch_size: {self.batch_size})"
            )
        except Exception as e:
            self.logger.error(f"Failed to initialize embedding adapter: {e}")
            raise

    async def embed(self, texts: List[str], input_type: Optional[str] = None) -> List[List[float]]:
        """
        Get embeddings for texts using the configured adapter.

        Automatically batches large requests to avoid API limits
        and manage GPU memory.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        # Use client-local adapter to avoid cross-request contamination from
        # other temporary EmbeddingClient instances (e.g., config test endpoints).
        adapter = self.adapter or self.manager.get_active_adapter()

        # If texts fit in one batch, send directly (most common case)
        if len(texts) <= self.batch_size:
            return await self._embed_batch(adapter, texts, input_type)

        # Split into batches for large requests
        all_embeddings: List[List[float]] = []
        total = len(texts)
        self.logger.info(
            f"Batching {total} texts into chunks of {self.batch_size} "
            f"({(total + self.batch_size - 1) // self.batch_size} batches)"
        )

        for i in range(0, total, self.batch_size):
            batch = texts[i : i + self.batch_size]
            batch_num = i // self.batch_size + 1
            total_batches = (total + self.batch_size - 1) // self.batch_size

            try:
                embeddings = await self._embed_batch(adapter, batch, input_type)
                all_embeddings.extend(embeddings)
                self.logger.debug(f"Batch {batch_num}/{total_batches}: embedded {len(batch)} texts")
            except Exception as e:
                self.logger.error(f"Batch {batch_num}/{total_batches} failed: {e}")
                raise

        self.logger.info(f"All batches complete: {len(all_embeddings)} embeddings generated")
        return all_embeddings

    async def _embed_batch(
        self, adapter, texts: List[str], input_type: Optional[str] = None
    ) -> List[List[float]]:
        """
        Embed a single batch of texts.

        Args:
            adapter: Active embedding adapter
            texts: Batch of texts to embed

        Returns:
            List of embedding vectors for this batch
        """
        request = EmbeddingRequest(
            texts=texts,
            model=self.config.model,
            dimensions=self.config.dim,
            input_type=input_type or self.config.input_type,
        )

        try:
            response = await adapter.embed(request)
            if len(response.embeddings) != len(texts):
                raise ValueError(
                    "Embedding server returned a different number of vectors than inputs"
                )
            if any(len(vector) != self.config.dim for vector in response.embeddings):
                raise ValueError(
                    f"Embedding dimension mismatch; expected {self.config.dim}. Update Settings and reindex existing knowledge bases."
                )
            return response.embeddings
        except Exception as e:
            self.logger.error(f"Embedding request failed: {e}")
            raise

    def embed_sync(self, texts: List[str]) -> List[List[float]]:
        """
        Synchronous wrapper for embed().

        Use this when you need to call from non-async context.
        """
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self.embed(texts))
                    return future.result()
            else:
                return loop.run_until_complete(self.embed(texts))
        except RuntimeError:
            return asyncio.run(self.embed(texts))

    def get_embedding_func(self):
        """
        Get an EmbeddingFunc compatible with LightRAG.

        Returns:
            EmbeddingFunc instance
        """
        from lightrag.utils import EmbeddingFunc
        import numpy as np

        # Create async wrapper that uses our adapter system
        # LightRAG expects numpy arrays, not Python lists
        async def embedding_wrapper(texts: List[str]):
            embeddings = await self.embed(texts)
            # Convert list of lists to numpy array for LightRAG compatibility
            return np.array(embeddings)

        return EmbeddingFunc(
            embedding_dim=self.config.dim,
            max_token_size=self.config.max_tokens,
            func=embedding_wrapper,
        )


# Singleton instance
_client: Optional[EmbeddingClient] = None


def get_embedding_client(config: Optional[EmbeddingConfig] = None) -> EmbeddingClient:
    """
    Get or create the singleton embedding client.

    Args:
        config: Optional configuration. Only used on first call.

    Returns:
        EmbeddingClient instance
    """
    global _client
    resolved = config or get_embedding_config()
    if _client is None or _client.config != resolved:
        _client = EmbeddingClient(resolved)
    return _client


def reset_embedding_client():
    """Reset the singleton embedding client."""
    global _client
    _client = None

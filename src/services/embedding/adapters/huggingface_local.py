# -*- coding: utf-8 -*-
"""
Local HuggingFace Embedding Adapter
====================================

Runs sentence-transformers models locally on GPU/CPU.
No API calls needed — eliminates costs and rate limits.

Recommended models for P100 16GB:
- intfloat/multilingual-e5-large-instruct (1024d, 512 tokens, ~2.8GB VRAM)
  Best multilingual quality, instruction-aware
- intfloat/multilingual-e5-large (1024d, 512 tokens, ~2.5GB VRAM)
  Great multilingual quality, simpler prefix
- BAAI/bge-m3 (1024d, 8192 tokens, ~2.5GB VRAM)
  Longest context, good multilingual
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
import time
from typing import Any, Dict, List

import numpy as np

from src.logging import get_logger

from .base import BaseEmbeddingAdapter, EmbeddingRequest, EmbeddingResponse

logger = get_logger("HFLocalEmbedding")

# Singleton model cache to avoid reloading
_model_cache: Dict[str, Any] = {}


class HuggingFaceLocalEmbeddingAdapter(BaseEmbeddingAdapter):
    """
    Local HuggingFace embedding adapter using sentence-transformers.

    Runs models directly on GPU/CPU without API calls.
    Supports automatic batching, CUDA acceleration, and model caching.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize HuggingFace local embedding adapter.

        Config keys:
            model: HuggingFace model name (e.g., "intfloat/multilingual-e5-large-instruct")
            dimensions: Expected embedding dimensions
            device: "cuda", "cpu", or "auto" (default: auto-detect)
            batch_size: Batch size for encoding (default: 64)
            max_seq_length: Override model's max sequence length (optional)
            normalize: Whether to L2-normalize embeddings (default: True)
            prompt_name: Prompt template name for instruction models (optional)
        """
        super().__init__(config)
        self.device = config.get("device") or os.environ.get("EMBEDDING_DEVICE", "auto")
        self.batch_size = int(
            config.get("batch_size") or os.environ.get("EMBEDDING_BATCH_SIZE", "64")
        )
        self.max_seq_length = config.get("max_seq_length")
        self.normalize = config.get("normalize", True)
        self.prompt_name = config.get("prompt_name")
        self._model = None
        self._total_tokens = 0
        # Keep heavy model operations off the event loop thread.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hf-embed")
        self._op_lock = asyncio.Lock()

    def _get_device(self) -> str:
        """Resolve device string."""
        if self.device and self.device != "auto":
            return self.device
        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"

    def _load_model(self):
        """Load sentence-transformers model (cached singleton)."""
        global _model_cache

        model_name = self.model
        cache_key = (model_name, self._get_device(), self.max_seq_length)
        if cache_key in _model_cache:
            self._model = _model_cache[cache_key]
            logger.debug(f"Using cached model: {model_name}")
            return

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers"
            )

        device = self._get_device()
        logger.info(f"Loading embedding model: {model_name} on {device}")
        start = time.time()

        # Use trust_remote_code for models that need it
        model = SentenceTransformer(
            model_name,
            device=device,
            trust_remote_code=os.getenv("EMBEDDING_TRUST_REMOTE_CODE", "false").lower() == "true",
        )

        # Override max_seq_length if specified
        if self.max_seq_length:
            model.max_seq_length = int(self.max_seq_length)

        elapsed = time.time() - start
        vram_info = ""
        try:
            import torch

            if torch.cuda.is_available():
                vram_mb = torch.cuda.memory_allocated(0) / 1024**2
                vram_info = f", VRAM: {vram_mb:.0f}MB"
        except Exception:
            pass

        logger.info(
            f"Model loaded in {elapsed:.1f}s "
            f"(dim={model.get_sentence_embedding_dimension()}, "
            f"max_seq={model.max_seq_length}, device={device}{vram_info})"
        )

        _model_cache[cache_key] = model
        self._model = model

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """
        Generate embeddings locally using sentence-transformers.

        Handles batching automatically — no API rate limits.
        """
        loop = asyncio.get_running_loop()
        async with self._op_lock:
            if self._model is None:
                await loop.run_in_executor(self._executor, self._load_model)

            texts = request.texts
            if "e5" in self.model.lower():
                if "instruct" in self.model.lower():
                    if request.input_type == "search_query":
                        texts = [
                            f"Instruct: Retrieve relevant passages for the query.\nQuery: {text}"
                            for text in texts
                        ]
                else:
                    prefix = "query: " if request.input_type == "search_query" else "passage: "
                    texts = [prefix + text for text in texts]
            if not texts:
                return EmbeddingResponse(
                    embeddings=[],
                    model=self.model,
                    dimensions=request.dimensions or self.dimensions or 0,
                    usage={"prompt_tokens": 0, "total_tokens": 0},
                )

            # Encode with batching (sentence-transformers handles this efficiently)
            start = time.time()
            embeddings_np = await loop.run_in_executor(
                self._executor,
                self._encode_sync,
                texts,
            )
            elapsed = time.time() - start

            # Convert numpy to list of lists
            if isinstance(embeddings_np, np.ndarray):
                embeddings = embeddings_np.tolist()
            else:
                embeddings = [
                    e.tolist() if hasattr(e, "tolist") else list(e) for e in embeddings_np
                ]

            dim = len(embeddings[0]) if embeddings else 0
            # Rough token estimate (4 chars ~= 1 token)
            est_tokens = sum(len(t) // 4 for t in texts)
            self._total_tokens += est_tokens

            if len(texts) > 10:
                logger.info(
                    f"Embedded {len(texts)} texts in {elapsed:.2f}s "
                    f"({len(texts) / elapsed:.0f} texts/s)"
                )
            else:
                logger.debug(f"Embedded {len(texts)} texts in {elapsed:.3f}s")

            return EmbeddingResponse(
                embeddings=embeddings,
                model=self.model,
                dimensions=dim,
                usage={
                    "prompt_tokens": est_tokens,
                    "total_tokens": self._total_tokens,
                },
            )

    def _encode_sync(self, texts: List[str]) -> np.ndarray:
        """Run sentence-transformers encode in the dedicated worker thread."""
        return self._model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=self.normalize,
            show_progress_bar=False,
            convert_to_numpy=True,
        )

    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the loaded model."""
        info = {
            "provider": "huggingface_local",
            "model": self.model,
            "device": self._get_device(),
            "batch_size": self.batch_size,
            "normalize": self.normalize,
        }
        if self._model is not None:
            info["dimensions"] = self._model.get_sentence_embedding_dimension()
            info["max_seq_length"] = self._model.max_seq_length
        return info

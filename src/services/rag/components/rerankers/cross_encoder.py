# -*- coding: utf-8 -*-
"""
Cross-Encoder Reranker
======================

Reranker using cross-encoder models from sentence-transformers.

Supported models:
- BAAI/bge-reranker-v2-m3 (default, multilingual, best quality)
- BAAI/bge-reranker-base (good balance)
- BAAI/bge-reranker-large (better quality, slower)
- cross-encoder/ms-marco-MiniLM-L-6-v2 (faster, smaller)
- cross-encoder/ms-marco-MiniLM-L-12-v2 (good balance)
"""

from typing import List, Optional

from src.logging import get_logger

from .base import BaseReranker, RerankerResult


class CrossEncoderReranker(BaseReranker):
    """
    Cross-encoder reranker using sentence-transformers.
    
    Cross-encoders jointly encode query and document together,
    which typically gives better relevance scores than bi-encoders
    but is slower (can't pre-compute document embeddings).
    
    Best used for reranking a small set of candidates (20-50 docs)
    retrieved by a faster method (e.g., dense retrieval).
    
    Example:
        reranker = CrossEncoderReranker(model_name="BAAI/bge-reranker-base")
        results = reranker.rerank(
            query="What is machine learning?",
            documents=["ML is a subset of AI...", "Deep learning uses neural networks..."],
            top_k=5
        )
    """
    
    name = "cross_encoder"
    
    # Default models by quality/speed tradeoff
    MODELS = {
        "fast": "cross-encoder/ms-marco-MiniLM-L-6-v2",
        "balanced": "BAAI/bge-reranker-base",
        "quality": "BAAI/bge-reranker-v2-m3",
    }
    
    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        device: str = "cuda",
        max_length: int = 512,
        batch_size: int = 32,
    ):
        """
        Initialize cross-encoder reranker.
        
        Args:
            model_name: HuggingFace model name or preset (fast/balanced/quality)
            device: Device to run on ("cpu", "cuda", "cuda:0", etc.)
            max_length: Maximum sequence length
            batch_size: Batch size for inference
        """
        self.logger = get_logger("CrossEncoderReranker")
        
        # Resolve preset names
        if model_name in self.MODELS:
            model_name = self.MODELS[model_name]
        
        self.model_name = model_name
        self.device = device
        self.max_length = max_length
        self.batch_size = batch_size
        
        self._model = None
        self._initialized = False
    
    def _ensure_initialized(self):
        """Lazy load the model."""
        if self._initialized:
            return
        
        try:
            from sentence_transformers import CrossEncoder
            
            self.logger.info(f"Loading reranker model: {self.model_name}")
            self._model = CrossEncoder(
                self.model_name,
                max_length=self.max_length,
                device=self.device,
            )
            self._initialized = True
            self.logger.info(f"Reranker loaded on device: {self.device}")
            
        except ImportError:
            self.logger.error(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers"
            )
            raise ImportError(
                "sentence-transformers is required for CrossEncoderReranker. "
                "Install with: pip install sentence-transformers"
            )
        except Exception as e:
            self.logger.error(f"Failed to load reranker model: {e}")
            raise
    
    def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: Optional[int] = None,
    ) -> List[RerankerResult]:
        """
        Rerank documents using cross-encoder.
        
        Args:
            query: Search query
            documents: List of document texts
            top_k: Number of top results (None = all)
            
        Returns:
            List of RerankerResult sorted by score (highest first)
        """
        if not documents:
            return []
        
        self._ensure_initialized()
        
        # Create query-document pairs
        pairs = [(query, doc) for doc in documents]
        
        # Get scores from cross-encoder
        try:
            scores = self._model.predict(
                pairs,
                batch_size=self.batch_size,
                show_progress_bar=False,
            )
        except Exception as e:
            self.logger.error(f"Reranking failed: {e}")
            # Return documents in original order with zero scores
            return [
                RerankerResult(text=doc, score=0.0, original_index=i)
                for i, doc in enumerate(documents)
            ][:top_k]
        
        # Create results with scores
        results = [
            RerankerResult(
                text=doc,
                score=float(score),
                original_index=i,
            )
            for i, (doc, score) in enumerate(zip(documents, scores))
        ]
        
        # Sort by score descending
        results.sort(key=lambda x: x.score, reverse=True)
        
        # Apply top_k limit
        if top_k is not None:
            results = results[:top_k]
        
        return results
    
    def get_scores(self, query: str, documents: List[str]) -> List[float]:
        """
        Get raw relevance scores without creating RerankerResult objects.
        
        Args:
            query: Search query
            documents: List of document texts
            
        Returns:
            List of scores (same order as input documents)
        """
        if not documents:
            return []
        
        self._ensure_initialized()
        
        pairs = [(query, doc) for doc in documents]
        
        try:
            scores = self._model.predict(
                pairs,
                batch_size=self.batch_size,
                show_progress_bar=False,
            )
            return [float(s) for s in scores]
        except Exception as e:
            self.logger.error(f"Scoring failed: {e}")
            return [0.0] * len(documents)


# Convenience function
def get_reranker(
    model: str = "balanced",
    device: str = "cpu",
) -> CrossEncoderReranker:
    """
    Get a reranker instance.
    
    Args:
        model: Model preset ("fast", "balanced", "quality") or HuggingFace model name
        device: Device to run on
        
    Returns:
        CrossEncoderReranker instance
    """
    return CrossEncoderReranker(model_name=model, device=device)

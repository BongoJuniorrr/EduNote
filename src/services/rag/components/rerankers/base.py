# -*- coding: utf-8 -*-
"""
Base Reranker
=============

Base classes for reranker components.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class RerankerResult:
    """Result from reranking operation."""
    text: str
    score: float
    original_index: int
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseReranker(ABC):
    """
    Abstract base class for rerankers.
    
    Rerankers take a query and a list of candidate documents,
    and return them reordered by relevance.
    """
    
    name: str = "base_reranker"
    
    @abstractmethod
    def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: Optional[int] = None,
    ) -> List[RerankerResult]:
        """
        Rerank documents by relevance to query.
        
        Args:
            query: The search query
            documents: List of document texts to rerank
            top_k: Number of top results to return (None = all)
            
        Returns:
            List of RerankerResult sorted by relevance (highest first)
        """
        pass
    
    def rerank_with_metadata(
        self,
        query: str,
        documents: List[Tuple[str, Dict[str, Any]]],
        top_k: Optional[int] = None,
    ) -> List[RerankerResult]:
        """
        Rerank documents with associated metadata.
        
        Args:
            query: The search query
            documents: List of (text, metadata) tuples
            top_k: Number of top results to return
            
        Returns:
            List of RerankerResult with preserved metadata
        """
        texts = [doc[0] for doc in documents]
        metadata_list = [doc[1] for doc in documents]
        
        results = self.rerank(query, texts, top_k)
        
        # Attach original metadata
        for result in results:
            if result.original_index < len(metadata_list):
                result.metadata.update(metadata_list[result.original_index])
        
        return results

# -*- coding: utf-8 -*-
"""
VGU Course RAG Tool
===================

RAG tool wrapper for VGU Course pipeline with citation support.
"""

from typing import Any, Dict, List, Optional

from src.logging import get_logger
from src.services.rag.factory import get_pipeline


class VGURAGTool:
    """
    RAG tool for VGU Course pipeline.
    
    Provides a simple interface for querying the VGU Course pipeline
    with automatic citation formatting.
    
    Example:
        tool = VGURAGTool(kb_name="calculus_textbook")
        result = await tool.search("derivative definition")
        print(result["answer"])
        for citation in result["citations"]:
            print(f"  - {citation}")
    """
    
    def __init__(
        self,
        kb_name: str,
        kb_base_dir: Optional[str] = None,
        enable_reranker: bool = True,
        **kwargs,
    ):
        """
        Initialize VGU RAG Tool.
        
        Args:
            kb_name: Knowledge base name
            kb_base_dir: Base directory for knowledge bases
            enable_reranker: Enable cross-encoder reranking
            **kwargs: Additional arguments for pipeline
        """
        self.logger = get_logger("VGURAGTool")
        self.kb_name = kb_name
        
        # Initialize pipeline
        self._pipeline = get_pipeline(
            "vgu_course",
            kb_base_dir=kb_base_dir,
            enable_reranker=enable_reranker,
            **kwargs,
        )
    
    async def search(
        self,
        query: str,
        mode: str = "hybrid",
        only_need_context: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Search the knowledge base.
        
        Args:
            query: Search query
            mode: Search mode (hybrid, local, global, naive)
            only_need_context: Return only context without LLM answer
            **kwargs: Additional arguments
            
        Returns:
            Search result with answer and citations
        """
        result = await self._pipeline.search(
            query=query,
            kb_name=self.kb_name,
            mode=mode,
            only_need_context=only_need_context,
            **kwargs,
        )
        
        return result
    
    async def get_context(
        self,
        query: str,
        mode: str = "hybrid",
        **kwargs,
    ) -> str:
        """
        Get retrieval context without LLM generation.
        
        Args:
            query: Search query
            mode: Search mode
            **kwargs: Additional arguments
            
        Returns:
            Retrieved context string
        """
        result = await self.search(
            query=query,
            mode=mode,
            only_need_context=True,
            **kwargs,
        )
        return result.get("content", "")
    
    def format_citations(self, result: Dict[str, Any]) -> str:
        """
        Format citations from search result.
        
        Args:
            result: Search result dictionary
            
        Returns:
            Formatted citations string
        """
        citations = result.get("citations", [])
        if not citations:
            return ""
        
        lines = ["**Sources:**"]
        for i, c in enumerate(citations, 1):
            doc_name = c.get("doc_name", "Unknown")
            page_start = c.get("page_start", 0)
            page_end = c.get("page_end", 0)
            section = c.get("section_path", "")
            
            if page_start == page_end:
                page_info = f"p.{page_start}"
            else:
                page_info = f"pp.{page_start}-{page_end}"
            
            if section:
                lines.append(f"{i}. [{doc_name}] {section}, {page_info}")
            else:
                lines.append(f"{i}. [{doc_name}] {page_info}")
        
        return "\n".join(lines)

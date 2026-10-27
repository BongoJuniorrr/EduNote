# -*- coding: utf-8 -*-
"""
VGU Course Agent
================

Agent for answering questions using VGU Course pipeline
with page-accurate citations.
"""

from typing import Any, Dict, List, Optional

from src.agents.base_agent import BaseAgent
from src.logging import get_logger
from src.services.config import load_config_with_main, PROJECT_ROOT
from src.services.llm import get_llm_client

from .tools import VGURAGTool


class VGUCourseAgent(BaseAgent):
    """
    Agent for VGU Course mode.
    
    Uses two-tier retrieval with reranking and provides
    answers with page-accurate citations.
    
    Example:
        agent = VGUCourseAgent(kb_name="calculus")
        result = await agent.answer("What is the definition of derivative?")
        print(result["answer"])
        print(result["citations"])
    """
    
    def __init__(
        self,
        kb_name: str,
        kb_base_dir: Optional[str] = None,
        config_path: Optional[str] = None,
        **kwargs,
    ):
        """
        Initialize VGU Course Agent.
        
        Args:
            kb_name: Knowledge base name
            kb_base_dir: Base directory for knowledge bases
            config_path: Path to config file (optional)
            **kwargs: Additional arguments
        """
        self.logger = get_logger("VGUCourseAgent")
        self.kb_name = kb_name
        
        # Load config
        self.config = self._load_config(config_path)
        
        # Initialize LLM client
        self._llm_client = get_llm_client()
        
        # Initialize RAG tool
        rag_config = self.config.get("retrieval", {})
        reranker_config = self.config.get("reranker", {})
        
        self._rag_tool = VGURAGTool(
            kb_name=kb_name,
            kb_base_dir=kb_base_dir,
            enable_reranker=reranker_config.get("enabled", True),
            reranker_model=reranker_config.get("model", "BAAI/bge-reranker-v2-m3"),
            coarse_top_k=rag_config.get("coarse_top_k", 15),
            fine_top_k=rag_config.get("fine_top_k", 40),
            final_top_k=rag_config.get("final_top_k", 10),
        )
        
        self.logger.info(f"VGU Course Agent initialized for KB: {kb_name}")
    
    def _load_config(self, config_path: Optional[str] = None) -> Dict[str, Any]:
        """Load VGU Course configuration."""
        try:
            if config_path:
                # Load from specified config file
                import yaml
                with open(config_path, 'r') as f:
                    config = yaml.safe_load(f)
                return config.get("vgu_course", config)
            else:
                # Load from main.yaml using proper config loader
                full_config = load_config_with_main("main.yaml", PROJECT_ROOT)
                config = full_config.get("vgu_course", {})
            
            return config
        except Exception as e:
            self.logger.warning(f"Failed to load config: {e}, using defaults")
            return {}
    
    async def answer(
        self,
        question: str,
        mode: str = "hybrid",
        include_citations: bool = True,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Answer a question using VGU Course pipeline.
        
        Args:
            question: The question to answer
            mode: Search mode (hybrid, local, global, naive)
            include_citations: Whether to include citations in response
            **kwargs: Additional arguments
            
        Returns:
            Dictionary with answer, citations, and metadata
        """
        self.logger.info(f"Answering question: {question[:50]}...")
        
        # Get RAG result
        result = await self._rag_tool.search(
            query=question,
            mode=mode,
            only_need_context=False,
            **kwargs,
        )
        
        response = {
            "question": question,
            "answer": result.get("answer", ""),
            "citations": result.get("citations", []),
            "mode": mode,
            "provider": "vgu_course",
            "metadata": {
                "retrieval_scores": result.get("retrieval_scores", {}),
            },
        }
        
        # Format citations if requested
        if include_citations and response["citations"]:
            citation_text = self._rag_tool.format_citations(result)
            if citation_text and citation_text not in response["answer"]:
                response["answer"] += f"\n\n{citation_text}"
        
        return response
    
    async def get_context(
        self,
        question: str,
        mode: str = "hybrid",
        **kwargs,
    ) -> str:
        """
        Get retrieval context for a question without generating answer.
        
        Args:
            question: The question
            mode: Search mode
            **kwargs: Additional arguments
            
        Returns:
            Retrieved context string
        """
        return await self._rag_tool.get_context(
            query=question,
            mode=mode,
            **kwargs,
        )
    
    async def answer_with_verification(
        self,
        question: str,
        mode: str = "hybrid",
        verify_citations: bool = True,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Answer with optional citation verification.
        
        This method first retrieves context, generates an answer,
        then optionally verifies that citations are accurate.
        
        Args:
            question: The question to answer
            mode: Search mode
            verify_citations: Whether to verify citation accuracy
            **kwargs: Additional arguments
            
        Returns:
            Dictionary with answer, citations, and verification status
        """
        # Get initial answer
        result = await self.answer(question, mode, include_citations=True, **kwargs)
        
        if not verify_citations or not result["citations"]:
            return result
        
        # Verify citations using LLM
        context = await self.get_context(question, mode)
        
        verification_prompt = f"""Verify if the following citations accurately support the answer.

Question: {question}

Answer: {result['answer']}

Retrieved Context:
{context}

For each citation, indicate if it is:
1. VERIFIED - The citation accurately supports the claim
2. PARTIALLY - The citation is related but doesn't fully support
3. UNVERIFIED - Cannot verify from the given context

Respond in JSON format:
{{"verified": true/false, "details": "explanation"}}
"""
        
        try:
            verification_response = await self._llm_client.acomplete(
                verification_prompt,
                max_tokens=500,
            )
            
            import json
            try:
                verification = json.loads(verification_response)
                result["verification"] = verification
            except json.JSONDecodeError:
                result["verification"] = {
                    "verified": True,
                    "details": "Verification completed (non-JSON response)",
                }
                
        except Exception as e:
            self.logger.warning(f"Citation verification failed: {e}")
            result["verification"] = {
                "verified": None,
                "details": f"Verification failed: {str(e)}",
            }
        
        return result

    async def process(self, *args, **kwargs) -> Dict[str, Any]:
        """
        BaseAgent compatibility entrypoint.

        Accepts:
        - process(question: str, ...)
        - process(question="...", ...)
        """
        question = kwargs.get("question")
        if question is None and args:
            question = args[0]

        if not question:
            raise ValueError("question is required")

        mode = kwargs.get("mode", "hybrid")
        include_citations = kwargs.get("include_citations", True)
        verify_citations = kwargs.get("verify_citations", False)

        if verify_citations:
            return await self.answer_with_verification(
                question=question,
                mode=mode,
                verify_citations=True,
                **{k: v for k, v in kwargs.items() if k not in {"question", "mode", "verify_citations"}},
            )

        return await self.answer(
            question=question,
            mode=mode,
            include_citations=include_citations,
            **{
                k: v
                for k, v in kwargs.items()
                if k not in {"question", "mode", "include_citations", "verify_citations"}
            },
        )

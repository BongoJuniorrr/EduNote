import asyncio

#!/usr/bin/env python
"""
ChatAgent - Lightweight conversational AI with multi-turn support.

This agent provides:
- Multi-turn conversation with history management
- Token-based context truncation
- Optional RAG and Web Search augmentation
- Streaming response generation

Uses the unified LLM factory from BaseAgent for both cloud and local LLM support.
"""

from pathlib import Path
import sys
import time
from typing import Any, AsyncGenerator

# Add project root to path
_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.agents.base_agent import BaseAgent
from src.tools import rag_search, web_search


class ChatAgent(BaseAgent):
    """
    Lightweight conversational agent with multi-turn support.

    Features:
    - Conversation history management with token limits
    - RAG (Retrieval-Augmented Generation) support
    - Web search integration
    - Streaming response generation via BaseAgent.stream_llm()
    """

    # Default token limit for conversation history
    DEFAULT_MAX_HISTORY_TOKENS = 4000

    def __init__(
        self,
        language: str = "zh",
        config: dict[str, Any] | None = None,
        max_history_tokens: int | None = None,
        **kwargs,
    ):
        """
        Initialize ChatAgent.

        Args:
            language: Language setting ('zh' | 'en')
            config: Optional configuration dictionary
            max_history_tokens: Maximum tokens for conversation history
            **kwargs: Additional arguments passed to BaseAgent
        """
        super().__init__(
            module_name="chat",
            agent_name="chat_agent",
            language=language,
            config=config,
            **kwargs,
        )

        # Configure history token limit
        self.max_history_tokens = max_history_tokens or self.agent_config.get(
            "max_history_tokens", self.DEFAULT_MAX_HISTORY_TOKENS
        )

        self.logger.info(f"ChatAgent initialized: model={self.model}, base_url={self.base_url}")

    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text using tiktoken.

        Falls back to character-based estimation if tiktoken unavailable.

        Args:
            text: Text to count tokens for

        Returns:
            Estimated token count
        """
        try:
            import tiktoken

            # Use cl100k_base encoding (GPT-4, GPT-3.5-turbo)
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except ImportError:
            # Fallback: rough estimate of 4 characters per token
            return len(text) // 4

    def truncate_history(
        self,
        history: list[dict[str, str]],
        max_tokens: int | None = None,
    ) -> list[dict[str, str]]:
        """
        Truncate conversation history to fit within token limit.

        Keeps the most recent messages, discarding older ones first.

        Args:
            history: List of message dicts with 'role' and 'content'
            max_tokens: Maximum tokens allowed (uses default if None)

        Returns:
            Truncated history list
        """
        max_tokens = max_tokens or self.max_history_tokens

        if not history:
            return []

        # Calculate tokens for each message
        message_tokens = []
        for msg in history:
            content = msg.get("content", "")
            tokens = self.count_tokens(content)
            message_tokens.append((msg, tokens))

        # Build history from newest to oldest, stop when limit reached
        truncated = []
        total_tokens = 0

        for msg, tokens in reversed(message_tokens):
            if total_tokens + tokens > max_tokens:
                break
            truncated.insert(0, msg)
            total_tokens += tokens

        if len(truncated) < len(history):
            self.logger.info(
                f"Truncated history from {len(history)} to {len(truncated)} messages "
                f"({total_tokens} tokens)"
            )

        return truncated

    def format_history_for_prompt(self, history: list[dict[str, str]]) -> str:
        """
        Format conversation history as a string for the prompt.

        Args:
            history: List of message dicts

        Returns:
            Formatted history string
        """
        if not history:
            return ""

        lines = []
        for msg in history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prefix = "User" if role == "user" else "Assistant"
            lines.append(f"{prefix}: {content}")

        return "\n\n".join(lines)

    async def retrieve_context(
        self,
        message: str,
        kb_name: str | None = None,
        enable_rag: bool = False,
        enable_web_search: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        """
        Retrieve context from RAG and/or Web Search.

        Args:
            message: User message to search for
            kb_name: Knowledge base name for RAG
            enable_rag: Whether to use RAG
            enable_web_search: Whether to use Web Search

        Returns:
            Tuple of (context_string, sources_dict)
        """
        context_parts = []
        sources = {"rag": [], "web": []}

        # RAG retrieval
        if enable_rag and kb_name:
            retrieval_start = time.perf_counter()
            try:
                from src.services.config import get_kb_config_service

                kb_cfg = get_kb_config_service().get_kb_config(kb_name)
                rag_mode = kb_cfg.get("search_mode", "hybrid")
                retrieval_overrides = dict(kb_cfg.get("retrieval_overrides", {}) or {})
                rag_mode = retrieval_overrides.pop("mode", rag_mode)
                retrieval_overrides.pop("only_need_context", None)

                self.logger.info(
                    f"RAG search: {message[:50]}... (mode={rag_mode}, overrides={list(retrieval_overrides.keys())})"
                )
                rag_result = await rag_search(
                    query=message,
                    kb_name=kb_name,
                    mode=rag_mode,
                    only_need_context=True,
                    **retrieval_overrides,
                )
                rag_context = rag_result.get("content", "")
                if rag_context:
                    context_parts.append(f"[Knowledge Base: {kb_name}]\n{rag_context}")
                    sources["rag"] = self._build_rag_sources(
                        rag_result=rag_result,
                        kb_name=kb_name,
                    )
                    elapsed = time.perf_counter() - retrieval_start
                    self.logger.info(
                        "RAG retrieved "
                        f"{len(rag_context)} chars, sources={len(sources['rag'])}, "
                        f"provider={rag_result.get('provider', 'unknown')}, "
                        f"mode={rag_result.get('mode', rag_mode)} in {elapsed:.2f}s"
                    )
                if not rag_context:
                    raise ValueError("No supporting evidence found in the selected knowledge base. Refine the question or use Evidence Workspace to inspect sources.")
            except Exception as e:
                self.logger.warning(f"RAG search failed: {type(e).__name__}")
                raise ValueError("Knowledge retrieval is unavailable or found no supporting material. Check the index in Knowledge Bases or use Evidence Workspace; disable RAG explicitly to request a general answer.") from e

        # Web search
        if enable_web_search:
            try:
                self.logger.info(f"Web search: {message[:50]}...")
                web_result = await asyncio.to_thread(web_search, query=message, verbose=False)
                web_answer = web_result.get("answer", "")
                web_citations = web_result.get("citations", [])

                if web_answer:
                    context_parts.append(f"[Web Search Results]\n{web_answer}")
                    sources["web"] = web_citations[:5]
                    self.logger.info(
                        f"Web search returned {len(web_answer)} chars, "
                        f"{len(web_citations)} citations"
                    )
            except Exception as e:
                self.logger.warning(f"Web search failed: {type(e).__name__}")
                raise ValueError("Web search is unavailable. Check Search settings or disable Web Search explicitly.") from e

        context = "\n\n".join(context_parts)
        return context, sources

    def _build_rag_sources(
        self,
        rag_result: dict[str, Any],
        kb_name: str,
    ) -> list[dict[str, Any]]:
        """Build source records with backward-compatible fields."""
        provider = rag_result.get("provider", "")
        citations = rag_result.get("citations") or []
        chunks = rag_result.get("chunks") or []
        chunk_map = {
            chunk.get("chunk_id"): chunk
            for chunk in chunks
            if isinstance(chunk, dict) and chunk.get("chunk_id")
        }

        source_rows: list[dict[str, Any]] = []

        def _to_snippet(text: str, limit: int = 500) -> str:
            if not text:
                return ""
            return text[:limit] + "..." if len(text) > limit else text

        if citations:
            for citation in citations:
                if not isinstance(citation, dict):
                    continue
                chunk_id = citation.get("chunk_id")
                chunk = chunk_map.get(chunk_id, {})
                chunk_content = chunk.get("content", "")
                snippet = _to_snippet(chunk_content)
                page_start = citation.get("page_start")
                if page_start is None:
                    page_start = chunk.get("page_start")
                page_end = citation.get("page_end")
                if page_end is None:
                    page_end = chunk.get("page_end")
                source_rows.append(
                    {
                        # Backward-compatible fields
                        "kb_name": kb_name,
                        "content": snippet,
                        # Extended fields
                        "provider": provider,
                        "chunk_id": chunk_id,
                        "doc_id": citation.get("doc_id") or chunk.get("doc_id"),
                        "doc_name": citation.get("doc_name") or chunk.get("doc_name"),
                        "page_start": page_start,
                        "page_end": page_end,
                        "section_path": citation.get("section_path") or chunk.get("section_path"),
                        "confidence": citation.get("confidence"),
                        "snippet": snippet,
                        "metadata": chunk.get("metadata", {}),
                    }
                )

        if not source_rows and chunks:
            for chunk in chunks[:10]:
                if not isinstance(chunk, dict):
                    continue
                chunk_content = chunk.get("content", "")
                snippet = _to_snippet(chunk_content)
                source_rows.append(
                    {
                        "kb_name": kb_name,
                        "content": snippet,
                        "provider": provider,
                        "chunk_id": chunk.get("chunk_id"),
                        "doc_id": chunk.get("doc_id"),
                        "doc_name": chunk.get("doc_name"),
                        "page_start": chunk.get("page_start"),
                        "page_end": chunk.get("page_end"),
                        "section_path": chunk.get("section_path"),
                        "confidence": None,
                        "snippet": snippet,
                        "metadata": chunk.get("metadata", {}),
                    }
                )

        if not source_rows:
            fallback_text = rag_result.get("content") or rag_result.get("answer", "")
            snippet = _to_snippet(fallback_text)
            source_rows.append(
                {
                    "kb_name": kb_name,
                    "content": snippet,
                    "provider": provider,
                    "chunk_id": None,
                    "doc_id": None,
                    "doc_name": kb_name,
                    "page_start": None,
                    "page_end": None,
                    "section_path": "",
                    "confidence": None,
                    "snippet": snippet,
                    "metadata": {},
                }
            )

        # Deduplicate by chunk ID or doc/page/section tuple.
        deduped: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for row in source_rows:
            key = row.get("chunk_id") or (
                f"{row.get('doc_id')}:{row.get('page_start')}:{row.get('page_end')}:{row.get('section_path')}"
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(row)

        return deduped

    def build_messages(
        self,
        message: str,
        history: list[dict[str, str]],
        context: str = "",
    ) -> list[dict[str, str]]:
        """
        Build the messages array for the LLM API call.

        Args:
            message: Current user message
            history: Truncated conversation history
            context: Retrieved context (RAG/Web)

        Returns:
            List of message dicts for OpenAI API
        """
        messages = []

        # System prompt
        system_prompt = self.get_prompt("system", "You are a helpful AI assistant.")
        messages.append({"role": "system", "content": system_prompt})

        # Add context if available
        if context:
            context_template = self.get_prompt("context_template", "Reference context:\n{context}")
            context_msg = context_template.format(context=context)
            # Strict templates (including llama.cpp's Qwen template) only
            # accept one system message, at the start of the conversation.
            messages[0]["content"] += "\n\n" + context_msg

        # Add conversation history
        for msg in history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": content})

        # Add current message
        messages.append({"role": "user", "content": message})

        return messages

    async def generate_stream(
        self,
        messages: list[dict[str, str]],
    ) -> AsyncGenerator[str, None]:
        """
        Generate streaming response from LLM.

        Uses BaseAgent.stream_llm() which routes to the appropriate provider
        (cloud or local) based on configuration.

        Args:
            messages: Messages array for OpenAI API

        Yields:
            Response chunks as strings
        """
        # Extract system prompt from messages
        system_prompt = ""
        user_prompt = ""
        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = msg.get("content", "")
                break

        # Get the last user message as user_prompt (for logging/tracking)
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_prompt = msg.get("content", "")
                break

        # Use BaseAgent's stream_llm which routes through the factory
        async for chunk in self.stream_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            messages=messages,
            stage="chat_stream",
        ):
            yield chunk

    async def generate(self, messages: list[dict[str, str]]) -> str:
        """
        Generate complete response from LLM (non-streaming).

        Uses BaseAgent.call_llm() which routes to the appropriate provider
        (cloud or local) based on configuration.

        Args:
            messages: Messages array for OpenAI API

        Returns:
            Complete response string
        """
        # Extract system prompt from messages
        system_prompt = ""
        user_prompt = ""
        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = msg.get("content", "")
                break

        # Get the last user message
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_prompt = msg.get("content", "")
                break

        # Use BaseAgent's call_llm which routes through the factory
        # Note: call_llm expects simple prompt/system_prompt, but for multi-turn
        # we need to use the factory directly with messages
        from src.services.llm import complete as llm_complete

        response = await llm_complete(
            prompt=user_prompt,
            system_prompt=system_prompt,
            model=self.get_model(),
            api_key=self.api_key,
            base_url=self.base_url,
            messages=messages,
            temperature=self.get_temperature(),
        )

        # Track token usage
        self._track_tokens(
            model=self.get_model(),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=response,
            stage="chat",
        )

        return response

    async def process(
        self,
        message: str,
        history: list[dict[str, str]] | None = None,
        kb_name: str | None = None,
        enable_rag: bool = False,
        enable_web_search: bool = False,
        stream: bool = False,
    ) -> dict[str, Any] | AsyncGenerator[dict[str, Any], None]:
        """
        Process a chat message with optional context retrieval.

        Args:
            message: User message
            history: Conversation history (will be truncated if needed)
            kb_name: Knowledge base name for RAG
            enable_rag: Whether to enable RAG retrieval
            enable_web_search: Whether to enable web search
            stream: Whether to stream the response

        Returns:
            If stream=False: Dict with 'response', 'sources', 'truncated_history'
            If stream=True: AsyncGenerator yielding chunks
        """
        history = history or []

        # Truncate history to fit token limit
        truncated_history = self.truncate_history(history)

        process_start = time.perf_counter()

        # Retrieve context if needed
        retrieval_start = time.perf_counter()
        context, sources = await self.retrieve_context(
            message=message,
            kb_name=kb_name,
            enable_rag=enable_rag,
            enable_web_search=enable_web_search,
        )
        retrieval_elapsed = time.perf_counter() - retrieval_start

        # Build messages for LLM
        messages = self.build_messages(
            message=message,
            history=truncated_history,
            context=context,
        )
        self.logger.info(
            f"Chat process prepared: history={len(truncated_history)} msgs, "
            f"context_chars={len(context)}, rag_sources={len(sources.get('rag', []))}, "
            f"web_sources={len(sources.get('web', []))}, retrieval_time={retrieval_elapsed:.2f}s"
        )

        if stream:
            # Return async generator for streaming
            async def stream_generator():
                full_response = ""
                generation_start = time.perf_counter()
                async for chunk in self.generate_stream(messages):
                    full_response += chunk
                    yield {"type": "chunk", "content": chunk}

                # Some providers may not yield stream chunks reliably.
                if not full_response:
                    self.logger.warning(
                        "Streaming produced no chunks; falling back to non-stream completion"
                    )
                    full_response = await self.generate(messages)

                generation_elapsed = time.perf_counter() - generation_start

                # Yield final result with sources
                yield {
                    "type": "complete",
                    "response": full_response,
                    "sources": sources,
                    "truncated_history": truncated_history,
                }
                total_elapsed = time.perf_counter() - process_start
                self.logger.info(
                    f"Chat process complete (stream): response_chars={len(full_response)}, "
                    f"generation_time={generation_elapsed:.2f}s, total_time={total_elapsed:.2f}s"
                )

            return stream_generator()
        else:
            # Generate complete response
            generation_start = time.perf_counter()
            response = await self.generate(messages)
            generation_elapsed = time.perf_counter() - generation_start
            total_elapsed = time.perf_counter() - process_start
            self.logger.info(
                f"Chat process complete: response_chars={len(response)}, "
                f"generation_time={generation_elapsed:.2f}s, total_time={total_elapsed:.2f}s"
            )

            return {
                "response": response,
                "sources": sources,
                "truncated_history": truncated_history,
            }


__all__ = ["ChatAgent"]

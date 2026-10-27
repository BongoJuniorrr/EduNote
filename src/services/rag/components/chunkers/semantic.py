# -*- coding: utf-8 -*-
"""
Semantic Chunker
================

Advanced chunker that splits documents based on TRUE semantic boundaries
using embedding similarity detection between sentences.

This is a significant improvement over simple separator-based chunking:
- Uses sentence embeddings to detect topic shifts
- Identifies natural semantic breakpoints via similarity drops
- Maintains context coherence within chunks
- Preserves document structure (headings, sections)
"""

import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple, Dict, Any

import numpy as np

from ...types import Chunk, Document
from ..base import BaseComponent


@dataclass
class SemanticSentence:
    """A sentence with its embedding and position info."""
    text: str
    start_pos: int
    end_pos: int
    embedding: Optional[np.ndarray] = None
    is_heading: bool = False
    page_num: int = 1


@dataclass
class SemanticBoundary:
    """A detected semantic boundary."""
    position: int
    similarity_drop: float
    sentence_index: int


class SemanticChunker(BaseComponent):
    """
    TRUE Semantic Chunker using Embedding Similarity.
    
    Algorithm:
    1. Split document into sentences
    2. Compute embeddings for each sentence (or sentence groups)
    3. Calculate cosine similarity between consecutive sentences
    4. Detect breakpoints where similarity drops significantly
    5. Group sentences between breakpoints into coherent chunks
    
    This approach ensures chunks contain semantically related content,
    leading to better retrieval quality.
    """

    name = "semantic_chunker"

    def __init__(
        self,
        # Chunking parameters
        target_chunk_size: int = 512,
        min_chunk_size: int = 100,
        max_chunk_size: int = 1500,
        chunk_overlap: int = 50,
        
        # Semantic detection parameters  
        similarity_threshold: float = 0.45,
        percentile_threshold: int = 25,
        window_size: int = 3,
        
        # Embedding parameters
        embedding_func: Optional[Callable] = None,
        embedding_batch_size: int = 32,
        
        # Fallback separators (used when embeddings unavailable)
        separators: List[str] = None,
    ):
        """
        Initialize semantic chunker.

        Args:
            target_chunk_size: Target chunk size in characters
            min_chunk_size: Minimum chunk size
            max_chunk_size: Maximum chunk size (hard limit)
            chunk_overlap: Overlap between chunks in characters
            
            similarity_threshold: Absolute threshold for breakpoint detection
            percentile_threshold: Percentile of similarities to use as dynamic threshold
            window_size: Number of sentences to average for similarity (smoothing)
            
            embedding_func: Async function to generate embeddings
            embedding_batch_size: Batch size for embedding generation
            
            separators: Fallback separators for non-semantic chunking
        """
        super().__init__()
        
        # Chunking params
        self.target_chunk_size = target_chunk_size
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.chunk_overlap = chunk_overlap
        
        # Semantic params
        self.similarity_threshold = similarity_threshold
        self.percentile_threshold = percentile_threshold
        self.window_size = window_size
        
        # Embedding
        self.embedding_func = embedding_func
        self.embedding_batch_size = embedding_batch_size
        self._embed_client = None
        
        # Fallback
        self.separators = separators or ["\n\n", "\n", ". ", " "]
        
        # Patterns for sentence splitting
        self._sentence_pattern = re.compile(
            r'(?<=[.!?])\s+(?=[A-Z])|(?<=[.!?])\n+|(?<=\n\n)'
        )
        self._heading_pattern = re.compile(
            r'^(?:#{1,6}\s+|(?:\d+\.)+\s+|Chapter\s+\d+|Section\s+\d+)',
            re.IGNORECASE | re.MULTILINE
        )

    # =========================================================================
    # Embedding Management
    # =========================================================================
    
    def _get_embedding_client(self):
        """Get embedding client (lazy load)."""
        if self._embed_client is None:
            try:
                from src.services.embedding import get_embedding_client
                self._embed_client = get_embedding_client()
            except ImportError:
                self.logger.warning("Embedding client not available")
        return self._embed_client
    
    async def _compute_embeddings(self, texts: List[str]) -> List[np.ndarray]:
        """
        Compute embeddings for a list of texts.
        
        Args:
            texts: List of text strings
            
        Returns:
            List of embedding vectors
        """
        if not texts:
            return []
        
        # Use provided embedding function
        if self.embedding_func:
            try:
                embeddings = await self.embedding_func(texts)
                return [np.array(e) for e in embeddings]
            except Exception as e:
                self.logger.warning(f"Embedding function failed: {e}")
        
        # Try default embedding client
        client = self._get_embedding_client()
        if client:
            try:
                # Batch processing
                all_embeddings = []
                for i in range(0, len(texts), self.embedding_batch_size):
                    batch = texts[i:i + self.embedding_batch_size]
                    batch_embeddings = await client.embed(batch)
                    all_embeddings.extend([np.array(e) for e in batch_embeddings])
                return all_embeddings
            except Exception as e:
                self.logger.warning(f"Embedding client failed: {e}")
        
        # Return empty (will use fallback chunking)
        return []
    
    # =========================================================================
    # Sentence Processing
    # =========================================================================
    
    def _split_into_sentences(
        self, 
        text: str, 
        page_mapping: Optional[Dict[int, int]] = None
    ) -> List[SemanticSentence]:
        """
        Split text into sentences with position tracking.
        
        Args:
            text: Input text
            page_mapping: Optional dict mapping char position to page number
            
        Returns:
            List of SemanticSentence objects
        """
        sentences = []
        
        # Split by various delimiters
        parts = re.split(r'(?<=[.!?])\s+|(?<=\n\n)', text)
        
        current_pos = 0
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            # Find actual position in original text
            start_pos = text.find(part, current_pos)
            if start_pos == -1:
                start_pos = current_pos
            end_pos = start_pos + len(part)
            
            # Check if this is a heading
            is_heading = bool(self._heading_pattern.match(part))
            
            # Determine page number
            page_num = 1
            if page_mapping:
                for pos, page in sorted(page_mapping.items()):
                    if pos <= start_pos:
                        page_num = page
            
            sentences.append(SemanticSentence(
                text=part,
                start_pos=start_pos,
                end_pos=end_pos,
                is_heading=is_heading,
                page_num=page_num,
            ))
            
            current_pos = end_pos
        
        return sentences
    
    def _cosine_similarity(self, v1: np.ndarray, v2: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(v1, v2) / (norm1 * norm2))
    
    def _compute_similarities(
        self, 
        sentences: List[SemanticSentence]
    ) -> List[float]:
        """
        Compute similarities between consecutive sentences.
        
        Uses windowed averaging for smoother boundary detection.
        
        Args:
            sentences: List of sentences with embeddings
            
        Returns:
            List of similarity scores (length = len(sentences) - 1)
        """
        if len(sentences) < 2:
            return []
        
        similarities = []
        
        for i in range(len(sentences) - 1):
            # Window averaging
            left_start = max(0, i - self.window_size + 1)
            right_end = min(len(sentences), i + self.window_size + 1)
            
            # Average embeddings in windows
            left_embeddings = [
                s.embedding for s in sentences[left_start:i+1] 
                if s.embedding is not None
            ]
            right_embeddings = [
                s.embedding for s in sentences[i+1:right_end]
                if s.embedding is not None
            ]
            
            if not left_embeddings or not right_embeddings:
                similarities.append(1.0)  # No breakpoint if missing embeddings
                continue
            
            left_avg = np.mean(left_embeddings, axis=0)
            right_avg = np.mean(right_embeddings, axis=0)
            
            sim = self._cosine_similarity(left_avg, right_avg)
            similarities.append(sim)
        
        return similarities
    
    def _detect_breakpoints(
        self,
        sentences: List[SemanticSentence],
        similarities: List[float],
    ) -> List[int]:
        """
        Detect semantic breakpoints based on similarity drops.
        
        Args:
            sentences: List of sentences
            similarities: Similarity scores between consecutive sentences
            
        Returns:
            List of sentence indices where breaks should occur
        """
        if not similarities:
            return []
        
        breakpoints = []
        
        # Calculate dynamic threshold
        sim_array = np.array(similarities)
        dynamic_threshold = np.percentile(sim_array, self.percentile_threshold)
        threshold = min(self.similarity_threshold, dynamic_threshold)
        
        for i, sim in enumerate(similarities):
            # Check for significant similarity drop
            if sim < threshold:
                breakpoints.append(i + 1)  # Break after sentence i
            
            # Always break at headings
            elif i + 1 < len(sentences) and sentences[i + 1].is_heading:
                breakpoints.append(i + 1)
        
        return breakpoints
    
    # =========================================================================
    # Chunk Assembly
    # =========================================================================
    
    def _assemble_chunks(
        self,
        sentences: List[SemanticSentence],
        breakpoints: List[int],
        source: str,
    ) -> List[Chunk]:
        """
        Assemble sentences into chunks based on breakpoints.
        
        Args:
            sentences: List of sentences
            breakpoints: Indices where chunks should break
            source: Document source path
            
        Returns:
            List of Chunks
        """
        if not sentences:
            return []
        
        chunks = []
        breakpoints = sorted(set([0] + breakpoints + [len(sentences)]))
        
        for i in range(len(breakpoints) - 1):
            start_idx = breakpoints[i]
            end_idx = breakpoints[i + 1]
            
            # Get sentences for this chunk
            chunk_sentences = sentences[start_idx:end_idx]
            if not chunk_sentences:
                continue
            
            # Combine text
            chunk_text = " ".join(s.text for s in chunk_sentences)
            
            # Check size constraints
            if len(chunk_text) > self.max_chunk_size:
                # Split oversized chunk
                sub_chunks = self._split_oversized(chunk_sentences, source)
                chunks.extend(sub_chunks)
            elif len(chunk_text) >= self.min_chunk_size:
                # Valid chunk
                page_start = min(s.page_num for s in chunk_sentences)
                page_end = max(s.page_num for s in chunk_sentences)
                
                chunks.append(Chunk(
                    content=chunk_text.strip(),
                    chunk_type="semantic",
                    metadata={
                        "start_pos": chunk_sentences[0].start_pos,
                        "end_pos": chunk_sentences[-1].end_pos,
                        "source": source,
                        "page_start": page_start,
                        "page_end": page_end,
                        "sentence_count": len(chunk_sentences),
                        "has_heading": any(s.is_heading for s in chunk_sentences),
                    },
                ))
            else:
                # Too small - merge with previous or next
                if chunks:
                    # Merge with previous
                    prev_chunk = chunks[-1]
                    new_content = prev_chunk.content + " " + chunk_text.strip()
                    if len(new_content) <= self.max_chunk_size:
                        prev_chunk.content = new_content
                        prev_chunk.metadata["end_pos"] = chunk_sentences[-1].end_pos
                        prev_chunk.metadata["page_end"] = max(
                            prev_chunk.metadata.get("page_end", 1),
                            max(s.page_num for s in chunk_sentences)
                        )
        
        return chunks
    
    def _split_oversized(
        self,
        sentences: List[SemanticSentence],
        source: str,
    ) -> List[Chunk]:
        """Split oversized chunk into smaller ones."""
        chunks = []
        current_sentences = []
        current_length = 0
        
        for sentence in sentences:
            sentence_len = len(sentence.text)
            
            if current_length + sentence_len > self.target_chunk_size and current_sentences:
                # Create chunk from accumulated sentences
                chunk_text = " ".join(s.text for s in current_sentences)
                page_start = min(s.page_num for s in current_sentences)
                page_end = max(s.page_num for s in current_sentences)
                
                chunks.append(Chunk(
                    content=chunk_text.strip(),
                    chunk_type="semantic",
                    metadata={
                        "start_pos": current_sentences[0].start_pos,
                        "end_pos": current_sentences[-1].end_pos,
                        "source": source,
                        "page_start": page_start,
                        "page_end": page_end,
                        "sentence_count": len(current_sentences),
                    },
                ))
                
                # Keep last sentence for overlap
                current_sentences = [current_sentences[-1]] if current_sentences else []
                current_length = len(current_sentences[0].text) if current_sentences else 0
            
            current_sentences.append(sentence)
            current_length += sentence_len + 1  # +1 for space
        
        # Add remaining sentences
        if current_sentences:
            chunk_text = " ".join(s.text for s in current_sentences)
            if len(chunk_text) >= self.min_chunk_size:
                page_start = min(s.page_num for s in current_sentences)
                page_end = max(s.page_num for s in current_sentences)
                
                chunks.append(Chunk(
                    content=chunk_text.strip(),
                    chunk_type="semantic",
                    metadata={
                        "start_pos": current_sentences[0].start_pos,
                        "end_pos": current_sentences[-1].end_pos,
                        "source": source,
                        "page_start": page_start,
                        "page_end": page_end,
                        "sentence_count": len(current_sentences),
                    },
                ))
        
        return chunks
    
    # =========================================================================
    # Fallback Chunking
    # =========================================================================

    @staticmethod
    def _align_to_word_start(text: str, pos: int) -> int:
        """Move position to the start of a word if currently inside one."""
        pos = max(0, min(pos, len(text)))
        while 0 < pos < len(text) and text[pos - 1].isalnum() and text[pos].isalnum():
            pos -= 1
        return pos

    @staticmethod
    def _align_to_word_end(text: str, pos: int, lookahead: int = 80) -> int:
        """Move position away from a mid-word split point."""
        pos = max(0, min(pos, len(text)))
        if pos <= 0 or pos >= len(text):
            return pos

        # If we're between two alnum chars, we're splitting a word.
        if text[pos - 1].isalnum() and text[pos].isalnum():
            forward = pos
            max_forward = min(len(text), pos + lookahead)
            while forward < max_forward and text[forward].isalnum():
                forward += 1
            if forward < len(text):
                return forward

            backward = pos
            while backward > 0 and text[backward - 1].isalnum():
                backward -= 1
            return backward

        return pos
    
    def _fallback_chunking(self, text: str, source: str) -> List[Chunk]:
        """
        Fallback to separator-based chunking when embeddings unavailable.
        
        Args:
            text: Input text
            source: Document source path
            
        Returns:
            List of Chunks
        """
        self.logger.info("Using fallback separator-based chunking")
        
        chunks = []
        current_pos = 0

        while current_pos < len(text):
            start_pos = self._align_to_word_start(text, current_pos)
            end_pos = min(start_pos + self.target_chunk_size, len(text))

            # Find natural break point
            if end_pos < len(text):
                for sep in self.separators:
                    search_start = max(start_pos + self.target_chunk_size - 200, start_pos)
                    sep_pos = text.rfind(sep, search_start, end_pos)
                    if sep_pos > start_pos:
                        end_pos = sep_pos + len(sep)
                        break

            end_pos = self._align_to_word_end(text, end_pos)
            if end_pos <= start_pos:
                end_pos = min(start_pos + self.target_chunk_size, len(text))

            chunk_text = text[start_pos:end_pos].strip()
            if chunk_text and len(chunk_text) >= self.min_chunk_size:
                chunks.append(
                    Chunk(
                        content=chunk_text,
                        chunk_type="text",
                        metadata={
                            "start_pos": start_pos,
                            "end_pos": end_pos,
                            "source": source,
                        },
                    )
                )

            next_pos = max(end_pos - self.chunk_overlap, 0)
            next_pos = self._align_to_word_start(text, next_pos)
            if next_pos <= start_pos:
                next_pos = end_pos

            current_pos = next_pos
            if current_pos >= len(text):
                break

        return chunks
    
    # =========================================================================
    # Main Processing
    # =========================================================================

    async def process(
        self, 
        doc: Document, 
        page_mapping: Optional[Dict[int, int]] = None,
        **kwargs
    ) -> List[Chunk]:
        """
        Chunk a document using semantic boundaries.

        Args:
            doc: Document to chunk
            page_mapping: Optional dict mapping char position to page number
            **kwargs: Additional arguments

        Returns:
            List of semantic Chunks
        """
        self.logger.info(f"Semantic chunking: {doc.file_path or 'inline'}")

        text = doc.content
        if not text:
            return []
        
        source = doc.file_path or "inline"
        
        # Step 1: Split into sentences
        sentences = self._split_into_sentences(text, page_mapping)
        self.logger.info(f"Split into {len(sentences)} sentences")
        
        if len(sentences) < 3:
            # Too few sentences for semantic analysis
            return self._fallback_chunking(text, source)
        
        # Step 2: Compute embeddings
        sentence_texts = [s.text for s in sentences]
        embeddings = await self._compute_embeddings(sentence_texts)
        
        if not embeddings or len(embeddings) != len(sentences):
            # Embeddings failed, use fallback
            return self._fallback_chunking(text, source)
        
        # Assign embeddings to sentences
        for i, emb in enumerate(embeddings):
            sentences[i].embedding = emb
        
        # Step 3: Compute similarities
        similarities = self._compute_similarities(sentences)
        self.logger.debug(f"Similarity stats: min={min(similarities):.3f}, max={max(similarities):.3f}")
        
        # Step 4: Detect breakpoints
        breakpoints = self._detect_breakpoints(sentences, similarities)
        self.logger.info(f"Detected {len(breakpoints)} semantic breakpoints")
        
        # Step 5: Assemble chunks
        chunks = self._assemble_chunks(sentences, breakpoints, source)
        
        self.logger.info(f"Created {len(chunks)} semantic chunks")
        return chunks
    
    # =========================================================================
    # Utility Methods for VGU Integration
    # =========================================================================
    
    async def chunk_content_list(
        self,
        content_items: List[Dict[str, Any]],
        doc_id: str,
        doc_name: str,
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Chunk a list of content items (from Docling/MinerU parser).
        
        This method is designed for direct integration with VGU Course Pipeline.
        
        Args:
            content_items: List of parsed content items with 'text', 'page_idx', etc.
            doc_id: Document identifier
            doc_name: Document name
            
        Returns:
            Tuple of (chunks_data, sections_data) as dicts for easy serialization
        """
        import hashlib
        
        # Build combined text with page tracking
        combined_text = []
        page_mapping = {}
        current_section = "Introduction"
        sections_info = {}
        
        current_pos = 0
        for item in content_items:
            text = item.get("text", "").strip()
            if not text:
                continue
            
            page_num = item.get("page_idx", 0) + 1  # Convert 0-indexed to 1-indexed
            page_mapping[current_pos] = page_num
            
            # Track section
            section_path = item.get("section_path") or item.get("heading") or item.get("title")
            if section_path:
                current_section = section_path
            
            if current_section not in sections_info:
                sections_info[current_section] = {
                    "page_start": page_num,
                    "page_end": page_num,
                    "item_count": 0,
                }
            sections_info[current_section]["page_end"] = max(
                sections_info[current_section]["page_end"], page_num
            )
            sections_info[current_section]["item_count"] += 1
            
            combined_text.append(text)
            current_pos += len(text) + 1  # +1 for space
        
        full_text = " ".join(combined_text)
        
        # Create Document and process
        doc = Document(content=full_text, file_path=doc_name)
        raw_chunks = await self.process(doc, page_mapping=page_mapping)
        
        # Convert to VGU-compatible format
        chunks_data = []
        for i, chunk in enumerate(raw_chunks):
            chunk_id = hashlib.md5(f"{doc_id}:{i}:{chunk.content[:50]}".encode()).hexdigest()[:12]
            
            # Determine section for this chunk
            chunk_section = "Introduction"
            for section_name, info in sections_info.items():
                page_start = chunk.metadata.get("page_start", 1)
                if info["page_start"] <= page_start <= info["page_end"]:
                    chunk_section = section_name
                    break
            
            chunks_data.append({
                "chunk_id": chunk_id,
                "content": chunk.content,
                "doc_id": doc_id,
                "doc_name": doc_name,
                "page_start": chunk.metadata.get("page_start", 1),
                "page_end": chunk.metadata.get("page_end", 1),
                "section_path": chunk_section,
                "chunk_type": chunk.chunk_type,
                "metadata": chunk.metadata,
            })
        
        # Build section summaries
        sections_data = []
        for section_name, info in sections_info.items():
            section_id = hashlib.md5(f"{doc_id}:{section_name}".encode()).hexdigest()[:12]
            
            # Find chunk IDs in this section
            section_chunk_ids = [
                c["chunk_id"] for c in chunks_data 
                if c["section_path"] == section_name
            ]
            
            sections_data.append({
                "section_id": section_id,
                "doc_id": doc_id,
                "doc_name": doc_name,
                "section_path": section_name,
                "summary": "",  # To be generated later
                "page_start": info["page_start"],
                "page_end": info["page_end"],
                "chunk_ids": section_chunk_ids,
            })
        
        return chunks_data, sections_data

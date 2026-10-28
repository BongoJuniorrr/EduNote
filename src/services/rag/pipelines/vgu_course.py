# -*- coding: utf-8 -*-
"""
VGU Course Pipeline
===================

Advanced RAG pipeline designed for long academic documents with:
- Two-tier indexing (coarse sections → fine chunks)
- Page-accurate citations with section paths
- Cross-encoder reranking for precision
- Multimodal support (images, tables, equations)
- Hybrid search (dense + sparse)
- TRUE Semantic Chunking (embedding-based boundary detection)
- 3-tier parsing: LlamaParse (cloud) → MinerU (local GPU) → PyMuPDF (basic)
- Image extraction and vision understanding

This pipeline combines the best of EduNote (multimodal, structure parsing)
and EduNote (long-doc support, citation accuracy) architectures.

Author: Tran Huu Vu Phuong
"""

import asyncio
import base64
import json
import hashlib
import pickle
import os
import re
import httpx
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from src.logging import get_logger
from src.logging.adapters import LightRAGLogContext


# =============================================================================
# LlamaParse Integration - Primary Parser
# =============================================================================

class LlamaParseClient:
    """
    LlamaParse API client for document parsing with image extraction.
    Superior to local parsers for complex academic documents.
    """
    
    API_BASE = "https://api.cloud.llamaindex.ai/api/parsing"
    
    def __init__(self, api_key: str, mode: str = "Agentic"):
        """
        Initialize LlamaParse client.
        
        Args:
            api_key: LlamaParse API key
            mode: Parsing mode - "Fast", "Cost Effective", "Agentic", "Agentic Plus"
        """
        self.api_key = api_key
        self.mode = mode
        self.logger = get_logger("llamaparse")
        
    async def parse_document(
        self,
        file_path: str,
        output_dir: str,
        extract_images: bool = True,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Parse document using LlamaParse API.
        
        Args:
            file_path: Path to document
            output_dir: Directory to save extracted images
            extract_images: Whether to extract images
            
        Returns:
            Tuple of (content_list, images_list)
        """
        file_path = Path(file_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger.info(f"[LlamaParse] Parsing: {file_path.name} (mode={self.mode})")
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }
        
        # Upload file
        async with httpx.AsyncClient(timeout=300) as client:
            # Step 1: Upload file
            with open(file_path, "rb") as f:
                files = {"file": (file_path.name, f, "application/octet-stream")}
                data = {
                    "parsing_instruction": "Extract all text, tables, and images. Preserve document structure with headings and sections. For academic documents, pay special attention to equations, figures, and references.",
                    "result_type": "markdown",
                    "premium_mode": "true" if self.mode in ["Agentic", "Agentic Plus"] else "false",
                    "extract_images": "true" if extract_images else "false",
                }
                
                response = await client.post(
                    f"{self.API_BASE}/upload",
                    headers=headers,
                    files=files,
                    data=data,
                )
                
                if response.status_code != 200:
                    raise Exception(f"LlamaParse upload failed: {response.text}")
                
                job_id = response.json().get("id")
                self.logger.info(f"[LlamaParse] Job created: {job_id}")
            
            # Step 2: Poll for completion
            max_attempts = 60  # 5 minutes max
            for attempt in range(max_attempts):
                await asyncio.sleep(5)
                
                status_response = await client.get(
                    f"{self.API_BASE}/job/{job_id}",
                    headers=headers,
                )
                
                if status_response.status_code != 200:
                    continue
                    
                status = status_response.json().get("status")
                
                if status == "SUCCESS":
                    self.logger.info(f"[LlamaParse] Parsing complete")
                    break
                elif status == "ERROR":
                    error_msg = status_response.json().get("error", "Unknown error")
                    raise Exception(f"LlamaParse parsing failed: {error_msg}")
                    
                self.logger.debug(f"[LlamaParse] Status: {status} (attempt {attempt + 1})")
            else:
                raise Exception("LlamaParse timeout")
            
            # Step 3: Get results
            result_response = await client.get(
                f"{self.API_BASE}/job/{job_id}/result/markdown",
                headers=headers,
            )
            
            if result_response.status_code != 200:
                raise Exception(f"Failed to get results: {result_response.text}")
            
            markdown_content = result_response.json().get("markdown", "")
            
            # Step 4: Get images if available
            images_list = []
            if extract_images:
                images_response = await client.get(
                    f"{self.API_BASE}/job/{job_id}/result/images",
                    headers=headers,
                )
                
                if images_response.status_code == 200:
                    images_data = images_response.json().get("images", [])
                    
                    for idx, img_data in enumerate(images_data):
                        img_name = img_data.get("name", f"image_{idx}.png")
                        img_base64 = img_data.get("data", "")
                        page_idx = img_data.get("page", 0)
                        
                        if img_base64:
                            # Save image
                            img_path = output_dir / img_name
                            img_bytes = base64.b64decode(img_base64)
                            with open(img_path, "wb") as f:
                                f.write(img_bytes)
                            
                            images_list.append({
                                "path": str(img_path),
                                "name": img_name,
                                "page_idx": page_idx,
                                "caption": img_data.get("caption", ""),
                            })
                    
                    self.logger.info(f"[LlamaParse] Extracted {len(images_list)} images")
        
        # Convert markdown to content_list format
        content_list = self._markdown_to_content_list(markdown_content, file_path.name)
        
        return content_list, images_list
    
    def _markdown_to_content_list(self, markdown: str, filename: str) -> List[Dict[str, Any]]:
        """Convert LlamaParse markdown output to content_list format."""
        content_list = []
        current_page = 0
        
        lines = markdown.split("\n")
        current_text = []
        
        for line in lines:
            # Detect page markers (LlamaParse adds these)
            if line.startswith("<!-- Page") or line.startswith("[Page"):
                # Extract page number
                match = re.search(r'Page\s*(\d+)', line)
                if match:
                    current_page = int(match.group(1)) - 1  # 0-indexed
                continue
            
            # Detect headings
            if line.startswith("#"):
                # Save previous text block
                if current_text:
                    text = "\n".join(current_text).strip()
                    if text:
                        content_list.append({
                            "type": "text",
                            "text": text,
                            "page_idx": current_page,
                        })
                    current_text = []
                
                # Determine heading level
                level = len(re.match(r'^#+', line).group())
                title_text = line.lstrip('#').strip()
                
                content_list.append({
                    "type": "title",
                    "text": title_text,
                    "page_idx": current_page,
                    "level": level,
                })
            
            # Detect images
            elif line.startswith("!["):
                match = re.match(r'!\[([^\]]*)\]\(([^)]+)\)', line)
                if match:
                    alt_text = match.group(1)
                    img_path = match.group(2)
                    content_list.append({
                        "type": "image",
                        "img_path": img_path,
                        "img_caption": [alt_text] if alt_text else [],
                        "page_idx": current_page,
                    })
            
            # Detect tables
            elif line.startswith("|") and "|" in line[1:]:
                if current_text:
                    text = "\n".join(current_text).strip()
                    if text:
                        content_list.append({
                            "type": "text",
                            "text": text,
                            "page_idx": current_page,
                        })
                    current_text = []
                
                # Collect table lines
                table_lines = [line]
                # Look ahead for more table lines would need index tracking
                content_list.append({
                    "type": "table",
                    "text": line,
                    "page_idx": current_page,
                })
            
            # Regular text
            else:
                if line.strip():
                    current_text.append(line)
                elif current_text:
                    # Empty line - save paragraph
                    text = "\n".join(current_text).strip()
                    if text:
                        content_list.append({
                            "type": "text",
                            "text": text,
                            "page_idx": current_page,
                        })
                    current_text = []
        
        # Save remaining text
        if current_text:
            text = "\n".join(current_text).strip()
            if text:
                content_list.append({
                    "type": "text",
                    "text": text,
                    "page_idx": current_page,
                })
        
        return content_list


async def parse_with_llamaparse(
    file_path: str,
    output_dir: str,
    api_key: str = None,
    mode: str = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Parse document using LlamaParse.
    
    Args:
        file_path: Path to document
        output_dir: Directory for extracted images
        api_key: LlamaParse API key (defaults to env var)
        mode: Parsing mode (defaults to env var)
        
    Returns:
        Tuple of (content_list, images_list)
    """
    api_key = api_key or os.getenv("LLAMAPARSE_API_KEY")
    mode = mode or os.getenv("LLAMAPARSE_MODE", "Agentic").strip('"')
    
    if not api_key:
        raise ValueError("LLAMAPARSE_API_KEY not set")
    
    client = LlamaParseClient(api_key=api_key, mode=mode)
    return await client.parse_document(file_path, output_dir, extract_images=True)


# =============================================================================
# Fallback Parser using PyMuPDF (when LlamaParse unavailable)
# =============================================================================

def _normalize_extracted_text(text: str) -> str:
    """Normalize parser text to reduce broken words from PDF span extraction."""
    if not text:
        return ""

    # Normalize spaces/newlines first
    text = re.sub(r"\s+", " ", text).strip()

    # Keep hyphenated compounds intact (e.g., North-Western)
    text = re.sub(r"(?<=[A-Za-z])\s*-\s*(?=[A-Za-z])", "-", text)

    # Merge letter-by-letter sequences often produced by PDF span extraction
    # Example: "K A R E N" -> "KAREN"
    text = re.sub(
        r"\b(?:[A-Za-z]\s+){3,}[A-Za-z]\b",
        lambda m: m.group(0).replace(" ", ""),
        text,
    )

    return text


def _merge_pymupdf_line_spans(spans: List[Dict[str, Any]]) -> str:
    """Merge a line's spans while avoiding artificial spaces between characters."""
    merged = ""
    for span in spans:
        span_text = span.get("text", "")
        if not span_text:
            continue

        if not merged:
            merged = span_text
            continue

        prev_char = merged[-1]
        next_char = span_text[0]

        add_space = False
        if not prev_char.isspace() and not next_char.isspace():
            # Do not add spaces around punctuation/hyphen boundaries.
            if next_char in ".,;:!?)]}%":
                add_space = False
            elif prev_char in "([{%$/#":
                add_space = False
            elif prev_char == "-" or next_char == "-":
                add_space = False
            # If next span is a single letter and previous ends with a letter,
            # this is often an OCR/PDF split within one word.
            elif len(span_text) == 1 and next_char.isalpha() and prev_char.isalpha():
                add_space = False
            else:
                add_space = True

        if add_space:
            merged += " "
        merged += span_text

    return _normalize_extracted_text(merged)


def parse_pdf_with_pymupdf(file_path: str, extract_images: bool = True, output_dir: str = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Fallback PDF parser using PyMuPDF when LlamaParse/MinerU fails.
    Returns content_list compatible format with image extraction.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise ImportError("PyMuPDF not installed. Run: pip install pymupdf")
    
    content_list = []
    images_list = []
    
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    
    with fitz.open(file_path) as doc:
        for page_num, page in enumerate(doc, 1):
            # Extract text blocks with position info
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
            
            for block_idx, block in enumerate(blocks):
                if block.get("type") == 0:  # Text block
                    lines = block.get("lines", [])
                    text_parts = []
                    
                    for line in lines:
                        spans = line.get("spans", [])
                        line_text = _merge_pymupdf_line_spans(spans)
                        if line_text:
                            text_parts.append(line_text)
                    
                    text = _normalize_extracted_text(" ".join(text_parts))
                    if not text:
                        continue
                    
                    # Detect content type based on font size and style
                    avg_size = 12
                    is_bold = False
                    if lines and lines[0].get("spans"):
                        avg_size = np.mean([s.get("size", 12) for s in lines[0]["spans"]])
                        is_bold = any("Bold" in s.get("font", "") for s in lines[0]["spans"])
                    
                    # Classify content type
                    if avg_size >= 18 or (is_bold and avg_size >= 14):
                        content_type = "title"
                    elif is_bold and avg_size >= 12:
                        content_type = "title"
                    elif re.match(r'^[\d.]+\s+\w', text) or re.match(r'^(Chapter|Section|Part)\s+\d', text):
                        content_type = "title"
                    else:
                        content_type = "text"
                    
                    content_list.append({
                        "type": content_type,
                        "text": text,
                        "page_idx": page_num - 1,  # 0-indexed
                        "bbox": block.get("bbox", [0, 0, 0, 0]),
                    })
                
                elif block.get("type") == 1 and extract_images and output_dir:  # Image block
                    # Extract image
                    try:
                        xref = block.get("xref")
                        if xref:
                            base_image = doc.extract_image(xref)
                            if base_image:
                                img_ext = base_image.get("ext", "png")
                                img_data = base_image.get("image")
                                
                                if img_data:
                                    img_name = f"page{page_num}_img{block_idx}.{img_ext}"
                                    img_path = output_dir / img_name
                                    
                                    with open(img_path, "wb") as f:
                                        f.write(img_data)
                                    
                                    images_list.append({
                                        "path": str(img_path),
                                        "name": img_name,
                                        "page_idx": page_num - 1,
                                        "caption": "",
                                    })
                                    
                                    content_list.append({
                                        "type": "image",
                                        "img_path": str(img_path),
                                        "img_caption": [],
                                        "page_idx": page_num - 1,
                                        "bbox": block.get("bbox", [0, 0, 0, 0]),
                                    })
                    except Exception as e:
                        pass  # Skip failed image extraction
    
    return content_list, images_list


def parse_docx_with_python_docx(file_path: str, extract_images: bool = True, output_dir: str = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Fallback DOCX parser using python-docx.
    Returns content_list compatible format with image extraction.
    """
    try:
        from docx import Document
        from docx.opc.constants import RELATIONSHIP_TYPE as RT
    except ImportError:
        raise ImportError("python-docx not installed. Run: pip install python-docx")
    
    content_list = []
    images_list = []
    
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    
    doc = Document(file_path)
    
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        
        # Detect content type based on style
        style_name = para.style.name if para.style else ""
        
        if "Heading" in style_name or "Title" in style_name:
            content_type = "title"
            level = 1
            if "Heading" in style_name:
                try:
                    level = int(style_name.replace("Heading ", "").split()[0])
                except:
                    level = 1
        elif re.match(r'^[\d.]+\s+\w', text) or re.match(r'^(Chapter|Section|Part)\s+\d', text):
            content_type = "title"
            level = 1
        else:
            content_type = "text"
            level = 0
        
        item = {
            "type": content_type,
            "text": text,
            "page_idx": 0,  # DOCX doesn't have page info
        }
        if content_type == "title":
            item["level"] = level
        content_list.append(item)
    
    # Process tables
    for table in doc.tables:
        table_text = []
        for row in table.rows:
            row_text = [cell.text.strip() for cell in row.cells]
            table_text.append(" | ".join(row_text))
        
        if table_text:
            content_list.append({
                "type": "table",
                "text": "\n".join(table_text),
                "page_idx": 0,
            })
    
    # Extract images
    if extract_images and output_dir:
        img_idx = 0
        for rel in doc.part.rels.values():
            if "image" in rel.reltype:
                try:
                    img_data = rel.target_part.blob
                    img_ext = rel.target_part.content_type.split("/")[-1]
                    if img_ext == "jpeg":
                        img_ext = "jpg"
                    
                    img_name = f"docx_img_{img_idx}.{img_ext}"
                    img_path = output_dir / img_name
                    
                    with open(img_path, "wb") as f:
                        f.write(img_data)
                    
                    images_list.append({
                        "path": str(img_path),
                        "name": img_name,
                        "page_idx": 0,
                        "caption": "",
                    })
                    
                    content_list.append({
                        "type": "image",
                        "img_path": str(img_path),
                        "img_caption": [],
                        "page_idx": 0,
                    })
                    
                    img_idx += 1
                except Exception:
                    pass
    
    return content_list, images_list


async def fallback_parse_document(
    file_path: str,
    output_dir: str = None,
    extract_images: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Fallback document parser when LlamaParse unavailable.
    Supports PDF and DOCX with image extraction.
    """
    file_path = Path(file_path)
    ext = file_path.suffix.lower()
    
    if ext == ".pdf":
        return parse_pdf_with_pymupdf(str(file_path), extract_images, output_dir)
    elif ext in [".docx", ".doc"]:
        return parse_docx_with_python_docx(str(file_path), extract_images, output_dir)
    else:
        raise ValueError(f"Unsupported file type for fallback parser: {ext}")


# =============================================================================
# GPU Detection and Configuration
# =============================================================================

def detect_gpu_device() -> str:
    """Detect best available GPU device. Handles P100 (sm_60) compatibility."""
    try:
        import torch
        if torch.cuda.is_available():
            # Get GPU info
            gpu_name = torch.cuda.get_device_name(0)
            gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            capability = torch.cuda.get_device_capability(0)
            print(f"[VGU] GPU detected: {gpu_name} ({gpu_memory:.1f}GB, sm_{capability[0]}{capability[1]})")
            
            # Verify GPU actually works by running a small tensor op
            try:
                test_tensor = torch.zeros(1, device="cuda")
                del test_tensor
                torch.cuda.empty_cache()
                print(f"[VGU] GPU validation passed, using CUDA")
                return "cuda"
            except RuntimeError as e:
                print(f"[VGU] GPU detected but CUDA operation failed: {e}")
                print(f"[VGU] This may be due to architecture mismatch (e.g., sm_60 P100 with newer PyTorch)")
                print(f"[VGU] Falling back to CPU")
                return "cpu"
        else:
            print("[VGU] CUDA not available, using CPU")
    except ImportError:
        print("[VGU] PyTorch not installed, using CPU")
    return "cpu"


DEFAULT_DEVICE = detect_gpu_device()


# =============================================================================
# Data Classes for VGU Course Pipeline
# =============================================================================

@dataclass
class Citation:
    """Page-accurate citation for evidence tracking."""
    doc_id: str
    doc_name: str
    page_start: int
    page_end: int
    section_path: str = ""
    chunk_id: str = ""
    confidence: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "doc_name": self.doc_name,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "section_path": self.section_path,
            "chunk_id": self.chunk_id,
            "confidence": self.confidence,
        }
    
    def __str__(self) -> str:
        if self.page_start == self.page_end:
            return f"[{self.doc_name}, p.{self.page_start}]"
        return f"[{self.doc_name}, pp.{self.page_start}-{self.page_end}]"


@dataclass
class VGUChunk:
    """Enhanced chunk with page-level metadata for citations."""
    chunk_id: str
    content: str
    doc_id: str
    doc_name: str
    page_start: int
    page_end: int
    section_path: str = ""
    chunk_type: str = "text"  # text, definition, theorem, table, figure, equation
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "content": self.content,
            "doc_id": self.doc_id,
            "doc_name": self.doc_name,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "section_path": self.section_path,
            "chunk_type": self.chunk_type,
            "metadata": self.metadata,
        }
    
    def to_citation(self, confidence: float = 1.0) -> Citation:
        return Citation(
            doc_id=self.doc_id,
            doc_name=self.doc_name,
            page_start=self.page_start,
            page_end=self.page_end,
            section_path=self.section_path,
            chunk_id=self.chunk_id,
            confidence=confidence,
        )


@dataclass 
class VGUSectionSummary:
    """Coarse-level section summary for two-tier retrieval."""
    section_id: str
    doc_id: str
    doc_name: str
    section_path: str
    summary: str
    page_start: int
    page_end: int
    chunk_ids: List[str] = field(default_factory=list)
    embedding: Optional[List[float]] = None


@dataclass
class VGUSearchResult:
    """Enhanced search result with citations and evidence."""
    query: str
    answer: str
    content: str
    citations: List[Citation] = field(default_factory=list)
    chunks: List[VGUChunk] = field(default_factory=list)
    mode: str = "hybrid"
    provider: str = "vgu_course"
    retrieval_scores: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "answer": self.answer,
            "content": self.content,
            "citations": [c.to_dict() for c in self.citations],
            "chunks": [c.to_dict() for c in self.chunks],
            "mode": self.mode,
            "provider": self.provider,
            "retrieval_scores": self.retrieval_scores,
            "metadata": self.metadata,
        }


# =============================================================================
# VGU Course Pipeline Implementation
# =============================================================================

class VGUCoursePipeline:
    """
    VGU Course RAG Pipeline - Optimized for long academic documents.
    
    Architecture:
    ┌─────────────────────────────────────────────────────────────────┐
    │                    DOCUMENT INGESTION                           │
    │  PDF/DOCX → Docling Parser → Structure Extraction → Chunking   │
    │                              ↓                                  │
    │  ┌─────────────────┐    ┌─────────────────┐                    │
    │  │ Coarse Index    │    │ Fine Index      │                    │
    │  │ (Sections)      │    │ (Chunks)        │                    │
    │  │ + Summaries     │    │ + Page metadata │                    │
    │  └─────────────────┘    └─────────────────┘                    │
    └─────────────────────────────────────────────────────────────────┘
                              ↓
    ┌─────────────────────────────────────────────────────────────────┐
    │                    RETRIEVAL (Two-Tier)                         │
    │  Query → Coarse Search → Filter Sections → Fine Search         │
    │                              ↓                                  │
    │  Candidates → Reranker → Top-K → Citation Assembly             │
    └─────────────────────────────────────────────────────────────────┘
    
    Features:
    - Two-tier indexing for efficient long-doc retrieval
    - Page-accurate citations
    - Cross-encoder reranking
    - Multimodal support (via Docling/MinerU)
    - Hybrid search (dense + knowledge graph)
    """
    
    name = "vgu_course"
    
    def __init__(
        self,
        kb_base_dir: Optional[str] = None,
        enable_reranker: bool = True,
        reranker_model: str = "BAAI/bge-reranker-v2-m3",
        reranker_device: str = "auto",  # auto, cuda, cpu
        enable_multimodal: bool = True,
        enable_query_expansion: bool = True,
        enable_hybrid_search: bool = True,
        enable_embedding_cache: bool = True,
        coarse_top_k: int = 15,
        fine_top_k: int = 40,
        final_top_k: int = 10,
        chunk_size: int = 400,
        chunk_overlap: int = 50,
    ):
        """
        Initialize VGU Course Pipeline (v2 - Optimized for 95+ score).
        
        Args:
            kb_base_dir: Base directory for knowledge bases
            enable_reranker: Enable cross-encoder reranking
            reranker_model: Reranker model name (HuggingFace)
            reranker_device: Device for reranker (auto, cuda, cpu)
            enable_multimodal: Enable image/table/equation processing
            enable_query_expansion: Enable LLM-based query expansion
            enable_hybrid_search: Enable BM25 + Dense hybrid search
            enable_embedding_cache: Cache embeddings to disk
            coarse_top_k: Number of sections to retrieve in coarse stage
            fine_top_k: Number of chunks to retrieve in fine stage  
            final_top_k: Final number of results after reranking
            chunk_size: Target chunk size in tokens
            chunk_overlap: Overlap between chunks
        """
        self.logger = get_logger("VGUCoursePipeline")
        self.kb_base_dir = kb_base_dir or str(
            Path(__file__).resolve().parent.parent.parent.parent.parent 
            / "data" / "knowledge_bases"
        )

        def _env_bool(name: str, default: bool) -> bool:
            value = os.getenv(name)
            if value is None:
                return default
            return value.strip().lower() in ("1", "true", "yes", "on")

        def _env_int(name: str, default: int) -> int:
            value = os.getenv(name)
            if value is None:
                return default
            try:
                return int(value)
            except ValueError:
                return default

        # Allow environment-based overrides for deployment tuning.
        enable_reranker = _env_bool("VGU_ENABLE_RERANKER", enable_reranker)
        enable_query_expansion = _env_bool("VGU_ENABLE_QUERY_EXPANSION", enable_query_expansion)
        enable_hybrid_search = _env_bool("VGU_ENABLE_HYBRID_SEARCH", enable_hybrid_search)
        coarse_top_k = _env_int("VGU_COARSE_TOP_K", coarse_top_k)
        fine_top_k = _env_int("VGU_FINE_TOP_K", fine_top_k)
        final_top_k = _env_int("VGU_FINAL_TOP_K", final_top_k)
        
        # GPU/Device settings
        self.device = DEFAULT_DEVICE if reranker_device == "auto" else reranker_device
        
        # Retrieval settings
        self.enable_reranker = enable_reranker
        self.reranker_model = reranker_model
        self.enable_multimodal = enable_multimodal
        self.enable_query_expansion = enable_query_expansion
        self.enable_hybrid_search = enable_hybrid_search
        self.enable_embedding_cache = enable_embedding_cache
        self.coarse_top_k = coarse_top_k
        self.fine_top_k = fine_top_k
        self.final_top_k = final_top_k
        
        # Chunking settings
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        
        # Lazy-loaded components
        self._reranker = None
        self._embed_client = None
        self._llm_client = None
        self._semantic_chunker = None
        self._bm25_index: Dict[str, Any] = {}  # BM25 index per KB
        self._embedding_cache: Dict[str, np.ndarray] = {}  # Embedding cache
        self._section_embeddings: Dict[str, np.ndarray] = {}  # Section embedding cache
        self._rag_instances: Dict[str, Any] = {}
        
        self.logger.info(
            f"VGU Course Pipeline v2 initialized: "
            f"device={self.device}, reranker={enable_reranker}, "
            f"query_expansion={enable_query_expansion}, hybrid={enable_hybrid_search}, "
            f"coarse_k={coarse_top_k}, fine_k={fine_top_k}, final_k={final_top_k}"
        )
    
    # =========================================================================
    # Lazy Component Loading
    # =========================================================================
    
    def _get_embed_client(self):
        """Get embedding client (lazy load)."""
        if self._embed_client is None:
            from src.services.embedding import get_embedding_client
            self._embed_client = get_embedding_client()
        return self._embed_client
    
    def _get_llm_client(self):
        """Get LLM client (lazy load)."""
        if self._llm_client is None:
            from src.services.llm import get_llm_client
            self._llm_client = get_llm_client()
        return self._llm_client
    
    def _get_reranker(self, force_enable: Optional[bool] = None):
        """Get reranker model (lazy load) with GPU acceleration."""
        reranker_enabled = self.enable_reranker if force_enable is None else bool(force_enable)
        if not reranker_enabled:
            return None

        if self._reranker is None:
            try:
                from sentence_transformers import CrossEncoder
                import torch
                
                # Determine device
                device = self.device
                if device == "cuda" and not torch.cuda.is_available():
                    self.logger.warning("CUDA requested but not available, falling back to CPU")
                    device = "cpu"
                
                # Configure for P100 16GB
                max_length = 512
                if device == "cuda":
                    # P100 can handle longer sequences
                    max_length = 1024
                    # Enable TF32 for better performance on newer GPUs
                    if hasattr(torch.backends, 'cuda'):
                        torch.backends.cuda.matmul.allow_tf32 = True
                
                self._reranker = CrossEncoder(
                    self.reranker_model, 
                    max_length=max_length,
                    device=device,
                )
                
                # Warmup inference
                if device == "cuda":
                    _ = self._reranker.predict([("warmup", "warmup")])
                    torch.cuda.empty_cache()
                
                self.logger.info(
                    f"Loaded reranker: {self.reranker_model} on {device} "
                    f"(max_length={max_length})"
                )
            except ImportError:
                self.logger.warning(
                    "sentence-transformers not installed. "
                    "Install with: pip install sentence-transformers"
                )
                self.enable_reranker = False
            except Exception as e:
                self.logger.warning(f"Failed to load reranker: {e}")
                self.enable_reranker = False
        return self._reranker
    
    def _get_semantic_chunker(self):
        """Get semantic chunker (lazy load)."""
        if self._semantic_chunker is None:
            try:
                from ..components.chunkers.semantic import SemanticChunker
                
                embed_client = self._get_embed_client()
                embed_func = None
                if embed_client:
                    embed_func = embed_client.embed
                
                self._semantic_chunker = SemanticChunker(
                    target_chunk_size=self.chunk_size,
                    min_chunk_size=100,
                    max_chunk_size=1500,
                    chunk_overlap=self.chunk_overlap,
                    similarity_threshold=0.45,
                    percentile_threshold=25,
                    window_size=3,
                    embedding_func=embed_func,
                )
                self.logger.info("Loaded semantic chunker with embedding similarity detection")
            except Exception as e:
                self.logger.warning(f"Failed to load semantic chunker: {e}")
                self._semantic_chunker = None
        return self._semantic_chunker
    
    def _get_rag_instance(self, kb_name: str):
        """Get or create RAG instance for a knowledge base."""
        kb_dir = Path(self.kb_base_dir) / kb_name
        working_dir = str(kb_dir / "rag_storage")
        
        if working_dir in self._rag_instances:
            return self._rag_instances[working_dir]
        
        # Setup RAG-Anything path
        project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
        raganything_path = project_root.parent / "raganything" / "RAG-Anything"
        import sys
        if raganything_path.exists() and str(raganything_path) not in sys.path:
            sys.path.insert(0, str(raganything_path))
        
        try:
            from raganything import RAGAnything, RAGAnythingConfig
            
            llm_client = self._get_llm_client()
            embed_client = self._get_embed_client()
            
            config = RAGAnythingConfig(
                working_dir=working_dir,
                enable_image_processing=self.enable_multimodal,
                enable_table_processing=self.enable_multimodal,
                enable_equation_processing=self.enable_multimodal,
            )
            
            # Performance optimization settings for LightRAG
            # These significantly reduce processing time for large documents
            lightrag_performance_kwargs = {
                # Disable gleaning (extra LLM calls for verification)
                # Set to 0 to skip gleaning entirely, reducing LLM calls by ~50%
                "entity_extract_max_gleaning": int(os.getenv("LIGHTRAG_MAX_GLEANING", "0")),
                
                # Enable LLM cache to avoid redundant API calls
                "enable_llm_cache": True,
                "enable_llm_cache_for_entity_extract": True,
                
                # Increase parallel processing for faster indexing
                "llm_model_max_async": int(os.getenv("LIGHTRAG_LLM_MAX_ASYNC", "16")),
                "embedding_batch_num": int(os.getenv("LIGHTRAG_EMBEDDING_BATCH", "32")),
                "embedding_func_max_async": int(os.getenv("LIGHTRAG_EMBED_MAX_ASYNC", "16")),
                
                # Limit entity/relation tokens for faster processing
                "max_entity_tokens": int(os.getenv("LIGHTRAG_MAX_ENTITY_TOKENS", "1500")),
                "max_relation_tokens": int(os.getenv("LIGHTRAG_MAX_RELATION_TOKENS", "1500")),
                
                # Chunk size optimization
                "chunk_token_size": int(os.getenv("LIGHTRAG_CHUNK_SIZE", "1200")),
                "chunk_overlap_token_size": int(os.getenv("LIGHTRAG_CHUNK_OVERLAP", "100")),
            }
            
            self.logger.info(
                f"[VGU] LightRAG optimization: gleaning={lightrag_performance_kwargs['entity_extract_max_gleaning']}, "
                f"async={lightrag_performance_kwargs['llm_model_max_async']}, "
                f"embed_batch={lightrag_performance_kwargs['embedding_batch_num']}"
            )
            
            rag = RAGAnything(
                config=config,
                llm_model_func=llm_client.get_model_func(),
                vision_model_func=llm_client.get_vision_model_func(),
                embedding_func=embed_client.get_embedding_func(),
                lightrag_kwargs=lightrag_performance_kwargs,
            )
            
            self._rag_instances[working_dir] = rag
            return rag
            
        except ImportError as e:
            self.logger.error(f"RAG-Anything not available: {e}")
            raise
    
    # =========================================================================
    # Document Parsing & Chunking
    # =========================================================================
    
    def _generate_chunk_id(self, doc_id: str, page: int, index: int) -> str:
        """Generate unique chunk ID."""
        content = f"{doc_id}:{page}:{index}"
        return hashlib.md5(content.encode()).hexdigest()[:12]
    
    def _extract_section_path(self, content_item: Dict) -> str:
        """Extract section path from content item metadata."""
        # Try various metadata fields
        if "section_path" in content_item:
            return content_item["section_path"]
        if "heading" in content_item:
            return content_item["heading"]
        if "title" in content_item:
            return content_item["title"]
        return ""
    
    async def _chunk_content_with_pages(
        self,
        content_items: List[Dict],
        doc_id: str,
        doc_name: str,
    ) -> Tuple[List[VGUChunk], List[VGUSectionSummary]]:
        """
        Chunk content while preserving page information.
        Uses semantic chunking when available, fallback to basic chunking.
        
        Returns:
            Tuple of (chunks, section_summaries)
        """
        # Try to use semantic chunking (await since this method is async)
        semantic_chunker = self._get_semantic_chunker()
        if semantic_chunker:
            try:
                return await self._semantic_chunk_content(content_items, doc_id, doc_name, semantic_chunker)
            except Exception as e:
                self.logger.warning(f"Semantic chunking failed, using basic: {e}")
        
        # Fallback to basic chunking
        return self._basic_chunk_content(content_items, doc_id, doc_name)
    
    async def _semantic_chunk_content(
        self,
        content_items: List[Dict],
        doc_id: str,
        doc_name: str,
        chunker,
    ) -> Tuple[List[VGUChunk], List[VGUSectionSummary]]:
        """
        Use semantic chunker with embedding similarity detection.
        
        This provides better chunk boundaries than basic separator-based chunking.
        """
        self.logger.info(f"Using semantic chunking for {doc_name}")
        
        # Use chunker's content list method
        chunks_data, sections_data = await chunker.chunk_content_list(
            content_items, doc_id, doc_name
        )
        
        # Convert to VGU data classes
        chunks = []
        for cd in chunks_data:
            chunks.append(VGUChunk(
                chunk_id=cd["chunk_id"],
                content=cd["content"],
                doc_id=cd["doc_id"],
                doc_name=cd["doc_name"],
                page_start=cd["page_start"],
                page_end=cd["page_end"],
                section_path=cd["section_path"],
                chunk_type=cd["chunk_type"],
                metadata=cd.get("metadata", {}),
            ))
        
        sections = []
        for sd in sections_data:
            sections.append(VGUSectionSummary(
                section_id=sd["section_id"],
                doc_id=sd["doc_id"],
                doc_name=sd["doc_name"],
                section_path=sd["section_path"],
                summary=sd["summary"],
                page_start=sd["page_start"],
                page_end=sd["page_end"],
                chunk_ids=sd["chunk_ids"],
            ))
        
        self.logger.info(f"Semantic chunking: {len(chunks)} chunks, {len(sections)} sections")
        return chunks, sections
    
    def _basic_chunk_content(
        self,
        content_items: List[Dict],
        doc_id: str,
        doc_name: str,
    ) -> Tuple[List[VGUChunk], List[VGUSectionSummary]]:
        """
        Basic chunking fallback (separator-based).
        
        Returns:
            Tuple of (chunks, section_summaries)
        """
        self.logger.info(f"Using basic chunking for {doc_name}")
        
        chunks: List[VGUChunk] = []
        sections: Dict[str, VGUSectionSummary] = {}
        
        current_section = "Introduction"
        chunk_index = 0
        
        for item in content_items:
            page_num = item.get("page_idx", 1) + 1  # Convert 0-indexed to 1-indexed
            item_type = item.get("type", "text")
            text = item.get("text", "")
            
            if not text.strip():
                continue
            
            # Update current section
            section_path = self._extract_section_path(item)
            if section_path:
                current_section = section_path
            
            # Create chunk
            chunk_id = self._generate_chunk_id(doc_id, page_num, chunk_index)
            chunk = VGUChunk(
                chunk_id=chunk_id,
                content=text,
                doc_id=doc_id,
                doc_name=doc_name,
                page_start=page_num,
                page_end=page_num,
                section_path=current_section,
                chunk_type=self._map_item_type(item_type),
                metadata={
                    "original_type": item_type,
                    "has_image": "img_path" in item,
                },
            )
            chunks.append(chunk)
            chunk_index += 1
            
            # Update section summary
            if current_section not in sections:
                section_id = hashlib.md5(f"{doc_id}:{current_section}".encode()).hexdigest()[:12]
                sections[current_section] = VGUSectionSummary(
                    section_id=section_id,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    section_path=current_section,
                    summary="",  # Will be generated later
                    page_start=page_num,
                    page_end=page_num,
                    chunk_ids=[],
                )
            
            section = sections[current_section]
            section.chunk_ids.append(chunk_id)
            section.page_end = max(section.page_end, page_num)
        
        return chunks, list(sections.values())
    
    def _map_item_type(self, item_type: str) -> str:
        """Map content item type to chunk type."""
        type_mapping = {
            "text": "text",
            "title": "heading",
            "table": "table",
            "figure": "figure",
            "image": "figure",
            "equation": "equation",
            "code": "code",
            "list": "list",
        }
        return type_mapping.get(item_type.lower(), "text")
    
    async def _process_images_with_vision(
        self,
        content_list: List[Dict[str, Any]],
        images_list: List[Dict[str, Any]],
        doc_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Process images using vision model to generate descriptions.
        
        This adds semantic understanding of diagrams, charts, and figures
        to improve RAG retrieval accuracy.
        
        Args:
            content_list: Original content list
            images_list: List of extracted images
            doc_id: Document ID
            
        Returns:
            Updated content_list with image descriptions
        """
        if not images_list:
            return content_list
        
        # Check if vision model available
        llm_model = os.getenv("LLM_MODEL", "")
        vision_capable = any(v in llm_model.lower() for v in ["gpt-4", "gemini", "claude-3"])
        
        if not vision_capable:
            self.logger.info("  → Vision model not available, skipping image understanding")
            return content_list
        
        llm_client = self._get_llm_client()
        
        # Build image path lookup
        image_lookup = {img["path"]: img for img in images_list}
        image_lookup.update({img["name"]: img for img in images_list})
        
        # Process each image in content_list
        for item in content_list:
            if item.get("type") != "image":
                continue
            
            img_path = item.get("img_path", "")
            if not img_path:
                continue
            
            # Find matching image
            img_info = image_lookup.get(img_path) or image_lookup.get(Path(img_path).name)
            
            if not img_info:
                continue
            
            # Check if already has caption
            existing_caption = item.get("img_caption", [])
            if existing_caption and existing_caption[0]:
                continue
            
            try:
                # Read image and encode to base64
                img_full_path = Path(img_info["path"])
                if not img_full_path.exists():
                    continue
                
                with open(img_full_path, "rb") as f:
                    img_data = base64.b64encode(f.read()).decode("utf-8")
                
                # Determine image type
                img_ext = img_full_path.suffix.lower()
                mime_type = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".gif": "image/gif",
                    ".webp": "image/webp",
                }.get(img_ext, "image/png")
                
                # Generate description using vision model
                prompt = """Analyze this image from an academic document. Provide:
1. A brief description of what the image shows
2. Key information or data presented
3. How it relates to educational content

Be concise but comprehensive. Focus on factual content that would help a student understand this material."""

                # Call vision API
                response = await llm_client.acomplete_with_vision(
                    prompt=prompt,
                    image_data=img_data,
                    image_mime_type=mime_type,
                    max_tokens=300,
                )
                
                description = response.strip()
                
                # Update item with description
                item["img_caption"] = [description]
                item["img_description"] = description
                
                self.logger.debug(f"  → Generated description for {img_full_path.name}")
                
            except Exception as e:
                self.logger.debug(f"  → Failed to process image {img_path}: {e}")
                continue
        
        return content_list
    
    async def _generate_section_summaries(
        self, 
        sections: List[VGUSectionSummary],
        chunks: List[VGUChunk],
    ) -> List[VGUSectionSummary]:
        """Generate summaries for each section using LLM."""
        llm_client = self._get_llm_client()
        
        # Build chunk lookup
        chunk_lookup = {c.chunk_id: c for c in chunks}
        
        for section in sections:
            # Gather section content
            section_content = []
            for chunk_id in section.chunk_ids[:10]:  # Limit to first 10 chunks
                if chunk_id in chunk_lookup:
                    section_content.append(chunk_lookup[chunk_id].content)
            
            if not section_content:
                section.summary = section.section_path
                continue
            
            combined = "\n".join(section_content)[:2000]  # Limit context
            
            try:
                # Generate extractive summary
                prompt = f"""Summarize this section in 2-3 sentences. Focus on key concepts and definitions.

Section: {section.section_path}
Content:
{combined}

Summary:"""
                
                response = await llm_client.acomplete(prompt, max_tokens=150)
                section.summary = response.strip()
                
            except Exception as e:
                self.logger.warning(f"Failed to generate summary for {section.section_path}: {e}")
                section.summary = section.section_path
        
        return sections
    
    # =========================================================================
    # Initialization
    # =========================================================================
    
    async def initialize(
        self,
        kb_name: str,
        file_paths: List[str],
        extract_numbered_items: bool = True,
        **kwargs,
    ) -> bool:
        """
        Initialize knowledge base with two-tier indexing.
        
        Processing Flow:
        1. Parse documents (Docling/MinerU)
        2. Create chunks with page metadata
        3. Generate section summaries (coarse index)
        4. Embed and store both indexes
        5. Extract numbered items (definitions, theorems, etc.)
        
        Args:
            kb_name: Knowledge base name
            file_paths: List of document paths
            extract_numbered_items: Whether to extract numbered items
            **kwargs: Additional arguments
            
        Returns:
            True if successful
        """
        from ..components.routing import FileTypeRouter
        from ..utils.image_migration import (
            cleanup_parser_output_dirs,
            migrate_images_and_update_paths,
        )
        
        self.logger.info(f"[VGU] Initializing KB '{kb_name}' with {len(file_paths)} files")
        
        kb_dir = Path(self.kb_base_dir) / kb_name
        content_list_dir = kb_dir / "content_list"
        images_dir = kb_dir / "images"
        vgu_index_dir = kb_dir / "vgu_index"
        
        # Create directories
        for d in [content_list_dir, images_dir, vgu_index_dir]:
            d.mkdir(parents=True, exist_ok=True)
        
        # Classify files
        classification = FileTypeRouter.classify_files(file_paths)
        self.logger.info(
            f"[VGU] File classification: {len(classification.needs_mineru)} complex, "
            f"{len(classification.text_files)} text, {len(classification.unsupported)} unsupported"
        )
        
        all_chunks: List[VGUChunk] = []
        all_sections: List[VGUSectionSummary] = []
        
        with LightRAGLogContext(scene="knowledge_init"):
            rag = self._get_rag_instance(kb_name)
            await rag._ensure_lightrag_initialized()
            
            total_files = len(classification.needs_mineru) + len(classification.text_files)
            
            # Process complex files (PDF, DOCX)
            for idx, file_path in enumerate(classification.needs_mineru, 1):
                file_name = Path(file_path).name
                ext = Path(file_path).suffix.lower()
                doc_id = hashlib.md5(file_path.encode()).hexdigest()[:12]
                
                self.logger.info(f"[VGU] Processing [{idx}/{total_files}]: {file_name}")
                
                # The parser is selected in workspace Settings, independently of retrieval.
                from src.services.document_processing import parse_document
                parsed = await parse_document(file_path, str(images_dir))
                content_list = parsed["content_list"]
                images_list = parsed["images"]
                parser_used = parsed["parser"]
                for warning in parsed["warnings"]:
                    self.logger.warning(warning)

                # Step 2: Process images with vision model (if available)
                self.logger.info("  Step 2/4: Processing images...")
                if images_list:
                    content_list = await self._process_images_with_vision(
                        content_list, images_list, doc_id
                    )
                    self.logger.info(f"  ✓ Processed {len(images_list)} images")
                else:
                    self.logger.info("  → No images to process")
                
                # Save content list
                content_file = content_list_dir / f"{Path(file_path).stem}.json"
                with open(content_file, "w", encoding="utf-8") as f:
                    json.dump(content_list, f, ensure_ascii=False, indent=2)
                
                # Step 3: Create chunks with page metadata
                self.logger.info("  Step 3/4: Creating chunks with page tracking...")
                chunks, sections = await self._chunk_content_with_pages(
                    content_list, doc_id, file_name
                )
                all_chunks.extend(chunks)
                all_sections.extend(sections)
                
                # Step 4: Insert into RAG (for hybrid search)
                self.logger.info("  Step 4/4: Inserting into knowledge graph...")
                await rag.insert_content_list(
                    content_list=content_list,
                    file_path=file_path,
                    doc_id=doc_id,
                )
                
                self.logger.info(f"  ✓ Completed: {file_name} ({len(chunks)} chunks)")
            
            # Process text files
            for idx, file_path in enumerate(classification.text_files, len(classification.needs_mineru) + 1):
                file_name = Path(file_path).name
                doc_id = hashlib.md5(file_path.encode()).hexdigest()[:12]
                
                self.logger.info(f"[VGU] Processing [{idx}/{total_files}] (text): {file_name}")
                
                content = await FileTypeRouter.read_text_file(file_path)
                if content.strip():
                    # Simple chunking for text files
                    chunk = VGUChunk(
                        chunk_id=self._generate_chunk_id(doc_id, 1, 0),
                        content=content,
                        doc_id=doc_id,
                        doc_name=file_name,
                        page_start=1,
                        page_end=1,
                        section_path="Main",
                        chunk_type="text",
                    )
                    all_chunks.append(chunk)
                    
                    await rag.lightrag.ainsert(content)
            
            # Clean up parser output
            await cleanup_parser_output_dirs(content_list_dir)
        
        # Generate section summaries
        self.logger.info(f"[VGU] Generating summaries for {len(all_sections)} sections...")
        all_sections = await self._generate_section_summaries(all_sections, all_chunks)
        
        # Save VGU index
        self.logger.info("[VGU] Saving VGU index...")
        await self._save_vgu_index(kb_name, all_chunks, all_sections)
        
        # Extract numbered items
        if extract_numbered_items:
            await self._extract_numbered_items(kb_name)
        
        self.logger.info(
            f"[VGU] KB '{kb_name}' initialized: "
            f"{len(all_chunks)} chunks, {len(all_sections)} sections"
        )
        
        return True
    
    async def _save_vgu_index(
        self,
        kb_name: str,
        chunks: List[VGUChunk],
        sections: List[VGUSectionSummary],
    ):
        """Save VGU index to disk."""
        kb_dir = Path(self.kb_base_dir) / kb_name
        vgu_index_dir = kb_dir / "vgu_index"
        vgu_index_dir.mkdir(parents=True, exist_ok=True)
        
        # Save chunks index
        chunks_data = [
            {
                "chunk_id": c.chunk_id,
                "content": c.content,
                "doc_id": c.doc_id,
                "doc_name": c.doc_name,
                "page_start": c.page_start,
                "page_end": c.page_end,
                "section_path": c.section_path,
                "chunk_type": c.chunk_type,
                "metadata": c.metadata,
            }
            for c in chunks
        ]
        
        with open(vgu_index_dir / "chunks.json", "w", encoding="utf-8") as f:
            json.dump(chunks_data, f, ensure_ascii=False, indent=2)
        
        # Save sections index
        sections_data = [
            {
                "section_id": s.section_id,
                "doc_id": s.doc_id,
                "doc_name": s.doc_name,
                "section_path": s.section_path,
                "summary": s.summary,
                "page_start": s.page_start,
                "page_end": s.page_end,
                "chunk_ids": s.chunk_ids,
            }
            for s in sections
        ]
        
        with open(vgu_index_dir / "sections.json", "w", encoding="utf-8") as f:
            json.dump(sections_data, f, ensure_ascii=False, indent=2)
        
        # Save metadata
        metadata = {
            "created_at": datetime.now().isoformat(),
            "total_chunks": len(chunks),
            "total_sections": len(sections),
            "pipeline": "vgu_course",
            "settings": {
                "enable_reranker": self.enable_reranker,
                "reranker_model": self.reranker_model,
                "enable_multimodal": self.enable_multimodal,
                "coarse_top_k": self.coarse_top_k,
                "fine_top_k": self.fine_top_k,
                "final_top_k": self.final_top_k,
            }
        }
        
        with open(vgu_index_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    async def _load_vgu_index(
        self, 
        kb_name: str,
    ) -> Tuple[List[VGUChunk], List[VGUSectionSummary]]:
        """Load VGU index from disk."""
        kb_dir = Path(self.kb_base_dir) / kb_name
        vgu_index_dir = kb_dir / "vgu_index"
        
        chunks: List[VGUChunk] = []
        sections: List[VGUSectionSummary] = []
        
        # Load chunks
        chunks_file = vgu_index_dir / "chunks.json"
        if chunks_file.exists():
            with open(chunks_file, "r", encoding="utf-8") as f:
                chunks_data = json.load(f)
                chunks = [
                    VGUChunk(
                        chunk_id=c["chunk_id"],
                        content=c["content"],
                        doc_id=c["doc_id"],
                        doc_name=c["doc_name"],
                        page_start=c["page_start"],
                        page_end=c["page_end"],
                        section_path=c.get("section_path", ""),
                        chunk_type=c.get("chunk_type", "text"),
                        metadata=c.get("metadata", {}),
                    )
                    for c in chunks_data
                ]
        
        # Load sections
        sections_file = vgu_index_dir / "sections.json"
        if sections_file.exists():
            with open(sections_file, "r", encoding="utf-8") as f:
                sections_data = json.load(f)
                sections = [
                    VGUSectionSummary(
                        section_id=s["section_id"],
                        doc_id=s["doc_id"],
                        doc_name=s["doc_name"],
                        section_path=s["section_path"],
                        summary=s["summary"],
                        page_start=s["page_start"],
                        page_end=s["page_end"],
                        chunk_ids=s.get("chunk_ids", []),
                    )
                    for s in sections_data
                ]
        
        return chunks, sections

    def _get_vgu_index_dir(self, kb_name: str) -> Path:
        """Return VGU index directory for a KB."""
        return Path(self.kb_base_dir) / kb_name / "vgu_index"

    def _get_embedding_cache_path(self, kb_name: str, cache_type: str) -> Path:
        """Return embedding cache file path for chunks/sections."""
        if cache_type == "chunks":
            return self._get_vgu_index_dir(kb_name) / "chunk_embeddings.pkl"
        return self._get_vgu_index_dir(kb_name) / "section_embeddings.pkl"

    def _load_embeddings_from_disk(self, kb_name: str, cache_type: str) -> Dict[str, np.ndarray]:
        """Load persisted embeddings cache for a KB."""
        cache_path = self._get_embedding_cache_path(kb_name, cache_type)
        if not cache_path.exists():
            return {}

        try:
            with open(cache_path, "rb") as f:
                payload = pickle.load(f)

            ids = payload.get("ids", [])
            vectors = payload.get("vectors")
            if not isinstance(ids, list) or not isinstance(vectors, np.ndarray):
                return {}
            if len(ids) != len(vectors):
                return {}

            loaded = {cid: np.array(vec, dtype=np.float32) for cid, vec in zip(ids, vectors)}
            self.logger.info(f"[VGU] Loaded {len(loaded)} {cache_type} embeddings from disk")
            return loaded
        except Exception as e:
            self.logger.warning(f"[VGU] Failed to load {cache_type} embedding cache: {e}")
            return {}

    def _save_embeddings_to_disk(
        self,
        kb_name: str,
        cache_type: str,
        embeddings: Dict[str, np.ndarray],
    ):
        """Persist embeddings cache to disk for faster cold starts."""
        if not embeddings:
            return

        cache_path = self._get_embedding_cache_path(kb_name, cache_type)
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            ids = list(embeddings.keys())
            vectors = np.stack([np.array(embeddings[cid], dtype=np.float32) for cid in ids], axis=0)
            payload = {"ids": ids, "vectors": vectors}

            temp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
            with open(temp_path, "wb") as f:
                pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
            temp_path.replace(cache_path)
        except Exception as e:
            self.logger.warning(f"[VGU] Failed to save {cache_type} embedding cache: {e}")
    
    # =========================================================================
    # Search / Retrieval
    # =========================================================================
    
    async def search(
        self,
        query: str,
        kb_name: str,
        mode: str = "hybrid",
        only_need_context: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Two-tier retrieval with page-accurate citations.
        
        Retrieval Flow:
        1. Coarse search: Find relevant sections
        2. Fine search: Retrieve chunks within those sections
        3. Rerank: Cross-encoder reranking for precision
        4. Citation assembly: Build citations with page info
        
        Args:
            query: Search query
            kb_name: Knowledge base name
            mode: Search mode (hybrid, local, global, naive)
            only_need_context: Return only context without LLM answer
            **kwargs: Additional arguments
            
        Returns:
            Search results with citations
        """
        self.logger.info(f"[VGU] Searching KB '{kb_name}': {query[:50]}...")

        enable_query_expansion = kwargs.get("enable_query_expansion", self.enable_query_expansion)
        enable_hybrid_search = kwargs.get("enable_hybrid_search", self.enable_hybrid_search)
        enable_reranker = kwargs.get("enable_reranker", self.enable_reranker)
        coarse_top_k = int(kwargs.get("coarse_top_k", self.coarse_top_k))
        fine_top_k = int(kwargs.get("fine_top_k", self.fine_top_k))
        final_top_k = int(kwargs.get("final_top_k", self.final_top_k))
        self.logger.debug(
            "[VGU] Runtime retrieval config: "
            f"query_expansion={enable_query_expansion}, hybrid={enable_hybrid_search}, "
            f"reranker={enable_reranker}, coarse_k={coarse_top_k}, fine_k={fine_top_k}, final_k={final_top_k}"
        )
        
        # Load VGU index
        chunks, sections = await self._load_vgu_index(kb_name)
        
        if not chunks:
            self.logger.warning(f"[VGU] No chunks found for KB '{kb_name}', falling back to RAG")
            return await self._fallback_search(query, kb_name, mode, only_need_context)
        
        # Stage 0: Query Expansion (if enabled)
        expanded_query = query
        if enable_query_expansion:
            self.logger.debug("[VGU] Stage 0: Query expansion")
            expanded_query = await self._expand_query(query)
        
        # Stage 1: Coarse retrieval (find relevant sections) - NOW EMBEDDING-BASED
        self.logger.debug(f"[VGU] Stage 1: Embedding-based coarse retrieval ({len(sections)} sections)")
        relevant_section_ids = await self._coarse_search(
            expanded_query, sections, kb_name, top_k=coarse_top_k
        )
        
        # Stage 2: Fine retrieval (get chunks from relevant sections)
        self.logger.debug(f"[VGU] Stage 2: Fine retrieval from {len(relevant_section_ids)} sections")
        candidate_chunks = self._filter_chunks_by_sections(chunks, relevant_section_ids)
        
        # If no chunks found in sections, use all chunks
        if not candidate_chunks:
            candidate_chunks = chunks
        
        # Stage 3: Hybrid search (BM25 + Dense) on candidates
        if enable_hybrid_search:
            self.logger.debug(f"[VGU] Stage 3: Hybrid BM25+Dense search on {len(candidate_chunks)} candidates")
            ranked_chunks = await self._hybrid_search(expanded_query, candidate_chunks, kb_name, fine_top_k)
        else:
            self.logger.debug(f"[VGU] Stage 3: Dense search on {len(candidate_chunks)} candidates")
            ranked_chunks = await self._semantic_search(expanded_query, candidate_chunks, fine_top_k)
        
        # Stage 4: GPU-accelerated Reranking
        if enable_reranker and ranked_chunks:
            self.logger.debug(f"[VGU] Stage 4: GPU reranking {len(ranked_chunks)} chunks on {self.device}")
            ranked_chunks = self._rerank_chunks(
                expanded_query,
                ranked_chunks,
                final_top_k,
                enable_reranker=enable_reranker,
            )
        else:
            ranked_chunks = ranked_chunks[:final_top_k]
        
        # Build context and citations
        context_parts = []
        citations = []
        
        for i, chunk in enumerate(ranked_chunks):
            context_parts.append(f"[{i+1}] {chunk.content}")
            citations.append(chunk.to_citation(confidence=1.0 - (i * 0.05)))  # Smaller decay
        
        context = "\n\n".join(context_parts)
        
        if only_need_context:
            return VGUSearchResult(
                query=query,
                answer="",
                content=context,
                citations=citations,
                chunks=ranked_chunks,
                mode=mode,
                provider="vgu_course",
                metadata={"expanded_query": expanded_query if expanded_query != query else None},
            ).to_dict()

        # Generate answer with RAG. If LightRAG runtime fails, degrade gracefully
        # to retrieval-only synthesis so caller does not get a hard error.
        answer_source = "lightrag"
        try:
            with LightRAGLogContext(scene="rag_search"):
                rag = self._get_rag_instance(kb_name)
                await rag._ensure_lightrag_initialized()
                answer = await rag.aquery(expanded_query, mode=mode, only_need_context=False)
            answer_str = answer if isinstance(answer, str) else str(answer)
        except Exception as e:
            answer_source = "retrieval_fallback"
            self.logger.warning(
                f"[VGU] LightRAG answer generation failed; using retrieval fallback: {e}"
            )
            answer_str = self._build_retrieval_fallback_answer(query, ranked_chunks, citations)
        
        # Append citations to answer
        if citations:
            citation_str = "\n\n**Sources:**\n" + "\n".join(
                f"- {c}" for c in citations[:final_top_k]
            )
            answer_str += citation_str
        
        result = VGUSearchResult(
            query=query,
            answer=answer_str,
            content=context,
            citations=citations,
            chunks=ranked_chunks,
            mode=mode,
            provider="vgu_course",
            retrieval_scores={
                "coarse_sections": len(relevant_section_ids),
                "candidate_chunks": len(candidate_chunks),
                "final_chunks": len(ranked_chunks),
            },
            metadata={
                "expanded_query": expanded_query if expanded_query != query else None,
                "retrieval_config": {
                    "enable_query_expansion": enable_query_expansion,
                    "enable_hybrid_search": enable_hybrid_search,
                    "enable_reranker": enable_reranker,
                    "coarse_top_k": coarse_top_k,
                    "fine_top_k": fine_top_k,
                    "final_top_k": final_top_k,
                },
                "answer_source": answer_source,
            },
        )
        
        return result.to_dict()
    
    async def _coarse_search(
        self, 
        query: str, 
        sections: List[VGUSectionSummary],
        kb_name: str = "",
        top_k: Optional[int] = None,
    ) -> List[str]:
        """
        Embedding-based coarse search to find relevant sections.
        
        This is a MAJOR upgrade from keyword-based to semantic search.
        Uses cached section embeddings for efficiency.
        """
        if not sections:
            return []
        
        # Get or compute section embeddings
        cache_key = f"{kb_name}_sections" if kb_name else "sections"

        if cache_key not in self._section_embeddings:
            cached = {}
            if self.enable_embedding_cache and kb_name:
                cached = self._load_embeddings_from_disk(kb_name, "sections")
            self._section_embeddings[cache_key] = cached

        section_embeddings = self._section_embeddings[cache_key]

        # Compute embeddings for any uncached sections
        missing_sections = [s for s in sections if s.section_id not in section_embeddings]
        if missing_sections:
            embed_client = self._get_embed_client()
            section_texts = [f"{s.section_path}: {s.summary}" for s in missing_sections]

            try:
                embeddings = await embed_client.embed(section_texts)
                section_embeddings.update(
                    {s.section_id: np.array(emb) for s, emb in zip(missing_sections, embeddings)}
                )
                self.logger.info(f"[VGU] Cached {len(section_embeddings)} section embeddings")

                if self.enable_embedding_cache and kb_name:
                    self._save_embeddings_to_disk(kb_name, "sections", section_embeddings)
            except Exception as e:
                self.logger.warning(f"Failed to embed sections, using keyword fallback: {e}")
                return await self._coarse_search_keyword_fallback(query, sections, top_k=top_k)
        
        # Embed query
        embed_client = self._get_embed_client()
        try:
            query_embedding = await embed_client.embed([query])
            query_vec = np.array(query_embedding[0])
        except Exception as e:
            self.logger.warning(f"Failed to embed query: {e}")
            return await self._coarse_search_keyword_fallback(query, sections, top_k=top_k)
        
        # Calculate similarities
        scored_sections = []
        for section in sections:
            if section.section_id in section_embeddings:
                section_vec = section_embeddings[section.section_id]
                # Cosine similarity
                similarity = np.dot(query_vec, section_vec) / (
                    np.linalg.norm(query_vec) * np.linalg.norm(section_vec) + 1e-8
                )
                scored_sections.append((section.section_id, float(similarity)))
        
        # Sort by similarity and return top-k section IDs
        scored_sections.sort(key=lambda x: x[1], reverse=True)
        
        # Log top sections for debugging
        if scored_sections:
            top_scores = [f"{s[1]:.3f}" for s in scored_sections[:3]]
            self.logger.debug(f"[VGU] Top section scores: {top_scores}")
        
        top_k = top_k or self.coarse_top_k
        return [s[0] for s in scored_sections[:top_k]]
    
    async def _coarse_search_keyword_fallback(
        self, 
        query: str, 
        sections: List[VGUSectionSummary],
        top_k: Optional[int] = None,
    ) -> List[str]:
        """Keyword-based fallback for coarse search."""
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        scored_sections = []
        for section in sections:
            section_text = f"{section.section_path} {section.summary}".lower()
            section_words = set(section_text.split())
            
            overlap = len(query_words & section_words)
            if overlap > 0 or any(word in section_text for word in query_words):
                scored_sections.append((section.section_id, overlap))
        
        scored_sections.sort(key=lambda x: x[1], reverse=True)
        top_k = top_k or self.coarse_top_k
        return [s[0] for s in scored_sections[:top_k]]
    
    def _filter_chunks_by_sections(
        self,
        chunks: List[VGUChunk],
        section_ids: List[str],
    ) -> List[VGUChunk]:
        """Filter chunks to those belonging to specified sections."""
        if not section_ids:
            return chunks
        
        section_id_set = set(section_ids)
        return [
            c for c in chunks 
            if hashlib.md5(f"{c.doc_id}:{c.section_path}".encode()).hexdigest()[:12] in section_id_set
        ]
    
    # =========================================================================
    # Query Expansion
    # =========================================================================
    
    async def _expand_query(self, query: str) -> str:
        """
        Expand query using LLM for better retrieval coverage.
        
        This generates related terms and reformulations to improve recall.
        """
        try:
            llm_client = self._get_llm_client()
            
            prompt = f"""You are a query expansion expert for academic document search.
Given the user query, generate an expanded version that includes:
1. The original query
2. Key related terms and synonyms
3. Alternative phrasings

Keep the expansion concise (max 100 words). Output ONLY the expanded query, no explanations.

User query: {query}

Expanded query:"""

            response = await llm_client.acomplete(prompt, max_tokens=150)
            expanded = response.strip()
            
            # Sanity check: expanded shouldn't be too different
            if len(expanded) > len(query) * 5 or len(expanded) < len(query) // 2:
                return query
            
            self.logger.debug(f"[VGU] Query expanded: '{query[:30]}...' → '{expanded[:50]}...'")
            return expanded
            
        except Exception as e:
            self.logger.warning(f"Query expansion failed: {e}")
            return query
    
    # =========================================================================
    # Hybrid BM25 + Dense Search
    # =========================================================================
    
    def _build_bm25_index(self, chunks: List[VGUChunk], kb_name: str):
        """Build BM25 index for a knowledge base."""
        try:
            from rank_bm25 import BM25Okapi
            import re
            
            # Tokenize chunks
            def tokenize(text: str) -> List[str]:
                # Simple tokenization
                text = text.lower()
                tokens = re.findall(r'\b\w+\b', text)
                return tokens
            
            tokenized_chunks = [tokenize(c.content) for c in chunks]
            bm25 = BM25Okapi(tokenized_chunks)
            
            self._bm25_index[kb_name] = {
                "bm25": bm25,
                "tokenize": tokenize,
                "chunks": chunks,
            }
            self.logger.info(f"[VGU] Built BM25 index for {kb_name} ({len(chunks)} chunks)")
            
        except ImportError:
            self.logger.warning("rank_bm25 not installed. Install with: pip install rank-bm25")
            self._bm25_index[kb_name] = None
        except Exception as e:
            self.logger.warning(f"Failed to build BM25 index: {e}")
            self._bm25_index[kb_name] = None
    
    async def _hybrid_search(
        self,
        query: str,
        chunks: List[VGUChunk],
        kb_name: str,
        top_k: int,
        bm25_weight: float = 0.3,
        dense_weight: float = 0.7,
    ) -> List[VGUChunk]:
        """
        Hybrid search combining BM25 (sparse) and Dense (semantic) retrieval.
        
        This improves both precision (exact matches) and recall (semantic similarity).
        
        Args:
            query: Search query
            chunks: Candidate chunks
            kb_name: Knowledge base name
            top_k: Number of results
            bm25_weight: Weight for BM25 scores (default 0.3)
            dense_weight: Weight for dense scores (default 0.7)
        """
        if not chunks:
            return []
        
        # Build BM25 index if not exists
        if kb_name not in self._bm25_index:
            self._build_bm25_index(chunks, kb_name)
        
        # Get BM25 scores
        bm25_scores = {}
        bm25_data = self._bm25_index.get(kb_name)
        
        if bm25_data and bm25_data.get("bm25"):
            try:
                tokenize = bm25_data["tokenize"]
                bm25 = bm25_data["bm25"]
                query_tokens = tokenize(query)
                
                scores = bm25.get_scores(query_tokens)
                
                # Normalize BM25 scores
                max_score = max(scores) if max(scores) > 0 else 1
                for i, chunk in enumerate(chunks):
                    bm25_scores[chunk.chunk_id] = scores[i] / max_score
            except Exception as e:
                self.logger.warning(f"BM25 scoring failed: {e}")
        
        # Get Dense scores (semantic)
        embed_client = self._get_embed_client()
        
        # Check cache for chunk embeddings
        cache_key = f"{kb_name}_chunks"
        if cache_key not in self._embedding_cache:
            cached = {}
            if self.enable_embedding_cache and kb_name:
                cached = self._load_embeddings_from_disk(kb_name, "chunks")
            self._embedding_cache[cache_key] = cached

        chunk_embeddings = self._embedding_cache[cache_key]

        # Compute embeddings only for missing chunks.
        missing_chunks = [c for c in chunks if c.chunk_id not in chunk_embeddings]
        if missing_chunks:
            chunk_texts = [c.content for c in missing_chunks]
            try:
                embeddings = await embed_client.embed(chunk_texts)
                chunk_embeddings.update(
                    {c.chunk_id: np.array(emb) for c, emb in zip(missing_chunks, embeddings)}
                )
                self.logger.info(f"[VGU] Cached {len(chunk_embeddings)} chunk embeddings")

                if self.enable_embedding_cache and kb_name:
                    self._save_embeddings_to_disk(kb_name, "chunks", chunk_embeddings)
            except Exception as e:
                self.logger.warning(f"Failed to embed chunks: {e}")
        
        # Embed query
        try:
            query_embedding = await embed_client.embed([query])
            query_vec = np.array(query_embedding[0])
        except Exception as e:
            self.logger.warning(f"Failed to embed query: {e}")
            # Fallback to BM25 only
            if bm25_scores:
                scored = sorted(bm25_scores.items(), key=lambda x: x[1], reverse=True)
                chunk_map = {c.chunk_id: c for c in chunks}
                return [chunk_map[cid] for cid, _ in scored[:top_k] if cid in chunk_map]
            return chunks[:top_k]
        
        # Calculate dense scores
        dense_scores = {}
        for chunk in chunks:
            if chunk.chunk_id in chunk_embeddings:
                chunk_vec = chunk_embeddings[chunk.chunk_id]
                similarity = np.dot(query_vec, chunk_vec) / (
                    np.linalg.norm(query_vec) * np.linalg.norm(chunk_vec) + 1e-8
                )
                dense_scores[chunk.chunk_id] = float(similarity)
            else:
                dense_scores[chunk.chunk_id] = 0.0
        
        # Normalize dense scores to [0, 1]
        if dense_scores:
            max_dense = max(dense_scores.values())
            min_dense = min(dense_scores.values())
            range_dense = max_dense - min_dense if max_dense != min_dense else 1
            for cid in dense_scores:
                dense_scores[cid] = (dense_scores[cid] - min_dense) / range_dense
        
        # Combine scores
        combined_scores = {}
        for chunk in chunks:
            cid = chunk.chunk_id
            bm25_s = bm25_scores.get(cid, 0.0)
            dense_s = dense_scores.get(cid, 0.0)
            combined_scores[cid] = bm25_weight * bm25_s + dense_weight * dense_s
        
        # Sort by combined score
        sorted_chunks = sorted(
            chunks, 
            key=lambda c: combined_scores.get(c.chunk_id, 0), 
            reverse=True
        )
        
        return sorted_chunks[:top_k]
    
    async def _semantic_search(
        self,
        query: str,
        chunks: List[VGUChunk],
        top_k: int,
    ) -> List[VGUChunk]:
        """Semantic search using embeddings with caching."""
        if not chunks:
            return []
        
        embed_client = self._get_embed_client()
        
        # Embed query
        query_embedding = await embed_client.embed([query])
        query_vec = np.array(query_embedding[0])
        
        # Embed chunks (batch) - use cache if available
        chunk_texts = [c.content for c in chunks]
        chunk_embeddings = await embed_client.embed(chunk_texts)
        
        # Calculate similarities
        scored_chunks = []
        for chunk, embedding in zip(chunks, chunk_embeddings):
            chunk_vec = np.array(embedding)
            # Cosine similarity
            similarity = np.dot(query_vec, chunk_vec) / (
                np.linalg.norm(query_vec) * np.linalg.norm(chunk_vec) + 1e-8
            )
            scored_chunks.append((chunk, similarity))
        
        # Sort by similarity
        scored_chunks.sort(key=lambda x: x[1], reverse=True)
        
        return [c for c, _ in scored_chunks[:top_k]]
    
    def _rerank_chunks(
        self,
        query: str,
        chunks: List[VGUChunk],
        top_k: int,
        enable_reranker: Optional[bool] = None,
    ) -> List[VGUChunk]:
        """Rerank chunks using cross-encoder."""
        reranker = self._get_reranker(force_enable=enable_reranker)
        if reranker is None:
            return chunks[:top_k]
        
        # Prepare pairs for reranking
        pairs = [(query, chunk.content) for chunk in chunks]
        
        try:
            scores = reranker.predict(pairs)
            
            # Sort by reranker score
            scored_chunks = list(zip(chunks, scores))
            scored_chunks.sort(key=lambda x: x[1], reverse=True)
            
            return [c for c, _ in scored_chunks[:top_k]]
            
        except Exception as e:
            self.logger.warning(f"Reranking failed: {e}")
            return chunks[:top_k]
    
    async def _fallback_search(
        self,
        query: str,
        kb_name: str,
        mode: str,
        only_need_context: bool,
    ) -> Dict[str, Any]:
        """Fallback to standard RAG search."""
        try:
            with LightRAGLogContext(scene="rag_search"):
                rag = self._get_rag_instance(kb_name)
                await rag._ensure_lightrag_initialized()
                answer = await rag.aquery(query, mode=mode, only_need_context=only_need_context)
            answer_str = answer if isinstance(answer, str) else str(answer)
        except Exception as e:
            self.logger.warning(
                f"[VGU] fallback_search could not run LightRAG query; "
                f"returning context-only summary: {e}"
            )
            answer_str = (
                "RAG answer generation is temporarily unavailable. "
                "Please re-process the knowledge base if this persists."
            )
        
        return {
            "query": query,
            "answer": answer_str,
            "content": answer_str,
            "citations": [],
            "mode": mode,
            "provider": "vgu_course",
        }

    def _build_retrieval_fallback_answer(
        self,
        query: str,
        chunks: List[VGUChunk],
        citations: List[str],
    ) -> str:
        if not chunks:
            return (
                "Unable to generate an LLM-grounded answer from LightRAG at the moment. "
                "No retrieved chunks were available."
            )

        lines = [
            f"LightRAG generation is unavailable for query: {query}",
            "Using retrieved course excerpts as a temporary fallback:",
        ]

        for index, chunk in enumerate(chunks[:5], start=1):
            snippet = " ".join(str(chunk.content or "").split())
            if len(snippet) > 320:
                snippet = f"{snippet[:317].rstrip()}..."
            lines.append(f"{index}. {snippet}")

        if citations:
            lines.append("\nEvidence references:")
            for citation in citations[:5]:
                lines.append(f"- {citation}")

        return "\n".join(lines)
    
    # =========================================================================
    # Numbered Items Extraction
    # =========================================================================
    
    async def _extract_numbered_items(self, kb_name: str):
        """Extract numbered items (definitions, theorems, etc.)."""
        try:
            from src.knowledge.extract_numbered_items import (
                extract_numbered_items_with_llm_async,
            )
            
            kb_dir = Path(self.kb_base_dir) / kb_name
            content_list_dir = kb_dir / "content_list"
            
            if not content_list_dir.exists():
                return
            
            all_content_items = []
            for json_file in content_list_dir.glob("*.json"):
                with open(json_file, "r", encoding="utf-8") as f:
                    content_items = json.load(f)
                    all_content_items.extend(content_items)
            
            if not all_content_items:
                return
            
            self.logger.info(f"[VGU] Extracting numbered items from {len(all_content_items)} items")
            
            llm_client = self._get_llm_client()
            items = await extract_numbered_items_with_llm_async(
                all_content_items,
                api_key=llm_client.config.api_key,
                base_url=llm_client.config.base_url,
            )
            
            if items:
                output_file = kb_dir / "numbered_items.json"
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(items, f, ensure_ascii=False, indent=2)
                self.logger.info(f"[VGU] Extracted {len(items)} numbered items")
                
        except Exception as e:
            self.logger.warning(f"[VGU] Failed to extract numbered items: {e}")
    
    # =========================================================================
    # Deletion
    # =========================================================================
    
    async def delete(self, kb_name: str) -> bool:
        """Delete knowledge base."""
        import shutil
        
        kb_dir = Path(self.kb_base_dir) / kb_name
        working_dir = str(kb_dir / "rag_storage")
        
        # Remove from cache
        if working_dir in self._rag_instances:
            del self._rag_instances[working_dir]
        
        # Delete directory
        if kb_dir.exists():
            shutil.rmtree(kb_dir)
            self.logger.info(f"[VGU] Deleted KB '{kb_name}'")
            return True
        
        return False

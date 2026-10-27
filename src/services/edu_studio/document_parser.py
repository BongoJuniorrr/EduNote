# -*- coding: utf-8 -*-
"""
Edu Studio document parser utilities.

Parses user-uploaded materials into plain text for agent workflows.
"""

import csv
import json
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, List

from src.logging import get_logger

logger = get_logger("EduStudioParser")

MAX_CONTENT_CHARS_PER_FILE = 30_000


@dataclass
class ParsedMaterial:
    """Parsed material payload used by Edu Studio workflows."""

    filename: str
    content: str
    content_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _truncate(text: str, max_chars: int = MAX_CONTENT_CHARS_PER_FILE) -> str:
    if len(text) <= max_chars:
        return text
    head = text[: int(max_chars * 0.75)]
    tail = text[-int(max_chars * 0.2) :]
    omitted = len(text) - len(head) - len(tail)
    return (
        f"{head}\n\n[... omitted {omitted} characters for context limit ...]\n\n{tail}"
    )


def _parse_text_like(raw: bytes, encoding: str = "utf-8") -> str:
    return raw.decode(encoding, errors="ignore").strip()


def _parse_json(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="ignore")
    parsed = json.loads(text)
    return json.dumps(parsed, ensure_ascii=False, indent=2)


def _parse_csv(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="ignore")
    reader = csv.reader(text.splitlines())
    rows = []
    for idx, row in enumerate(reader):
        rows.append(row)
        if idx >= 80:
            break

    if not rows:
        return ""

    max_cols = max(len(row) for row in rows)
    normalized = [row + [""] * (max_cols - len(row)) for row in rows]
    header = normalized[0]
    lines = [" | ".join(header), " | ".join(["---"] * max_cols)]
    for row in normalized[1:]:
        lines.append(" | ".join(row))
    return "\n".join(lines)


def _parse_pdf(raw: bytes) -> tuple[str, dict[str, Any]]:
    try:
        import fitz  # PyMuPDF
    except Exception as e:  # pragma: no cover - optional dependency
        raise RuntimeError("PyMuPDF is not available for PDF parsing") from e

    sections: list[str] = []
    metadata: dict[str, Any] = {}
    with fitz.open(stream=raw, filetype="pdf") as doc:
        metadata["pages"] = doc.page_count
        for page_index, page in enumerate(doc):
            page_text = page.get_text("text").strip()
            if page_text:
                sections.append(f"## Page {page_index + 1}\n{page_text}")
    return "\n\n".join(sections), metadata


def _parse_docx(raw: bytes) -> tuple[str, dict[str, Any]]:
    try:
        from docx import Document
    except Exception as e:  # pragma: no cover - optional dependency
        raise RuntimeError("python-docx is not available for DOCX parsing") from e

    doc = Document(BytesIO(raw))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    return "\n\n".join(paragraphs), {"paragraphs": len(paragraphs)}


def parse_uploaded_material(
    filename: str,
    raw: bytes,
    content_type: str | None = None,
) -> ParsedMaterial:
    """
    Parse uploaded material to plain text.
    """
    ext = Path(filename).suffix.lower()
    warnings: list[str] = []
    metadata: dict[str, Any] = {}

    try:
        if ext in {".txt", ".md", ".markdown", ".rst"}:
            content = _parse_text_like(raw)
        elif ext in {".json"}:
            content = _parse_json(raw)
        elif ext in {".csv", ".tsv"}:
            content = _parse_csv(raw)
        elif ext in {".pdf"}:
            content, parsed_meta = _parse_pdf(raw)
            metadata.update(parsed_meta)
        elif ext in {".docx"}:
            content, parsed_meta = _parse_docx(raw)
            metadata.update(parsed_meta)
        else:
            # Fallback for unsupported file types
            content = _parse_text_like(raw)
            if not content:
                warnings.append(
                    f"Unsupported or binary file '{filename}'. No text could be extracted."
                )
    except Exception as e:
        logger.warning(f"Failed to parse {filename}: {e}")
        content = ""
        warnings.append(f"Failed to parse '{filename}': {e}")

    if not content:
        warnings.append(f"No extractable text found in '{filename}'.")

    content = _truncate(content)

    return ParsedMaterial(
        filename=filename,
        content=content,
        content_type=content_type or "",
        metadata=metadata,
        warnings=warnings,
    )


def combine_materials_text(
    source_text: str,
    materials: List[ParsedMaterial] | None = None,
) -> str:
    """
    Build a normalized context block for Edu Studio workflows.
    """
    sections: list[str] = []
    if source_text and source_text.strip():
        sections.append("## User Input\n" + source_text.strip())

    for material in materials or []:
        if not material.content:
            continue
        sections.append(
            f"## Material: {material.filename}\n{material.content.strip()}"
        )

    return "\n\n".join(sections).strip()

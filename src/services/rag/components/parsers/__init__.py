# -*- coding: utf-8 -*-
"""
Document Parsers
================

Parsers for extracting content from various document formats.
"""

from .base import BaseParser
from .markdown import MarkdownParser
from .pdf import PDFParser
from .text import TextParser

__all__ = [
    "BaseParser",
    "PDFParser",
    "MarkdownParser",
    "TextParser",
]

# MinerU parser is imported lazily to avoid import errors when MinerU is not installed
# Usage: from src.services.rag.components.parsers.mineru import parse_pdf_with_mineru

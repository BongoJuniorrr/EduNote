# -*- coding: utf-8 -*-
"""
VGU Course Agent Module
=======================

Agents optimized for long academic documents with page-accurate citations.

Features:
- Two-tier retrieval (coarse sections → fine chunks)
- Page-accurate citations
- Cross-encoder reranking
- Multimodal support (images, tables, equations)

Usage:
    from src.agents.vgu_course import VGUCourseAgent
    
    agent = VGUCourseAgent(kb_name="my_course")
    result = await agent.answer("What is machine learning?")
"""

from .agent import VGUCourseAgent
from .tools import VGURAGTool

__all__ = [
    "VGUCourseAgent",
    "VGURAGTool",
]

"""
Agents Module - Unified agent system for EduNote.

This module provides a unified BaseAgent class and module-specific agents:
- solve: Question solving agents (MainSolver, SolveAgent, etc.)
- research: Deep research agents (DecomposeAgent, ResearchAgent, etc.)
- guide: Guided learning agents (ChatAgent, LocateAgent, etc.)
- ideagen: Idea generation agents (IdeaGenerationWorkflow, etc.)
- co_writer: Co-writing agents (EditAgent, NarratorAgent)
- question: Question generation agents (ReAct architecture, separate base)
- chat: Lightweight conversational agent with session management

Usage:
    from src.agents.base_agent import BaseAgent

    class MyAgent(BaseAgent):
        async def process(self, *args, **kwargs):
            ...
"""

import importlib

__all__ = ["BaseAgent", "ChatAgent", "SessionManager"]


def __getattr__(name: str):
    if name == "BaseAgent":
        return importlib.import_module(f"{__name__}.base_agent").BaseAgent
    if name in {"ChatAgent", "SessionManager"}:
        chat_module = importlib.import_module(f"{__name__}.chat")
        return getattr(chat_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

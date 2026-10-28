"""
Chat API Router
================

WebSocket endpoint for lightweight chat with session management.
REST endpoints for session operations.
"""

import asyncio
import contextlib
from pathlib import Path
import sys
import time

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

_project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_project_root))

from src.agents.chat import ChatAgent, SessionManager
from src.logging import get_logger
from src.security.auth import (
    AuthenticatedUser,
    get_current_user,
    get_current_websocket_user,
)
from src.services.config import load_config_with_main
from src.services.llm.config import get_llm_config
from src.services.settings.interface_settings import get_ui_language

# Initialize logger
project_root = Path(__file__).parent.parent.parent.parent
config = load_config_with_main("solve_config.yaml", project_root)
log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get("log_dir")
logger = get_logger("ChatAPI", level="INFO", log_dir=log_dir)

router = APIRouter()

# Initialize session manager
session_manager = SessionManager()


# =============================================================================
# REST Endpoints for Session Management
# =============================================================================


@router.get("/chat/sessions")
async def list_sessions(limit: int = 20, user: AuthenticatedUser = Depends(get_current_user)):
    """
    List recent chat sessions.

    Args:
        limit: Maximum number of sessions to return

    Returns:
        List of session summaries
    """
    return session_manager.list_sessions(limit=limit, include_messages=False)


@router.get("/chat/sessions/{session_id}")
async def get_session(session_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    """
    Get a specific chat session with full message history.

    Args:
        session_id: Session identifier

    Returns:
        Complete session data including messages
    """
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.delete("/chat/sessions/{session_id}")
async def delete_session(session_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    """
    Delete a chat session.

    Args:
        session_id: Session identifier

    Returns:
        Success message
    """
    if session_manager.delete_session(session_id):
        return {"status": "deleted", "session_id": session_id}
    raise HTTPException(status_code=404, detail="Session not found")


# =============================================================================
# WebSocket Endpoint for Chat
# =============================================================================


@router.websocket("/chat")
async def websocket_chat(websocket: WebSocket):
    """
    WebSocket endpoint for chat with session and context management.

    Message format:
    {
        "message": str,              # User message
        "session_id": str | null,    # Session ID (null for new session)
        "history": [...] | null,     # Optional: explicit history override
        "kb_name": str,              # Knowledge base name (for RAG)
        "enable_rag": bool,          # Enable RAG retrieval
        "enable_web_search": bool    # Enable Web Search
    }

    Response format:
    - {"type": "session", "session_id": str}           # Session ID (new or existing)
    - {"type": "status", "stage": str, "message": str} # Status updates
    - {"type": "stream", "content": str}               # Streaming response chunks
    - {"type": "sources", "rag": list, "web": list}    # Source citations
    - {"type": "result", "content": str}               # Final complete response
    - {"type": "error", "message": str}                # Error message
    """
    await websocket.accept()
    try:
        user = await get_current_websocket_user(websocket)
    except HTTPException as error:
        await websocket.close(code=4401, reason=error.detail)
        return

    async def heartbeat_sender(interval_sec: int = 15):
        """Send lightweight status updates to keep long-running WS requests alive."""
        while True:
            await asyncio.sleep(interval_sec)
            await websocket.send_json(
                {
                    "type": "status",
                    "stage": "processing",
                    "message": "Still processing...",
                }
            )

    try:
        while True:
            # Receive message
            data = await websocket.receive_json()
            # Use current UI language (fallback to config/main.yaml system.language)
            language = get_ui_language(default=config.get("system", {}).get("language", "en"))
            message = data.get("message", "").strip()
            session_id = data.get("session_id")
            explicit_history = data.get("history")  # Optional override
            kb_name = data.get("kb_name", "")
            enable_rag = data.get("enable_rag", False)
            enable_web_search = data.get("enable_web_search", False)

            if not message:
                await websocket.send_json({"type": "error", "message": "Message is required"})
                continue

            logger.info(
                f"Chat request: session={session_id}, "
                f"message={message[:50]}..., rag={enable_rag}, web={enable_web_search}"
            )

            try:
                request_start = time.perf_counter()
                session_stage_start = time.perf_counter()

                # Get or create session
                if session_id:
                    session = session_manager.get_session(session_id)
                    if not session:
                        # Session not found, create new one
                        session = session_manager.create_session(
                            title=message[:50] + ("..." if len(message) > 50 else ""),
                            settings={
                                "kb_name": kb_name,
                                "enable_rag": enable_rag,
                                "enable_web_search": enable_web_search,
                            },
                        )
                        session_id = session["session_id"]
                else:
                    # Create new session
                    session = session_manager.create_session(
                        title=message[:50] + ("..." if len(message) > 50 else ""),
                        settings={
                            "kb_name": kb_name,
                            "enable_rag": enable_rag,
                            "enable_web_search": enable_web_search,
                        },
                    )
                    session_id = session["session_id"]

                # Send session ID to frontend
                await websocket.send_json(
                    {
                        "type": "session",
                        "session_id": session_id,
                    }
                )

                # Build history from session or explicit override
                if explicit_history is not None:
                    history = explicit_history
                else:
                    # Get history from session messages
                    history = [
                        {"role": msg["role"], "content": msg["content"]}
                        for msg in session.get("messages", [])
                    ]

                # Add user message to session
                session_manager.add_message(
                    session_id=session_id,
                    role="user",
                    content=message,
                )
                session_stage_elapsed = time.perf_counter() - session_stage_start

                # Initialize ChatAgent
                try:
                    llm_config = get_llm_config()
                    api_key = llm_config.api_key
                    base_url = llm_config.base_url
                    api_version = getattr(llm_config, "api_version", None)
                except Exception:
                    api_key = None
                    base_url = None
                    api_version = None

                agent = ChatAgent(
                    language=language,
                    config=config,
                    api_key=api_key,
                    base_url=base_url,
                    api_version=api_version,
                )
                logger.info(
                    f"Chat session/history ready: session={session_id}, "
                    f"history={len(history)}, elapsed={session_stage_elapsed:.2f}s"
                )

                # Send status updates
                if enable_rag and kb_name:
                    await websocket.send_json(
                        {
                            "type": "status",
                            "stage": "rag",
                            "message": f"Searching knowledge base: {kb_name}...",
                        }
                    )

                if enable_web_search:
                    await websocket.send_json(
                        {
                            "type": "status",
                            "stage": "web",
                            "message": "Searching the web...",
                        }
                    )

                await websocket.send_json(
                    {
                        "type": "status",
                        "stage": "generating",
                        "message": "Generating response...",
                    }
                )

                # Process with streaming
                full_response = ""
                sources = {"rag": [], "web": []}

                heartbeat_task = asyncio.create_task(heartbeat_sender())
                generation_stage_start = time.perf_counter()
                try:
                    stream_generator = await agent.process(
                        message=message,
                        history=history,
                        kb_name=kb_name,
                        enable_rag=enable_rag,
                        enable_web_search=enable_web_search,
                        stream=True,
                    )

                    async for chunk_data in stream_generator:
                        if chunk_data["type"] == "chunk":
                            await websocket.send_json(
                                {
                                    "type": "stream",
                                    "content": chunk_data["content"],
                                }
                            )
                            full_response += chunk_data["content"]
                        elif chunk_data["type"] == "complete":
                            full_response = chunk_data["response"]
                            sources = chunk_data.get("sources", {"rag": [], "web": []})
                finally:
                    heartbeat_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await heartbeat_task
                generation_stage_elapsed = time.perf_counter() - generation_stage_start

                # Send sources if any
                send_stage_start = time.perf_counter()
                if sources.get("rag") or sources.get("web"):
                    await websocket.send_json({"type": "sources", **sources})

                # Send final result
                await websocket.send_json(
                    {
                        "type": "result",
                        "content": full_response,
                    }
                )
                send_stage_elapsed = time.perf_counter() - send_stage_start

                # Save assistant message to session
                session_manager.add_message(
                    session_id=session_id,
                    role="assistant",
                    content=full_response,
                    sources=sources if (sources.get("rag") or sources.get("web")) else None,
                )

                total_elapsed = time.perf_counter() - request_start
                logger.info(
                    f"Chat completed: session={session_id}, {len(full_response)} chars, "
                    f"rag_sources={len(sources.get('rag', []))}, "
                    f"web_sources={len(sources.get('web', []))}, "
                    f"generation={generation_stage_elapsed:.2f}s, ws_send={send_stage_elapsed:.2f}s, "
                    f"total={total_elapsed:.2f}s"
                )

            except WebSocketDisconnect:
                logger.info("Client disconnected during chat processing")
                break
            except Exception as e:
                logger.exception(f"Chat processing error: {e}")
                try:
                    await websocket.send_json({"type": "error", "message": str(e)})
                except (RuntimeError, WebSocketDisconnect, ConnectionError):
                    break

    except WebSocketDisconnect:
        logger.debug("Client disconnected from chat")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except (RuntimeError, WebSocketDisconnect, ConnectionError):
            pass

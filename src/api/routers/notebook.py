"""
Notebook API Router
Provides notebook creation, querying, updating, deletion, and record management functions
"""

from pathlib import Path
import sys
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# Ensure module can be imported
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.api.utils.notebook_manager import notebook_manager
from src.services.notebook_canvas import notebook_canvas_service

router = APIRouter()


# === Request/Response Models ===


class CreateNotebookRequest(BaseModel):
    """Create notebook request"""

    name: str
    description: str = ""
    color: str = "#3B82F6"
    icon: str = "book"


class UpdateNotebookRequest(BaseModel):
    """Update notebook request"""

    name: str | None = None
    description: str | None = None
    color: str | None = None
    icon: str | None = None


class AddRecordRequest(BaseModel):
    """Add record request"""

    notebook_ids: list[str]
    record_type: Literal[
        "solve", "question", "research", "co_writer", "chat", "note", "canvas", "slide_pro"
    ]
    title: str
    user_query: str
    output: str
    metadata: dict = Field(default_factory=dict)
    kb_name: str | None = None


class RemoveRecordRequest(BaseModel):
    """Remove record request"""

    record_id: str


class AddSingleRecordRequest(BaseModel):
    """Add a single record into one notebook"""

    type: Literal[
        "solve", "question", "research", "co_writer", "chat", "note", "canvas", "slide_pro"
    ]
    title: str
    user_query: str
    output: str
    metadata: dict = Field(default_factory=dict)
    kb_name: str | None = None


class ImportRecordsRequest(BaseModel):
    """Batch import records into a notebook"""

    records: list[AddSingleRecordRequest]


class UpdateManualNoteRequest(BaseModel):
    """Update a manual note record"""

    title: str
    content: str


class CanvasCreateSessionRequest(BaseModel):
    title: str = ""
    notebook_id: str | None = None


class CanvasStrokesBatchRequest(BaseModel):
    page_index: int = 0
    strokes: list[dict] = Field(default_factory=list)
    overlays: list[dict] = Field(default_factory=list)
    layers: list[dict] | None = None
    dirty_regions: list[dict] = Field(default_factory=list)
    snapshot_data_url: str | None = None
    replace_page: bool = False


class CanvasConfirmRequest(BaseModel):
    block_updates: list[dict] = Field(default_factory=list)


class CanvasCommitRequest(BaseModel):
    notebook_id: str
    title: str = ""
    user_query: str = ""
    force_commit: bool = False


# === API Endpoints ===


@router.get("/list")
async def list_notebooks():
    """
    Get all notebook list

    Returns:
        Notebook list (includes summary information)
    """
    try:
        notebooks = notebook_manager.list_notebooks()
        return {"notebooks": notebooks, "total": len(notebooks)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/statistics")
async def get_statistics():
    """
    Get notebook statistics

    Returns:
        Statistics information
    """
    try:
        stats = notebook_manager.get_statistics()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """Health check"""
    return {"status": "healthy", "service": "notebook"}


@router.post("/create")
async def create_notebook(request: CreateNotebookRequest):
    """
    Create new notebook

    Args:
        request: Create request

    Returns:
        Created notebook information
    """
    try:
        notebook = notebook_manager.create_notebook(
            name=request.name,
            description=request.description,
            color=request.color,
            icon=request.icon,
        )
        return {"success": True, "notebook": notebook}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/canvas/sessions")
async def create_canvas_session(request: CanvasCreateSessionRequest):
    """Create a draft Advanced Notebook Canvas session."""
    try:
        session = notebook_canvas_service.create_session(
            title=request.title,
            notebook_id=request.notebook_id,
        )
        return {"success": True, "session": session}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/canvas/sessions/{session_id}")
async def get_canvas_session(session_id: str):
    """Get Advanced Notebook Canvas session details."""
    try:
        session = notebook_canvas_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Canvas session not found")
        return {"success": True, "session": session}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/canvas/sessions/{session_id}/strokes:batch")
async def add_canvas_strokes_batch(session_id: str, request: CanvasStrokesBatchRequest):
    """Store stroke/layer batch for a canvas session."""
    try:
        session = notebook_canvas_service.add_strokes_batch(
            session_id=session_id,
            page_index=request.page_index,
            strokes=request.strokes,
            overlays=request.overlays,
            layers=request.layers,
            dirty_regions=request.dirty_regions,
            snapshot_data_url=request.snapshot_data_url,
            replace_page=request.replace_page,
        )
        return {"success": True, "session": session}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/canvas/sessions/{session_id}/process")
async def process_canvas_session(session_id: str):
    """Run OCR -> structure -> linking -> quality pipeline."""
    try:
        session = await notebook_canvas_service.process_session(session_id)
        return {
            "success": True,
            "session": session,
            "quality": session.get("quality", {}),
            "review_issues": session.get("review_issues", []),
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/canvas/sessions/{session_id}/confirm")
async def confirm_canvas_session(session_id: str, request: CanvasConfirmRequest):
    """Apply user confirmations for low-confidence OCR blocks."""
    try:
        session = notebook_canvas_service.confirm_blocks(session_id, request.block_updates)
        return {
            "success": True,
            "session": session,
            "review_issues": session.get("review_issues", []),
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/canvas/sessions/{session_id}/commit")
async def commit_canvas_session(session_id: str, request: CanvasCommitRequest):
    """Commit canvas session as a notebook record with type=canvas."""
    try:
        payload = notebook_canvas_service.commit_session(
            session_id=session_id,
            notebook_id=request.notebook_id,
            title=request.title,
            user_query=request.user_query,
            force_commit=request.force_commit,
        )
        return {"success": True, **payload}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{notebook_id}")
async def get_notebook(notebook_id: str):
    """
    Get notebook details

    Args:
        notebook_id: Notebook ID

    Returns:
        Notebook details (includes all records)
    """
    try:
        notebook = notebook_manager.get_notebook(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")
        return notebook
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{notebook_id}")
async def update_notebook(notebook_id: str, request: UpdateNotebookRequest):
    """
    Update notebook information

    Args:
        notebook_id: Notebook ID
        request: Update request

    Returns:
        Updated notebook information
    """
    try:
        notebook = notebook_manager.update_notebook(
            notebook_id=notebook_id,
            name=request.name,
            description=request.description,
            color=request.color,
            icon=request.icon,
        )
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")
        return {"success": True, "notebook": notebook}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{notebook_id}")
async def delete_notebook(notebook_id: str):
    """
    Delete notebook

    Args:
        notebook_id: Notebook ID

    Returns:
        Deletion result
    """
    try:
        success = notebook_manager.delete_notebook(notebook_id)
        if not success:
            raise HTTPException(status_code=404, detail="Notebook not found")
        return {"success": True, "message": "Notebook deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/add_record")
async def add_record(request: AddRecordRequest):
    """
    Add record to notebook

    Args:
        request: Add record request

    Returns:
        Addition result
    """
    try:
        result = notebook_manager.add_record(
            notebook_ids=request.notebook_ids,
            record_type=request.record_type,
            title=request.title,
            user_query=request.user_query,
            output=request.output,
            metadata=request.metadata,
            kb_name=request.kb_name,
        )
        return {
            "success": True,
            "record": result["record"],
            "added_to_notebooks": result["added_to_notebooks"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{notebook_id}/records")
async def add_record_to_notebook(notebook_id: str, request: AddSingleRecordRequest):
    """
    Add one record to a specific notebook.

    This endpoint keeps compatibility with legacy frontend flows that post to
    `/api/v1/notebook/{notebook_id}/records`.
    """
    try:
        result = notebook_manager.add_record(
            notebook_ids=[notebook_id],
            record_type=request.type,
            title=request.title,
            user_query=request.user_query,
            output=request.output,
            metadata=request.metadata,
            kb_name=request.kb_name,
        )
        if notebook_id not in result["added_to_notebooks"]:
            raise HTTPException(status_code=404, detail="Notebook not found")
        return {
            "success": True,
            "record": result["record"],
            "added_to_notebooks": result["added_to_notebooks"],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{notebook_id}/records/import")
async def import_records_to_notebook(notebook_id: str, request: ImportRecordsRequest):
    """
    Import multiple records into a specific notebook.
    """
    if not request.records:
        raise HTTPException(status_code=400, detail="No records provided")

    imported = []
    try:
        for record in request.records:
            result = notebook_manager.add_record(
                notebook_ids=[notebook_id],
                record_type=record.type,
                title=record.title,
                user_query=record.user_query,
                output=record.output,
                metadata=record.metadata,
                kb_name=record.kb_name,
            )
            if notebook_id in result["added_to_notebooks"]:
                imported.append(result["record"])

        if not imported:
            raise HTTPException(status_code=404, detail="Notebook not found")

        return {
            "success": True,
            "imported_count": len(imported),
            "records": imported,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{notebook_id}/records/{record_id}/manual_note")
async def update_manual_note(
    notebook_id: str, record_id: str, request: UpdateManualNoteRequest
):
    """
    Update a manual note only (record type=note and source=manual_note).
    """
    title = request.title.strip()
    content = request.content.strip()
    if not title or not content:
        raise HTTPException(status_code=400, detail="Title and content are required")

    try:
        record, reason = notebook_manager.update_manual_note(
            notebook_id=notebook_id,
            record_id=record_id,
            title=title,
            content=content,
        )
        if reason == "notebook_not_found":
            raise HTTPException(status_code=404, detail="Notebook not found")
        if reason == "record_not_found":
            raise HTTPException(status_code=404, detail="Record not found")
        if reason == "forbidden":
            raise HTTPException(
                status_code=403,
                detail="Only manual notes can be edited by this endpoint",
            )
        return {"success": True, "record": record}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{notebook_id}/records/{record_id}/manual_note")
async def remove_manual_note(notebook_id: str, record_id: str):
    """
    Remove a manual note only (record type=note and source=manual_note).
    """
    try:
        success, reason = notebook_manager.remove_manual_note(notebook_id, record_id)
        if reason == "notebook_not_found":
            raise HTTPException(status_code=404, detail="Notebook not found")
        if reason == "record_not_found":
            raise HTTPException(status_code=404, detail="Record not found")
        if reason == "forbidden":
            raise HTTPException(
                status_code=403,
                detail="Only manual notes can be deleted by this endpoint",
            )
        return {"success": success, "message": "Manual note removed successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{notebook_id}/records/{record_id}")
async def remove_record(notebook_id: str, record_id: str):
    """
    Remove record from notebook

    Args:
        notebook_id: Notebook ID
        record_id: Record ID

    Returns:
        Deletion result
    """
    try:
        success = notebook_manager.remove_record(notebook_id, record_id)
        if not success:
            raise HTTPException(status_code=404, detail="Record not found")
        return {"success": True, "message": "Record removed successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

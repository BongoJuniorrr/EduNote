"""
Knowledge Base API Router
=========================

Handles knowledge base CRUD operations, file uploads, and initialization.
"""

import asyncio
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
import traceback

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel

from src.api.utils.progress_broadcaster import ProgressBroadcaster
from src.api.utils.task_id_manager import TaskIDManager
from src.knowledge.add_documents import DocumentAdder
from src.knowledge.initializer import KnowledgeBaseInitializer
from src.knowledge.manager import KnowledgeBaseManager
from src.knowledge.progress_tracker import ProgressStage, ProgressTracker
from src.utils.document_validator import DocumentValidator
from src.utils.error_utils import format_exception_message

_project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_project_root))
from src.logging import get_logger
from src.security.auth import AuthenticatedUser, get_optional_current_user
from src.services.config import load_config_with_main
from src.services.llm import get_llm_config
from src.services.queue import get_job_store

# Initialize logger with config
project_root = Path(__file__).parent.parent.parent.parent
config = load_config_with_main("solve_config.yaml", project_root)  # Use any config to get main.yaml
log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get("log_dir")
logger = get_logger("Knowledge", level="INFO", log_dir=log_dir)

router = APIRouter()

# Constants for byte conversions
BYTES_PER_GB = 1024**3
BYTES_PER_MB = 1024**2


def format_bytes_human_readable(size_bytes: int) -> str:
    """Format bytes into human-readable string (GB, MB, or bytes)."""
    if size_bytes >= BYTES_PER_GB:
        return f"{size_bytes / BYTES_PER_GB:.1f} GB"
    elif size_bytes >= BYTES_PER_MB:
        return f"{size_bytes / BYTES_PER_MB:.1f} MB"
    else:
        return f"{size_bytes} bytes"


_kb_base_dir = _project_root / "data" / "knowledge_bases"

# Lazy initialization, keyed by workspace root.
kb_managers = {}


def get_kb_base_dir() -> Path:
    return _kb_base_dir


def get_kb_manager():
    """Get the manager for the personal knowledge-base directory."""
    base_dir = get_kb_base_dir()
    key = str(base_dir.resolve())
    if key not in kb_managers:
        kb_managers[key] = KnowledgeBaseManager(base_dir=key)
    return kb_managers[key]


async def save_uploaded_document(upload: UploadFile, directory: Path) -> Path:
    """Validate and atomically replace an upload within its raw directory."""
    directory.mkdir(parents=True, exist_ok=True)
    directory = directory.resolve()
    try:
        safe_name = DocumentValidator.validate_upload_safety(upload.filename or "", None)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    target = directory / safe_name
    if target.is_symlink() or target.resolve().parent != directory:
        raise HTTPException(422, "Upload path escapes the document directory")
    temporary = None
    try:
        total = 0
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            while chunk := await upload.read(65536):
                total += len(chunk)
                if total > DocumentValidator.MAX_FILE_SIZE:
                    raise HTTPException(413, "Document exceeds the upload size limit")
                stream.write(chunk)
        DocumentValidator.validate_upload_safety(safe_name, total)
        temporary.replace(target)
        upload.filename = safe_name
        return target
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class KnowledgeBaseInfo(BaseModel):
    name: str
    is_default: bool
    statistics: dict


class LinkFolderRequest(BaseModel):
    """Request model for linking a local folder to a KB."""

    folder_path: str


class LinkedFolderInfo(BaseModel):
    """Response model for linked folder information."""

    id: str
    path: str
    added_at: str
    file_count: int


class KnowledgeQueryRequest(BaseModel):
    kb_name: str
    query: str
    mode: str = "hybrid"
    provider: str | None = None
    execution: str = "system"


def get_workspace_llm_profile() -> dict:
    """Resolve the one active configuration from Settings or .env."""
    config = get_llm_config()
    return {
        "api_key": config.api_key,
        "base_url": config.base_url,
        "model": config.model,
        "provider": config.binding,
        "api_version": config.api_version,
    }


async def run_initialization_task(initializer: KnowledgeBaseInitializer):
    """Background task for knowledge base initialization"""
    task_manager = TaskIDManager.get_instance()
    task_id = task_manager.generate_task_id("kb_init", initializer.kb_name)

    try:
        if not initializer.progress_tracker:
            initializer.progress_tracker = ProgressTracker(
                initializer.kb_name, initializer.base_dir
            )

        initializer.progress_tracker.task_id = task_id

        logger.info(f"[{task_id}] Initializing KB: {initializer.kb_name}")

        await initializer.process_documents()
        initializer.extract_numbered_items()

        initializer.progress_tracker.update(
            ProgressStage.COMPLETED, "Knowledge base initialization complete!", current=1, total=1
        )

        logger.success(f"[{task_id}] KB '{initializer.kb_name}' initialized")
        task_manager.update_task_status(task_id, "completed")
    except Exception as e:
        error_msg = str(e)

        logger.error(f"[{task_id}] KB '{initializer.kb_name}' init failed: {error_msg}")

        task_manager.update_task_status(task_id, "error", error=error_msg)

        if initializer.progress_tracker:
            initializer.progress_tracker.update(
                ProgressStage.ERROR, f"Initialization failed: {error_msg}", error=error_msg
            )


async def run_upload_processing_task(
    kb_name: str,
    base_dir: str,
    api_key: str,
    base_url: str,
    uploaded_file_paths: list[str],
    rag_provider: str = None,
    folder_id: str = None,
):
    """Background task for processing uploaded files.

    Args:
        kb_name: Knowledge base name
        base_dir: Base directory for knowledge bases
        api_key: LLM API key
        base_url: LLM API base URL
        uploaded_file_paths: List of file paths to process
        rag_provider: RAG provider (ignored - we use the one from KB metadata)
        folder_id: Optional folder ID for sync state update
    """
    task_manager = TaskIDManager.get_instance()
    task_key = f"{kb_name}_upload_{len(uploaded_file_paths)}"
    task_id = task_manager.generate_task_id("kb_upload", task_key)

    progress_tracker = ProgressTracker(kb_name, Path(base_dir))
    progress_tracker.task_id = task_id

    try:
        logger.info(f"[{task_id}] Processing {len(uploaded_file_paths)} files to KB '{kb_name}'")
        progress_tracker.update(
            ProgressStage.PROCESSING_DOCUMENTS,
            f"Processing {len(uploaded_file_paths)} files...",
            current=0,
            total=len(uploaded_file_paths),
        )

        adder = DocumentAdder(
            kb_name=kb_name,
            base_dir=base_dir,
            api_key=api_key,
            base_url=base_url,
            progress_tracker=progress_tracker,
            rag_provider=rag_provider,
        )

        # Stage files and check for duplicates
        staged_files = adder.add_documents(uploaded_file_paths, allow_duplicates=False)

        if not staged_files:
            logger.info(f"[{task_id}] No new files to process (all duplicates or invalid)")
            progress_tracker.update(
                ProgressStage.COMPLETED,
                "No new files to process (all duplicates or invalid)",
                current=0,
                total=0,
            )
            task_manager.update_task_status(task_id, "completed")
            return

        # Process staged files
        processed_files = await adder.process_new_documents(staged_files)

        if processed_files:
            progress_tracker.update(
                ProgressStage.EXTRACTING_ITEMS,
                "Extracting numbered items...",
                current=0,
                total=len(processed_files),
            )
            adder.extract_numbered_items_for_new_docs(processed_files, batch_size=20)

        adder.update_metadata(len(processed_files) if processed_files else 0)

        # Update folder sync state if this was a folder sync
        if folder_id and processed_files:
            try:
                manager = get_kb_manager()
                manager.update_folder_sync_state(
                    kb_name, folder_id, [str(f) for f in processed_files]
                )
                logger.info(f"[{task_id}] Updated folder sync state for folder '{folder_id}'")
            except Exception as sync_err:
                logger.warning(f"[{task_id}] Failed to update folder sync state: {sync_err}")

        num_processed = len(processed_files) if processed_files else 0
        progress_tracker.update(
            ProgressStage.COMPLETED,
            f"Successfully processed {num_processed} files!",
            current=num_processed,
            total=num_processed,
        )

        logger.success(f"[{task_id}] Processed {num_processed} files to KB '{kb_name}'")
        task_manager.update_task_status(task_id, "completed")
    except Exception as e:
        error_msg = f"Upload processing failed (KB '{kb_name}'): {e}"
        logger.error(f"[{task_id}] {error_msg}")

        task_manager.update_task_status(task_id, "error", error=error_msg)

        progress_tracker.update(
            ProgressStage.ERROR, f"Processing failed: {error_msg}", error=error_msg
        )


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        manager = get_kb_manager()
        config_exists = manager.config_file.exists()
        kb_count = len(manager.list_knowledge_bases())
        return {
            "status": "ok",
            "config_file": str(manager.config_file),
            "config_exists": config_exists,
            "base_dir": str(manager.base_dir),
            "base_dir_exists": manager.base_dir.exists(),
            "knowledge_bases_count": kb_count,
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}


@router.get("/rag-providers")
async def get_rag_providers():
    """Get list of available RAG providers."""
    try:
        from src.services.rag.service import RAGService

        providers = RAGService.list_providers()
        return {"providers": providers}
    except Exception as e:
        logger.error(f"Error getting RAG providers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/configs")
async def get_all_kb_configs():
    """Get all knowledge base configurations from centralized config file."""
    try:
        from src.services.config import get_kb_config_service

        service = get_kb_config_service()
        return service.get_all_configs()
    except Exception as e:
        logger.error(f"Error getting KB configs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{kb_name}/config")
async def get_kb_config(kb_name: str):
    """Get configuration for a specific knowledge base."""
    try:
        from src.services.config import get_kb_config_service

        service = get_kb_config_service()
        config = service.get_kb_config(kb_name)
        return {"kb_name": kb_name, "config": config}
    except Exception as e:
        logger.error(f"Error getting config for KB '{kb_name}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{kb_name}/config")
async def update_kb_config(kb_name: str, config: dict):
    """Update configuration for a specific knowledge base."""
    try:
        from src.services.config import get_kb_config_service

        service = get_kb_config_service()
        service.set_kb_config(kb_name, config)
        return {"status": "success", "kb_name": kb_name, "config": service.get_kb_config(kb_name)}
    except Exception as e:
        logger.error(f"Error updating config for KB '{kb_name}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/configs/sync")
async def sync_configs_from_metadata():
    """Sync all KB configurations from their metadata.json files to centralized config."""
    try:
        from src.services.config import get_kb_config_service

        service = get_kb_config_service()
        service.sync_all_from_metadata(get_kb_base_dir())
        return {"status": "success", "message": "Configurations synced from metadata files"}
    except Exception as e:
        logger.error(f"Error syncing configs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/default")
async def get_default_kb():
    """Get the default knowledge base."""
    try:
        manager = get_kb_manager()
        default_kb = manager.get_default()
        return {"default_kb": default_kb}
    except Exception as e:
        logger.error(f"Error getting default KB: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/default/{kb_name}")
async def set_default_kb(kb_name: str):
    """Set the default knowledge base."""
    try:
        manager = get_kb_manager()

        # Verify KB exists
        if kb_name not in manager.list_knowledge_bases():
            raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")

        manager.set_default(kb_name)
        return {"status": "success", "default_kb": kb_name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting default KB: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list", response_model=list[KnowledgeBaseInfo])
async def list_knowledge_bases():
    """List all available knowledge bases with their details."""
    try:
        manager = get_kb_manager()
        kb_names = manager.list_knowledge_bases()

        logger.info(f"Found {len(kb_names)} knowledge bases: {kb_names}")

        if not kb_names:
            logger.info("No knowledge bases found, returning empty list")
            return []

        result = []
        errors = []

        for name in kb_names:
            try:
                info = manager.get_info(name)
                logger.debug(f"Successfully got info for KB '{name}': {info.get('statistics', {})}")
                result.append(
                    KnowledgeBaseInfo(
                        name=info["name"],
                        is_default=info["is_default"],
                        statistics=info.get("statistics", {}),
                    )
                )
            except Exception as e:
                error_msg = f"Error getting info for KB '{name}': {e}"
                errors.append(error_msg)
                logger.warning(f"{error_msg}\n{traceback.format_exc()}")
                try:
                    kb_dir = manager.base_dir / name
                    if kb_dir.exists():
                        logger.info(f"KB '{name}' directory exists, creating fallback info")
                        result.append(
                            KnowledgeBaseInfo(
                                name=name,
                                is_default=name == manager.get_default(),
                                statistics={
                                    "raw_documents": 0,
                                    "images": 0,
                                    "content_lists": 0,
                                    "rag_initialized": False,
                                },
                            )
                        )
                except Exception as fallback_err:
                    logger.error(f"Fallback also failed for KB '{name}': {fallback_err}")

        if errors and not result:
            error_detail = f"Failed to load knowledge bases. Errors: {'; '.join(errors)}"
            logger.error(error_detail)
            raise HTTPException(status_code=500, detail=error_detail)

        if errors:
            logger.warning(
                f"Some KBs had errors, returning {len(result)} results. Errors: {errors}"
            )

        logger.info(f"Returning {len(result)} knowledge bases")
        return result
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Error listing knowledge bases: {e}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to list knowledge bases: {e!s}")


@router.post("/query", status_code=202)
async def enqueue_knowledge_query(
    request: KnowledgeQueryRequest,
    user: AuthenticatedUser | None = Depends(get_optional_current_user),
):
    """Queue retrieval so embedding/local model work never blocks the API request."""
    if request.execution not in {"system", "remote"}:
        raise HTTPException(status_code=400, detail="execution must be 'system' or 'remote'")
    if not request.query.strip() or len(request.query) > 20_000:
        raise HTTPException(status_code=400, detail="query must contain 1-20000 characters")
    kind = "rag_query_remote"
    job = get_job_store().enqueue(
        user.id,
        kind,
        {
            "query": request.query,
            "kb_name": request.kb_name,
            "mode": request.mode,
            "provider": request.provider,
        },
    )
    return {"job": job.__dict__}


@router.get("/{kb_name}")
async def get_knowledge_base_details(kb_name: str):
    """Get detailed info for a specific KB."""
    try:
        manager = get_kb_manager()
        return manager.get_info(kb_name)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{kb_name}")
async def delete_knowledge_base(kb_name: str):
    """Delete a knowledge base."""
    from urllib.parse import unquote

    kb_name = unquote(kb_name)  # Decode URL-encoded name (e.g., "Exploring%20CS" -> "Exploring CS")
    try:
        manager = get_kb_manager()
        success = manager.delete_knowledge_base(kb_name, confirm=True)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to delete knowledge base")
        logger.info(f"KB '{kb_name}' deleted")
        return {"message": f"Knowledge base '{kb_name}' deleted successfully"}
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{kb_name}/upload")
async def upload_files(
    kb_name: str,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    rag_provider: str = Form(None),
    user: AuthenticatedUser | None = Depends(get_optional_current_user),
):
    """Upload files to a knowledge base and process them in background."""
    try:
        manager = get_kb_manager()
        kb_path = manager.get_knowledge_base_path(kb_name)
        raw_dir = kb_path / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        profile = get_workspace_llm_profile()
        api_key = profile["api_key"]
        base_url = profile["base_url"]

        uploaded_files = []
        uploaded_file_paths = []

        for file in files:
            file_path = await save_uploaded_document(file, raw_dir)
            uploaded_files.append(file.filename)
            uploaded_file_paths.append(str(file_path))

        logger.info(f"Uploading {len(uploaded_files)} files to KB '{kb_name}'")

        background_tasks.add_task(
            run_upload_processing_task,
            kb_name=kb_name,
            base_dir=str(get_kb_base_dir()),
            api_key=api_key,
            base_url=base_url,
            uploaded_file_paths=uploaded_file_paths,
            rag_provider=rag_provider,
        )

        return {
            "message": f"Uploaded {len(uploaded_files)} files. Processing in background.",
            "files": uploaded_files,
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    except Exception as e:
        # Unexpected failure (Server error)
        formatted_error = format_exception_message(e)
        raise HTTPException(status_code=500, detail=formatted_error) from e


@router.post("/create")
async def create_knowledge_base(
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    files: list[UploadFile] = File(...),
    rag_provider: str = Form("raganything"),
    user: AuthenticatedUser | None = Depends(get_optional_current_user),
):
    """Create a new knowledge base and initialize it with files."""
    from src.knowledge.manager import validate_kb_name
    try:
        validate_kb_name(name)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    try:
        manager = get_kb_manager()
        if name in manager.list_knowledge_bases():
            raise HTTPException(status_code=400, detail=f"Knowledge base '{name}' already exists")

        profile = get_workspace_llm_profile()
        api_key = profile["api_key"]
        base_url = profile["base_url"]

        logger.info(f"Creating KB: {name}")

        # Register KB to kb_config.json immediately with "initializing" status
        # This ensures the KB appears in the list right away
        manager.update_kb_status(
            name=name,
            status="initializing",
            progress={
                "stage": "initializing",
                "message": "Initializing knowledge base...",
                "percent": 0,
                "current": 0,
                "total": len(files),
            },
        )
        # Also store rag_provider in config (reload and update)
        manager.config = manager._load_config()
        if name in manager.config.get("knowledge_bases", {}):
            manager.config["knowledge_bases"][name]["rag_provider"] = rag_provider
            manager._save_config()

        progress_tracker = ProgressTracker(name, get_kb_base_dir())

        initializer = KnowledgeBaseInitializer(
            kb_name=name,
            base_dir=str(get_kb_base_dir()),
            api_key=api_key,
            base_url=base_url,
            progress_tracker=progress_tracker,
            rag_provider=rag_provider,
        )

        initializer.create_directory_structure()

        manager = get_kb_manager()
        if name not in manager.list_knowledge_bases():
            logger.warning(f"KB {name} not found in config, registering manually")
            initializer._register_to_config()

        uploaded_files = []
        for file in files:
            await save_uploaded_document(file, initializer.raw_dir)
            uploaded_files.append(file.filename)

        progress_tracker.update(
            ProgressStage.PROCESSING_DOCUMENTS,
            f"Saved {len(uploaded_files)} files, preparing to process...",
            current=0,
            total=len(uploaded_files),
        )

        background_tasks.add_task(run_initialization_task, initializer)

        logger.success(f"KB '{name}' created, processing {len(uploaded_files)} files in background")

        return {
            "message": f"Knowledge base '{name}' created. Processing {len(uploaded_files)} files in background.",
            "name": name,
            "files": uploaded_files,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create KB: {e}")
        logger.debug(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{kb_name}/progress")
async def get_progress(kb_name: str):
    """Get initialization progress for a knowledge base"""
    try:
        progress_tracker = ProgressTracker(kb_name, get_kb_base_dir())
        progress = progress_tracker.get_progress()

        if progress is None:
            return {"status": "not_started", "message": "Initialization not started"}

        return progress
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{kb_name}/progress/clear")
async def clear_progress(kb_name: str):
    """Clear progress file for a knowledge base (useful for stuck states)"""
    try:
        progress_tracker = ProgressTracker(kb_name, get_kb_base_dir())
        progress_tracker.clear()
        return {"status": "success", "message": f"Progress cleared for {kb_name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/{kb_name}/progress/ws")
async def websocket_progress(websocket: WebSocket, kb_name: str):
    """WebSocket endpoint for real-time progress updates"""
    await websocket.accept()

    broadcaster = ProgressBroadcaster.get_instance()

    try:
        await broadcaster.connect(kb_name, websocket)

        progress_tracker = ProgressTracker(kb_name, get_kb_base_dir())
        initial_progress = progress_tracker.get_progress()

        # Check if KB is already ready (has rag_storage)
        kb_dir = get_kb_base_dir() / kb_name
        rag_storage_dir = kb_dir / "rag_storage"
        kb_is_ready = rag_storage_dir.exists() and rag_storage_dir.is_dir()

        # Only send non-completed progress if KB is not ready
        # or if progress is recent (within 5 minutes)
        if initial_progress:
            stage = initial_progress.get("stage")
            timestamp = initial_progress.get("timestamp")

            should_send = False
            if stage in ["completed", "error"] or not kb_is_ready:
                should_send = True
            elif timestamp:
                # Check if progress is recent
                try:
                    progress_time = datetime.fromisoformat(timestamp)
                    now = datetime.now()
                    age_seconds = (now - progress_time).total_seconds()
                    if age_seconds < 300:  # 5 minutes
                        should_send = True
                except:
                    pass

            if should_send:
                await websocket.send_json({"type": "progress", "data": initial_progress})

        last_progress = initial_progress
        last_timestamp = initial_progress.get("timestamp") if initial_progress else None

        while True:
            try:
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                except asyncio.TimeoutError:
                    current_progress = progress_tracker.get_progress()
                    if current_progress:
                        current_timestamp = current_progress.get("timestamp")
                        if current_timestamp != last_timestamp:
                            await websocket.send_json(
                                {"type": "progress", "data": current_progress}
                            )
                            last_progress = current_progress
                            last_timestamp = current_timestamp

                            if current_progress.get("stage") in ["completed", "error"]:
                                await asyncio.sleep(3)
                                break
                    continue

            except WebSocketDisconnect:
                break
            except Exception:
                break

    except Exception as e:
        logger.debug(f"Progress WS error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass
    finally:
        await broadcaster.disconnect(kb_name, websocket)
        try:
            await websocket.close()
        except:
            pass


@router.post("/{kb_name}/link-folder", response_model=LinkedFolderInfo)
async def link_folder(kb_name: str, request: LinkFolderRequest):
    """
    Link a local folder to a knowledge base.

    This allows syncing documents from a local folder (which can be
    synced with SharePoint, Google Drive, OneLake, etc.) to the KB.

    The folder path supports:
    - Absolute paths: /Users/name/Documents or C:\\Users\\name\\Documents
    - Home directory: ~/Documents
    - Relative paths (resolved from server working directory)
    """
    try:
        manager = get_kb_manager()
        folder_info = manager.link_folder(kb_name, request.folder_path)
        logger.info(f"Linked folder '{request.folder_path}' to KB '{kb_name}'")
        return LinkedFolderInfo(**folder_info)
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{kb_name}/linked-folders", response_model=list[LinkedFolderInfo])
async def get_linked_folders(kb_name: str):
    """Get list of linked folders for a knowledge base."""
    try:
        manager = get_kb_manager()
        folders = manager.get_linked_folders(kb_name)
        return [LinkedFolderInfo(**f) for f in folders]
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{kb_name}/linked-folders/{folder_id}")
async def unlink_folder(kb_name: str, folder_id: str):
    """Unlink a folder from a knowledge base."""
    try:
        manager = get_kb_manager()
        success = manager.unlink_folder(kb_name, folder_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Folder '{folder_id}' not found")
        logger.info(f"Unlinked folder '{folder_id}' from KB '{kb_name}'")
        return {"message": "Folder unlinked successfully", "folder_id": folder_id}
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{kb_name}/sync-folder/{folder_id}")
async def sync_folder(kb_name: str, folder_id: str, background_tasks: BackgroundTasks):
    """
    Sync files from a linked folder to the knowledge base.

    This scans the linked folder for supported documents and processes
    any new files that haven't been added yet.
    """
    try:
        manager = get_kb_manager()

        # Get linked folders and find the one with matching ID
        folders = manager.get_linked_folders(kb_name)
        folder_info = next((f for f in folders if f["id"] == folder_id), None)

        if not folder_info:
            raise HTTPException(status_code=404, detail=f"Linked folder '{folder_id}' not found")

        folder_path = folder_info["path"]

        # Check for changes (new or modified files)
        changes = manager.detect_folder_changes(kb_name, folder_id)
        files_to_process = changes["new_files"] + changes["modified_files"]

        if not files_to_process:
            return {"message": "No new or modified files to sync", "files": [], "file_count": 0}

        # Get LLM config
        try:
            llm_config = get_llm_config()
            api_key = llm_config.api_key
            base_url = llm_config.base_url
        except ValueError as e:
            raise HTTPException(status_code=500, detail=f"LLM config error: {e!s}")

        logger.info(
            f"Syncing {len(files_to_process)} files from folder '{folder_path}' to KB '{kb_name}'"
        )

        # NOTE: We DO NOT update sync state here anymore.
        # It is updated in run_upload_processing_task only after successful processing.
        # This prevents marking files as synced if processing fails (race condition fix).

        # Add background task to process files
        background_tasks.add_task(
            run_upload_processing_task,
            kb_name=kb_name,
            base_dir=str(get_kb_base_dir()),
            api_key=api_key,
            base_url=base_url,
            uploaded_file_paths=files_to_process,
            folder_id=folder_id,  # Pass folder_id to update state on success
        )

        return {
            "message": f"Syncing {len(files_to_process)} files from linked folder",
            "folder_path": folder_path,
            "new_files": changes["new_count"],
            "modified_files": changes["modified_count"],
            "file_count": len(files_to_process),
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Knowledge Graph Viewer API - View entity-relationship graph from RAG storage
# =============================================================================


@router.get("/{kb_name}/graph")
async def get_knowledge_graph(
    kb_name: str,
    limit: int = 500,
    search: str = None,
    entity_type: str = None,
):
    """
    Get knowledge graph data (entities and relationships) for visualization.

    Parses the GraphML file from LightRAG/RAGAnything storage and returns
    nodes and edges suitable for Cytoscape.js rendering.

    Args:
        kb_name: Knowledge base name
        limit: Max number of nodes to return (default 500, for performance)
        search: Optional search filter for entity names/descriptions
        entity_type: Optional filter by entity type
    """
    from urllib.parse import unquote
    import xml.etree.ElementTree as ET

    kb_name = unquote(kb_name)

    try:
        manager = get_kb_manager()
        kb_path = manager.get_knowledge_base_path(kb_name)
        rag_storage = kb_path / "rag_storage"
        graph_path = rag_storage / "graph_chunk_entity_relation.graphml"

        if not graph_path.exists():
            return {
                "kb_name": kb_name,
                "has_graph": False,
                "nodes": [],
                "edges": [],
                "stats": {"total_nodes": 0, "total_edges": 0, "entity_types": []},
                "message": "No knowledge graph found. This KB may use a provider without graph RAG.",
            }

        # Parse GraphML
        try:
            tree = ET.parse(str(graph_path))
            root = tree.getroot()
        except ET.ParseError as e:
            logger.warning(
                f"GraphML parse failed for KB '{kb_name}': {e}. Falling back to JSON graph stores."
            )
            return _build_graph_from_json_fallback(
                kb_name=kb_name,
                rag_storage=rag_storage,
                limit=limit,
                search=search,
                entity_type=entity_type,
            )

        # GraphML namespace
        ns = {"g": "http://graphml.graphstruct.org/xmlns"}
        # Try without namespace if not found
        graph = root.find(".//g:graph", ns)
        if graph is None:
            graph = root.find(".//{http://graphml.graphstruct.org/xmlns}graph")
        if graph is None:
            # Try default namespace detection
            for child in root:
                if child.tag.endswith("graph"):
                    graph = child
                    break

        if graph is None:
            return {
                "kb_name": kb_name,
                "has_graph": False,
                "nodes": [],
                "edges": [],
                "stats": {"total_nodes": 0, "total_edges": 0, "entity_types": []},
                "message": "Could not parse knowledge graph file.",
            }

        # Detect namespace from tag
        tag_ns = ""
        if "}" in graph.tag:
            tag_ns = graph.tag.split("}")[0] + "}"

        # Parse key definitions to map key IDs to attribute names
        key_map = {}
        for key_elem in root.findall(f".//{tag_ns}key"):
            key_id = key_elem.get("id", "")
            attr_name = key_elem.get("attr.name", key_id)
            key_map[key_id] = attr_name

        # Parse nodes
        all_nodes = []
        entity_types_set = set()
        for node_elem in graph.findall(f".//{tag_ns}node"):
            node_id = node_elem.get("id", "")
            node_data = {"id": node_id}
            for data_elem in node_elem.findall(f"{tag_ns}data"):
                key = data_elem.get("key", "")
                attr_name = key_map.get(key, key)
                text = data_elem.text or ""
                node_data[attr_name] = text

            node_entity_type = node_data.get("entity_type", "unknown")
            entity_types_set.add(node_entity_type)

            # Apply search filter
            if search:
                search_lower = search.lower()
                name_match = search_lower in node_id.lower()
                desc_match = search_lower in node_data.get("description", "").lower()
                type_match = search_lower in node_entity_type.lower()
                if not (name_match or desc_match or type_match):
                    continue

            # Apply entity type filter
            if entity_type and not entity_type_filter_match(node_entity_type, entity_type):
                continue

            all_nodes.append(
                {
                    "id": node_id,
                    "label": node_id,
                    "entity_type": node_data.get("entity_type", "unknown"),
                    "description": (
                        node_data.get("description", "")[:300] + "..."
                        if len(node_data.get("description", "")) > 300
                        else node_data.get("description", "")
                    ),
                    "source_doc": node_data.get("file_path", ""),
                }
            )

        total_nodes = len(all_nodes)

        # Limit nodes for performance
        displayed_nodes = all_nodes[:limit]
        displayed_node_ids = {n["id"] for n in displayed_nodes}

        # Parse edges (only between displayed nodes)
        all_edges_count = 0
        edges = []
        for edge_elem in graph.findall(f".//{tag_ns}edge"):
            all_edges_count += 1
            source = edge_elem.get("source", "")
            target = edge_elem.get("target", "")
            if source in displayed_node_ids and target in displayed_node_ids:
                edge_data = {}
                for data_elem in edge_elem.findall(f"{tag_ns}data"):
                    key = data_elem.get("key", "")
                    attr_name = key_map.get(key, key)
                    text = data_elem.text or ""
                    edge_data[attr_name] = text

                weight = 1.0
                try:
                    weight = float(edge_data.get("weight", "1.0"))
                except (ValueError, TypeError):
                    weight = 1.0

                edges.append(
                    {
                        "source": source,
                        "target": target,
                        "label": edge_data.get("description", "")[:100],
                        "keywords": edge_data.get("keywords", ""),
                        "weight": weight,
                    }
                )

        return {
            "kb_name": kb_name,
            "has_graph": True,
            "nodes": displayed_nodes,
            "edges": edges,
            "stats": {
                "total_nodes": total_nodes,
                "total_edges": all_edges_count,
                "displayed_nodes": len(displayed_nodes),
                "displayed_edges": len(edges),
                "entity_types": sorted(list(entity_types_set)),
            },
        }

    except ValueError:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    except Exception as e:
        logger.error(f"Error getting knowledge graph: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


def entity_type_filter_match(actual_type: str, filter_type: str) -> bool:
    """Check if entity type matches filter (case-insensitive)."""
    if not filter_type:
        return True
    return actual_type.lower() == filter_type.lower()


def _build_graph_from_json_fallback(
    kb_name: str,
    rag_storage: Path,
    limit: int,
    search: str | None,
    entity_type: str | None,
) -> dict:
    """
    Build lightweight graph payload from JSON stores when GraphML is corrupted.

    This fallback keeps the graph viewer usable and avoids returning HTTP 500.
    """
    entities_path = rag_storage / "kv_store_full_entities.json"
    relations_path = rag_storage / "kv_store_full_relations.json"

    if not entities_path.exists() or not relations_path.exists():
        return {
            "kb_name": kb_name,
            "has_graph": False,
            "nodes": [],
            "edges": [],
            "stats": {
                "total_nodes": 0,
                "total_edges": 0,
                "displayed_nodes": 0,
                "displayed_edges": 0,
                "entity_types": [],
            },
            "message": "Knowledge graph file is corrupted and fallback data is unavailable.",
        }

    with open(entities_path, encoding="utf-8") as f:
        entities_store = json.load(f)
    with open(relations_path, encoding="utf-8") as f:
        relations_store = json.load(f)

    entity_names: set[str] = set()
    for item in entities_store.values():
        if not isinstance(item, dict):
            continue
        for name in item.get("entity_names", []) or []:
            if isinstance(name, str) and name.strip():
                entity_names.add(name.strip())

    all_nodes = []
    search_lower = (search or "").lower().strip()
    for name in sorted(entity_names):
        node_entity_type = "unknown"

        if (
            search_lower
            and search_lower not in name.lower()
            and search_lower not in node_entity_type
        ):
            continue

        if entity_type and not entity_type_filter_match(node_entity_type, entity_type):
            continue

        all_nodes.append(
            {
                "id": name,
                "label": name,
                "entity_type": node_entity_type,
                "description": "",
                "source_doc": "",
            }
        )

    total_nodes = len(all_nodes)
    displayed_nodes = all_nodes[:limit]
    displayed_node_ids = {n["id"] for n in displayed_nodes}

    edges = []
    all_edges_count = 0
    for item in relations_store.values():
        if not isinstance(item, dict):
            continue
        for pair in item.get("relation_pairs", []) or []:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            source = str(pair[0]).strip()
            target = str(pair[1]).strip()
            if not source or not target:
                continue

            all_edges_count += 1
            if source in displayed_node_ids and target in displayed_node_ids:
                edges.append(
                    {
                        "source": source,
                        "target": target,
                        "label": "",
                        "keywords": "",
                        "weight": 1.0,
                    }
                )

    return {
        "kb_name": kb_name,
        "has_graph": True,
        "nodes": displayed_nodes,
        "edges": edges,
        "stats": {
            "total_nodes": total_nodes,
            "total_edges": all_edges_count,
            "displayed_nodes": len(displayed_nodes),
            "displayed_edges": len(edges),
            "entity_types": ["unknown"],
        },
        "message": "GraphML is corrupted; showing fallback graph from JSON stores.",
    }


# =============================================================================
# Chunk Viewer API - View chunks, metadata, and RAG storage info
# =============================================================================


@router.get("/{kb_name}/chunks")
async def get_knowledge_base_chunks(
    kb_name: str,
    page: int = 1,
    page_size: int = 20,
    search: str = None,
):
    """
    Get chunks from a knowledge base with pagination.

    Returns chunks with their metadata including:
    - chunk_id, content, doc_name, page numbers
    - section_path, chunk_type
    - For VGU Course: section summaries
    """
    import pickle
    from urllib.parse import unquote

    kb_name = unquote(kb_name)

    try:
        manager = get_kb_manager()
        kb_path = manager.get_knowledge_base_path(kb_name)

        result = {
            "kb_name": kb_name,
            "total_chunks": 0,
            "page": page,
            "page_size": page_size,
            "chunks": [],
            "sections": [],
            "storage_info": {},
        }

        # Check VGU index first (VGU Course mode)
        vgu_index_dir = kb_path / "vgu_index"
        chunks_json = vgu_index_dir / "chunks.json"
        chunks_pkl = vgu_index_dir / "chunks.pkl"
        sections_json = vgu_index_dir / "sections.json"
        sections_pkl = vgu_index_dir / "sections.pkl"

        # Try JSON first (new format), then PKL (legacy)
        all_chunks = []
        if chunks_json.exists():
            with open(chunks_json, "r", encoding="utf-8") as f:
                all_chunks = json.load(f)
        elif chunks_pkl.exists():
            with open(chunks_pkl, "rb") as f:
                all_chunks = pickle.load(f)

        if all_chunks:
            # Filter by search if provided
            if search:
                search_lower = search.lower()
                all_chunks = [
                    c
                    for c in all_chunks
                    if search_lower in c.get("content", "").lower()
                    or search_lower in c.get("doc_name", "").lower()
                    or search_lower in c.get("section_path", "").lower()
                ]

            result["total_chunks"] = len(all_chunks)

            # Paginate
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paginated_chunks = all_chunks[start_idx:end_idx]

            # Convert to serializable format
            result["chunks"] = [
                {
                    "chunk_id": c.chunk_id if hasattr(c, "chunk_id") else c.get("chunk_id"),
                    "content": (c.content if hasattr(c, "content") else c.get("content", ""))[:500]
                    + "..."
                    if len(c.content if hasattr(c, "content") else c.get("content", "")) > 500
                    else (c.content if hasattr(c, "content") else c.get("content", "")),
                    "content_length": len(
                        c.content if hasattr(c, "content") else c.get("content", "")
                    ),
                    "doc_id": c.doc_id if hasattr(c, "doc_id") else c.get("doc_id"),
                    "doc_name": c.doc_name if hasattr(c, "doc_name") else c.get("doc_name"),
                    "page_start": c.page_start if hasattr(c, "page_start") else c.get("page_start"),
                    "page_end": c.page_end if hasattr(c, "page_end") else c.get("page_end"),
                    "section_path": c.section_path
                    if hasattr(c, "section_path")
                    else c.get("section_path"),
                    "chunk_type": c.chunk_type if hasattr(c, "chunk_type") else c.get("chunk_type"),
                }
                for c in paginated_chunks
            ]

            # Load sections if available (JSON first, then PKL)
            sections = []
            if sections_json.exists():
                with open(sections_json, "r", encoding="utf-8") as f:
                    sections = json.load(f)
            elif sections_pkl.exists():
                with open(sections_pkl, "rb") as f:
                    sections = pickle.load(f)

            if sections:
                result["sections"] = [
                    {
                        "section_id": s.section_id
                        if hasattr(s, "section_id")
                        else s.get("section_id"),
                        "section_path": s.section_path
                        if hasattr(s, "section_path")
                        else s.get("section_path"),
                        "summary": s.summary if hasattr(s, "summary") else s.get("summary"),
                        "doc_name": s.doc_name if hasattr(s, "doc_name") else s.get("doc_name"),
                        "page_start": s.page_start
                        if hasattr(s, "page_start")
                        else s.get("page_start"),
                        "page_end": s.page_end if hasattr(s, "page_end") else s.get("page_end"),
                        "chunk_count": len(
                            s.chunk_ids if hasattr(s, "chunk_ids") else s.get("chunk_ids", [])
                        ),
                    }
                    for s in sections[:50]  # Limit to 50 sections
                ]

        # Check LightRAG storage
        rag_storage = kb_path / "rag_storage"
        if rag_storage.exists():
            storage_info = {}

            # Check vector DBs
            for vdb_file in ["vdb_chunks.json", "vdb_entities.json", "vdb_relationships.json"]:
                vdb_path = rag_storage / vdb_file
                if vdb_path.exists():
                    try:
                        with open(vdb_path, "r") as f:
                            vdb_data = json.load(f)
                        storage_info[vdb_file] = {
                            "exists": True,
                            "size_kb": vdb_path.stat().st_size / 1024,
                            "record_count": len(vdb_data.get("data", []))
                            if isinstance(vdb_data, dict)
                            else 0,
                        }
                    except:
                        storage_info[vdb_file] = {"exists": True, "error": "Could not read"}

            # Check graph
            graph_path = rag_storage / "graph_chunk_entity_relation.graphml"
            if graph_path.exists():
                storage_info["knowledge_graph"] = {
                    "exists": True,
                    "size_kb": graph_path.stat().st_size / 1024,
                }

            # Check KV stores
            for kv_file in ["kv_store_full_docs.json", "kv_store_text_chunks.json"]:
                kv_path = rag_storage / kv_file
                if kv_path.exists():
                    try:
                        with open(kv_path, "r") as f:
                            kv_data = json.load(f)
                        storage_info[kv_file] = {
                            "exists": True,
                            "size_kb": kv_path.stat().st_size / 1024,
                            "record_count": len(kv_data) if isinstance(kv_data, dict) else 0,
                        }
                    except:
                        storage_info[kv_file] = {"exists": True, "error": "Could not read"}

            result["storage_info"] = storage_info

        # If no VGU chunks, try to read from LightRAG text_chunks
        if result["total_chunks"] == 0:
            text_chunks_path = rag_storage / "kv_store_text_chunks.json"
            if text_chunks_path.exists():
                try:
                    with open(text_chunks_path, "r") as f:
                        text_chunks = json.load(f)

                    all_chunks = list(text_chunks.items())

                    if search:
                        search_lower = search.lower()
                        all_chunks = [
                            (k, v)
                            for k, v in all_chunks
                            if search_lower in v.get("content", "").lower()
                        ]

                    result["total_chunks"] = len(all_chunks)

                    start_idx = (page - 1) * page_size
                    end_idx = start_idx + page_size
                    paginated = all_chunks[start_idx:end_idx]

                    result["chunks"] = [
                        {
                            "chunk_id": k,
                            "content": v.get("content", "")[:500] + "..."
                            if len(v.get("content", "")) > 500
                            else v.get("content", ""),
                            "content_length": len(v.get("content", "")),
                            "tokens": v.get("tokens"),
                            "full_doc_id": v.get("full_doc_id"),
                        }
                        for k, v in paginated
                    ]
                except Exception as e:
                    logger.warning(f"Could not read text_chunks: {e}")

        return result

    except ValueError:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_name}' not found")
    except Exception as e:
        logger.error(f"Error getting chunks: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{kb_name}/chunks/{chunk_id}")
async def get_chunk_detail(kb_name: str, chunk_id: str):
    """Get full details of a specific chunk."""
    import pickle
    from urllib.parse import unquote

    kb_name = unquote(kb_name)
    chunk_id = unquote(chunk_id)

    try:
        manager = get_kb_manager()
        kb_path = manager.get_knowledge_base_path(kb_name)

        # Try VGU index first (JSON then PKL)
        chunks_json = kb_path / "vgu_index" / "chunks.json"
        chunks_pkl = kb_path / "vgu_index" / "chunks.pkl"

        all_chunks = []
        if chunks_json.exists():
            with open(chunks_json, "r", encoding="utf-8") as f:
                all_chunks = json.load(f)
        elif chunks_pkl.exists():
            with open(chunks_pkl, "rb") as f:
                all_chunks = pickle.load(f)

        if all_chunks:
            for c in all_chunks:
                cid = c.chunk_id if hasattr(c, "chunk_id") else c.get("chunk_id")
                if cid == chunk_id:
                    return {
                        "chunk_id": cid,
                        "content": c.content if hasattr(c, "content") else c.get("content"),
                        "doc_id": c.doc_id if hasattr(c, "doc_id") else c.get("doc_id"),
                        "doc_name": c.doc_name if hasattr(c, "doc_name") else c.get("doc_name"),
                        "page_start": c.page_start
                        if hasattr(c, "page_start")
                        else c.get("page_start"),
                        "page_end": c.page_end if hasattr(c, "page_end") else c.get("page_end"),
                        "section_path": c.section_path
                        if hasattr(c, "section_path")
                        else c.get("section_path"),
                        "chunk_type": c.chunk_type
                        if hasattr(c, "chunk_type")
                        else c.get("chunk_type"),
                        "metadata": c.metadata if hasattr(c, "metadata") else c.get("metadata", {}),
                    }

        # Try LightRAG text_chunks
        text_chunks_path = kb_path / "rag_storage" / "kv_store_text_chunks.json"
        if text_chunks_path.exists():
            with open(text_chunks_path, "r") as f:
                text_chunks = json.load(f)

            if chunk_id in text_chunks:
                return {"chunk_id": chunk_id, **text_chunks[chunk_id]}

        raise HTTPException(status_code=404, detail=f"Chunk '{chunk_id}' not found")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

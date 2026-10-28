"""Workspace document parser settings and a bounded upload preview."""

from pathlib import Path
import tempfile
import shutil
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from src.security.auth import AuthenticatedUser, get_current_user
from src.services.queue import get_job_store
from src.services.document_previews import preview_directory

from src.services.document_processing import (
    DocumentProcessingConfig,
    capabilities,
    get_document_config,
    run_parser_process,
    public_document_config,
    save_document_config,
)

router = APIRouter()


@router.get("")
async def get_settings():
    return {"config": public_document_config(), "presets": capabilities()}


@router.put("")
async def update_settings(config: DocumentProcessingConfig):
    try:
        return {"config": save_document_config(config)}
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/test")
async def test_document(file: UploadFile = File(...), background: bool = False,
                        user: AuthenticatedUser = Depends(get_current_user)):
    preview_id = uuid.uuid4().hex
    staged = preview_directory(user.id, preview_id) if background else None
    temporary = None if staged else tempfile.TemporaryDirectory(prefix="edunote-parser-")
    directory = staged or Path(temporary.name)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    queued = False
    try:
        path = Path(directory) / ("input" + Path(file.filename or "input.pdf").suffix.lower())
        if path.suffix not in {".pdf", ".docx", ".pptx", ".png", ".jpg", ".jpeg", ".txt", ".md"}:
            raise HTTPException(422, "Unsupported preview file type")
        total = 0
        with path.open("wb") as stream:
            while chunk := await file.read(65536):
                total += len(chunk)
                if total > 20 * 1024 * 1024:
                    raise HTTPException(413, "Preview file limit is 20 MiB")
                stream.write(chunk)
        path.chmod(0o600)
        cfg = get_document_config()
        if background:
            snapshot = directory / "config.json"
            snapshot.write_text(cfg.model_dump_json())
            snapshot.chmod(0o600)
            job = get_job_store().enqueue(user.id, "document_preview", {"preview_id": preview_id})
            queued = True
            return JSONResponse({"test_id": job.id, "status": job.status}, status_code=202)
        try:
            result = await run_parser_process(path, Path(directory) / "output", cfg)
        except Exception as error:
            raise HTTPException(422, str(error)) from error
        return result
    finally:
        if staged and not queued:
            shutil.rmtree(staged, ignore_errors=True)
        if temporary:
            temporary.cleanup()


@router.get("/tests/{test_id}")
async def get_document_test(test_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    try:
        job = get_job_store().get(test_id, user.id)
    except LookupError as error:
        raise HTTPException(404, "Document test not found") from error
    if job.kind != "document_preview":
        raise HTTPException(404, "Document test not found")
    return {"test_id": job.id, "status": job.status, "result": job.result, "error": job.error}

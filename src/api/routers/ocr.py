"""Queued OCR endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.security.auth import AuthenticatedUser, get_current_user
from src.services.ocr import ensure_ocr_allowed
from src.services.queue import get_job_store
from src.services.storage import get_storage_service

router = APIRouter()


class OCRJobRequest(BaseModel):
    relative_path: str = Field(min_length=1, max_length=500)
    mode: str = "basic"
    remote: bool = False


@router.post("", status_code=202)
async def enqueue_ocr(request: OCRJobRequest, user: AuthenticatedUser = Depends(get_current_user)):
    remote = request.remote
    try:
        ensure_ocr_allowed(request.mode, remote=remote)
        path = get_storage_service().safe_path(user.id, request.relative_path)
        if not path.is_file():
            raise FileNotFoundError("OCR input file not found")
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except (ValueError, FileNotFoundError, LookupError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    kind = "ocr_remote" if remote else ("ocr_heavy" if request.mode == "heavy" else "ocr_basic")
    job = get_job_store().enqueue(
        user.id,
        kind,
        {
            "relative_path": request.relative_path,
            "remote": remote,
        },
    )
    return {"job": job.__dict__}

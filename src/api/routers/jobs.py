"""User-scoped durable job endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.security.auth import AuthenticatedUser, get_current_user
from src.services.queue import get_job_store

router = APIRouter()


class JobCreate(BaseModel):
    kind: str = Field(min_length=1, max_length=80)
    payload: dict = Field(default_factory=dict)


@router.post("", status_code=202)
async def create_job(request: JobCreate, user: AuthenticatedUser = Depends(get_current_user)):
    raise HTTPException(
        422, "Use the typed learning, OCR or document endpoints to submit validated jobs"
    )


@router.get("")
async def list_jobs(user: AuthenticatedUser = Depends(get_current_user)):
    return {"jobs": [job.__dict__ for job in get_job_store().list(None)]}


@router.get("/{job_id}")
async def get_job(job_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    try:
        job = get_job_store().get(job_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Job not found") from error
    return {"job": job.__dict__}


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    try:
        job = get_job_store().get(job_id)
        if job.status in {"completed", "failed", "cancelled"}:
            return {"job": job.__dict__}
        job = get_job_store().cancel(job_id, job.owner_id)
        if job.kind == "document_preview":
            # Running handlers are stopped by the worker; queued previews also
            # need upload/snapshot cleanup because their handler never executes.
            import shutil

            from src.services.document_previews import preview_directory

            shutil.rmtree(preview_directory(user.id, job.payload["preview_id"]), ignore_errors=True)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Job not found") from error
    return {"job": job.__dict__}


@router.post("/{job_id}/retry", status_code=202)
async def retry_job(job_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    try:
        old = get_job_store().get(job_id)
    except LookupError as error:
        raise HTTPException(404, "Job not found") from error
    if old.status not in {"failed", "cancelled"} or old.kind not in {
        "evidence",
        "study_pack",
        "settings_diagnostics",
    }:
        raise HTTPException(
            409, "This job cannot be safely retried. Submit a fresh request from its feature page."
        )
    import uuid

    from src.api.routers.learning import enqueue

    return enqueue(old.kind, dict(old.payload), uuid.uuid4().hex)

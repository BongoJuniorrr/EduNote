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
    job = get_job_store().enqueue(user.id, request.kind, request.payload)
    return {"job": job.__dict__}


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
        job = get_job_store().update(job_id, status="cancelled")
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Job not found") from error
    return {"job": job.__dict__}

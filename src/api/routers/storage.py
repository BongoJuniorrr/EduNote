"""Authenticated storage quota endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from src.security.auth import AuthenticatedUser, get_current_user
from src.services.storage import QuotaExceededError, get_storage_service

router = APIRouter()


@router.get("/usage")
async def get_storage_usage(user: AuthenticatedUser = Depends(get_current_user)):
    return get_storage_service().usage(user.id).as_dict()


@router.post("/check")
async def check_storage_capacity(
    size_bytes: int,
    user: AuthenticatedUser = Depends(get_current_user),
):
    try:
        usage = get_storage_service().assert_can_write(user.id, size_bytes)
    except QuotaExceededError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    return {"allowed": True, **usage.as_dict(), "requested_bytes": size_bytes}

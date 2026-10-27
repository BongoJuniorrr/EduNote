"""
About API Router
Provides endpoints for About Us team members.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.utils.about_manager import ALLOWED_MEMBER_ROLES, about_manager

router = APIRouter()


class CreateMemberRequest(BaseModel):
    full_name: str
    alias: str
    student_id: str
    university: str
    roles: list[str]
    tasks: str = ""


@router.get("/members")
async def list_members():
    try:
        members = about_manager.list_members()
        return {"members": members, "total": len(members)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/members")
async def create_member(request: CreateMemberRequest):
    try:
        full_name = request.full_name.strip()
        alias = request.alias.strip()
        student_id = request.student_id.strip()
        university = request.university.strip()
        roles = [role.strip() for role in request.roles if role and role.strip()]

        if not full_name:
            raise HTTPException(status_code=400, detail="full_name is required")
        if not alias:
            raise HTTPException(status_code=400, detail="alias is required")
        if not student_id:
            raise HTTPException(status_code=400, detail="student_id is required")
        if not university:
            raise HTTPException(status_code=400, detail="university is required")
        if not roles:
            raise HTTPException(status_code=400, detail="at least one role is required")

        invalid_roles = [role for role in roles if role not in ALLOWED_MEMBER_ROLES]
        if invalid_roles:
            raise HTTPException(
                status_code=400,
                detail=f"invalid roles: {', '.join(invalid_roles)}",
            )

        member = about_manager.add_member(
            full_name=full_name,
            alias=alias,
            student_id=student_id,
            university=university,
            roles=roles,
            tasks=request.tasks,
        )
        return {"success": True, "member": member}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/members/{member_id}")
async def delete_member(member_id: str):
    try:
        success = about_manager.delete_member(member_id)
        if not success:
            raise HTTPException(status_code=404, detail="Member not found")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Cookie, Header, Query
from pydantic import BaseModel, EmailStr, Field

router = APIRouter(prefix="/users", tags=["users"])


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    nickname: Optional[str] = None
    role: Literal["admin", "member"] = "member"
    marketing_opt_in: bool = False
    invite_code: Optional[str] = Field(None, alias="inviteCode")


class UserResponse(BaseModel):
    id: UUID
    name: str
    email: EmailStr
    created_at: datetime
    role: Literal["admin", "member"]
    deleted_at: Optional[datetime] = None


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: UUID,
    include_meta: bool = Query(False),
    x_trace_id: Optional[str] = Header(None),
    session_id: Optional[str] = Cookie(None),
):
    return {
        "id": user_id,
        "name": "Ada",
        "email": "ada@example.com",
        "created_at": datetime.utcnow(),
        "role": "member",
        "deleted_at": None,
    }


@router.post("", response_model=UserResponse, status_code=201)
def create_user(body: UserCreate):
    return {
        "id": UUID("00000000-0000-0000-0000-000000000001"),
        "name": body.name,
        "email": body.email,
        "created_at": datetime.utcnow(),
        "role": body.role,
        "deleted_at": None,
    }

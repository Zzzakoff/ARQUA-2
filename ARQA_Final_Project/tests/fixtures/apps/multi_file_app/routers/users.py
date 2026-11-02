from pydantic import BaseModel
from fastapi import APIRouter

router = APIRouter(prefix="/users", tags=["users"])


class UserResponse(BaseModel):
    id: int
    name: str


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: int):
    return {"id": user_id, "name": "Ada"}


from datetime import datetime

from fastapi import FastAPI, Header, Query
from pydantic import BaseModel, EmailStr

app = FastAPI()


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    nickname: str | None = None


class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    created_at: datetime


@app.get("/users/{user_id}", response_model=UserResponse, tags=["users"])
def get_user(user_id: int, include_meta: bool = Query(False), x_trace_id: str | None = Header(None)):
    return {
        "id": user_id,
        "name": "Ada",
        "email": "ada@example.com",
        "created_at": datetime.utcnow().isoformat(),
    }


@app.post("/users", response_model=UserResponse, status_code=201, tags=["users"])
def create_user(body: UserCreate):
    return {
        "id": 1,
        "name": body.name,
        "email": body.email,
        "created_at": datetime.utcnow().isoformat(),
    }


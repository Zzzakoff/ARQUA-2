"""Synthetic source for static analysis only; importing it is not required."""

from typing import Annotated
from fastapi import FastAPI, Query
from pydantic import BaseModel
from external_models import ExternalUser

app = FastAPI()


class User(BaseModel):
    id: int
    nickname: str | None = None


@app.get(path="/users/{user_id}", response_model=User)
async def get_user(user_id: int, query: Annotated[str, Query(alias="search")] = ""):
    return {"id": user_id, "nickname": None}


@app.get("/external", response_model=ExternalUser)
async def get_external():
    return load_external_user()

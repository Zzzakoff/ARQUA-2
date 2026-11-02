from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(prefix="/orders", tags=["orders"])


class LineItem(BaseModel):
    sku: str
    quantity: int


class OrderCreate(BaseModel):
    user_id: str
    items: list[LineItem]
    priority: Literal["standard", "express"] = "standard"


class OrderResponse(BaseModel):
    id: int
    status: Literal["pending", "paid", "cancelled"]
    created_at: datetime
    items: list[LineItem]
    total: float


@router.get("", response_model=list[OrderResponse])
def list_orders(status: Optional[str] = Query(None), limit: int = Query(50)):
    return []


@router.post("", response_model=OrderResponse, status_code=201)
def create_order(body: OrderCreate):
    return {
        "id": 1,
        "status": "pending",
        "created_at": datetime.utcnow(),
        "items": body.items,
        "total": 25.0,
    }


@router.delete("/{order_id}", status_code=204)
def cancel_order(order_id: int, reason: Optional[str] = Query(None)):
    return None

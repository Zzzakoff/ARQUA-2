from fastapi import APIRouter, Header
from pydantic import BaseModel

router = APIRouter(prefix="/admin", tags=["admin"])


class AuditEvent(BaseModel):
    id: int
    action: str
    actor: str


@router.get("/audit", response_model=list[AuditEvent])
def list_audit_events(x_admin_token: str = Header(...)):
    return []

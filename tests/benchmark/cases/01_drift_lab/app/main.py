from fastapi import FastAPI

from .routers.admin import router as admin_router
from .routers.orders import router as orders_router
from .routers.users import router as users_router

app = FastAPI(title="Drift Lab API")

app.include_router(users_router, prefix="/api")
app.include_router(orders_router, prefix="/api")
app.include_router(admin_router)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}


@app.get("/internal/metrics", tags=["system"])
def metrics():
    return {"requests": 42}

from fastapi import FastAPI

from .routers.users import router as users_router

app = FastAPI(root_path="/api")
app.include_router(users_router)


import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fastapi_app.api.router import api_router
from fastapi_app.core.config import get_settings
from fastapi_app.db.base import Base
from fastapi_app.db.session import engine

logging.basicConfig(level=logging.INFO)
settings = get_settings()

app = FastAPI(title=settings.app_name, debug=settings.debug)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.on_event("startup")
def startup() -> None:
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

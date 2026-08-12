"""Automated Bug Investigator — FastAPI entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.observability import shutdown_langfuse
from api.routers import analyze, buggy_app


def _load_dotenv() -> None:
    """Load root .env when running locally (Compose injects env_file itself)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    # api/main.py -> api/ -> project root
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")


_load_dotenv()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    shutdown_langfuse()


app = FastAPI(
    title="Automated Bug Investigator",
    description="Bug Fixer as a Service — LangGraph multi-agent pipeline",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze.router)
app.include_router(buggy_app.router)


@app.get("/health")
def health():
    from api.config import get_settings

    settings = get_settings()
    return {
        "status": "ok",
        "langfuse_enabled": settings.langfuse_enabled,
    }


@app.get("/")
def root():
    return {
        "app": "Automated Bug Investigator",
        "docs": "/docs",
        "endpoints": [
            "POST /api/analyze",
            "GET /api/analyze/{run_id}/status",
            "GET /api/analyze/{run_id}/result",
            "POST /api/analyze/{run_id}/approve",
            "GET /api/buggy-app/errors/latest",
            "POST /api/buggy-app/trigger/{bug_id}",
        ],
    }

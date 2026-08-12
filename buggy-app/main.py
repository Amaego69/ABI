"""
buggy-app — demo FastAPI storefront with intentional bugs.

Standalone test project (NOT part of Bug Investigator docker-compose).
Run locally / in Docker to produce real tracebacks for Bug Investigator.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from routers import triggers

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="buggy-app",
    description="Demo e-commerce API with intentional bugs for Bug Investigator demos.",
    version="1.0.0",
)

app.include_router(triggers.router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def ui():
    """Simple demo UI to trigger bugs and see success after a fix."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api")
def api_info():
    return {
        "app": "buggy-app",
        "docs": "/docs",
        "ui": "/",
        "triggers": [
            "POST /trigger/empty-cart-checkout",
            "POST /trigger/invalid-discount-type",
            "GET /trigger/async-price-fetch",
        ],
    }


@app.get("/health")
def health():
    return {"status": "ok"}

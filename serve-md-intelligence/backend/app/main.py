"""FastAPI application factory. `uvicorn backend.app.main:app --reload`."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.routes import router
from backend.app.settings import REPO_ROOT, settings

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


def create_app(warehouse_path: Path | None = None) -> FastAPI:
    app = FastAPI(
        title="SERVE MD Intelligence API",
        version="0.1.0",
        description="Geographic investment intelligence for Medicare-focused primary care expansion.",
    )
    app.state.warehouse_path = warehouse_path or settings.warehouse_path
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    if FRONTEND_DIST.exists():  # single-container deployment: serve the built SPA
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            candidate = FRONTEND_DIST / path
            if path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()

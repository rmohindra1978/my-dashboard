"""FastAPI dependencies: warehouse connection per request, optional shared-secret auth."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import duckdb
from fastapi import Depends, Header, HTTPException, Request, status

from backend.app.data.warehouse import connect, ensure_schema
from backend.app.settings import settings


def get_con(request: Request) -> Iterator[duckdb.DuckDBPyConnection]:
    """One DuckDB connection per request against the app's warehouse path (overridable in tests)."""
    path: Path = request.app.state.warehouse_path
    con = connect(path, read_only=False)
    try:
        ensure_schema(con)
        yield con
    finally:
        con.close()


def require_token(
    x_access_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    """If SERVEMD_ACCESS_TOKEN is configured, every /api call must present it (header or bearer)."""
    expected = settings.access_token
    if not expected:
        return
    presented = x_access_token
    if not presented and authorization and authorization.lower().startswith("bearer "):
        presented = authorization[7:]
    if presented != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing access token")


Con = Depends(get_con)
Auth = Depends(require_token)

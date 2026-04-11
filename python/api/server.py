"""Veritas API server — read-only observation layer.

A separate process from main.py. They share only the SQLite journal
and JSONL event log files on disk.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from python.api.middleware import ReadOnlyMiddleware

_STATIC_DIR = Path(__file__).parent / "static"
from python.api.routes import state, assumptions, trades, verify

log = logging.getLogger("veritas.api")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    log.info("Veritas API server starting")
    yield


app = FastAPI(
    title="Veritas",
    version="0.1",
    description="Read-only observation API for the Veritas trading agent.",
    lifespan=_lifespan,
)

app.add_middleware(ReadOnlyMiddleware)

app.include_router(state.router)
app.include_router(assumptions.router)
app.include_router(trades.router)
app.include_router(verify.router)


app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "veritas_version": "0.1"}


@app.get("/", include_in_schema=False)
async def dashboard():
    return FileResponse(str(_STATIC_DIR / "index.html"))

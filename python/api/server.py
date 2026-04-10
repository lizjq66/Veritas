"""Veritas API server — read-only observation layer.

A separate process from main.py. They share only the SQLite journal
and JSONL event log files on disk.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from python.api.middleware import ReadOnlyMiddleware

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


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "veritas_version": "0.1"}

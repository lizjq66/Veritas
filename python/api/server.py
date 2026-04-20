"""Veritas API server — verification surface + observation layer.

The primary role of this server is to expose the three-gate verifier
over HTTP so downstream agents can submit trade proposals and receive
certificates. A small read-only observation layer (state, assumptions,
trades, theorem lookup) runs alongside for trust inspection.

Routes:

    POST /verify/proposal        — run all three gates
    POST /verify/signal          — Gate 1 only
    POST /verify/constraints     — Gate 2 only
    POST /verify/portfolio       — Gate 3 only
    GET  /verify/theorem/{name}  — theorem proof status

    GET  /state                  — runner state (if any demo is running)
    GET  /assumptions            — assumption library + reliability
    GET  /assumptions/{name}     — detail
    GET  /trades                 — trade history (from bundled demo runner)
    GET  /trades/{id}            — detail
    GET  /stream/events          — SSE event feed from the bundled runner
    GET  /health                 — liveness

The observation layer is strictly read-only. Only the verification
routes accept POST. See `middleware.py` for the enforcement.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from python.api.middleware import ReadOnlyMiddleware
from python.api.routes import state, assumptions, trades, verify, stream

_STATIC_DIR = Path(__file__).parent / "static"

log = logging.getLogger("veritas.api")

_runner = None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _runner
    log.info("Veritas API server starting")
    if os.environ.get("VERITAS_LIVE_MODE") == "1":
        from python.api.live_runner import LiveRunner
        from python.api.events import broker
        db_path = Path(os.environ.get("VERITAS_DB_PATH", "data/veritas.db"))
        _runner = LiveRunner(broker, db_path)
        await _runner.start()
    yield
    if _runner:
        await _runner.stop()


app = FastAPI(
    title="Veritas",
    version="0.1",
    description=(
        "Lean-backed pre-trade verifier. Primary surface: POST /verify/*. "
        "Read-only observation: GET /state, /assumptions, /trades, "
        "/verify/theorem/{name}."
    ),
    lifespan=_lifespan,
)

app.add_middleware(ReadOnlyMiddleware)

app.include_router(verify.router)
app.include_router(state.router)
app.include_router(assumptions.router)
app.include_router(trades.router)
app.include_router(stream.router)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "veritas_version": "0.1"}


@app.get("/", include_in_schema=False)
async def demo_page():
    """Verification playground — the product surface as a web UI.
    Agents use POST /verify/proposal; humans use this page to see what
    happens when they do."""
    return FileResponse(str(_STATIC_DIR / "index.html"))


@app.get("/runner", include_in_schema=False)
async def runner_dashboard():
    """Example-runner dashboard — shows state / assumptions / trades
    from the bundled funding-reversion caller. Secondary surface."""
    return FileResponse(str(_STATIC_DIR / "runner.html"))

"""SSE endpoint — real-time event stream."""

from __future__ import annotations

import json

from fastapi import APIRouter
from starlette.responses import StreamingResponse

from python.api.events import broker

router = APIRouter()


async def _event_generator():
    """Yield SSE-formatted events from the broker."""
    async for event in broker.subscribe():
        data = json.dumps(event)
        yield f"data: {data}\n\n"


@router.get("/stream/events")
async def stream_events():
    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

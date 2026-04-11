"""SSE event broker — in-memory pub/sub for real-time observability."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator


class EventBroker:
    """Fan-out broker: main loop publishes, SSE subscribers receive."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []

    async def publish(self, event: dict) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    async def subscribe(self) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.append(q)
        try:
            while True:
                event = await q.get()
                yield event
        finally:
            self._subscribers.remove(q)


broker = EventBroker()

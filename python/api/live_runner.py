"""Background runner that feeds fake market data through the real loop.

Publishes events to the SSE broker so the dashboard can show
Veritas thinking in real time.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from python.api.events import EventBroker
from python.bridge import VeritasCore
from python.executor import FakeExecutor
from python.observer import FakeObserver
from python.main import run_loop

log = logging.getLogger("veritas.live")


class LiveRunner:
    def __init__(self, broker: EventBroker, db_path: Path) -> None:
        self.broker = broker
        self.db_path = db_path
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        log.info("Live runner started (fake market)")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("Live runner stopped")

    async def _run(self) -> None:
        loop = asyncio.get_event_loop()
        broker = self.broker

        def on_event(event: dict) -> None:
            asyncio.run_coroutine_threadsafe(broker.publish(event), loop)

        while True:
            try:
                await asyncio.to_thread(
                    run_loop,
                    observer=FakeObserver(),
                    executor=FakeExecutor(),
                    core=VeritasCore(),
                    db_path=self.db_path,
                    max_cycles=6,
                    on_event=on_event,
                )
            except Exception:
                log.exception("Live runner iteration failed")
            await asyncio.sleep(1)

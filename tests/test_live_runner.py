"""Tests for the live runner background loop."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from python.api.events import EventBroker
from python.api.live_runner import LiveRunner


@pytest.mark.asyncio
async def test_runner_start_stop():
    broker = EventBroker()
    with tempfile.TemporaryDirectory() as tmpdir:
        runner = LiveRunner(broker, Path(tmpdir) / "test.db")
        await runner.start()
        assert runner._task is not None
        await asyncio.sleep(0.1)
        await runner.stop()


@pytest.mark.asyncio
async def test_runner_publishes_events():
    broker = EventBroker()
    received = []

    async def collect():
        async for event in broker.subscribe():
            received.append(event)
            if len(received) >= 5:
                break

    with tempfile.TemporaryDirectory() as tmpdir:
        runner = LiveRunner(broker, Path(tmpdir) / "test.db")
        collector = asyncio.create_task(collect())
        await runner.start()
        await asyncio.wait_for(collector, timeout=15.0)
        await runner.stop()

    assert len(received) >= 5
    types = {e["type"] for e in received}
    assert "observe" in types


@pytest.mark.asyncio
async def test_runner_event_order():
    broker = EventBroker()
    received = []

    async def collect():
        async for event in broker.subscribe():
            received.append(event)
            if len(received) >= 20:
                break

    with tempfile.TemporaryDirectory() as tmpdir:
        runner = LiveRunner(broker, Path(tmpdir) / "test.db")
        collector = asyncio.create_task(collect())
        await runner.start()
        await asyncio.wait_for(collector, timeout=30.0)
        await runner.stop()

    # First event should be observe
    assert received[0]["type"] == "observe"
    # All events have timestamps
    for e in received:
        assert "timestamp" in e

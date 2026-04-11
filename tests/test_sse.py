"""Tests for SSE event stream and broker."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from python.api.events import EventBroker
from python.api.server import app

client = TestClient(app)


def test_stream_endpoint_in_openapi():
    """GET /stream/events is registered as a route."""
    r = client.get("/openapi.json")
    schema = r.json()
    assert "/stream/events" in schema["paths"]
    assert "get" in schema["paths"]["/stream/events"]


def test_post_stream_rejected():
    r = client.post("/stream/events")
    assert r.status_code == 405


@pytest.mark.asyncio
async def test_broker_publish_subscribe():
    broker = EventBroker()
    received = []

    async def sub():
        async for event in broker.subscribe():
            received.append(event)
            if len(received) >= 2:
                break

    task = asyncio.create_task(sub())
    await asyncio.sleep(0.05)
    await broker.publish({"type": "observe", "timestamp": "00:00:00"})
    await broker.publish({"type": "decide", "timestamp": "00:00:01"})
    await asyncio.wait_for(task, timeout=1.0)

    assert len(received) == 2
    assert received[0]["type"] == "observe"
    assert received[1]["type"] == "decide"


@pytest.mark.asyncio
async def test_broker_multiple_subscribers():
    broker = EventBroker()
    r1, r2 = [], []

    async def sub(out):
        async for event in broker.subscribe():
            out.append(event)
            if len(out) >= 1:
                break

    t1 = asyncio.create_task(sub(r1))
    t2 = asyncio.create_task(sub(r2))
    await asyncio.sleep(0.05)
    await broker.publish({"type": "test"})
    await asyncio.wait_for(asyncio.gather(t1, t2), timeout=1.0)

    assert len(r1) == 1
    assert len(r2) == 1


@pytest.mark.asyncio
async def test_broker_cleanup_on_disconnect():
    broker = EventBroker()
    assert len(broker._subscribers) == 0

    async def sub():
        async for event in broker.subscribe():
            break

    task = asyncio.create_task(sub())
    await asyncio.sleep(0.05)
    assert len(broker._subscribers) == 1
    await broker.publish({"type": "done"})
    await asyncio.wait_for(task, timeout=1.0)
    await asyncio.sleep(0.05)
    assert len(broker._subscribers) == 0

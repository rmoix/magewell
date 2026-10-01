"""Integration tests for FastAPI endpoints."""

import asyncio
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch

from app.main import app
from app.models import HealthStatus, SignalInfo, DeviceLiveStatus
from app.state import state_manager


@pytest.mark.asyncio
async def test_api_devices_and_summary():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Test /api/devices
        resp = await client.get("/api/devices")
        assert resp.status_code == 200
        devices = resp.json()
        assert isinstance(devices, list)
        assert len(devices) > 0

        # Test /api/summary
        resp_sum = await client.get("/api/summary")
        assert resp_sum.status_code == 200
        summary = resp_sum.json()
        assert "total_devices" in summary
        assert "online_count" in summary
        assert "offline_count" in summary


@pytest.mark.asyncio
async def test_api_get_device_by_id():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/devices/mw-cam-01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "mw-cam-01"
        assert data["name"] == "Studio A - Cam 1 (Main Wide)"


@pytest.mark.asyncio
async def test_api_device_not_found():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/devices/non-existent-device-999")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_api_alerts_and_clear():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Clear alerts
        resp_clear = await client.post("/api/alerts/clear")
        assert resp_clear.status_code == 200

        # Get alerts
        resp_alerts = await client.get("/api/alerts")
        assert resp_alerts.status_code == 200
        assert resp_alerts.json() == []


@pytest.mark.asyncio
async def test_api_reload_config():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/reload-config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["device_count"] == 20


@pytest.mark.asyncio
async def test_root_dashboard_html():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "MAGEWELL MINI-NMS" in resp.text
        assert "Studio A - Cam 1" in resp.text


@pytest.mark.asyncio
async def test_sse_generator_and_broadcaster():
    from unittest.mock import MagicMock
    from app.routes.events import event_generator, broadcaster
    import json

    mock_request = MagicMock()
    mock_request.is_disconnected = AsyncMock(return_value=False)

    gen = event_generator(mock_request)
    # Read the initial snapshot event
    first_chunk = await anext(gen)
    assert first_chunk.startswith("data:")
    data = json.loads(first_chunk[len("data:"):])
    assert data["type"] == "snapshot"
    assert len(data["data"]["devices"]) == 20

    # Test broadcasting a custom event
    broadcast_task = asyncio.create_task(
        broadcaster.broadcast("test_event", {"key": "value"})
    )
    await broadcast_task
    second_chunk = await anext(gen)
    assert "test_event" in second_chunk

    # Close generator
    await gen.aclose()

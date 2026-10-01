"""Unit tests for Magewell HTTP Client and Poller."""

import pytest
import httpx
from unittest.mock import AsyncMock, patch

from app.magewell_client import MagewellClient, parse_signal_data, _parse_frame_rate
from app.models import DeviceAuth, DeviceConfig, DeviceExpectedState, HealthStatus
from app.poller import DevicePoller


def test_parse_frame_rate():
    assert _parse_frame_rate(50) == 50.0
    assert _parse_frame_rate("5000") == 50.0
    assert _parse_frame_rate(5994) == 59.94
    assert _parse_frame_rate("50000") == 50.0
    assert _parse_frame_rate(60.0) == 60.0
    assert _parse_frame_rate(None) is None
    assert _parse_frame_rate("invalid") is None


def test_parse_signal_data():
    raw_data = {
        "signal-locked": True,
        "width": 1920,
        "height": 1080,
        "frame-rate": 5000,
        "color-format": "YUV422",
        "interlaced": False,
    }
    sig = parse_signal_data(raw_data)
    assert sig.locked is True
    assert sig.width == 1920
    assert sig.height == 1080
    assert sig.frame_rate == 50.0
    assert sig.color_format == "YUV422"
    assert sig.interlaced is False


@pytest.mark.asyncio
async def test_magewell_client_success():
    client = MagewellClient(timeout=1.0)
    dev = DeviceConfig(
        id="test-1",
        name="Test Cam",
        ip="127.0.0.1",
        auth=DeviceAuth(username="admin", password="password123"),
    )

    mock_summary = {"name": "Test Cam", "ndi-name": "TEST-CAM", "streaming": True}
    mock_signal = {
        "signal-locked": True,
        "width": 1920,
        "height": 1080,
        "frame-rate": 5000,
        "color-format": "YUV422",
    }
    mock_device = {
        "product-name": "Pro Convert HDMI Plus",
        "serial-no": "B1001",
        "firmware-version": "1.0.600",
        "board-temperature": 45.2,
        "cpu-usage": 12.0,
        "memory-usage": 28.5,
    }

    async def mock_fetch(c, base_url, endpoint, auth):
        if "summary" in endpoint:
            return mock_summary
        if "signal" in endpoint:
            return mock_signal
        if "device" in endpoint:
            return mock_device
        return None

    with patch.object(client, "fetch_endpoint", side_effect=mock_fetch):
        is_online, resp_ms, telemetry, error_msg = await client.query_device(dev)
        assert is_online is True
        assert error_msg is None
        assert telemetry["summary"]["ndi-name"] == "TEST-CAM"
        assert telemetry["signal"]["width"] == 1920
        assert telemetry["device"]["board-temperature"] == 45.2


@pytest.mark.asyncio
async def test_magewell_client_offline():
    client = MagewellClient(timeout=1.0)
    dev = DeviceConfig(id="test-off", name="Offline Unit", ip="192.168.254.254")

    async def mock_fetch_fail(c, base_url, endpoint, auth):
        return None

    with patch.object(client, "fetch_endpoint", side_effect=mock_fetch_fail):
        is_online, resp_ms, telemetry, error_msg = await client.query_device(dev)
        assert is_online is False
        assert "Device unreachable" in error_msg


@pytest.mark.asyncio
async def test_poller_isolation_and_execution():
    from app.models import AppConfig, PollingConfig

    dev1 = DeviceConfig(id="dev-1", name="Dev 1", ip="192.168.1.101")
    dev2 = DeviceConfig(id="dev-2", name="Dev 2", ip="192.168.1.102")
    cfg = AppConfig(
        polling=PollingConfig(interval_seconds=1.0, concurrency_limit=2),
        devices=[dev1, dev2],
    )

    poller = DevicePoller(config=cfg)

    # Mock query_device so dev1 is online and dev2 is offline
    async def mock_query(device, client=None):
        if device.id == "dev-1":
            return True, 15.0, {
                "signal": {"signal-locked": True, "width": 1920, "height": 1080, "frame-rate": 50.0},
                "device": {"board-temperature": 42.0},
                "summary": {"ndi-name": "DEV1-STREAM"},
            }, None
        return False, 2000.0, {}, "ConnectTimeout"

    with patch.object(poller._magewell_client, "query_device", side_effect=mock_query):
        statuses = await poller.poll_all_devices()
        assert len(statuses) == 2
        
        status1 = next(s for s in statuses if s.id == "dev-1")
        status2 = next(s for s in statuses if s.id == "dev-2")

        assert status1.is_online is True
        assert status1.signal.locked is True
        assert status1.signal.width == 1920
        assert status1.temperature_c == 42.0

        assert status2.is_online is False
        assert status2.status == HealthStatus.OFFLINE

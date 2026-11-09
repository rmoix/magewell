import httpx
import pytest

from app.models import AppConfig, ManualDevice
from simulator.device import SimDevice, make_app


class FailingTransport(httpx.AsyncBaseTransport):
    """Simula un equip apagat."""

    async def handle_async_request(self, request):
        raise httpx.ConnectError("simulated: host unreachable", request=request)


class Fleet:
    """Equips simulats indexats per port, servits en procés (sense xarxa)."""

    def __init__(self, devices):
        self.devices = {9000 + i: d for i, d in enumerate(devices, start=1)}
        self.down = set()

    def transport(self, ip, port):
        if port in self.down:
            return FailingTransport()
        return httpx.ASGITransport(app=make_app(self.devices[port]))

    def config(self, **kw) -> AppConfig:
        cfg = AppConfig(**kw)
        cfg.discovery.enabled = False
        cfg.devices = [ManualDevice(ip="10.0.0.1", port=p) for p in self.devices] + list(cfg.devices)
        return cfg


@pytest.fixture
def encoder():
    return SimDevice("encoder", "HDMI Plus", "B312000000001", 1, "CAM1")


@pytest.fixture
def decoder():
    return SimDevice("decoder", "NDI to HDMI", "B401000000002", 2, source="PGM")

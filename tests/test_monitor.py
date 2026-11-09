from pathlib import Path

import httpx

from app.config import ConfigManager
from app.main import create_app
from app.models import ExpectedState, HealthStatus, ManualDevice, Role
from app.service import Monitor
from simulator.device import SimDevice
from tests.conftest import Fleet


class StaticConfig(ConfigManager):
    def __init__(self, cfg):
        super().__init__(Path("unused.yaml"))
        self._cfg = cfg

    def load(self):
        self.config = self._cfg
        return self._cfg


async def make_monitor(tmp_path, fleet, **cfg_kw):
    m = Monitor(StaticConfig(fleet.config(**cfg_kw)), data_dir=tmp_path, transport_factory=fleet.transport)
    await m.start(background=False)
    return m


async def test_poll_cycle_statuses(tmp_path):
    fleet = Fleet([
        SimDevice("encoder", "HDMI Plus", "S1", 1, "CAM1"),
        SimDevice("encoder", "HDMI Plus", "S2", 2, "CAM2", signal=False),
        SimDevice("decoder", "NDI to HDMI", "S3", 3, source="PGM"),
        SimDevice("encoder", "HDMI Plus", "S4", 4, "CAM4", password="x"),
    ])
    m = await make_monitor(tmp_path, fleet)
    await m.poll_all()
    by_port = {d.port: d for d in m.state.all()}
    assert by_port[9001].status == HealthStatus.OK and by_port[9001].name == "CAM1"
    assert by_port[9002].status == HealthStatus.NO_SIGNAL
    assert by_port[9003].status == HealthStatus.OK and by_port[9003].role == Role.DECODER
    assert by_port[9004].status == HealthStatus.AUTH_ERROR
    s = m.state.summary()
    assert (s.total, s.ok, s.no_signal, s.auth_error) == (4, 2, 1, 1)
    await m.stop()


async def test_offline_needs_consecutive_failures(tmp_path):
    fleet = Fleet([SimDevice("encoder", "HDMI Plus", "S1", 1, "CAM1")])
    m = await make_monitor(tmp_path, fleet)
    await m.poll_all()
    assert m.state.all()[0].status == HealthStatus.OK
    fleet.down.add(9001)
    m.poller.forget("10.0.0.1:9001")  # força nou transport
    await m.poll_all()
    assert m.state.all()[0].status == HealthStatus.OK  # 1 error: encara no
    await m.poll_all()
    d = m.state.all()[0]
    assert d.status == HealthStatus.OFFLINE
    assert d.serial == "S1" and d.model  # es conserven les dades conegudes
    assert any(a.status == HealthStatus.OFFLINE for a in m.state.alerts())
    await m.stop()


async def test_override_by_serial_and_expected(tmp_path):
    fleet = Fleet([SimDevice("encoder", "HDMI Plus", "S1", 1, "CAM1", fmt="1080p59.94")])
    m = await make_monitor(
        tmp_path, fleet,
        devices=[ManualDevice(serial="S1", name="Càmera escenari", location="Escenari",
                              expected=ExpectedState(frame_rate=50))],
    )
    await m.poll_all()  # 1r: aprèn el número de sèrie
    await m.poll_all()
    d = m.state.all()[0]
    assert d.name == "Càmera escenari" and d.location == "Escenari"
    assert d.status == HealthStatus.WARNING
    await m.stop()


async def test_inventory_persists(tmp_path):
    fleet = Fleet([SimDevice("encoder", "HDMI Plus", "S1", 1, "CAM1")])
    m = await make_monitor(tmp_path, fleet)
    m.registry.add_discovered("10.0.0.9", 80)
    await m.stop()
    assert "10.0.0.9" in (tmp_path / "inventory.json").read_text()


async def test_http_api(tmp_path):
    fleet = Fleet([SimDevice("encoder", "HDMI Plus", "S1", 1, "CAM1")])
    m = Monitor(StaticConfig(fleet.config()), data_dir=tmp_path, transport_factory=fleet.transport)
    app = create_app(m, background=False)
    async with app.router.lifespan_context(app):
        await m.poll_all()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get("/")
            assert r.status_code == 200 and "Magewell NMS" in r.text
            devs = (await c.get("/api/devices")).json()
            assert devs[0]["status"] == "OK"
            raw = (await c.get(f"/api/devices/{devs[0]['id']}/raw")).json()
            assert "get-summary-info" in raw
            assert (await c.get("/api/summary")).json()["ok"] == 1
            assert (await c.post("/api/poll-now")).status_code == 200
            assert (await c.delete(f"/api/devices/{devs[0]['id']}")).status_code == 400  # manual: no es pot oblidar
            assert (await c.get("/api/devices/nope")).status_code == 404

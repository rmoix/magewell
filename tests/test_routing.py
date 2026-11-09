import httpx
import pytest

from app.main import create_app
from app.models import HealthStatus
from app.routing import RouteError, split_ndi_name
from simulator.device import SimDevice
from tests.conftest import Fleet
from tests.test_monitor import StaticConfig, make_monitor
from app.service import Monitor


def ndi_fleet():
    devs = [
        SimDevice("encoder", "HDMI Plus", "S1", 1, "CAM1"),
        SimDevice("encoder", "HDMI Plus", "S2", 2, "CAM2", signal=False),
        SimDevice("decoder", "NDI to HDMI", "S3", 3, source="REGIA (PGM)"),
    ]
    for d in devs:
        d.network = devs
        d.extra_sources = ["REGIA (PGM)", "REGIA (PVW)"]
    return Fleet(devs)


def test_split_ndi_name():
    assert split_ndi_name("REGIA (PGM)") == ("REGIA", "PGM")
    assert split_ndi_name("PC (Cam (1))") == ("PC", "Cam (1)")
    assert split_ndi_name("CAM1") == ("CAM1", "")


async def test_refresh_sources_and_link_encoders(tmp_path):
    fleet = ndi_fleet()
    m = await make_monitor(tmp_path, fleet)
    await m.poll_all()
    sources = {s.name: s for s in await m.router.refresh()}
    assert set(sources) == {"CAM1", "CAM2", "REGIA (PGM)", "REGIA (PVW)"}
    assert sources["CAM1"].device_id == "10.0.0.1:9001"
    assert sources["REGIA (PGM)"].device_id is None
    assert sources["REGIA (PGM)"].seen_by == ["10.0.0.1:9003"]
    await m.stop()


async def test_route_changes_decoder_source(tmp_path):
    fleet = ndi_fleet()
    m = await make_monitor(tmp_path, fleet)
    await m.poll_all()
    dec_id = "10.0.0.1:9003"
    st = await m.router.route(dec_id, "CAM1")
    assert st.ndi.name == "CAM1" and st.status == HealthStatus.OK
    assert fleet.devices[9003].source == "CAM1"
    # Una font sense senyal: el decoder queda enrutat però sense vídeo
    st = await m.router.route(dec_id, "CAM2")
    assert st.ndi.name == "CAM2" and st.status == HealthStatus.NO_SIGNAL
    assert any("Enrutament" in a.message for a in m.state.alerts())
    await m.stop()


async def test_route_errors(tmp_path):
    fleet = ndi_fleet()
    m = await make_monitor(tmp_path, fleet)
    await m.poll_all()
    with pytest.raises(RouteError, match="no és un decoder"):
        await m.router.route("10.0.0.1:9001", "CAM2")
    with pytest.raises(RouteError, match="no trobat"):
        await m.router.route("nope", "CAM2")
    m.config.routing.enabled = False
    with pytest.raises(RouteError, match="desactivat"):
        await m.router.route("10.0.0.1:9003", "CAM1")
    await m.stop()


async def test_route_rejected_by_device(tmp_path):
    fleet = ndi_fleet()
    m = await make_monitor(tmp_path, fleet)
    await m.poll_all()
    original = fleet.devices[9003].handle

    def reject(method, params, sid):
        if method == "set-channel":
            return {"status": 16}, None
        return original(method, params, sid)

    fleet.devices[9003].handle = reject
    with pytest.raises(RouteError, match="NOT_EXIST"):
        await m.router.route("10.0.0.1:9003", "CAM1")
    await m.stop()


async def test_routing_http(tmp_path):
    fleet = ndi_fleet()
    m = Monitor(StaticConfig(fleet.config()), data_dir=tmp_path, transport_factory=fleet.transport)
    app = create_app(m, background=False)
    async with app.router.lifespan_context(app):
        await m.poll_all()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/routing/refresh")
            assert len(r.json()["sources"]) == 4
            r = await c.post("/api/routing/route", json={"rx": "10.0.0.1:9003", "tx": "REGIA (PVW)"})
            assert r.status_code == 200 and r.json()["confirmed"] is True
            r = await c.post("/api/routing/route", json={"rx": "10.0.0.1:9001", "tx": "REGIA (PVW)"})
            assert r.status_code == 409

import httpx

from app.discovery import expand_targets, identify
from simulator.device import SimDevice, make_app


def test_expand_cidr_range_single():
    assert len(expand_targets(["192.168.1.0/24"])) == 254
    assert expand_targets(["10.0.0.5-7"]) == ["10.0.0.5", "10.0.0.6", "10.0.0.7"]
    assert expand_targets(["10.0.0.250-10.0.1.1"]) == ["10.0.0.250", "10.0.0.251", "10.0.0.252", "10.0.0.253",
                                                        "10.0.0.254", "10.0.0.255", "10.0.1.0", "10.0.1.1"]
    assert expand_targets(["127.0.0.1"]) == ["127.0.0.1"]


def test_expand_exclude_dedupe_and_limit():
    out = expand_targets(["10.0.0.1-10", "10.0.0.5-15 (Ethernet)"], exclude=["10.0.0.3"])
    assert "10.0.0.3" not in out and len(out) == 14
    assert len(expand_targets(["10.0.0.0/16"], max_hosts=100)) == 100


async def test_identify_magewell():
    t = httpx.ASGITransport(app=make_app(SimDevice("encoder", "HDMI Plus", "B1")))
    h = await identify("10.0.0.1", 80, transport=t)
    assert h.kind == "mwapi"

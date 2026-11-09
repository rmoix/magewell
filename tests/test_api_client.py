import httpx
import pytest

from app.magewell.api import AuthFailed, DeviceUnreachable, MagewellSession, NotMagewell, md5_hex
from app.models import Credential
from simulator.device import make_app
from tests.conftest import FailingTransport


def session(dev, creds=None):
    return MagewellSession("10.0.0.1", 80, creds or [Credential()], transport=httpx.ASGITransport(app=make_app(dev)))


def test_md5_matches_magewell_doc_example():
    # L'exemple de la documentació oficial: id=Admin&pass=e3afed0047b08059d0fada10f400c1e5
    assert md5_hex("Admin") == "e3afed0047b08059d0fada10f400c1e5"


async def test_login_and_call(encoder):
    s = session(encoder)
    data = await s.call("get-summary-info")
    assert data["status"] == 0
    assert data["device"]["serial-no"] == encoder.serial
    assert s.logged_in
    await s.close()


async def test_relogin_when_session_expires(encoder):
    s = session(encoder)
    await s.call("get-summary-info")
    encoder.sessions.clear()  # l'equip s'ha reiniciat: la cookie ja no és vàlida
    data = await s.call("get-summary-info")
    assert data["status"] == 0
    await s.close()


async def test_credentials_fallback(encoder):
    encoder.password = "secret"
    s = session(encoder, [Credential(password="wrong"), Credential(password="secret")])
    await s.call("ping")
    assert s.active_credential.password == "secret"
    await s.close()


async def test_auth_failed(encoder):
    encoder.password = "secret"
    s = session(encoder)
    with pytest.raises(AuthFailed):
        await s.call("get-summary-info")
    await s.close()


async def test_unreachable():
    s = MagewellSession("10.0.0.1", transport=FailingTransport())
    with pytest.raises(DeviceUnreachable):
        await s.raw("ping")
    await s.close()


async def test_not_magewell():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/html")]})
        await send({"type": "http.response.body", "body": b"<html>router</html>"})

    s = MagewellSession("10.0.0.1", transport=httpx.ASGITransport(app=app))
    with pytest.raises(NotMagewell):
        await s.raw("ping")
    await s.close()

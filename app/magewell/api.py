"""Sessió HTTP amb un equip Magewell Pro Convert.

Documentació oficial:
  https://www.magewell.com/api-docs/pro-convert-encoder-api/
  https://www.magewell.com/api-docs/pro-convert-decoder-api/

Resum del protocol:
  - Totes les crides: GET http://<ip>/mwapi?method=<nom>[&param=valor]
  - Resposta JSON amb camp "status" (0 = èxit). Vegeu STATUS_NAMES.
  - Login: method=login&id=<usuari>&pass=<md5(contrasenya) en hex>. La sessió viatja a la cookie "sid".
  - Usuari per defecte de fàbrica: Admin / Admin.
"""

import hashlib
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from app.models import Credential

logger = logging.getLogger(__name__)

STATUS_SUCCESS = 0
STATUS_NOT_PERMITTED = 31
STATUS_AUTH_FAILED = 36
STATUS_NOT_LOGGED_IN = 37

STATUS_NAMES = {
    0: "SUCCESS", 1: "PENDING", 2: "TIMEOUT", 3: "INTERRUPTED", 4: "TRY_AGAIN",
    5: "NOT_IMPLEMENTED", 6: "UNKNOWN_ERROR", 7: "INVALID_ARG", 8: "NO_MEMORY",
    9: "UNSUPPORTED", 10: "FILE_BUSY", 11: "DEVICE_BUSY", 12: "DEVICE_LOST",
    13: "IO_FAILED", 14: "READ_FAILED", 15: "WRITE_FAILED", 16: "NOT_EXIST",
    17: "TOO_MANY", 18: "TOO_LARGE", 19: "OVERFLOW", 20: "UNDERFLOW",
    21: "FORMAT_ERROR", 22: "FILE_EXISTS", 23: "FILE_TYPE_ERROR",
    24: "DEVICE_TYPE_ERROR", 25: "IS_DIRECTORY", 26: "READ_ONLY",
    27: "RANGE_ERROR", 28: "BROKEN_PIPE", 29: "NO_SPACE", 30: "NOT_DIRECTORY",
    31: "NOT_PERMITTED", 32: "BAD_ADDRESS", 33: "SEEK_ERROR",
    34: "CROSS_DEVICE_LINK", 35: "NOT_INITIALIZED", 36: "AUTH_FAILED",
    37: "NOT_LOGGED_IN", 38: "WRONG_STATE", 39: "MISMATCH", 40: "VERIFY_FAILED",
    41: "CONSTRAINT_VIOLATION",
}

# Mètodes només de lectura, segurs per a la captura de diagnòstic. MAI s'hi han d'afegir set-*, reboot, update...
READ_ONLY_METHODS = [
    "ping",
    "get-caps",
    "get-summary-info",
    "get-signal-info",
    "get-video-config",
    "get-ndi-config",
    "get-tally",
    "get-channel",
    "list-channels",
    "get-eth-status",
    "get-auto-reboot",
    "get-update-state",
]


def md5_hex(password: str) -> str:
    return hashlib.md5(password.encode("utf-8")).hexdigest()


def status_name(code: Any) -> str:
    return STATUS_NAMES.get(code, str(code)) if isinstance(code, int) else str(code)


class DeviceUnreachable(Exception):
    """Error de xarxa / timeout."""


class NotMagewell(Exception):
    """L'equip respon però no amb l'API /mwapi esperada."""


class AuthFailed(Exception):
    """Cap de les credencials configurades és vàlida."""


class MagewellSession:
    """Una sessió persistent (keep-alive + cookie sid) amb un sol equip.

    Es fa servir un client HTTP per equip: les cookies no es distingeixen per port,
    així que compartir client entre equips (o entre simuladors a 127.0.0.1) barrejaria sessions.
    """

    def __init__(
        self,
        ip: str,
        port: int = 80,
        credentials: Optional[List[Credential]] = None,
        timeout: float = 2.5,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.ip = ip
        self.port = port
        self.credentials = credentials or [Credential()]
        self.timeout = timeout
        self.base_url = f"http://{ip}" if port == 80 else f"http://{ip}:{port}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=1, keepalive_expiry=30),
            headers={"User-Agent": "magewell-mini-nms"},
        )
        self.logged_in = False
        self.active_credential: Optional[Credential] = None
        self.last_rtt_ms: Optional[float] = None

    async def close(self) -> None:
        await self._client.aclose()

    async def raw(self, method: str, **params: Any) -> Dict[str, Any]:
        """Crida sense gestió de sessió. Retorna el JSON (dict)."""
        query = {"method": method, **params}
        t0 = time.perf_counter()
        try:
            resp = await self._client.get("/mwapi", params=query)
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as e:
            raise DeviceUnreachable(f"{type(e).__name__}: {e}") from e
        except httpx.HTTPError as e:
            raise DeviceUnreachable(str(e)) from e
        self.last_rtt_ms = round((time.perf_counter() - t0) * 1000, 1)

        if resp.status_code in (401, 403):
            return {"status": STATUS_NOT_LOGGED_IN, "_http": resp.status_code}
        if resp.status_code != 200:
            raise NotMagewell(f"HTTP {resp.status_code} a /mwapi")
        try:
            data = resp.json()
        except ValueError as e:
            raise NotMagewell("La resposta de /mwapi no és JSON") from e
        if not isinstance(data, dict) or "status" not in data:
            raise NotMagewell("JSON sense camp 'status'")
        return data

    async def login(self) -> None:
        """Prova les credencials en ordre (començant per l'última que ha funcionat)."""
        creds = list(self.credentials)
        if self.active_credential in creds:
            creds.remove(self.active_credential)
            creds.insert(0, self.active_credential)

        last_status: Any = None
        for cred in creds:
            data = await self.raw("login", id=cred.username, **{"pass": md5_hex(cred.password)})
            last_status = data.get("status")
            if last_status == STATUS_SUCCESS:
                # Alguns firmwares podrien retornar l'sid al cos en lloc de (o a més de) la cookie.
                sid = data.get("sid")
                if sid and "sid" not in self._client.cookies:
                    self._client.cookies.set("sid", str(sid))
                self.logged_in = True
                self.active_credential = cred
                logger.info("Login correcte a %s amb l'usuari '%s'", self.base_url, cred.username)
                return
        self.logged_in = False
        raise AuthFailed(
            f"Login rebutjat ({status_name(last_status)}). Revisa usuari/contrasenya a config.yaml"
        )

    async def call(self, method: str, **params: Any) -> Dict[str, Any]:
        """Crida amb sessió: fa login si cal i reintenta una vegada si la sessió ha caducat."""
        if not self.logged_in:
            await self.login()
        data = await self.raw(method, **params)
        if data.get("status") in (STATUS_NOT_LOGGED_IN, STATUS_NOT_PERMITTED):
            self.logged_in = False
            await self.login()
            data = await self.raw(method, **params)
        return data

    async def logout(self) -> None:
        if self.logged_in:
            try:
                await self.raw("logout")
            except Exception:
                pass
            self.logged_in = False

"""Sondeig d'un equip: crida l'API, parseja i construeix el DeviceStatus."""

import asyncio
import logging
from typing import Callable, Dict, Optional, Tuple

import httpx

from app.health import evaluate, merge_expected
from app.magewell.api import AuthFailed, DeviceUnreachable, MagewellSession, NotMagewell, status_name
from app.magewell.parse import parse_all
from app.models import AppConfig, DeviceStatus, HealthStatus, NdiInfo, Role, SignalInfo
from app.registry import Registry, Target, now_iso

logger = logging.getLogger(__name__)

TransportFactory = Callable[[str, int], Optional[httpx.AsyncBaseTransport]]


def display_name(t: Target, role: Role, ndi_name: Optional[str], model: Optional[str]) -> str:
    if t.name:
        return t.name
    if role == Role.ENCODER and ndi_name:
        return ndi_name
    if t.last_name:
        return t.last_name
    kind = {Role.ENCODER: "Encoder", Role.DECODER: "Decoder"}.get(role, "Magewell")
    return f"{kind} {t.id}"


def seed_status(t: Target, config: AppConfig) -> DeviceStatus:
    return DeviceStatus(
        id=t.id, ip=t.ip, port=t.port, source=t.source,
        name=t.name or t.last_name or f"Magewell {t.id}",
        location=t.location, model=t.last_model, serial=t.serial,
        expected=merge_expected(config.defaults.expected, t.expected),
        status=HealthStatus.UNKNOWN, issues=["Pendent del primer sondeig"],
    )


class Poller:
    def __init__(self, registry: Registry, transport_factory: Optional[TransportFactory] = None):
        self.registry = registry
        self.transport_factory = transport_factory
        self._sessions: Dict[str, MagewellSession] = {}

    def session(self, t: Target, timeout: float) -> MagewellSession:
        s = self._sessions.get(t.id)
        creds = self.registry.credentials_for(t)
        if s is None or s.credentials != creds or s.timeout != timeout:
            if s is not None:
                self._drop(t.id)
            transport = self.transport_factory(t.ip, t.port) if self.transport_factory else None
            s = MagewellSession(t.ip, t.port, creds, timeout=timeout, transport=transport)
            self._sessions[t.id] = s
        return s

    def _drop(self, tid: str) -> None:
        s = self._sessions.pop(tid, None)
        if s is not None:
            try:
                asyncio.get_running_loop().create_task(s.close())
            except RuntimeError:
                pass

    def forget(self, tid: str) -> None:
        self._drop(tid)

    async def close(self) -> None:
        for s in list(self._sessions.values()):
            await s.close()
        self._sessions.clear()

    async def poll(self, t: Target, prev: Optional[DeviceStatus], config: AppConfig) -> Tuple[DeviceStatus, Optional[dict]]:
        expected = merge_expected(config.defaults.expected, t.expected)
        base = prev.model_copy(deep=True) if prev else seed_status(t, config)
        base.expected = expected
        base.location = t.location
        base.source = t.source
        base.last_checked = now_iso()
        session = self.session(t, config.polling.timeout_seconds)
        raw: Dict[str, dict] = {}

        try:
            summary = await session.call("get-summary-info")
            raw["get-summary-info"] = summary
            if summary.get("status") != 0:
                raise NotMagewell(f"get-summary-info ha retornat {status_name(summary.get('status'))}")
            role_hint = parse_all(summary)["role"]
            signal = channel = None
            if role_hint == Role.DECODER:
                channel = await session.call("get-channel")
                raw["get-channel"] = channel
            else:
                signal = await session.call("get-signal-info")
                raw["get-signal-info"] = signal
            parsed = parse_all(summary, signal, channel)
        except DeviceUnreachable as e:
            return self._failure(base, t, config, f"No respon: {e}"), None
        except AuthFailed as e:
            st = self._online(base, session)
            st.status = HealthStatus.AUTH_ERROR
            st.error_message = str(e)
            st.status, st.issues = evaluate(st)
            return st, raw or None
        except NotMagewell as e:
            st = self._online(base, session)
            st.status = HealthStatus.UNKNOWN
            st.error_message = str(e)
            st.issues = [str(e)]
            return st, raw or None
        except Exception as e:  # mai ha de tombar el bucle
            logger.exception("Error inesperat sondejant %s", t.id)
            return self._failure(base, t, config, f"Error intern: {e}"), None

        st = self._online(base, session)
        st.role = parsed["role"]
        st.model = parsed["model"] or st.model
        st.serial = parsed["serial"] or st.serial
        for k in ("firmware", "hw_revision", "temperature_c", "cpu_usage", "memory_usage",
                  "uptime_s", "fan_rpm", "output_state", "mac", "link_speed"):
            setattr(st, k, parsed[k])
        st.signal = parsed["signal"]
        st.ndi = parsed["ndi"]
        st.error_message = None
        st.name = display_name(t, st.role, st.ndi.name, st.model)
        # Si el número de sèrie ja era a l'inventari amb una altra IP, el registre elimina l'entrada antiga.
        remembered = st.ndi.name if st.role == Role.ENCODER else None  # només noms reals, no els generats
        for rid in self.registry.update_identity(t.id, st.serial, remembered, st.model):
            self._drop(rid)
        # Pot ser que ara coincideixi una sobreescriptura per número de sèrie.
        if t.name:
            st.name = t.name
        st.location = t.location
        st.expected = merge_expected(config.defaults.expected, t.expected)
        st.status = HealthStatus.UNKNOWN
        st.status, st.issues = evaluate(st)
        return st, raw

    @staticmethod
    def _online(base: DeviceStatus, session: MagewellSession) -> DeviceStatus:
        base.is_online = True
        base.consecutive_failures = 0
        base.response_time_ms = session.last_rtt_ms
        base.last_seen = base.last_checked
        return base

    @staticmethod
    def _failure(base: DeviceStatus, t: Target, config: AppConfig, msg: str) -> DeviceStatus:
        base.consecutive_failures += 1
        base.error_message = msg
        if base.consecutive_failures >= config.polling.offline_after_failures or base.status == HealthStatus.UNKNOWN:
            base.is_online = False
            base.response_time_ms = None
            base.signal = SignalInfo()
            base.ndi = NdiInfo(name=base.ndi.name)
            base.status, base.issues = evaluate(base)
        # Si encara no s'ha arribat al llindar es manté l'estat anterior (evita falses alarmes per un timeout puntual).
        return base

"""Enrutament NDI: llista de fonts (Tx) i canvi de font dels decoders (Rx).

A NDI no hi ha un router central: és el receptor qui tria la font. Per tant:
  - Tx = fonts NDI que veuen els decoders a la xarxa (get-ndi-sources). Inclou fonts que no són Magewell (vMix, OBS...).
  - Rx = decoders Magewell. La font actual és la que retorna get-channel (ja la llegeix el sondeig normal).
  - Enrutar = set-channel&ndi-name=true&name=<font> al decoder.

Pendent de confirmar amb equips reals: si set-channel accepta qualsevol font descoberta o només les predefinides
(list-channels). Si l'equip respon amb un error, es mostra el codi exacte a l'usuari.
"""

import asyncio
import datetime
import logging
import re
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from app.magewell.api import AuthFailed, DeviceUnreachable, NotMagewell, status_name
from app.models import DeviceStatus, HealthStatus, NdiSource, Role
from app.registry import now_iso

if TYPE_CHECKING:
    from app.service import Monitor

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^(.*?)\s*\((.*)\)\s*$")


class RouteError(Exception):
    pass


def split_ndi_name(name: str) -> Tuple[str, str]:
    """'REGIA (PGM)' -> ('REGIA', 'PGM'). Sense parèntesi -> (nom, '')."""
    m = _NAME_RE.match(name)
    if m and m.group(1):
        return m.group(1).strip(), m.group(2).strip()
    return name.strip(), ""


def same_source(a: Optional[str], b: Optional[str]) -> bool:
    return bool(a) and bool(b) and a.strip().casefold() == b.strip().casefold()


class Router:
    def __init__(self, monitor: "Monitor"):
        self.m = monitor
        self.sources: Dict[str, NdiSource] = {}  # clau: nom en minúscules
        self.last_refresh: Optional[str] = None
        self._refresh_lock = asyncio.Lock()
        self._route_lock = asyncio.Lock()

    # ------------------------------------------------------------------ fonts (Tx)
    def decoders(self) -> List[DeviceStatus]:
        return [d for d in self.m.state.all() if d.role == Role.DECODER]

    async def refresh(self) -> List[NdiSource]:
        """Demana get-ndi-sources a tots els decoders en línia (o als encoders si no n'hi ha cap)."""
        async with self._refresh_lock:
            cfg = self.m.config
            online = [d for d in self.m.state.all() if d.is_online and d.status != HealthStatus.AUTH_ERROR]
            askers = [d for d in online if d.role == Role.DECODER] or [d for d in online if d.role == Role.ENCODER][:2]

            async def ask(dev: DeviceStatus):
                t = self.m.registry.get(dev.id)
                if not t:
                    return dev.id, []
                try:
                    resp = await self.m.poller.session(t, cfg.polling.timeout_seconds).call("get-ndi-sources")
                except (DeviceUnreachable, AuthFailed, NotMagewell) as e:
                    logger.debug("get-ndi-sources a %s: %s", dev.id, e)
                    return dev.id, []
                if resp.get("status") != 0:
                    return dev.id, []
                return dev.id, [s for s in resp.get("sources") or [] if isinstance(s, dict) and s.get("ndi-name")]

            results = await asyncio.gather(*(ask(d) for d in askers))
            stamp = now_iso()
            seen_now: Dict[str, NdiSource] = {}
            for dev_id, items in results:
                for it in items:
                    name = str(it["ndi-name"])
                    key = name.casefold()
                    src = seen_now.get(key) or self.sources.get(key)
                    if src is None:
                        machine, stream = split_ndi_name(name)
                        src = NdiSource(name=name, machine=machine, stream=stream)
                    src = src.model_copy()
                    src.ip_addr = it.get("ip-addr") or src.ip_addr
                    src.last_seen = stamp
                    src.online = True
                    if key not in seen_now:
                        src.seen_by = []
                    if dev_id not in src.seen_by:
                        src.seen_by.append(dev_id)
                    seen_now[key] = src

            # Les fonts que ja no es veuen es mantenen un temps (marcades com a no visibles) i després s'obliden.
            now = datetime.datetime.now(datetime.timezone.utc)
            merged: Dict[str, NdiSource] = dict(seen_now)
            for key, src in self.sources.items():
                if key in merged or not src.last_seen:
                    continue
                age = (now - datetime.datetime.fromisoformat(src.last_seen)).total_seconds()
                if age < cfg.routing.forget_after_seconds:
                    src.online = age < cfg.routing.source_ttl_seconds
                    merged[key] = src
            # Si no hi ha ningú a qui preguntar (tots offline), no oblidem res.
            self.sources = merged if askers else self.sources
            self._link_encoders()
            self.last_refresh = stamp
            self.m.broadcaster.publish("sources", self.snapshot())
            return self.sources_list()

    def _link_encoders(self) -> None:
        """Associa cada font a l'encoder Magewell que l'emet (pel nom NDI, o per IP si és única)."""
        encoders = [d for d in self.m.state.all() if d.role == Role.ENCODER]
        by_ip: Dict[str, List[DeviceStatus]] = {}
        for e in encoders:
            by_ip.setdefault(e.ip, []).append(e)
        for src in self.sources.values():
            src.device_id = None
            for e in encoders:
                n = e.ndi.name
                if n and (same_source(n, src.name) or same_source(n, src.stream)):
                    src.device_id = e.id
                    break
            if src.device_id is None and src.ip_addr:
                host = src.ip_addr.rsplit(":", 1)[0]
                if len(by_ip.get(host, [])) == 1:
                    src.device_id = by_ip[host][0].id

    def sources_list(self) -> List[NdiSource]:
        return sorted(self.sources.values(), key=lambda s: (s.machine.casefold(), s.stream.casefold()))

    def snapshot(self) -> dict:
        return {
            "sources": [s.model_dump() for s in self.sources_list()],
            "last_refresh": self.last_refresh,
            "enabled": self.m.config.routing.enabled,
        }

    # ------------------------------------------------------------------ enrutar
    async def route(self, rx_id: str, tx_name: str) -> DeviceStatus:
        if not self.m.config.routing.enabled:
            raise RouteError("L'enrutament està desactivat a config.yaml (routing.enabled: false)")
        tx_name = (tx_name or "").strip()
        if not tx_name:
            raise RouteError("Falta el nom de la font")
        dev = self.m.state.get(rx_id)
        t = self.m.registry.get(dev.id) if dev else None
        if not dev or not t:
            raise RouteError(f"Equip '{rx_id}' no trobat")
        if dev.role != Role.DECODER:
            raise RouteError(f"'{dev.name}' no és un decoder")
        if not dev.is_online:
            raise RouteError(f"'{dev.name}' no respon")

        async with self._route_lock:
            session = self.m.poller.session(t, self.m.config.polling.timeout_seconds)
            previous = dev.ndi.name
            try:
                resp = await session.call("set-channel", **{"ndi-name": "true", "name": tx_name})
            except AuthFailed as e:
                raise RouteError(f"Error d'autenticació a '{dev.name}': {e}") from e
            except (DeviceUnreachable, NotMagewell) as e:
                raise RouteError(f"'{dev.name}' no ha respost: {e}") from e
            code = resp.get("status")
            if code != 0:
                raise RouteError(
                    f"'{dev.name}' ha rebutjat el canvi de font (status {code} {status_name(code)}). "
                    "Pot ser que l'equip només accepti fonts predefinides."
                )

            # Tornem a llegir l'equip de seguida per reflectir el canvi sense esperar el següent cicle.
            status, raw = await self.m.poller.poll(t, self.m.state.get(t.id), self.m.config)
            alert = self.m.state.upsert(status, raw)
            if alert:
                self.m.broadcaster.publish("alert", alert.model_dump())
            ev = self.m.state.log_event(status, "info", f"Enrutament: '{status.name}' ← '{tx_name}' (abans: '{previous or '—'}')")
            self.m.broadcaster.publish("alert", ev.model_dump())
            self.m.publish_snapshot("devices")
            if not same_source(status.ndi.name, tx_name):
                logger.warning("%s ha acceptat set-channel però get-channel retorna '%s'", t.id, status.ndi.name)
            return status

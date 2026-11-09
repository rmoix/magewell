"""Estat en viu dels equips i historial d'alertes (memòria + data/events.log)."""

import collections
import logging
from pathlib import Path
from typing import Deque, Dict, List, Optional

from app.models import AlertEvent, DeviceStatus, HealthStatus, Role, Summary
from app.registry import now_iso

logger = logging.getLogger(__name__)

SEVERITY = {
    HealthStatus.OFFLINE: "error",
    HealthStatus.NO_SIGNAL: "error",
    HealthStatus.AUTH_ERROR: "error",
    HealthStatus.WARNING: "warning",
    HealthStatus.OK: "info",
    HealthStatus.UNKNOWN: "info",
}

MESSAGES = {
    HealthStatus.OFFLINE: "'{name}' ha deixat de respondre",
    HealthStatus.NO_SIGNAL: "'{name}' sense senyal",
    HealthStatus.AUTH_ERROR: "'{name}': error d'autenticació",
    HealthStatus.WARNING: "'{name}': {issues}",
    HealthStatus.OK: "'{name}' torna a estar OK",
}


class StateStore:
    def __init__(self, events_log: Optional[Path] = None, max_alerts: int = 300):
        self._devices: Dict[str, DeviceStatus] = {}
        self._raw: Dict[str, dict] = {}
        self._alerts: Deque[AlertEvent] = collections.deque(maxlen=max_alerts)
        self._last_poll: Optional[str] = None
        self.events_log = events_log

    def upsert(self, status: DeviceStatus, raw: Optional[dict] = None) -> Optional[AlertEvent]:
        """Desa l'estat i retorna una alerta si hi ha hagut un canvi d'estat rellevant."""
        prev = self._devices.get(status.id)
        self._devices[status.id] = status
        if raw is not None:
            self._raw[status.id] = raw
        self._last_poll = now_iso()

        if prev is None or prev.status == status.status:
            # També alertem si, dins de WARNING, canvia el motiu.
            if prev is not None and status.status == HealthStatus.WARNING and prev.issues != status.issues:
                return self._alert(status, "warning", f"'{status.name}': {'; '.join(status.issues)}")
            return None
        if prev.status == HealthStatus.UNKNOWN and status.status == HealthStatus.OK:
            return None  # primer sondeig correcte: no cal soroll
        msg = MESSAGES.get(status.status, "'{name}': {issues}").format(
            name=status.name, issues="; ".join(status.issues)
        )
        if status.status in (HealthStatus.NO_SIGNAL,) and status.issues:
            msg += f" — {status.issues[0]}"
        return self._alert(status, SEVERITY.get(status.status, "info"), msg)

    def _alert(self, status: DeviceStatus, severity: str, msg: str) -> AlertEvent:
        a = AlertEvent(
            timestamp=now_iso(), device_id=status.id, device_name=status.name, ip=status.ip,
            severity=severity, status=status.status, message=msg, issues=list(status.issues),
        )
        self._alerts.appendleft(a)
        logger.info("[%s] %s (%s)", severity.upper(), msg, status.ip)
        if self.events_log:
            try:
                self.events_log.parent.mkdir(parents=True, exist_ok=True)
                with self.events_log.open("a", encoding="utf-8") as f:
                    f.write(f"{a.timestamp}\t{severity.upper()}\t{status.ip}\t{status.name}\t{msg}\n")
            except OSError as e:
                logger.warning("No s'ha pogut escriure a events.log: %s", e)
        return a

    def remove(self, device_id: str) -> None:
        self._devices.pop(device_id, None)
        self._raw.pop(device_id, None)

    def get(self, device_id: str) -> Optional[DeviceStatus]:
        if device_id in self._devices:
            return self._devices[device_id]
        for d in self._devices.values():
            if d.ip == device_id or (d.serial and d.serial == device_id):
                return d
        return None

    def raw(self, device_id: str) -> Optional[dict]:
        return self._raw.get(device_id)

    def all(self) -> List[DeviceStatus]:
        return list(self._devices.values())

    def summary(self) -> Summary:
        devs = self.all()
        s = Summary(total=len(devs), last_poll=self._last_poll)
        for d in devs:
            key = d.status.value.lower()
            setattr(s, key, getattr(s, key) + 1)
            if d.role == Role.ENCODER:
                s.encoders += 1
            elif d.role == Role.DECODER:
                s.decoders += 1
        return s

    def alerts(self, limit: int = 100) -> List[AlertEvent]:
        return list(self._alerts)[:limit]

    def clear_alerts(self) -> None:
        self._alerts.clear()

"""In-memory state management and alert tracking for Magewell Mini-NMS."""

import collections
import datetime
import logging
from typing import Dict, List, Optional

from app.drift_detector import DriftDetector
from app.models import (
    AlertEvent,
    AppConfig,
    DeviceConfig,
    DeviceLiveStatus,
    HealthStatus,
    NmsSummary,
    SignalInfo,
)

logger = logging.getLogger(__name__)


class StateManager:
    """Central in-memory store for device statuses, telemetry, and system alerts."""

    def __init__(self, max_alerts: int = 100):
        self._devices: Dict[str, DeviceLiveStatus] = {}
        self._alerts: collections.deque[AlertEvent] = collections.deque(maxlen=max_alerts)
        self._last_poll_timestamp: Optional[str] = None

    def initialize_from_config(self, config: AppConfig) -> None:
        """Seed state with initial offline records for all configured devices."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        current_ids = {d.id for d in config.devices}

        # Remove devices no longer in config
        for dev_id in list(self._devices.keys()):
            if dev_id not in current_ids:
                del self._devices[dev_id]

        # Add or preserve existing
        for dev in config.devices:
            if dev.id not in self._devices:
                self._devices[dev.id] = DeviceLiveStatus(
                    id=dev.id,
                    name=dev.name,
                    ip=dev.ip,
                    port=dev.port,
                    model=dev.model,
                    role=dev.role,
                    location=dev.location,
                    status=HealthStatus.OFFLINE,
                    is_online=False,
                    response_time_ms=0.0,
                    signal=SignalInfo(locked=False),
                    expected=dev.expected,
                    drifts=["Sense sondeig inicial"],
                    last_seen=None,
                    last_checked=None,
                    error_message=None,
                )
            else:
                # Update configuration metadata without wiping live telemetry
                existing = self._devices[dev.id]
                existing.name = dev.name
                existing.ip = dev.ip
                existing.port = dev.port
                existing.model = dev.model
                existing.role = dev.role
                existing.location = dev.location
                existing.expected = dev.expected

    def update_device(self, status: DeviceLiveStatus) -> Optional[AlertEvent]:
        """
        Audit device status, update state store, and record alerts on state transitions.
        """
        status = DriftDetector.audit_device(status)
        previous = self._devices.get(status.id)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._last_poll_timestamp = now_iso

        alert: Optional[AlertEvent] = None

        # Check for meaningful state transitions or new drifts
        if previous is not None and previous.status != status.status:
            severity = "info"
            msg = f"Estat canviat de {previous.status.value} a {status.status.value}"
            if status.status == HealthStatus.OFFLINE:
                severity = "error"
                msg = f"L'equip '{status.name}' s'ha desconnectat de la xarxa"
            elif status.status == HealthStatus.NO_SIGNAL:
                severity = "error"
                msg = f"Pèrdua de senyal d'entrada de vídeo a '{status.name}'"
            elif status.status == HealthStatus.WARNING:
                severity = "warning"
                drift_desc = "; ".join(status.drifts)
                msg = f"Desviació detectada a '{status.name}': {drift_desc}"
            elif status.status == HealthStatus.OK:
                severity = "info"
                msg = f"L'equip '{status.name}' ha recuperat l'estat òptim (OK)"

            alert = AlertEvent(
                timestamp=now_iso,
                device_id=status.id,
                device_name=status.name,
                ip=status.ip,
                severity=severity,
                status=status.status,
                message=msg,
                drifts=list(status.drifts),
            )
            self._alerts.appendleft(alert)
            logger.info(f"Alert generated: [{severity.upper()}] {msg}")

        self._devices[status.id] = status
        return alert

    def update_batch(self, statuses: List[DeviceLiveStatus]) -> List[AlertEvent]:
        """Update multiple device statuses at once."""
        alerts: List[AlertEvent] = []
        for s in statuses:
            alert = self.update_device(s)
            if alert:
                alerts.append(alert)
        return alerts

    def get_device(self, device_id: str) -> Optional[DeviceLiveStatus]:
        """Get live status for a single device by ID or IP."""
        if device_id in self._devices:
            return self._devices[device_id]
        for dev in self._devices.values():
            if dev.ip == device_id:
                return dev
        return None

    def get_all_devices(self) -> List[DeviceLiveStatus]:
        """Return list of all device statuses."""
        return list(self._devices.values())

    def get_summary(self) -> NmsSummary:
        """Calculate overall fleet health metrics."""
        devices = list(self._devices.values())
        total = len(devices)
        online = sum(1 for d in devices if d.is_online)
        offline = sum(1 for d in devices if not d.is_online)
        ok_count = sum(1 for d in devices if d.status == HealthStatus.OK)
        warning_count = sum(1 for d in devices if d.status == HealthStatus.WARNING)
        no_signal_count = sum(1 for d in devices if d.status == HealthStatus.NO_SIGNAL)

        return NmsSummary(
            total_devices=total,
            online_count=online,
            offline_count=offline,
            ok_count=ok_count,
            warning_count=warning_count,
            no_signal_count=no_signal_count,
            last_poll_timestamp=self._last_poll_timestamp,
        )

    def get_recent_alerts(self, limit: int = 50) -> List[AlertEvent]:
        """Return the most recent alerts."""
        return list(self._alerts)[:limit]

    def clear_alerts(self) -> None:
        """Clear alerts history."""
        self._alerts.clear()


# Global singleton state manager
state_manager = StateManager()

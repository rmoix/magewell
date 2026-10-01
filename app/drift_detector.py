"""Drift and discrepancy audit engine for Magewell devices."""

import logging
from typing import List, Tuple

from app.models import (
    DeviceExpectedState,
    DeviceLiveStatus,
    HealthStatus,
)

logger = logging.getLogger(__name__)


class DriftDetector:
    """Compares live device telemetry against declared expected configuration."""

    @staticmethod
    def audit_device(status: DeviceLiveStatus) -> DeviceLiveStatus:
        """
        Evaluate device telemetry against expected state and compute health status & drifts.
        Mutates and returns the status object with updated status and drifts.
        """
        if not status.is_online:
            status.status = HealthStatus.OFFLINE
            if not status.drifts:
                status.drifts = ["Dispositiu desconnectat (OFFLINE)"]
            return status

        expected: DeviceExpectedState = status.expected or DeviceExpectedState()
        drifts: List[str] = []
        has_no_signal = False

        # 1. Video Signal Lock Check
        if expected.signal_locked is True:
            if not status.signal.locked:
                has_no_signal = True
                drifts.append("Pèrdua de senyal d'entrada de vídeo (Sense senyal HDMI/SDI)")

        # 2. Video Format Audit (Only if signal is locked)
        if status.signal.locked:
            # Resolution Check
            if expected.width is not None and expected.height is not None:
                if status.signal.width != expected.width or status.signal.height != expected.height:
                    actual_res = f"{status.signal.width or '?'}x{status.signal.height or '?'}"
                    expected_res = f"{expected.width}x{expected.height}"
                    drifts.append(f"Resolució divergent: esperat {expected_res}, real {actual_res}")

            # Frame Rate Check (with 0.5 fps tolerance for 59.94 vs 60 or float rounding)
            if expected.frame_rate is not None and status.signal.frame_rate is not None:
                if abs(status.signal.frame_rate - expected.frame_rate) > 0.5:
                    drifts.append(
                        f"Freqüència de quadre divergent: esperat {expected.frame_rate} fps, "
                        f"real {status.signal.frame_rate} fps"
                    )

            # Color Format Check
            if expected.color_format and status.signal.color_format:
                if expected.color_format.strip().lower() not in status.signal.color_format.strip().lower():
                    drifts.append(
                        f"Espai de color divergent: esperat {expected.color_format}, "
                        f"real {status.signal.color_format}"
                    )

        # 3. Hardware Thermal Check
        if expected.max_temperature_c is not None and status.temperature_c is not None:
            if status.temperature_c > expected.max_temperature_c:
                drifts.append(
                    f"Alerta de temperatura: {status.temperature_c:.1f}°C "
                    f"(límit esperat: {expected.max_temperature_c:.1f}°C)"
                )

        # 4. Stream / NDI Name Audit
        if expected.ndi_name and status.ndi_name:
            if expected.ndi_name.strip() != status.ndi_name.strip():
                drifts.append(
                    f"Nom de flux NDI modificat: esperat '{expected.ndi_name}', "
                    f"real '{status.ndi_name}'"
                )

        # Classify final health status
        if has_no_signal:
            status.status = HealthStatus.NO_SIGNAL
        elif drifts:
            status.status = HealthStatus.WARNING
        else:
            status.status = HealthStatus.OK

        status.drifts = drifts
        return status

"""Unit tests for Drift Detector and State Manager."""

import pytest
from app.drift_detector import DriftDetector
from app.models import (
    AppConfig,
    DeviceConfig,
    DeviceExpectedState,
    DeviceLiveStatus,
    HealthStatus,
    SignalInfo,
)
from app.state import StateManager


def test_drift_ok_state():
    status = DeviceLiveStatus(
        id="dev-1",
        name="Cam 1",
        ip="192.168.1.101",
        model="Pro Convert HDMI Plus",
        status=HealthStatus.OK,
        is_online=True,
        temperature_c=45.0,
        signal=SignalInfo(
            locked=True,
            width=1920,
            height=1080,
            frame_rate=50.0,
            color_format="YUV422",
        ),
        expected=DeviceExpectedState(
            signal_locked=True,
            width=1920,
            height=1080,
            frame_rate=50.0,
            color_format="YUV422",
            max_temperature_c=65.0,
        ),
    )
    result = DriftDetector.audit_device(status)
    assert result.status == HealthStatus.OK
    assert len(result.drifts) == 0


def test_drift_no_signal():
    status = DeviceLiveStatus(
        id="dev-2",
        name="Cam 2",
        ip="192.168.1.102",
        model="Pro Convert HDMI Plus",
        status=HealthStatus.OK,
        is_online=True,
        signal=SignalInfo(locked=False),
        expected=DeviceExpectedState(signal_locked=True),
    )
    result = DriftDetector.audit_device(status)
    assert result.status == HealthStatus.NO_SIGNAL
    assert any("Sense senyal" in d or "senyal" in d for d in result.drifts)


def test_drift_resolution_and_framerate_mismatch():
    status = DeviceLiveStatus(
        id="dev-3",
        name="Cam 3",
        ip="192.168.1.103",
        model="Pro Convert HDMI Plus",
        is_online=True,
        signal=SignalInfo(
            locked=True,
            width=1280,
            height=720,
            frame_rate=60.0,
        ),
        expected=DeviceExpectedState(
            signal_locked=True,
            width=1920,
            height=1080,
            frame_rate=50.0,
        ),
    )
    result = DriftDetector.audit_device(status)
    assert result.status == HealthStatus.WARNING
    assert len(result.drifts) == 2
    assert any("Resolució" in d for d in result.drifts)
    assert any("Freqüència de quadre" in d for d in result.drifts)


def test_drift_temperature_overheat():
    status = DeviceLiveStatus(
        id="dev-4",
        name="Cam 4",
        ip="192.168.1.104",
        model="Pro Convert HDMI Plus",
        is_online=True,
        temperature_c=72.5,
        signal=SignalInfo(locked=True, width=1920, height=1080, frame_rate=50.0),
        expected=DeviceExpectedState(
            signal_locked=True,
            width=1920,
            height=1080,
            frame_rate=50.0,
            max_temperature_c=65.0,
        ),
    )
    result = DriftDetector.audit_device(status)
    assert result.status == HealthStatus.WARNING
    assert any("temperatura" in d.lower() for d in result.drifts)


def test_drift_ndi_name_divergence():
    status = DeviceLiveStatus(
        id="dev-5",
        name="Cam 5",
        ip="192.168.1.105",
        model="Pro Convert HDMI Plus",
        is_online=True,
        ndi_name="STUDIO-B-CHANGED",
        signal=SignalInfo(locked=True, width=1920, height=1080, frame_rate=50.0),
        expected=DeviceExpectedState(
            signal_locked=True,
            width=1920,
            height=1080,
            frame_rate=50.0,
            ndi_name="STUDIO-A-MAIN",
        ),
    )
    result = DriftDetector.audit_device(status)
    assert result.status == HealthStatus.WARNING
    assert any("Nom de flux NDI" in d for d in result.drifts)


def test_state_manager_transitions_and_alerts():
    sm = StateManager()
    cfg = AppConfig(
        devices=[
            DeviceConfig(id="dev-1", name="Cam 1", ip="192.168.1.101"),
            DeviceConfig(id="dev-2", name="Cam 2", ip="192.168.1.102"),
        ]
    )
    sm.initialize_from_config(cfg)
    assert len(sm.get_all_devices()) == 2
    summary = sm.get_summary()
    assert summary.total_devices == 2
    assert summary.offline_count == 2

    # Update dev-1 to online OK
    st1 = DeviceLiveStatus(
        id="dev-1",
        name="Cam 1",
        ip="192.168.1.101",
        model="Pro Convert HDMI Plus",
        is_online=True,
        signal=SignalInfo(locked=True, width=1920, height=1080, frame_rate=50.0),
        expected=DeviceExpectedState(signal_locked=True, width=1920, height=1080, frame_rate=50.0),
    )
    alert = sm.update_device(st1)
    assert alert is not None
    assert alert.status == HealthStatus.OK
    assert len(sm.get_recent_alerts()) == 1

    summary2 = sm.get_summary()
    assert summary2.online_count == 1
    assert summary2.offline_count == 1
    assert summary2.ok_count == 1

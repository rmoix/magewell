"""Data models for Magewell Mini-NMS."""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class HealthStatus(str, Enum):
    OK = "OK"
    WARNING = "WARNING"
    NO_SIGNAL = "NO_SIGNAL"
    OFFLINE = "OFFLINE"


class SignalInfo(BaseModel):
    locked: bool = False
    width: Optional[int] = None
    height: Optional[int] = None
    frame_rate: Optional[float] = None
    color_format: Optional[str] = None
    interlaced: Optional[bool] = False
    aspect_ratio: Optional[str] = None


class DeviceExpectedState(BaseModel):
    signal_locked: Optional[bool] = True
    width: Optional[int] = 1920
    height: Optional[int] = 1080
    frame_rate: Optional[float] = 50.0
    color_format: Optional[str] = None
    max_temperature_c: Optional[float] = 65.0
    ndi_name: Optional[str] = None


class DeviceAuth(BaseModel):
    username: str = "admin"
    password: str = "password123"


class DeviceConfig(BaseModel):
    id: str
    name: str
    ip: str
    port: int = 80
    model: str = "Pro Convert HDMI Plus"
    role: Optional[str] = "Encoder"
    location: Optional[str] = "Studio"
    auth: DeviceAuth = Field(default_factory=DeviceAuth)
    expected: DeviceExpectedState = Field(default_factory=DeviceExpectedState)


class PollingConfig(BaseModel):
    interval_seconds: float = 3.0
    timeout_seconds: float = 2.0
    concurrency_limit: int = 5


class AppConfig(BaseModel):
    polling: PollingConfig = Field(default_factory=PollingConfig)
    devices: List[DeviceConfig] = Field(default_factory=list)


class DeviceLiveStatus(BaseModel):
    id: str
    name: str
    ip: str
    port: int = 80
    model: str
    role: Optional[str] = None
    location: Optional[str] = None
    status: HealthStatus = HealthStatus.OFFLINE
    is_online: bool = False
    response_time_ms: float = 0.0
    temperature_c: Optional[float] = None
    cpu_usage: Optional[float] = None
    memory_usage: Optional[float] = None
    firmware_version: Optional[str] = None
    serial_no: Optional[str] = None
    ndi_name: Optional[str] = None
    streaming_active: Optional[bool] = None
    signal: SignalInfo = Field(default_factory=SignalInfo)
    expected: DeviceExpectedState = Field(default_factory=DeviceExpectedState)
    drifts: List[str] = Field(default_factory=list)
    last_seen: Optional[str] = None
    last_checked: Optional[str] = None
    error_message: Optional[str] = None


class NmsSummary(BaseModel):
    total_devices: int = 0
    online_count: int = 0
    offline_count: int = 0
    ok_count: int = 0
    warning_count: int = 0
    no_signal_count: int = 0
    last_poll_timestamp: Optional[str] = None


class AlertEvent(BaseModel):
    timestamp: str
    device_id: str
    device_name: str
    ip: str
    severity: str  # "error", "warning", "info"
    status: HealthStatus
    message: str
    drifts: List[str] = Field(default_factory=list)

"""Models de dades (configuració i estat en viu)."""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Configuració
# ---------------------------------------------------------------------------


class Credential(BaseModel):
    username: str = "Admin"
    password: str = "Admin"


class ExpectedState(BaseModel):
    """Estat esperat. Qualsevol camp a None vol dir 'no comprovar'."""

    signal_locked: Optional[bool] = True
    width: Optional[int] = None
    height: Optional[int] = None
    frame_rate: Optional[float] = None
    interlaced: Optional[bool] = None
    ndi_name: Optional[str] = None
    ndi_source: Optional[str] = None  # decoders: nom de la font NDI que hauria de rebre
    min_ndi_clients: Optional[int] = None  # encoders: mínim de receptors connectats
    max_temperature_c: Optional[float] = None
    output_connected: Optional[bool] = None  # decoders: pantalla connectada a la sortida


class ManualDevice(BaseModel):
    """Equip declarat a mà, o sobreescriptura de dades d'un equip descobert (per IP o número de sèrie)."""

    ip: Optional[str] = None
    serial: Optional[str] = None
    port: int = 80
    name: Optional[str] = None
    location: Optional[str] = None
    credentials: Optional[Credential] = None
    expected: Optional[ExpectedState] = None
    ignore: bool = False


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    open_browser: bool = True


class PollingConfig(BaseModel):
    interval_seconds: float = Field(3.0, ge=1.0)
    timeout_seconds: float = Field(2.5, gt=0)
    concurrency_limit: int = Field(8, ge=1)
    offline_after_failures: int = Field(2, ge=1)


class DiscoveryConfig(BaseModel):
    enabled: bool = True
    on_startup: bool = True
    rescan_minutes: float = 10.0  # 0 = només manual
    subnets: List[str] = Field(default_factory=list)  # buit = autodetecció de les interfícies locals
    ports: List[int] = Field(default_factory=lambda: [80])
    exclude: List[str] = Field(default_factory=list)
    connect_timeout: float = 0.6
    concurrency: int = 128
    max_hosts: int = 4096
    forget_after_days: float = 0  # 0 = no oblidar mai equips descoberts


class DefaultsConfig(BaseModel):
    expected: ExpectedState = Field(default_factory=lambda: ExpectedState(max_temperature_c=80.0))


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    polling: PollingConfig = Field(default_factory=PollingConfig)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    credentials: List[Credential] = Field(default_factory=lambda: [Credential()])
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    devices: List[ManualDevice] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Estat en viu
# ---------------------------------------------------------------------------


class HealthStatus(str, Enum):
    OK = "OK"
    WARNING = "WARNING"
    NO_SIGNAL = "NO_SIGNAL"
    AUTH_ERROR = "AUTH_ERROR"
    OFFLINE = "OFFLINE"
    UNKNOWN = "UNKNOWN"


class Role(str, Enum):
    ENCODER = "Encoder"
    DECODER = "Decoder"
    UNKNOWN = "Unknown"


class SignalInfo(BaseModel):
    locked: bool = False
    state: Optional[str] = None  # encoder: input-state cru (no-signal, locking, 1920x1080p50...)
    width: Optional[int] = None
    height: Optional[int] = None
    frame_rate: Optional[float] = None  # field-rate segons Magewell (1080i50 -> 50)
    interlaced: Optional[bool] = None
    color_format: Optional[str] = None
    sampling: Optional[str] = None
    color_depth: Optional[int] = None
    hdcp: Optional[str] = None
    audio: Optional[str] = None
    label: Optional[str] = None  # format curt, p. ex. "1080p50"


class NdiInfo(BaseModel):
    name: Optional[str] = None  # encoder: nom del flux que emet; decoder: font que rep
    enabled: Optional[bool] = None
    connected: Optional[bool] = None  # decoder
    num_clients: Optional[int] = None  # encoder
    video_bitrate_kbps: Optional[int] = None
    video_drop_frames: Optional[int] = None
    audio_drop_frames: Optional[int] = None
    tally_program: Optional[bool] = None
    tally_preview: Optional[bool] = None


class DeviceStatus(BaseModel):
    id: str
    ip: str
    port: int = 80
    name: str
    location: Optional[str] = None
    source: str = "discovered"  # discovered | manual
    model: Optional[str] = None
    role: Role = Role.UNKNOWN
    serial: Optional[str] = None
    firmware: Optional[str] = None
    hw_revision: Optional[str] = None
    mac: Optional[str] = None
    link_speed: Optional[str] = None
    status: HealthStatus = HealthStatus.UNKNOWN
    is_online: bool = False
    response_time_ms: Optional[float] = None
    temperature_c: Optional[float] = None
    cpu_usage: Optional[float] = None
    memory_usage: Optional[float] = None
    uptime_s: Optional[int] = None
    fan_rpm: Optional[int] = None
    output_state: Optional[str] = None
    signal: SignalInfo = Field(default_factory=SignalInfo)
    ndi: NdiInfo = Field(default_factory=NdiInfo)
    expected: ExpectedState = Field(default_factory=ExpectedState)
    issues: List[str] = Field(default_factory=list)
    consecutive_failures: int = 0
    last_seen: Optional[str] = None
    last_checked: Optional[str] = None
    error_message: Optional[str] = None


class Summary(BaseModel):
    total: int = 0
    ok: int = 0
    warning: int = 0
    no_signal: int = 0
    offline: int = 0
    auth_error: int = 0
    unknown: int = 0
    encoders: int = 0
    decoders: int = 0
    last_poll: Optional[str] = None


class AlertEvent(BaseModel):
    timestamp: str
    device_id: str
    device_name: str
    ip: str
    severity: str  # error | warning | info
    status: HealthStatus
    message: str
    issues: List[str] = Field(default_factory=list)


class ScanHost(BaseModel):
    ip: str
    port: int
    kind: str  # mwapi | magewell-other | http
    detail: Optional[str] = None


class ScanReport(BaseModel):
    running: bool = False
    started: Optional[str] = None
    finished: Optional[str] = None
    targets: List[str] = Field(default_factory=list)
    hosts_scanned: int = 0
    progress: float = 0.0
    found: List[ScanHost] = Field(default_factory=list)
    new_devices: int = 0
    error: Optional[str] = None


RawTelemetry = Dict[str, Any]

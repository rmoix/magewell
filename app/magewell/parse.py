"""Converteix les respostes JSON de Magewell a camps de DeviceStatus.

El parser és tolerant: si un firmware no retorna un camp, es deixa a None.
Quan tinguem captures reals (vegeu `magewell-nms capture`), s'han d'afegir com a
fixtures a tests/fixtures/ i ajustar aquí qualsevol diferència.
"""

import re
from typing import Any, Dict, Optional

from app.models import NdiInfo, Role, SignalInfo

NO_SIGNAL_STATES = {"no-signal", "nosignal", "none", "locking", "unsupported", "", "unknown"}
_MODE_RE = re.compile(r"(\d{3,4})\s*x\s*(\d{3,4})\s*([pi])?\s*([\d.]+)?", re.I)


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _i(v: Any) -> Optional[int]:
    f = _f(v)
    return None if f is None else int(f)


def _b(v: Any) -> Optional[bool]:
    if v is None:
        return None
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "on")
    return bool(v)


def _s(v: Any) -> Optional[str]:
    return None if v is None or v == "" else str(v)


def format_label(width: Optional[int], height: Optional[int], rate: Optional[float], interlaced: Optional[bool]) -> Optional[str]:
    """1920x1080, 50, progressive -> '1080p50'. 1280x720 -> '720p59.94'. Formats no estàndard -> '1024x768p60'."""
    if not width or not height:
        return None
    scan = "i" if interlaced else "p"
    rate_s = f"{rate:g}" if rate else ""
    if (width, height) in {(1920, 1080), (1280, 720), (3840, 2160), (720, 576), (720, 480), (4096, 2160)}:
        return f"{height}{scan}{rate_s}"
    return f"{width}x{height}{scan}{rate_s}"


def parse_input_state(state: Optional[str]) -> SignalInfo:
    """Interpreta device.input-state d'un encoder: 'no-signal', 'locking', 'unsupported' o un mode tipus '1920x1080p60'."""
    sig = SignalInfo(state=state)
    if state is None:
        return sig
    if state.strip().lower() in NO_SIGNAL_STATES:
        sig.locked = False
        return sig
    sig.locked = True
    m = _MODE_RE.search(state)
    if m:
        sig.width, sig.height = int(m.group(1)), int(m.group(2))
        sig.interlaced = (m.group(3) or "p").lower() == "i"
        sig.frame_rate = _f(m.group(4))
    return sig


def detect_role(summary: Dict[str, Any]) -> Role:
    device = summary.get("device") or {}
    ndi = summary.get("ndi") or {}
    model = str(device.get("model") or "").lower()
    if "ndi to" in model or "ip to" in model or "decoder" in model:
        return Role.DECODER
    if "input-state" in device or "num-clients" in ndi:
        return Role.ENCODER
    if "connected" in ndi:
        return Role.DECODER
    if any(k in model for k in ("hdmi", "sdi")):
        return Role.ENCODER
    return Role.UNKNOWN


def parse_device(summary: Dict[str, Any]) -> Dict[str, Any]:
    device = summary.get("device") or {}
    eth = summary.get("ethernet") or {}
    model = _s(device.get("model"))
    product = _s(device.get("name"))
    # A la doc, device.name = "Pro Convert" i device.model = "NDI to HDMI". Els unim per al model complet.
    full_model = " ".join(x for x in (product, model) if x) or None
    return {
        "device_name": product,
        "model": full_model,
        "serial": _s(device.get("serial-no")),
        "firmware": _s(device.get("fw-version")),
        "hw_revision": _s(device.get("hw-revision")),
        "temperature_c": _f(device.get("core-temp")),
        "cpu_usage": _f(device.get("cpu-usage")),
        "memory_usage": _f(device.get("memory-usage")),
        "uptime_s": _i(device.get("up-time")),
        "fan_rpm": _i(device.get("fan-rpm")),
        "output_state": _s(device.get("output-state")),
        "mac": _s(eth.get("mac-addr")),
        "link_speed": _s(eth.get("state")),
    }


def parse_ndi(summary: Dict[str, Any]) -> NdiInfo:
    ndi = summary.get("ndi") or {}
    return NdiInfo(
        name=_s(ndi.get("name")),
        enabled=_b(ndi.get("enabled")),
        connected=_b(ndi.get("connected")),
        num_clients=_i(ndi.get("num-clients")),
        video_bitrate_kbps=_i(ndi.get("video-bit-rate")),
        video_drop_frames=_i(ndi.get("video-drop-frames")),
        audio_drop_frames=_i(ndi.get("audio-drop-frames")),
        tally_program=_b(ndi.get("tally-program")),
        tally_preview=_b(ndi.get("tally-preview")),
    )


def parse_encoder_signal(summary: Dict[str, Any], signal: Optional[Dict[str, Any]]) -> SignalInfo:
    device = summary.get("device") or {}
    sig = parse_input_state(_s(device.get("input-state")))

    if signal and signal.get("status", 0) == 0:
        video = signal.get("video-info") or {}
        audio = signal.get("audio-info") or {}
        hdmi = signal.get("hdmi-info") or {}
        w, h = _i(video.get("width")), _i(video.get("height"))
        if w and h:
            sig.width, sig.height = w, h
            # Si input-state no hi és (firmware antic), deduïm el lock de la resolució.
            if sig.state is None:
                sig.locked = True
        rate = _f(video.get("field-rate"))
        if rate:
            sig.frame_rate = rate
        scan = _s(video.get("scan"))
        if scan:
            sig.interlaced = scan.lower() == "interlaced"
        sig.color_format = _s(video.get("color-format")) or sig.color_format
        sig.sampling = _s(video.get("sampling"))
        sig.color_depth = _i(video.get("color-depth"))
        sig.hdcp = _s(hdmi.get("hdcp"))
        if audio.get("num-channels"):
            sr = _i(audio.get("sample-rate"))
            sig.audio = f"{audio.get('num-channels')}ch {sr // 1000 if sr else '?'}kHz {audio.get('codec') or ''}".strip()

    if not sig.locked:
        sig.width = sig.height = sig.frame_rate = None
    sig.label = format_label(sig.width, sig.height, sig.frame_rate, sig.interlaced) if sig.locked else None
    return sig


def parse_decoder_signal(summary: Dict[str, Any]) -> SignalInfo:
    """Per a un decoder, 'senyal' = està rebent una font NDI amb vídeo."""
    ndi = summary.get("ndi") or {}
    connected = _b(ndi.get("connected"))
    w, h = _i(ndi.get("video-width")), _i(ndi.get("video-height"))
    rate = _f(ndi.get("video-field-rate"))
    scan = _s(ndi.get("video-scan"))
    locked = bool(connected) and bool(w) and bool(h)
    sig = SignalInfo(
        locked=locked,
        state="connected" if connected else "disconnected",
        width=w if locked else None,
        height=h if locked else None,
        frame_rate=rate if locked else None,
        interlaced=(scan.lower() == "interlaced") if scan else None,
    )
    if locked and ndi.get("audio-num-channels"):
        sr = _i(ndi.get("audio-sample-rate"))
        sig.audio = f"{ndi.get('audio-num-channels')}ch {sr // 1000 if sr else '?'}kHz"
    sig.label = format_label(sig.width, sig.height, sig.frame_rate, sig.interlaced) if locked else None
    return sig


def parse_all(
    summary: Dict[str, Any],
    signal: Optional[Dict[str, Any]] = None,
    channel: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Retorna un dict amb els camps a aplicar a DeviceStatus."""
    out = parse_device(summary)
    role = detect_role(summary)
    out["role"] = role
    ndi = parse_ndi(summary)
    if role == Role.DECODER:
        out["signal"] = parse_decoder_signal(summary)
        # get-channel retorna la font seleccionada; és més fiable que ndi.name per saber què s'ha triat.
        if channel and channel.get("status", 0) == 0 and channel.get("name"):
            ndi.name = str(channel["name"])
    else:
        out["signal"] = parse_encoder_signal(summary, signal)
    out["ndi"] = ndi
    return out

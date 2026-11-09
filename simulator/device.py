"""Un equip Magewell Pro Convert simulat (API /mwapi segons la documentació oficial).

Formats de resposta basats en:
  https://www.magewell.com/api-docs/pro-convert-encoder-api/
  https://www.magewell.com/api-docs/pro-convert-decoder-api/
Quan tinguem captures reals, s'han d'ajustar aquí perquè el simulador s'hi assembli tant com sigui possible.
"""

import asyncio
import hashlib
import random
import secrets
from dataclasses import dataclass, field
from typing import Dict, Optional

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

FORMATS = {
    "1080p50": (1920, 1080, "progressive", 50.0),
    "1080i50": (1920, 1080, "interlaced", 50.0),
    "1080p59.94": (1920, 1080, "progressive", 59.94),
    "720p50": (1280, 720, "progressive", 50.0),
    "2160p50": (3840, 2160, "progressive", 50.0),
    "2160p25": (3840, 2160, "progressive", 25.0),
}


@dataclass
class SimDevice:
    role: str  # "encoder" | "decoder"
    model: str  # p. ex. "HDMI Plus", "NDI to HDMI"
    serial: str
    board_id: int = 0
    ndi_name: str = ""
    password: str = "Admin"
    username: str = "Admin"
    # Estat dinàmic
    signal: bool = True
    fmt: str = "1080p50"
    ndi_clients: int = 1
    ndi_enabled: bool = True
    source: str = ""  # decoder: font NDI seleccionada
    output_connected: bool = True
    temp: float = 55.0
    drop_frames: int = 0
    hang: bool = False  # simula equip penjat (no respon)
    sessions: Dict[str, bool] = field(default_factory=dict)

    # ----------------------------------------------------------------- respostes
    def summary(self) -> dict:
        w, h, scan, rate = FORMATS[self.fmt]
        device = {
            "name": "Pro Convert",
            "model": self.model,
            "serial-no": self.serial,
            "hw-revision": "A",
            "fw-version": "1.2.112",
            "up-to-date": True,
            "cpu-usage": round(random.uniform(15, 45), 2),
            "memory-usage": round(random.uniform(30, 40), 2),
            "core-temp": round(self.temp + random.uniform(-0.5, 0.5), 2),
            "board-id": self.board_id,
            "up-time": 3600 * 5 + random.randint(0, 100),
            "sd-size": 0,
        }
        eth = {
            "state": "1000m", "mac-addr": "70:B3:D5:75:" + self.serial[-4:-2] + ":" + self.serial[-2:],
            "ip-addr": "0.0.0.0", "ip-mask": "255.255.255.0", "gw-addr": "0.0.0.0", "dns-addr": "0.0.0.0",
            "tx-speed-kbps": 0, "rx-speed-kbps": 0,
        }
        rndis = {"state": "disconnected", "ip-addr": "192.168.66.1", "tx-speed-kbps": 0, "rx-speed-kbps": 0}
        if self.role == "encoder":
            device.update({
                "input-state": f"{w}x{h}{'i' if scan == 'interlaced' else 'p'}{rate:g}" if self.signal else "no-signal",
                "output-state": "active" if self.signal else "unconnected",
                "ptz-proto": "none", "ptz-state": "unknown", "fan-rpm": 0,
            })
            ndi = {
                "name": self.ndi_name, "enabled": self.ndi_enabled,
                "num-clients": self.ndi_clients if self.signal else 0,
                "tally-preview": False, "tally-program": self.board_id == 1,
                "audio-drop-frames": 0, "video-drop-frames": self.drop_frames,
                "video-bit-rate": random.randint(90000, 130000) if self.signal and self.ndi_clients else 0,
                "audio-bit-rate": 1536 if self.signal else 0,
                "video-width": w if self.signal else 0, "video-height": h if self.signal else 0,
                "video-scan": scan, "video-field-rate": rate if self.signal else 0,
                "audio-num-channels": 2, "audio-sample-rate": 48000, "audio-bit-count": 16,
            }
        else:
            device.update({"output-state": "active" if self.output_connected else "unconnected"})
            ndi = {
                "name": self.source, "connected": self.signal,
                "tally-preview": False, "tally-program": False,
                "audio-drop-frames": 0, "video-drop-frames": self.drop_frames,
                "video-bit-rate": random.randint(90000, 130000) if self.signal else 0, "audio-bit-rate": 0,
                "video-width": w if self.signal else 0, "video-height": h if self.signal else 0,
                "video-scan": scan, "video-field-rate": rate if self.signal else 0.0,
                "audio-num-channels": 2 if self.signal else 0, "audio-sample-rate": 48000 if self.signal else 0,
                "audio-bit-count": 16, "audio-jitter": 26, "video-jitter": 7,
            }
        return {"status": 0, "device": device, "ethernet": eth, "rndis": rndis, "ndi": ndi}

    def signal_info(self) -> dict:
        if self.role != "encoder":
            return {"status": 9}  # UNSUPPORTED (suposició: els decoders no tenen entrada)
        w, h, scan, rate = FORMATS[self.fmt]
        if not self.signal:
            return {"status": 0, "signal-info-types": [], "video-info": {}, "audio-info": {}}
        return {
            "status": 0,
            "signal-info-types": ["video-info", "audio-info", "hdmi-info", "sdi-info", "info-frames"],
            "video-info": {
                "codec": "uncompressed", "width": w, "height": h, "scan": scan, "field-rate": rate,
                "color-depth": 10 if "SDI" in self.model else 8,
                "color-format": "bt.709", "aspect-ratio": "16:9", "sampling": "4:2:2",
                "quant-range": "limited", "sat-range": "limited", "frame-struct": "2d",
            },
            "audio-info": {"codec": "lpcm", "num-channels": 2, "sample-rate": 48000, "bit-count": 24},
            "hdmi-info": {"mode": "hdmi", "vic": 31, "scramble": False, "clock-ratio": 1, "hdcp": "none",
                          "repeat-count": 0, "it-content": False, "timing-mode-line": ""},
            "sdi-info": {}, "info-frames": [],
        }

    def handle(self, method: str, params: dict, sid: Optional[str]) -> tuple[dict, Optional[str]]:
        if method == "ping":
            return {"status": 0}, None
        if method == "login":
            expected = hashlib.md5(self.password.encode()).hexdigest()
            if params.get("id") == self.username and params.get("pass", "").lower() == expected:
                new_sid = secrets.token_hex(16)
                self.sessions[new_sid] = True
                return {"status": 0}, new_sid
            return {"status": 36}, None
        if not sid or sid not in self.sessions:
            return {"status": 37}, None
        if method == "logout":
            self.sessions.pop(sid, None)
            return {"status": 0}, None
        if method == "get-summary-info":
            return self.summary(), None
        if method == "get-signal-info":
            return self.signal_info(), None
        if method == "get-channel":
            if self.role != "decoder":
                return {"status": 9}, None
            return {"status": 0, "name": self.source, "ndi-name": True}, None
        if method == "get-ndi-config":
            return {"status": 0, "enable": self.ndi_enabled, "source-name": self.ndi_name, "group-name": "public"}, None
        if method.startswith("get-") or method.startswith("list-"):
            return {"status": 5}, None  # NOT_IMPLEMENTED al simulador
        return {"status": 31}, None  # el simulador no accepta escriptures


def make_app(dev: SimDevice) -> Starlette:
    async def mwapi(request: Request):
        if dev.hang:
            await asyncio.sleep(30)
        params = dict(request.query_params)
        method = params.pop("method", "")
        data, new_sid = dev.handle(method, params, request.cookies.get("sid"))
        resp = JSONResponse(data)
        if new_sid:
            resp.set_cookie("sid", new_sid, httponly=True)
        return resp

    async def root(request: Request):
        return HTMLResponse(f"<html><head><title>Magewell Pro Convert {dev.model}</title></head><body>Magewell</body></html>")

    return Starlette(routes=[Route("/mwapi", mwapi), Route("/", root)])

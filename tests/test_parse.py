import json
from pathlib import Path

import pytest

from app.magewell.parse import format_label, parse_all, parse_input_state
from app.models import Role
from simulator.device import SimDevice


def test_input_state():
    assert parse_input_state("no-signal").locked is False
    assert parse_input_state("locking").locked is False
    s = parse_input_state("1920x1080p60")
    assert (s.locked, s.width, s.height, s.frame_rate, s.interlaced) == (True, 1920, 1080, 60.0, False)
    s = parse_input_state("1920x1080i50")
    assert s.interlaced is True and s.frame_rate == 50


def test_labels():
    assert format_label(1920, 1080, 50, False) == "1080p50"
    assert format_label(1920, 1080, 50, True) == "1080i50"
    assert format_label(1280, 720, 59.94, False) == "720p59.94"
    assert format_label(1024, 768, 60, False) == "1024x768p60"


def test_encoder_parse():
    d = SimDevice("encoder", "HDMI Plus", "B1", 1, "CAM1", fmt="1080i50")
    out = parse_all(d.summary(), d.signal_info())
    assert out["role"] == Role.ENCODER
    assert out["model"] == "Pro Convert HDMI Plus"
    assert out["serial"] == "B1"
    assert out["signal"].locked and out["signal"].label == "1080i50"
    assert out["signal"].sampling == "4:2:2"
    assert out["ndi"].name == "CAM1" and out["ndi"].num_clients == 1


def test_encoder_no_signal():
    d = SimDevice("encoder", "HDMI Plus", "B1", 1, "CAM1", signal=False)
    out = parse_all(d.summary(), d.signal_info())
    assert out["signal"].locked is False
    assert out["signal"].label is None


def test_decoder_parse():
    d = SimDevice("decoder", "NDI to HDMI", "B2", 2, source="PGM")
    out = parse_all(d.summary(), None, {"status": 0, "name": "REGIA (PGM)"})
    assert out["role"] == Role.DECODER
    assert out["signal"].locked and out["signal"].label == "1080p50"
    assert out["ndi"].name == "REGIA (PGM)"
    d.signal = False
    out = parse_all(d.summary())
    assert out["signal"].locked is False


def test_doc_example_decoder_summary():
    """Exemple de la documentació oficial (decoder sense font)."""
    summary = {
        "status": 0,
        "device": {"name": "Pro Convert", "model": "NDI to HDMI", "serial-no": "101", "hw-revision": "A",
                   "fw-version": "1.1.157", "up-to-date": True, "output-state": "connected", "cpu-usage": 60.00,
                   "memory-usage": 37.46, "core-temp": 69.23, "board-id": 0, "up-time": 19972, "sd-size": 0},
        "ethernet": {"state": "disconnected", "mac-addr": "70:B3:D5:75:D2:41"},
        "ndi": {"name": "#00 (B401180706020)", "connected": True, "video-width": 0, "video-height": 0,
                "video-scan": "progressive", "video-field-rate": 0.00},
    }
    out = parse_all(summary)
    assert out["role"] == Role.DECODER
    assert out["temperature_c"] == 69.23
    assert out["signal"].locked is False  # connectat però sense vídeo


# ----------------------------------------------------------------------------
# Captures reals: copia aquí els .json generats amb `MagewellNMS.exe capture`
# i aquest test comprovarà que el parser els entén.
# ----------------------------------------------------------------------------
CAPTURES = sorted((Path(__file__).parent / "fixtures" / "captures").glob("*.json"))


@pytest.mark.parametrize("path", CAPTURES, ids=[p.name for p in CAPTURES])
def test_real_captures(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    summary = data.get("get-summary-info") or {}
    if summary.get("status") != 0:
        pytest.skip(f"captura sense summary vàlid: {summary}")
    out = parse_all(summary, data.get("get-signal-info"), data.get("get-channel"))
    assert out["role"] != Role.UNKNOWN, "no s'ha pogut deduir si és encoder o decoder"
    assert out["serial"], "falta el número de sèrie"
    assert out["model"]

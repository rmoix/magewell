from app.health import evaluate, merge_expected
from app.models import DeviceStatus, ExpectedState, HealthStatus, NdiInfo, Role, SignalInfo


def dev(**kw):
    base = dict(id="x", ip="10.0.0.1", name="X", is_online=True, role=Role.ENCODER,
                signal=SignalInfo(locked=True, width=1920, height=1080, frame_rate=50, interlaced=False),
                ndi=NdiInfo(name="CAM1", enabled=True, num_clients=1), expected=ExpectedState())
    base.update(kw)
    return DeviceStatus(**base)


def test_ok():
    assert evaluate(dev()) == (HealthStatus.OK, [])


def test_offline():
    st, issues = evaluate(dev(is_online=False, error_message="timeout"))
    assert st == HealthStatus.OFFLINE and issues == ["timeout"]


def test_no_signal_encoder_and_decoder():
    st, issues = evaluate(dev(signal=SignalInfo(locked=False, state="no-signal")))
    assert st == HealthStatus.NO_SIGNAL
    st, issues = evaluate(dev(role=Role.DECODER, signal=SignalInfo(locked=False), ndi=NdiInfo(name="PGM")))
    assert st == HealthStatus.NO_SIGNAL and "PGM" in issues[0]


def test_no_signal_not_alarmed_when_not_expected():
    st, _ = evaluate(dev(signal=SignalInfo(locked=False), expected=ExpectedState(signal_locked=False)))
    assert st == HealthStatus.OK


def test_format_mismatch():
    st, issues = evaluate(dev(expected=ExpectedState(width=1920, height=1080, frame_rate=59.94)))
    assert st == HealthStatus.WARNING and "59.94" in issues[0]


def test_temperature_and_drops():
    st, issues = evaluate(dev(temperature_c=85, expected=ExpectedState(max_temperature_c=80),
                              ndi=NdiInfo(name="CAM1", video_drop_frames=3)))
    assert st == HealthStatus.WARNING and len(issues) == 2


def test_decoder_output_and_source():
    d = dev(role=Role.DECODER, output_state="unconnected", ndi=NdiInfo(name="PVW"),
            expected=ExpectedState(output_connected=True, ndi_source="PGM"))
    st, issues = evaluate(d)
    assert st == HealthStatus.WARNING and len(issues) == 2


def test_merge_expected_only_overrides_set_fields():
    defaults = ExpectedState(frame_rate=50, max_temperature_c=80)
    merged = merge_expected(defaults, ExpectedState(width=3840, height=2160))
    assert (merged.frame_rate, merged.width, merged.max_temperature_c) == (50, 3840, 80)

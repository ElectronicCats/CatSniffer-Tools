"""
Unit tests for the BLE Spam protocol backend (modules.protocols.ble_spam).

Pure-parser tests plus controller tests driven by a fake serial transport fed
from the real hardware-captured transcript in ``fixtures/ble_spam_session.txt``.
No hardware required.
"""

from collections import deque
from pathlib import Path

import pytest

from modules.core.exceptions import ConnectionError as CatnipConnectionError
from modules.core.exceptions import FeatureUnavailable, ProtocolError, ValidationError
from modules.protocols.ble_spam import (
    BAUDRATE,
    CMD_MAXLEN,
    INT_UNIT_MAX,
    INT_UNIT_MIN,
    BleSpamController,
    LineKind,
    PowerProfile,
    SpamMode,
    SpamStats,
    SpamStatus,
    parse_line,
    parse_stats,
    parse_status,
    validate_interval,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ble_spam_session.txt"
# Hardened-firmware transcript (pwr/int/stats/scan/WARN + extended status).
MEJORAS_FIXTURE = Path(__file__).parent / "fixtures" / "ble_spam_mejoras_session.txt"


def _device_lines_from(path):
    """Meaningful device output lines from *path* (no comments/markers/blanks)."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("<<<"):
            continue
        out.append(line)
    return out


def _device_lines():
    """Meaningful device output lines from the base fixture."""
    return _device_lines_from(FIXTURE)


# ── constants ─────────────────────────────────────────────────────────────────
def test_baudrate_and_cmd_len_pinned_from_spike():
    assert BAUDRATE == 921600
    assert CMD_MAXLEN == 24


# ── SpamMode ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "value,expected",
    [
        ("apple", SpamMode.APPLE),
        ("APPLE", SpamMode.APPLE),  # firmware reports modes upper-cased
        ("p", SpamMode.APPLE),  # short alias
        ("all", SpamMode.ALL),
        ("a", SpamMode.ALL),
        ("samsung", SpamMode.SAMSUNG),
    ],
)
def test_spam_mode_from_str(value, expected):
    assert SpamMode.from_str(value) is expected


def test_spam_mode_from_str_rejects_unknown():
    with pytest.raises(ValueError):
        SpamMode.from_str("nokia")


def test_spam_mode_tokens():
    assert SpamMode.APPLE.token == "apple"
    assert SpamMode.APPLE.short == "p"


# ── parse_status ──────────────────────────────────────────────────────────────
def test_parse_status_plan_example():
    # Exact example from the integration plan's success criteria.
    st = parse_status("SPAM: mode=apple running=1 models=12")
    assert st == SpamStatus(mode=SpamMode.APPLE, running=True, models=12)


def test_parse_status_real_lines():
    assert parse_status("SPAM: mode=ALL running=0 models=82") == SpamStatus(
        SpamMode.ALL, False, 82
    )
    assert parse_status("SPAM: mode=APPLE running=1 models=22") == SpamStatus(
        SpamMode.APPLE, True, 22
    )


def test_parse_status_none_for_non_status():
    assert parse_status("SPAM: stopped") is None
    assert parse_status("SPAM: Beats Flex (11/82)") is None


# ── parse_line classification ────────────────────────────────────────────────
def test_parse_line_banner():
    assert parse_line("CatSniffer:BleSpam ALL").kind is LineKind.BANNER


def test_parse_line_status():
    line = parse_line("SPAM: mode=apple running=1 models=22")
    assert line.kind is LineKind.STATUS
    assert line.status == SpamStatus(SpamMode.APPLE, True, 22)


def test_parse_line_cycle_with_and_without_model_prefix():
    first = parse_line("SPAM: model Apple AirPods 1 (1/22)")
    assert first.kind is LineKind.CYCLE
    assert (first.model, first.index, first.total) == ("Apple AirPods 1", 1, 22)

    rest = parse_line("SPAM: Beats Flex (11/82)")
    assert rest.kind is LineKind.CYCLE
    assert (rest.model, rest.index, rest.total) == ("Beats Flex", 11, 82)


def test_parse_line_stats():
    assert parse_line("SPAM: cycles=2000").kind is LineKind.STATS
    assert parse_line("SPAM: cycles=2000").cycles == 2000
    assert (
        parse_line("SPAM: start mode=APPLE models=22 int=20-30ms").kind
        is LineKind.STATS
    )
    assert parse_line("SPAM: addr fc:99:ae:e0:7c:8b").kind is LineKind.STATS


def test_parse_line_error():
    line = parse_line("ERR: unknown cmd 'foo' (type help)")
    assert line.kind is LineKind.ERROR
    assert line.message == "unknown cmd 'foo' (type help)"


def test_parse_line_info_acks():
    assert parse_line("SPAM: stopped").kind is LineKind.INFO
    assert parse_line("SPAM: already running").kind is LineKind.INFO
    assert parse_line("SPAM: mode -> APPLE (stopped)").kind is LineKind.INFO
    assert (
        parse_line(
            "SPAM cmds: all|apple|android|windows|samsung, start, stop, status"
        ).kind
        is LineKind.INFO
    )


def test_mode_change_not_misread_as_cycle():
    # "(stopped)" must not trip the (i/n) cycle pattern → guards against R3.
    assert parse_line("SPAM: mode -> APPLE (stopped)").kind is LineKind.INFO


# ── fixture: no false positives ──────────────────────────────────────────────
def test_fixture_lines_all_classified_without_unknown():
    if not FIXTURE.exists():
        pytest.skip("hardware-captured transcript fixture not present")
    lines = _device_lines()
    assert lines, "fixture yielded no device lines"
    kinds = {parse_line(l).kind for l in lines}
    # Every real device line must be recognised.
    for line in lines:
        assert parse_line(line).kind is not LineKind.UNKNOWN, line
    # The transcript exercises each of these categories.
    assert {LineKind.STATUS, LineKind.CYCLE, LineKind.STATS, LineKind.INFO} <= kinds


# ── controller (fake serial transport) ───────────────────────────────────────
class FakeSerial:
    """Minimal serial-like transport for driving BleSpamController in tests."""

    def __init__(self, incoming=b""):
        # split into readline-sized chunks preserving line endings
        self._lines = (
            deque((l + "\n").encode() for l in incoming.decode().splitlines())
            if incoming
            else deque()
        )
        self.written = []
        self.closed = False

    def readline(self):
        return self._lines.popleft() if self._lines else b""

    def write(self, data):
        self.written.append(data)

    def flush(self):
        pass

    def close(self):
        self.closed = True


def test_controller_send_appends_newline():
    fake = FakeSerial()
    ctl = BleSpamController(fake)
    ctl.send("apple")
    assert fake.written == [b"apple\n"]


def test_controller_send_rejects_overlong_command():
    ctl = BleSpamController(FakeSerial())
    with pytest.raises(ValidationError):
        ctl.send("x" * (CMD_MAXLEN + 1))


def test_controller_send_rejects_empty():
    ctl = BleSpamController(FakeSerial())
    with pytest.raises(ValidationError):
        ctl.send("   ")


def test_controller_commands_write_expected_tokens():
    fake = FakeSerial()
    ctl = BleSpamController(fake)
    ctl.set_mode(SpamMode.APPLE)
    ctl.start()
    ctl.stop()
    assert fake.written == [b"apple\n", b"start\n", b"stop\n"]


def test_controller_status_parses_reply():
    # per-cycle noise before the actual status reply (interleaving, R3)
    fake = FakeSerial(
        b"SPAM: Beats Flex (11/82)\n" b"SPAM: mode=APPLE running=1 models=22\n"
    )
    ctl = BleSpamController(fake)
    st = ctl.status(timeout=1.0)
    assert st == SpamStatus(SpamMode.APPLE, True, 22)
    assert fake.written == [b"status\n"]  # it sent the query


def test_controller_status_timeout_raises():
    ctl = BleSpamController(FakeSerial())  # no reply
    with pytest.raises(ProtocolError) as exc:
        ctl.status(timeout=0.1)
    # Phase 5: the typed error must carry actionable next steps, not just a message.
    assert exc.value.hint
    assert any("catnip flash" in step for step in exc.value.hint)


def test_open_failure_raises_connection_error_with_hint(monkeypatch):
    # Phase 5: a port that will not open surfaces a typed ConnectionError whose
    # hint points the user at the fix, not a bare pyserial traceback.
    import modules.core.usb_connection as usb

    monkeypatch.setattr(usb, "open_serial_port", lambda *a, **k: None)
    with pytest.raises(CatnipConnectionError) as exc:
        BleSpamController.open("/dev/ttyNOPE", baudrate=921600)
    assert exc.value.hint


def test_controller_read_events_yields_parsed_lines():
    fake = FakeSerial(
        b"SPAM: start mode=APPLE models=22 int=20-30ms\n"
        b"SPAM: Apple AirPods 2 (2/22)\n"
    )
    ctl = BleSpamController(fake)
    events = []
    for ev in ctl.read_events():
        events.append(ev)
        if len(events) == 2:
            break
    assert events[0].kind is LineKind.STATS
    assert events[1].kind is LineKind.CYCLE


def test_context_manager_stops_and_closes_owned_port():
    fake = FakeSerial()
    with BleSpamController(fake, owns=True):
        pass
    assert fake.written == [b"stop\n"]  # R5: stop on exit
    assert fake.closed is True


def test_context_manager_does_not_close_borrowed_port():
    fake = FakeSerial()
    with BleSpamController(fake, owns=False):
        pass
    assert fake.written == [b"stop\n"]
    assert fake.closed is False


# ── Phase 2: hardened-firmware controller commands ───────────────────────────
def test_set_power_writes_profile_token():
    fake = FakeSerial()
    BleSpamController(fake).set_power(PowerProfile.HIGH)
    assert fake.written == [b"pwr high\n"]


def test_set_power_uses_firmware_token_not_name():
    fake = FakeSerial()
    BleSpamController(fake).set_power(PowerProfile.BALANCED)
    assert fake.written == [b"pwr bal\n"]  # value "bal", not "BALANCED"


def test_set_interval_writes_min_max():
    fake = FakeSerial()
    BleSpamController(fake).set_interval(0x20, 0x4000)
    assert fake.written == [b"int 32 16384\n"]


def test_set_interval_out_of_range_raises_without_writing():
    # Success criterion: rejects before touching the port (R4/D-C3).
    fake = FakeSerial()
    ctl = BleSpamController(fake)
    with pytest.raises(ValidationError):
        ctl.set_interval(10, 20)  # below INT_UNIT_MIN (0x20)
    assert fake.written == []


def test_set_interval_min_greater_than_max_raises_without_writing():
    fake = FakeSerial()
    ctl = BleSpamController(fake)
    with pytest.raises(ValidationError):
        ctl.set_interval(60, 40)
    assert fake.written == []


# ── Phase 5: end-to-end interval confirmation (defence in depth) ─────────────
def test_set_interval_confirm_returns_on_ack():
    # With confirm=True the controller reads the firmware echo and returns.
    fake = FakeSerial(b"SPAM: int=40-60 (x0.625ms)\n")
    ctl = BleSpamController(fake)
    ctl.set_interval(40, 60, confirm=True, timeout=1.0)  # no raise
    assert fake.written == [b"int 40 60\n"]


def test_set_interval_confirm_maps_late_range_error():
    # A firmware that rejects an in-host-range interval (build mismatch) must
    # surface as a ValidationError, not a silent success (R4/Fase 5).
    fake = FakeSerial(
        b"SPAM: Beats Flex (11/82)\n"  # interleaved cycle line, skipped
        b"ERR: int range 0x20<=min<=max<=0x4000\n"
    )
    ctl = BleSpamController(fake)
    with pytest.raises(ValidationError):
        ctl.set_interval(40, 60, confirm=True, timeout=1.0)
    assert fake.written == [b"int 40 60\n"]  # it did send before the reply


def test_set_interval_confirm_best_effort_on_silence():
    # A quiet echo (no ack within timeout) is not a failure: the write went out.
    fake = FakeSerial()  # no reply at all
    ctl = BleSpamController(fake)
    ctl.set_interval(40, 60, confirm=True, timeout=0.1)  # returns, no raise
    assert fake.written == [b"int 40 60\n"]


def test_set_interval_no_confirm_is_fire_and_forget():
    # Default path: no read, so start/run never wait on the ack.
    fake = FakeSerial(b"ERR: int range 0x20<=min<=max<=0x4000\n")
    ctl = BleSpamController(fake)
    ctl.set_interval(40, 60)  # does not read the reply, no raise
    assert fake.written == [b"int 40 60\n"]


def test_stats_parses_telemetry_skipping_interleaved_lines():
    # A per-cycle line and a bare cycles= line (both STATS-kind but stats=None)
    # precede the telemetry line; the loop must skip them (R3).
    fake = FakeSerial(
        b"SPAM: Beats Flex (11/82)\n"
        b"SPAM: cycles=2000\n"
        b"STATS: cycles=2000 stack=200/1024 run=1 pwr=high int=32-48 heap=8000/16000\n"
    )
    st = BleSpamController(fake).stats(timeout=1.0)
    assert st == SpamStats(
        cycles=2000,
        stack_used=200,
        stack_size=1024,
        heap_free=8000,
        heap_total=16000,
        power=PowerProfile.HIGH,
        int_min=32,
        int_max=48,
    )
    assert fake.written == [b"stats\n"]


def test_stats_timeout_raises_protocol_error_with_hint():
    ctl = BleSpamController(FakeSerial())  # no reply
    with pytest.raises(ProtocolError) as exc:
        ctl.stats(timeout=0.1)
    assert exc.value.hint


def test_set_scan_on_state_ack_returns():
    fake = FakeSerial(b"SCAN: on (passive 160/80)\n")
    BleSpamController(fake).set_scan(True, timeout=1.0)
    assert fake.written == [b"scan on\n"]


def test_set_scan_off_writes_token():
    fake = FakeSerial(b"SCAN: off\n")
    BleSpamController(fake).set_scan(False, timeout=1.0)
    assert fake.written == [b"scan off\n"]


def test_set_scan_skips_report_lines_until_state_ack():
    # Interleaved SCAN report lines (rssi=…) must not be mistaken for the ack.
    fake = FakeSerial(b"SCAN: aa:bb:cc:dd:ee:ff rssi=-60 len=12\n" b"SCAN: off\n")
    BleSpamController(fake).set_scan(False, timeout=1.0)  # returns, no raise


def test_set_scan_unknown_cmd_raises_feature_unavailable():
    # Binary built without SPAM_WITH_SCAN → typed error, does not hang (R2).
    fake = FakeSerial(b"ERR: unknown cmd 'scan' (type help)\n")
    with pytest.raises(FeatureUnavailable) as exc:
        BleSpamController(fake).set_scan(True, timeout=1.0)
    assert exc.value.hint
    assert any("SPAM_WITH_SCAN" in step for step in exc.value.hint)


def test_set_scan_not_ready_raises_feature_unavailable():
    fake = FakeSerial(b"ERR: scan not ready\n")
    with pytest.raises(FeatureUnavailable):
        BleSpamController(fake).set_scan(True, timeout=1.0)


def test_set_scan_timeout_raises_protocol_error():
    ctl = BleSpamController(FakeSerial())  # silent binary
    with pytest.raises(ProtocolError) as exc:
        ctl.set_scan(True, timeout=0.1)
    assert exc.value.hint


def test_read_scan_events_yields_only_reports():
    fake = FakeSerial(
        b"SCAN: on (passive 160/80)\n"  # state line → filtered out
        b"SCAN: aa:bb:cc:dd:ee:ff rssi=-60 len=12\n"  # report → yielded
        b"SPAM: Beats Flex (11/82)\n"  # cycle → filtered out
        b"SCAN: 11:22:33:44:55:66 rssi=-42 len=8\n"  # report → yielded
    )
    ctl = BleSpamController(fake)
    events = []
    for ev in ctl.read_scan_events():
        events.append(ev)
        if len(events) == 2:
            break
    assert [e.addr for e in events] == ["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"]
    assert [e.rssi for e in events] == [-60, -42]


# ── Phase 6: PowerProfile ─────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "value,expected",
    [
        ("high", PowerProfile.HIGH),
        ("HIGH", PowerProfile.HIGH),  # firmware upper-cases in some replies
        ("bal", PowerProfile.BALANCED),
        ("balanced", PowerProfile.BALANCED),  # enum name, not just the token
        ("low", PowerProfile.LOW),
        ("  Low  ", PowerProfile.LOW),  # surrounding whitespace tolerated
    ],
)
def test_power_profile_from_str(value, expected):
    assert PowerProfile.from_str(value) is expected


def test_power_profile_from_str_rejects_unknown():
    with pytest.raises(ValueError):
        PowerProfile.from_str("turbo")


def test_power_profile_tokens_are_firmware_tokens():
    # The wire token is the enum value, not the enum name (bal, not BALANCED).
    assert PowerProfile.BALANCED.value == "bal"
    assert [p.value for p in PowerProfile] == ["high", "bal", "low"]


# ── Phase 6: validate_interval (pure host-side domain check, D-C3/R4) ─────────
@pytest.mark.parametrize("mn,mx", [(INT_UNIT_MIN, INT_UNIT_MAX), (32, 48), (40, 60), (100, 100)])
def test_validate_interval_accepts_in_range(mn, mx):
    validate_interval(mn, mx)  # must not raise


@pytest.mark.parametrize(
    "mn,mx",
    [
        (INT_UNIT_MIN - 1, 100),  # min below floor (0x20)
        (100, INT_UNIT_MAX + 1),  # max above ceiling (0x4000)
        (60, 40),  # min > max
        (0, 0),  # both below floor
    ],
)
def test_validate_interval_rejects_out_of_range(mn, mx):
    with pytest.raises(ValidationError):
        validate_interval(mn, mx)


def test_interval_unit_bounds_pinned_to_firmware_domain():
    # 0x20..0x4000 raw 0.625 ms ticks == 32..16384 == 20 ms..10.24 s.
    assert (INT_UNIT_MIN, INT_UNIT_MAX) == (0x20, 0x4000) == (32, 16384)


# ── Phase 6: hardened-firmware line parsing (each new format) ────────────────
def test_parse_status_extended_fills_new_fields():
    # Hardened status carries rot/pwr/int in addition to the base fields.
    st = parse_status("SPAM: mode=ALL running=1 models=82 rot=cycle pwr=low int=40-60")
    assert st == SpamStatus(
        mode=SpamMode.ALL,
        running=True,
        models=82,
        rot="cycle",
        power=PowerProfile.LOW,
        int_min=40,
        int_max=60,
    )


def test_parse_status_base_leaves_new_fields_none():
    # R1: a base-firmware status line still parses, with the new fields None.
    st = parse_status("SPAM: mode=APPLE running=1 models=22")
    assert (st.rot, st.power, st.int_min, st.int_max) == (None, None, None, None)


def test_parse_stats_telemetry_line():
    s = parse_stats(
        "STATS: cycles=1500 stack=812/1024 run=1 pwr=low int=40-60 heap=12992/16384"
    )
    assert s == SpamStats(
        cycles=1500,
        stack_used=812,
        stack_size=1024,
        heap_free=12992,
        heap_total=16384,
        power=PowerProfile.LOW,
        int_min=40,
        int_max=60,
    )


def test_parse_stats_none_for_non_telemetry():
    assert parse_stats("SPAM: cycles=2000") is None  # bare cycles, not STATS:
    assert parse_stats("STATS: garbage") is None


@pytest.mark.parametrize(
    "line,kind",
    [
        # extended status
        ("SPAM: mode=ALL running=0 models=82 rot=cycle pwr=high int=32-48", LineKind.STATUS),
        # on-demand telemetry
        ("STATS: cycles=0 stack=352/1024 run=0 pwr=low int=40-60 heap=13120/16384", LineKind.STATS),
        # extended start line (still generic STATS, D-C2: not enriched)
        ("SPAM: start mode=ALL models=82 pwr=low int=40-60 rot=cycle", LineKind.STATS),
        # stack low-water warning
        ("WARN: stack low 840/1024 B (>=80%)", LineKind.WARN),
        # scan report + scan state lines
        ("SCAN: 4c:19:2a:7f:e1:03 rssi=-52 len=31", LineKind.SCAN),
        ("SCAN: on (passive 160/80)", LineKind.SCAN),
        ("SCAN: already on", LineKind.SCAN),
        ("SCAN: off", LineKind.SCAN),
        # pwr/int command acks (no mode= → INFO, not STATUS)
        ("SPAM: pwr=bal int=64-96", LineKind.INFO),
        ("SPAM: int=40-60 (x0.625ms)", LineKind.INFO),
        # hardened help + new errors
        ("SPAM cmds: all|apple|android|windows|samsung, start, stop, status, stats, pwr high|bal|low, int <min> <max>, scan on|off", LineKind.INFO),
        ("ERR: usage: pwr high|bal|low", LineKind.ERROR),
        ("ERR: int range 0x20<=min<=max<=0x4000", LineKind.ERROR),
        ("ERR: usage: int <min> <max> (units 0.625ms, 32-16384)", LineKind.ERROR),
        ("ERR: unknown cmd 'scan' (type help)", LineKind.ERROR),
        ("ERR: scan not ready", LineKind.ERROR),
    ],
)
def test_parse_line_hardened_formats(line, kind):
    assert parse_line(line).kind is kind


def test_parse_line_scan_report_extracts_fields():
    line = parse_line("SCAN: d8:9e:3f:11:0a:bc rssi=-71 len=27")
    assert line.kind is LineKind.SCAN
    assert (line.addr, line.rssi, line.data_len) == ("d8:9e:3f:11:0a:bc", -71, 27)


def test_parse_line_scan_state_has_no_report_fields():
    # A state line must not look like a report (rssi None), so set_scan reads it as an ack.
    line = parse_line("SCAN: on (passive 160/80)")
    assert line.kind is LineKind.SCAN
    assert line.rssi is None and line.addr is None


def test_parse_line_stats_telemetry_attaches_stats():
    line = parse_line(
        "STATS: cycles=1500 stack=812/1024 run=1 pwr=low int=40-60 heap=12992/16384"
    )
    assert line.kind is LineKind.STATS
    assert line.stats is not None and line.stats.stack_used == 812
    assert line.cycles == 1500  # mirrored for the live view's convenience


# ── Phase 6: hardened fixture classifies cleanly (R1 backward-compat) ────────
def test_mejoras_fixture_lines_all_classified_without_unknown():
    if not MEJORAS_FIXTURE.exists():
        pytest.skip("hardened transcript fixture not present")
    lines = _device_lines_from(MEJORAS_FIXTURE)
    assert lines, "fixture yielded no device lines"
    for line in lines:
        assert parse_line(line).kind is not LineKind.UNKNOWN, line
    kinds = {parse_line(l).kind for l in lines}
    # The hardened transcript exercises every new category plus the base ones.
    assert {
        LineKind.STATUS,
        LineKind.STATS,
        LineKind.WARN,
        LineKind.SCAN,
        LineKind.ERROR,
        LineKind.INFO,
    } <= kinds


def test_mejoras_fixture_has_extended_status_and_telemetry():
    if not MEJORAS_FIXTURE.exists():
        pytest.skip("hardened transcript fixture not present")
    lines = _device_lines_from(MEJORAS_FIXTURE)
    parsed = [parse_line(l) for l in lines]
    # At least one status carries the hardened pwr/int fields.
    statuses = [p.status for p in parsed if p.kind is LineKind.STATUS and p.status]
    assert any(s.power is not None and s.int_min is not None for s in statuses)
    # At least one real telemetry line (STATS with parsed stats) is present.
    assert any(p.kind is LineKind.STATS and p.stats is not None for p in parsed)

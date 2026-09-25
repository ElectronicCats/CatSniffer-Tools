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
    BleSpamController,
    LineKind,
    PowerProfile,
    SpamMode,
    SpamStats,
    SpamStatus,
    parse_line,
    parse_status,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ble_spam_session.txt"


def _device_lines():
    """Meaningful device output lines from the fixture (no comments/markers)."""
    out = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("<<<"):
            continue
        out.append(line)
    return out


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

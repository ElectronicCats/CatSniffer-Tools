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
from modules.core.exceptions import ProtocolError, ValidationError
from modules.protocols.ble_spam import (
    BAUDRATE,
    CMD_MAXLEN,
    BleSpamController,
    LineKind,
    SpamMode,
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
        ("APPLE", SpamMode.APPLE),   # firmware reports modes upper-cased
        ("p", SpamMode.APPLE),       # short alias
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
    assert parse_line("SPAM: start mode=APPLE models=22 int=20-30ms").kind is LineKind.STATS
    assert parse_line("SPAM: addr fc:99:ae:e0:7c:8b").kind is LineKind.STATS


def test_parse_line_error():
    line = parse_line("ERR: unknown cmd 'foo' (type help)")
    assert line.kind is LineKind.ERROR
    assert line.message == "unknown cmd 'foo' (type help)"


def test_parse_line_info_acks():
    assert parse_line("SPAM: stopped").kind is LineKind.INFO
    assert parse_line("SPAM: already running").kind is LineKind.INFO
    assert parse_line("SPAM: mode -> APPLE (stopped)").kind is LineKind.INFO
    assert parse_line("SPAM cmds: all|apple|android|windows|samsung, start, stop, status").kind is LineKind.INFO


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
        self._lines = deque(
            (l + "\n").encode() for l in incoming.decode().splitlines()
        ) if incoming else deque()
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
        b"SPAM: Beats Flex (11/82)\n"
        b"SPAM: mode=APPLE running=1 models=22\n"
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
    assert fake.written == [b"stop\n"]   # R5: stop on exit
    assert fake.closed is True


def test_context_manager_does_not_close_borrowed_port():
    fake = FakeSerial()
    with BleSpamController(fake, owns=False):
        pass
    assert fake.written == [b"stop\n"]
    assert fake.closed is False

"""
BLE Spam — protocol constants and line parser.

The CC1352P7 BLE-spam firmware speaks a small line-oriented ASCII protocol over
the bridge UART:

  * Host → device: one short command per line, terminated with ``\\n``
    (``all|apple|android|windows|samsung``, ``start``, ``stop``, ``status``,
    ``help``). The firmware buffer is ``SPAM_CMD_MAXLEN`` bytes; longer input is
    truncated, so tokens are always short.
  * Device → host: ``\\r\\n``-terminated lines, prefixed ``SPAM:`` (state) or
    ``ERR:`` (error). Asynchronous per-cycle lines are interleaved with command
    replies, so the stream must be classified **by pattern, not by order**
    (there is no strict one-reply-per-command guarantee).

Everything here is pure and side-effect free; :mod:`controller` owns the serial
I/O. Values were confirmed hardware-in-the-loop against a CatSniffer v3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from modules.core.exceptions import ValidationError

# Effective host baud over the bridge port (CDC0). Matches the firmware UART and
# gives full-rate delivery with no loss; lower values throttle the USB-CDC pipe.
BAUDRATE = 921600

# Firmware command buffer size (SPAM_CMD_MAXLEN). Commands longer than this are
# silently truncated by the firmware, so the controller refuses to send them.
CMD_MAXLEN = 24

# Minimum gap between consecutive command writes. The firmware queues incoming
# command lines, but this keeps a safety margin so a burst (mode -> start ->
# status) never outruns the device even on older/other firmware that processes
# one line at a time. Small enough to be imperceptible for interactive use.
SEND_GAP_S = 0.02


class SpamMode(Enum):
    """Advertising-spam vendor set, with the firmware's long and short tokens."""

    ALL = ("all", "a")
    APPLE = ("apple", "p")
    ANDROID = ("android", "n")
    WINDOWS = ("windows", "w")
    SAMSUNG = ("samsung", "s")

    def __init__(self, token: str, short: str) -> None:
        self.token = token  # long command token, e.g. "apple"
        self.short = short  # single-letter alias, e.g. "p"

    @classmethod
    def from_str(cls, value: str) -> "SpamMode":
        """Resolve a mode from its long token, short alias or name (any case).

        The firmware reports modes upper-cased in ``status`` (``mode=APPLE``)
        but accepts lower-case tokens as input, so matching is case-insensitive.
        """
        key = value.strip().lower()
        for mode in cls:
            if key in (mode.token, mode.short, mode.name.lower()):
                return mode
        raise ValueError(f"unknown spam mode: {value!r}")


class PowerProfile(Enum):
    """TX power/interval profile the hardened firmware couples together.

    The firmware token is the enum value (``pwr high|bal|low`` on input and
    ``pwr=high`` in ``status``/``STATS`` output). Each profile also pins an
    advertising interval; the host only cares about the token here — the
    coupled interval arrives on the wire (``int=…``) and is parsed separately.
    """

    HIGH = "high"
    BALANCED = "bal"
    LOW = "low"

    @classmethod
    def from_str(cls, value: str) -> "PowerProfile":
        """Resolve a profile from its firmware token or name (any case)."""
        key = value.strip().lower()
        for profile in cls:
            if key in (profile.value, profile.name.lower()):
                return profile
        raise ValueError(f"unknown power profile: {value!r}")


@dataclass(frozen=True)
class SpamStatus:
    """Parsed ``status`` reply: active mode, whether emitting, and model count.

    The hardened firmware appends ``rot``/``pwr``/``int`` to the status line;
    those fields stay ``None`` against the base firmware (and the base fixture),
    so existing constructors keep working unchanged (R1).
    """

    mode: SpamMode
    running: bool
    models: int
    rot: Optional[str] = None
    power: Optional["PowerProfile"] = None
    int_min: Optional[int] = None
    int_max: Optional[int] = None


@dataclass(frozen=True)
class SpamStats:
    """Parsed ``STATS: …`` telemetry line (hardened firmware, on demand).

    Wire format (``ble_spam.c:646``)::

        STATS: cycles=%u stack=%u/%u run=%u pwr=%s int=%u-%u heap=%u/%u
    """

    cycles: int
    stack_used: int
    stack_size: int
    heap_free: int
    heap_total: int
    power: Optional[PowerProfile] = None
    int_min: Optional[int] = None
    int_max: Optional[int] = None


class LineKind(Enum):
    """Classification of a single device output line."""

    BANNER = "banner"  # one-shot boot banner (CatSniffer:BleSpam ...)
    STATUS = "status"  # SPAM: mode=... running=... models=...
    CYCLE = "cycle"  # SPAM: [model ]<name> (i/n)  — per advertisement
    STATS = "stats"  # SPAM: start.../cycles=.../addr / STATS: … telemetry
    WARN = "warn"  # WARN: stack low u/u B (>=n%)
    SCAN = "scan"  # SCAN: <mac> rssi/len report or on|off|ready|already state
    ERROR = "error"  # ERR: ...
    INFO = "info"  # command acks & misc (stopped, mode ->, help, ...)
    UNKNOWN = "unknown"  # anything unrecognised


@dataclass(frozen=True)
class SpamLine:
    """A classified output line plus any structured fields extracted from it."""

    kind: LineKind
    raw: str
    status: Optional[SpamStatus] = None
    model: Optional[str] = None
    index: Optional[int] = None
    total: Optional[int] = None
    cycles: Optional[int] = None
    addr: Optional[str] = None
    message: Optional[str] = None
    stats: Optional[SpamStats] = None
    rssi: Optional[int] = None
    data_len: Optional[int] = None


# ── interval validation (units of 0.625 ms; firmware domain, D-C3) ────────────
# The firmware validates 0x20 <= min <= max <= 0x4000 (32..16384 → 20 ms..10.24 s).
# The host validates in the *same* raw domain so a bad interval fails immediately,
# without a round-trip to the device (R4).
INT_UNIT_MIN = 0x20
INT_UNIT_MAX = 0x4000


def validate_interval(mn: int, mx: int) -> None:
    """Raise :class:`ValidationError` unless ``0x20 <= mn <= mx <= 0x4000``.

    Units are the firmware's raw 0.625 ms ticks. Pure and reusable by both the
    controller (before writing) and the CLI (before opening a port).
    """
    if not (INT_UNIT_MIN <= mn <= mx <= INT_UNIT_MAX):
        raise ValidationError(
            f"interval {mn}-{mx} out of range: need "
            f"{INT_UNIT_MIN} <= min <= max <= {INT_UNIT_MAX} "
            f"(units of 0.625 ms → {INT_UNIT_MIN}..{INT_UNIT_MAX} = 20 ms..10.24 s)"
        )


# ── line patterns ────────────────────────────────────────────────────────────
# Status: base fields are required; the hardened firmware's rot/pwr/int are
# optional trailing groups so the base fixture keeps parsing identically (R1).
_RE_STATUS = re.compile(
    r"SPAM:\s*mode=(?P<mode>\w+)\s+running=(?P<running>[01])\s+models=(?P<models>\d+)"
    r"(?:\s+rot=(?P<rot>\S+))?"
    r"(?:\s+pwr=(?P<pwr>\w+))?"
    r"(?:\s+int=(?P<imin>\d+)-(?P<imax>\d+))?"
)
_RE_START = re.compile(r"SPAM:\s*start\s+mode=(?P<mode>\w+)\s+models=(?P<models>\d+)")
_RE_CYCLES = re.compile(r"SPAM:\s*cycles=(?P<cycles>\d+)")
_RE_ADDR = re.compile(r"SPAM:\s*addr\s+(?P<addr>[0-9A-Fa-f:]+)")
# First per-cycle line carries a "model " prefix; the rest do not.
_RE_CYCLE = re.compile(
    r"SPAM:\s*(?:model\s+)?(?P<model>.+?)\s+\((?P<i>\d+)/(?P<n>\d+)\)\s*$"
)
# Hardened firmware, distinct prefixes (STATS:/WARN:/SCAN:).
_RE_STATS_TELEMETRY = re.compile(
    r"STATS:\s*cycles=(?P<cycles>\d+)\s+stack=(?P<su>\d+)/(?P<ss>\d+)"
    r"\s+run=(?P<run>\d+)\s+pwr=(?P<pwr>\w+)\s+int=(?P<imin>\d+)-(?P<imax>\d+)"
    r"\s+heap=(?P<hf>\d+)/(?P<ht>\d+)"
)
_RE_SCAN_REPORT = re.compile(
    r"SCAN:\s*(?P<mac>(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})"
    r"\s+rssi=(?P<rssi>-?\d+)\s+len=(?P<len>\d+)"
)
# Standalone acks for `pwr`/`int` (no mode= field, so not a full status).
_RE_PWR_INT_ACK = re.compile(r"SPAM:\s*(?:pwr|int)=")

_INFO_MARKERS = ("stopped", "already running", "mode ->", "uart control ready")


def _power_from(value: Optional[str]) -> Optional[PowerProfile]:
    """Best-effort ``PowerProfile`` from an optional token (None/unknown → None)."""
    if not value:
        return None
    try:
        return PowerProfile.from_str(value)
    except ValueError:
        return None


def parse_status(line: str) -> Optional[SpamStatus]:
    """Parse a ``SPAM: mode=… running=… models=…`` line, or None if it is not one.

    The hardened firmware's trailing ``rot``/``pwr``/``int`` fields are filled
    only when present; against the base firmware they stay ``None``.
    """
    m = _RE_STATUS.search(line)
    if not m:
        return None
    try:
        mode = SpamMode.from_str(m.group("mode"))
    except ValueError:
        return None
    imin, imax = m.group("imin"), m.group("imax")
    return SpamStatus(
        mode=mode,
        running=m.group("running") == "1",
        models=int(m.group("models")),
        rot=m.group("rot"),
        power=_power_from(m.group("pwr")),
        int_min=int(imin) if imin is not None else None,
        int_max=int(imax) if imax is not None else None,
    )


def parse_stats(line: str) -> Optional[SpamStats]:
    """Parse a ``STATS: …`` telemetry line, or None if it is not one."""
    m = _RE_STATS_TELEMETRY.search(line)
    if not m:
        return None
    return SpamStats(
        cycles=int(m.group("cycles")),
        stack_used=int(m.group("su")),
        stack_size=int(m.group("ss")),
        heap_free=int(m.group("hf")),
        heap_total=int(m.group("ht")),
        power=_power_from(m.group("pwr")),
        int_min=int(m.group("imin")),
        int_max=int(m.group("imax")),
    )


def parse_line(line: str) -> SpamLine:
    """Classify one device output line into a :class:`SpamLine`.

    Order matters: more specific ``SPAM:`` patterns are tested before the generic
    per-cycle pattern so that status/stats lines are never misread as cycles.
    """
    raw = line.rstrip("\r\n")
    text = raw.strip()

    if not text:
        return SpamLine(LineKind.UNKNOWN, raw)

    if text.startswith("ERR:"):
        return SpamLine(LineKind.ERROR, raw, message=text[4:].strip())

    if "CatSniffer:BleSpam" in text:
        return SpamLine(LineKind.BANNER, raw, message=text)

    # Hardened-firmware prefixes (distinct from SPAM:), classified first.
    if text.startswith("STATS:"):
        stats = parse_stats(text)
        if stats is not None:
            return SpamLine(
                LineKind.STATS, raw, stats=stats, cycles=stats.cycles, message=text
            )
        return SpamLine(LineKind.STATS, raw, message=text)

    if text.startswith("WARN:"):
        return SpamLine(LineKind.WARN, raw, message=text)

    if text.startswith("SCAN:"):
        m = _RE_SCAN_REPORT.search(text)
        if m:
            return SpamLine(
                LineKind.SCAN,
                raw,
                addr=m.group("mac"),
                rssi=int(m.group("rssi")),
                data_len=int(m.group("len")),
                message=text,
            )
        # on|off|ready|already … state lines carry no report fields.
        return SpamLine(LineKind.SCAN, raw, message=text)

    status = parse_status(text)
    if status is not None:
        return SpamLine(LineKind.STATUS, raw, status=status)

    if _RE_START.search(text):
        return SpamLine(LineKind.STATS, raw, message=text)

    m = _RE_CYCLES.search(text)
    if m:
        return SpamLine(LineKind.STATS, raw, cycles=int(m.group("cycles")))

    m = _RE_ADDR.search(text)
    if m:
        return SpamLine(LineKind.STATS, raw, addr=m.group("addr"), message=text)

    # `pwr`/`int` command acks (checked before the generic cycle pattern).
    if _RE_PWR_INT_ACK.match(text):
        return SpamLine(LineKind.INFO, raw, message=text)

    m = _RE_CYCLE.search(text)
    if m:
        return SpamLine(
            LineKind.CYCLE,
            raw,
            model=m.group("model").strip(),
            index=int(m.group("i")),
            total=int(m.group("n")),
        )

    low = text.lower()
    if text.startswith("SPAM cmds:") or any(mark in low for mark in _INFO_MARKERS):
        return SpamLine(LineKind.INFO, raw, message=text)

    return SpamLine(LineKind.UNKNOWN, raw, message=text)

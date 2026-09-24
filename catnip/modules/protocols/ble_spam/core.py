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


@dataclass(frozen=True)
class SpamStatus:
    """Parsed ``status`` reply: active mode, whether emitting, and model count."""

    mode: SpamMode
    running: bool
    models: int


class LineKind(Enum):
    """Classification of a single device output line."""

    BANNER = "banner"  # one-shot boot banner (CatSniffer:BleSpam ...)
    STATUS = "status"  # SPAM: mode=... running=... models=...
    CYCLE = "cycle"  # SPAM: [model ]<name> (i/n)  — per advertisement
    STATS = "stats"  # SPAM: start.../cycles=.../addr ... running stats
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


# ── line patterns ────────────────────────────────────────────────────────────
_RE_STATUS = re.compile(
    r"SPAM:\s*mode=(?P<mode>\w+)\s+running=(?P<running>[01])\s+models=(?P<models>\d+)"
)
_RE_START = re.compile(r"SPAM:\s*start\s+mode=(?P<mode>\w+)\s+models=(?P<models>\d+)")
_RE_CYCLES = re.compile(r"SPAM:\s*cycles=(?P<cycles>\d+)")
_RE_ADDR = re.compile(r"SPAM:\s*addr\s+(?P<addr>[0-9A-Fa-f:]+)")
# First per-cycle line carries a "model " prefix; the rest do not.
_RE_CYCLE = re.compile(
    r"SPAM:\s*(?:model\s+)?(?P<model>.+?)\s+\((?P<i>\d+)/(?P<n>\d+)\)\s*$"
)

_INFO_MARKERS = ("stopped", "already running", "mode ->", "uart control ready")


def parse_status(line: str) -> Optional[SpamStatus]:
    """Parse a ``SPAM: mode=… running=… models=…`` line, or None if it is not one."""
    m = _RE_STATUS.search(line)
    if not m:
        return None
    try:
        mode = SpamMode.from_str(m.group("mode"))
    except ValueError:
        return None
    return SpamStatus(
        mode=mode,
        running=m.group("running") == "1",
        models=int(m.group("models")),
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

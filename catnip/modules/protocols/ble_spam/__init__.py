# BLE Spam protocol backend
# ==========================
# Host-side control of the CC1352P7 BLE advertising-spam firmware over the
# CatSniffer bridge port (CDC0). Pure protocol/transport layer, decoupled from
# Click so it can be unit-tested against a captured serial transcript.

from .core import (
    BAUDRATE,
    CMD_MAXLEN,
    INT_UNIT_MAX,
    INT_UNIT_MIN,
    LineKind,
    PowerProfile,
    SpamLine,
    SpamMode,
    SpamStats,
    SpamStatus,
    parse_line,
    parse_stats,
    parse_status,
    validate_interval,
)
from .controller import BleSpamController

__all__ = [
    "BAUDRATE",
    "CMD_MAXLEN",
    "INT_UNIT_MIN",
    "INT_UNIT_MAX",
    "LineKind",
    "PowerProfile",
    "SpamLine",
    "SpamMode",
    "SpamStats",
    "SpamStatus",
    "parse_line",
    "parse_stats",
    "parse_status",
    "validate_interval",
    "BleSpamController",
]

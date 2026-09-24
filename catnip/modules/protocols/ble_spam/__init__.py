# BLE Spam protocol backend
# ==========================
# Host-side control of the CC1352P7 BLE advertising-spam firmware over the
# CatSniffer bridge port (CDC0). Pure protocol/transport layer, decoupled from
# Click so it can be unit-tested against a captured serial transcript.

from .core import (
    BAUDRATE,
    CMD_MAXLEN,
    LineKind,
    SpamLine,
    SpamMode,
    SpamStatus,
    parse_line,
    parse_status,
)
from .controller import BleSpamController

__all__ = [
    "BAUDRATE",
    "CMD_MAXLEN",
    "LineKind",
    "SpamLine",
    "SpamMode",
    "SpamStatus",
    "parse_line",
    "parse_status",
    "BleSpamController",
]

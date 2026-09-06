"""Single source of truth for verifying which CC1352 firmware is running.

Before this module existed, the same ~50-line "check metadata, fall back to
direct communication, flash if missing, retry verification" sequence was
copy-pasted into every ``sniff`` command (see
``analisis-bombercat-vs-catnip.md``, section 2) and the checks themselves
lived as methods on :class:`~modules.core.catnip.Catnip`, mixing plain bridge
I/O with firmware-verification business logic. ``FirmwareVerifier`` now owns
that logic; ``Catnip.check_*`` are kept as thin deprecated wrappers so
existing callers (``protocols/cli/cativity.py``, ``protocols/cli/vhci.py``)
keep working unchanged.
"""

import time
from base64 import b64decode, b64encode
from binascii import Error as BAError
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import serial

from protocol.sniffer_ti import SnifferTI

from .usb_connection import BridgeConnection, ShellConnection


class Confidence(Enum):
    """How a verification was confirmed, most reliable first."""

    NONE = "none"
    DIRECT = "direct communication"
    METADATA = "metadata"


@dataclass
class VerificationResult:
    verified: bool
    confidence: Confidence = Confidence.NONE

    def __bool__(self) -> bool:
        return self.verified


class FirmwareVerifier:
    """Verifies a device's CC1352 firmware against an official firmware id.

    Each check opens its own short-lived connection rather than reusing one
    handed in, so calling :meth:`verify` repeatedly (e.g. from
    :meth:`verify_with_retries` right after a flash, while the port is still
    settling) is safe.
    """

    # Firmware ids that can be confirmed by talking to the CC1352 directly.
    # Firmwares outside this set can only be confirmed via metadata.
    _DIRECT_CHECK_IDS = {"ti_sniffer", "sniffle"}

    def __init__(self, bridge_port: Optional[str], shell_port: Optional[str] = None):
        self.bridge_port = bridge_port
        self.shell_port = shell_port

    # ── individual checks ────────────────────────────────────────────────

    def verify_metadata(self, official_id: str) -> bool:
        """Verify via the firmware id stored in RP2040 flash (Cat-Shell port).

        More reliable than direct CC1352 communication because it does not
        depend on the CC1352 being responsive.
        """
        from ..firmware.fw_metadata import FirmwareMetadata

        if not self.shell_port:
            return False

        try:
            shell = ShellConnection(port=self.shell_port)
            if not shell.connect():
                return False

            metadata = FirmwareMetadata(shell)
            current_id = metadata.get_firmware_id()
            shell.disconnect()

            return bool(current_id) and current_id == official_id
        except Exception:
            return False

    def verify_direct(self, official_id: str) -> bool:
        """Verify by talking to the CC1352 over the bridge port directly."""
        if official_id == "ti_sniffer":
            return self._check_ti_firmware()
        if official_id == "sniffle":
            return self._check_sniffle_firmware_smart()
        return False

    def verify(self, official_id: str) -> VerificationResult:
        """Try metadata first (more reliable), then direct communication."""
        if self.verify_metadata(official_id):
            return VerificationResult(True, Confidence.METADATA)
        if official_id in self._DIRECT_CHECK_IDS and self.verify_direct(official_id):
            return VerificationResult(True, Confidence.DIRECT)
        return VerificationResult(False, Confidence.NONE)

    def verify_with_retries(
        self, official_id: str, retries: int = 0, delay: float = 0.5
    ) -> VerificationResult:
        """Call :meth:`verify` up to ``1 + retries`` times, pausing ``delay``
        seconds between attempts, stopping as soon as it succeeds."""
        result = self.verify(official_id)
        attempt = 0
        while not result.verified and attempt < retries:
            time.sleep(delay)
            result = self.verify(official_id)
            attempt += 1
        return result

    # ── direct-communication protocol probes ────────────────────────────
    # Ported from Catnip.check_flag/check_ti_firmware/check_sniffle_firmware*
    # (kept there as deprecated wrappers around this class).

    def _check_flag(self, flag: bytes, timeout: float = 2) -> bool:
        bridge = BridgeConnection(port=self.bridge_port)
        if not bridge.connect():
            return False
        conn = bridge.connection
        if conn is None:
            return False
        conn.timeout = timeout
        bridge.write(SnifferTI().Commands().stop())
        bridge.write(SnifferTI().Commands().ping())
        got = bridge.read(16)
        result = got[7:8].hex() == "40" or flag in got
        bridge.disconnect()
        return result

    def _check_ti_firmware(self, timeout: float = 2) -> bool:
        return self._check_flag(flag=b"TI Packet", timeout=timeout)

    def _check_sniffle_firmware_smart(
        self, timeout: float = 3, max_retries: int = 2
    ) -> bool:
        # Ensure port is closed before direct communication attempt.
        return self._check_sniffle_firmware(timeout, max_retries)

    def _check_sniffle_firmware(self, timeout: float = 3, max_retries: int = 2) -> bool:
        flag = [0x24]
        b0 = (len(flag) + 3) // 3
        msg = b64encode(bytes([b0, *flag])) + b"\r\n"

        for attempt in range(max_retries + 1):
            bridge = BridgeConnection(port=self.bridge_port)
            try:
                if attempt > 0:
                    time.sleep(1)

                if not bridge.connect():
                    continue

                conn = bridge.connection
                if conn is None:
                    continue

                conn.timeout = timeout

                try:
                    conn.reset_input_buffer()
                    conn.reset_output_buffer()
                except Exception:
                    bridge.disconnect()
                    continue

                bridge.write(msg)
                time.sleep(0.2)

                start = time.time()
                pkt = b""
                while time.time() - start < timeout:
                    try:
                        line = bridge.readline()
                        if line:
                            pkt = line
                            break
                    except Exception:
                        pass
                    time.sleep(0.05)

                if not pkt:
                    bridge.disconnect()
                    continue

                try:
                    decoded = b64decode(pkt.rstrip())
                    bridge.disconnect()
                    if len(decoded) >= 3:
                        return True
                except (BAError, ValueError):
                    bridge.disconnect()
                    continue

            except serial.SerialException:
                try:
                    bridge.disconnect()
                except Exception:
                    pass
            except Exception:
                try:
                    bridge.disconnect()
                except Exception:
                    pass
            finally:
                try:
                    if bridge.connection and bridge.connection.is_open:
                        bridge.disconnect()
                except Exception:
                    pass

        return False

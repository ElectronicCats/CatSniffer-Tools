"""
BLE Spam — serial controller.

Thin control layer over the CC1352 bridge port. It reuses the project's serial
helpers (:func:`modules.core.usb_connection.open_serial_port`, the same entry the
AirTag scanner uses to read a CC1352 application over the bridge) rather than
re-implementing port setup.

The controller accepts any serial-like object (``write`` / ``flush`` /
``readline`` / ``close``), so it can be driven in tests by a fake transport fed
from a captured transcript — no hardware required. Use :meth:`open` to build one
against a real port.

Safety (R5): the firmware boots emitting, and selecting a mode while running
restarts the cycle. The context manager always sends ``stop`` on exit so the
hardware is never left advertising after the controller goes away.
"""

from __future__ import annotations

import time
from typing import Iterator, Optional

from ...core.exceptions import ConnectionError as CatnipConnectionError
from ...core.exceptions import ProtocolError, ValidationError
from .core import BAUDRATE, CMD_MAXLEN, LineKind, SpamLine, SpamMode, SpamStatus, parse_line


class BleSpamController:
    """Drive the BLE-spam firmware over an open serial-like transport."""

    def __init__(self, serial_obj, *, owns: bool = False) -> None:
        self._serial = serial_obj
        self._owns = owns  # whether we opened (and must close) the port

    # ── construction ──────────────────────────────────────────────────────
    @classmethod
    def open(
        cls,
        port: str,
        baudrate: int = BAUDRATE,
        timeout: float = 0.5,
    ) -> "BleSpamController":
        """Open *port* and return a controller that owns the connection."""
        from ...core.usb_connection import open_serial_port

        ser = open_serial_port(port, baudrate=baudrate, timeout=timeout)
        if ser is None:
            raise CatnipConnectionError(f"could not open {port} at {baudrate} baud")
        return cls(ser, owns=True)

    # ── low-level I/O ─────────────────────────────────────────────────────
    def send(self, cmd: str) -> None:
        """Send a single command line, appending ``\\n`` and enforcing the length cap."""
        token = cmd.strip()
        if not token:
            raise ValidationError("empty command")
        if len(token) > CMD_MAXLEN:
            raise ValidationError(
                f"command {token!r} exceeds firmware limit of {CMD_MAXLEN} bytes"
            )
        self._serial.write((token + "\n").encode("ascii"))
        self._serial.flush()

    def _readline(self) -> str:
        raw = self._serial.readline()
        if isinstance(raw, bytes):
            return raw.decode("ascii", errors="replace")
        return raw or ""

    # ── commands ──────────────────────────────────────────────────────────
    def set_mode(self, mode: SpamMode) -> None:
        """Select a vendor mode (restarts the cycle if already running)."""
        self.send(mode.token)

    def start(self) -> None:
        """Start the advertising-spam cycle."""
        self.send("start")

    def stop(self) -> None:
        """Stop emitting."""
        self.send("stop")

    def status(self, timeout: float = 1.0) -> SpamStatus:
        """Send ``status`` and return the first :class:`SpamStatus` reply.

        Because per-cycle lines are interleaved with replies, this reads and
        classifies lines until a STATUS line arrives or *timeout* elapses.
        """
        self.send("status")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self._readline()
            if not line:
                continue
            parsed = parse_line(line)
            if parsed.kind is LineKind.STATUS and parsed.status is not None:
                return parsed.status
        raise ProtocolError("no status reply from BLE-spam firmware")

    def read_events(self) -> Iterator[SpamLine]:
        """Yield parsed lines as they arrive (blocks per read timeout).

        Empty reads (idle timeouts) are skipped. The caller controls the loop
        lifetime, e.g. breaking on ``KeyboardInterrupt``.
        """
        while True:
            line = self._readline()
            if not line:
                continue
            yield parse_line(line)

    # ── lifecycle ─────────────────────────────────────────────────────────
    def close(self) -> None:
        """Close the port if this controller opened it."""
        if self._owns and self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass

    def __enter__(self) -> "BleSpamController":
        return self

    def __exit__(self, *_exc) -> None:
        # R5: never leave the hardware advertising.
        try:
            self.stop()
        except Exception:
            pass
        self.close()

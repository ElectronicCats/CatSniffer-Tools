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
from ...core.exceptions import FeatureUnavailable, ProtocolError, ValidationError
from .core import (
    BAUDRATE,
    CMD_MAXLEN,
    SEND_GAP_S,
    LineKind,
    PowerProfile,
    SpamLine,
    SpamMode,
    SpamStats,
    SpamStatus,
    parse_line,
    validate_interval,
)


class BleSpamController:
    """Drive the BLE-spam firmware over an open serial-like transport."""

    def __init__(self, serial_obj, *, owns: bool = False) -> None:
        self._serial = serial_obj
        self._owns = owns  # whether we opened (and must close) the port
        self._last_send = 0.0  # monotonic time of the last write, for pacing

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
            raise CatnipConnectionError(
                f"could not open {port} at {baudrate} baud",
                hint=[
                    "Check the CatSniffer is connected: catnip device list",
                    "Close any other program holding the port (serial monitors, IDEs)",
                ],
            )
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
        # Space consecutive commands so a burst never outruns the firmware.
        gap = SEND_GAP_S - (time.monotonic() - self._last_send)
        if gap > 0:
            time.sleep(gap)
        self._serial.write((token + "\n").encode("ascii"))
        self._serial.flush()
        self._last_send = time.monotonic()

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
        raise ProtocolError(
            "no status reply from BLE-spam firmware",
            hint=[
                "Confirm the ble_spam firmware is flashed: catnip flash ble_spam",
                "The CC1352 may still be resetting after connect — retry the command",
            ],
        )

    def set_power(self, profile: PowerProfile) -> None:
        """Select a TX-power/interval profile (``pwr high|bal|low``).

        Mirrors :meth:`set_mode`: fire-and-forget. The firmware acks with
        ``SPAM: pwr=… int=…`` (classified as INFO, not a full status), so there
        is nothing to return; the coupled interval is observed later via
        :meth:`status` or :meth:`stats`.
        """
        self.send(f"pwr {profile.value}")

    def set_interval(
        self, mn: int, mx: int, *, confirm: bool = False, timeout: float = 1.0
    ) -> None:
        """Override the advertising interval (``int <min> <max>``, 0.625 ms units).

        Validates in the firmware's own domain **before** touching the port
        (R4/D-C3), so an out-of-range interval raises :class:`ValidationError`
        without a write or a round-trip. On valid input the firmware echoes
        ``SPAM: int=<mn>-<mx> (x0.625ms)``.

        With ``confirm`` (Fase 5, end-to-end validation) it also reads the reply
        for a bounded *timeout* and turns a late ``ERR: int range …`` into a
        :class:`ValidationError` — defence in depth: host pre-validation makes
        that reply impossible from a sound firmware, but a mismatched build must
        not slip through as silent success. Interleaved per-cycle lines are
        skipped; a missing ack within *timeout* is treated as best-effort (the
        write went out, so the happy path is never failed on a quiet echo).
        Fire-and-forget by default, so ``start``/``run`` never wait on the ack.
        """
        validate_interval(mn, mx)  # raises before any write
        self.send(f"int {mn} {mx}")
        if not confirm:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self._readline()
            if not line:
                continue
            parsed = parse_line(line)
            if (
                parsed.kind is LineKind.INFO
                and parsed.message
                and "int=" in parsed.message
            ):
                return  # SPAM: int=<mn>-<mx> (x0.625ms) — firmware accepted it
            if parsed.kind is LineKind.ERROR and parsed.message:
                low = parsed.message.lower()
                if "int range" in low or ("usage" in low and "int" in low):
                    raise ValidationError(
                        f"firmware rejected interval {mn}-{mx}: {parsed.message}",
                        hint=[
                            "Use units of 0.625 ms in 32..16384 (20 ms..10.24 s)",
                            "Example: catnip spam int 40 60",
                        ],
                    )
        # No ack seen within timeout: the write went out; do not fail the
        # happy path on a quiet echo (a busy cycle may crowd it out).

    def stats(self, timeout: float = 1.0) -> SpamStats:
        """Send ``stats`` and return the first telemetry line as :class:`SpamStats`.

        Same read-and-classify-by-pattern loop as :meth:`status`: per-cycle and
        other ``STATS:``-family lines (start/cycles/addr, which carry no parsed
        ``stats``) are skipped until the telemetry line arrives or *timeout*
        elapses. The bounded deadline keeps an unresponsive binary from hanging
        the CLI (R2/Fase 5).
        """
        self.send("stats")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self._readline()
            if not line:
                continue
            parsed = parse_line(line)
            if parsed.kind is LineKind.STATS and parsed.stats is not None:
                return parsed.stats
        raise ProtocolError(
            "no telemetry reply from BLE-spam firmware",
            hint=[
                "Confirm the hardened ble_spam firmware is flashed: catnip flash ble_spam",
                "The CC1352 may still be resetting after connect — retry the command",
            ],
        )

    def set_scan(self, on: bool, timeout: float = 1.0) -> None:
        """Toggle the passive GAP coexistence scan (``scan on|off``).

        Reads the reply to distinguish three outcomes (R2):

        * a ``SCAN:`` **state** line (``on``/``off``/``already …``/``ready``) →
          success, returns ``None``;
        * ``ERR: scan not ready`` or ``ERR: unknown cmd`` → an **older** flashed
          image built before scan became the default (``SPAM_WITH_SCAN=0``), so
          raise :class:`FeatureUnavailable` (fix: reflash) rather than hang
          waiting for a ``SCAN:`` that never comes;
        * nothing within *timeout* → :class:`ProtocolError`.

        Interleaved ``SCAN:`` **report** lines (``rssi=…``) are skipped; only a
        state line (``rssi is None``) counts as the acknowledgement.
        """
        self.send("scan on" if on else "scan off")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self._readline()
            if not line:
                continue
            parsed = parse_line(line)
            if parsed.kind is LineKind.SCAN and parsed.rssi is None:
                return  # state ack: on|off|already|ready
            if parsed.kind is LineKind.ERROR and parsed.message:
                low = parsed.message.lower()
                if "scan not ready" in low or "unknown cmd" in low:
                    raise FeatureUnavailable(
                        "the flashed ble_spam image predates built-in BLE scan",
                        hint=[
                            "Scan ships enabled by default now — reflash the "
                            "current firmware: catnip flash ble_spam",
                            "Only if you build your own image, keep the default "
                            "SPAM_WITH_SCAN=1 (SPAM_WITH_SCAN=0 opts out)",
                        ],
                    )
        raise ProtocolError(
            "no scan reply from BLE-spam firmware",
            hint=[
                "Confirm the hardened ble_spam firmware is flashed: catnip flash ble_spam",
                "The CC1352 may still be resetting after connect — retry the command",
            ],
        )

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

    def read_scan_events(self) -> Iterator[SpamLine]:
        """Yield only ``SCAN:`` **report** lines (``rssi is not None``).

        A filtered sibling of :meth:`read_events` for the live view's scan feed;
        state lines and the rest of the stream are dropped.
        """
        for event in self.read_events():
            if event.kind is LineKind.SCAN and event.rssi is not None:
                yield event

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

import os
import time
import threading
import platform
import statistics
import struct
import serial

# Internal
from .catnip import (
    CatSnifferDevice,
    Catnip,
    ShellConnection,
    LoRaConnection,
    DEFAULT_READLINE_MAX_BYTES,
)
from .pipes import UnixPipe, WindowsPipe, Wireshark
from protocol.sniffer_sx import (
    SnifferSx,
    LORATAP_DLT,
    modulation_command,
    sx1262_band_command,
)
from protocol.sniffer_ti import SnifferTI, PacketCategory, cc1352_band_command
from protocol.common import (
    START_OF_FRAME,
    END_OF_FRAME,
    PCAP_MAX_PACKET_SIZE,
    PCAP_PACKET_HEADER_FORMAT,
    PCAP_PACKET_HEADER_LEN,
    get_global_header,
)

from ..firmware.fw_status import read_loss_counters
from ..utils._version import __version__

# External
from ..utils.output import (
    console,
    print_success,
    print_warning,
    print_error,
    print_info,
    print_dim,
    refuse_overwrite,
)

sniffer = SnifferTI()
snifferSx = SnifferSx()
snifferTICmd = sniffer.Commands()
snifferSxCmd = snifferSx.Commands()
snifferSxFskCmd = snifferSx.FskCommands()

# Delay between shell commands (seconds) — RP2040 needs a small gap
_SHELL_CMD_DELAY = 0.15

# Seconds to wait for Wireshark to open the pipe
_WIRESHARK_PIPE_TIMEOUT = 30

# The RP2040 firmware (lora_rx_cb) emits "LORA RX: ..." lines on Cat-LoRa.
# We match with `in` instead of `startswith` to handle both "RX:" and "LORA RX:" variants.
_LORA_LINE_PREFIX = b"RX:"

# The firmware also sends a welcome banner on Cat-LoRa at startup and after
# lora_mode changes — we skip those silently.
_IGNORE_PREFIXES = (b"LoRa Control Port", b"LoRa mode set")


# ──────────────────────────────────────────────────────────────────────────────
# Packet logging (shared by all sniff bridges)
# ──────────────────────────────────────────────────────────────────────────────


class PacketLogWriter:
    """Append captured packets to raw-hex and/or decoded-ASCII log files.

    Both destinations are optional. Every line has the shape:

        RX: <payload> | <meta>

    where ``<payload>`` is either the hex dump (raw file) or the printable
    ASCII rendering (ascii file), and ``<meta>`` is a protocol-specific tail.
    The metadata is passed in per packet by the caller, so each protocol logs
    only the fields that make sense for it — e.g. ``RSSI: -30 | SNR: 7`` for
    LoRa but just ``RSSI: -45`` for Zigbee/Thread (802.15.4 has no SNR).
    If ``meta`` is empty the trailing separator is omitted.
    """

    def __init__(self, raw_file: str = None, ascii_file: str = None):
        if raw_file:
            refuse_overwrite(raw_file)
        if ascii_file:
            refuse_overwrite(ascii_file)
        self.raw_fh = open(raw_file, "a", encoding="ascii") if raw_file else None
        self.ascii_fh = open(ascii_file, "a", encoding="ascii") if ascii_file else None
        if self.raw_fh:
            print_success(f"Logging raw hex to {raw_file}")
        if self.ascii_fh:
            print_success(f"Logging ASCII to {ascii_file}")

    @property
    def enabled(self) -> bool:
        return self.raw_fh is not None or self.ascii_fh is not None

    @staticmethod
    def _to_ascii(payload: bytes) -> str:
        return "".join(chr(b) if 32 <= b < 127 else "." for b in payload)

    def write(self, payload: bytes, meta: str = "") -> None:
        if not self.enabled:
            return
        suffix = f" | {meta}" if meta else ""
        if self.raw_fh:
            self.raw_fh.write(f"RX: {payload.hex()}{suffix}\n")
            self.raw_fh.flush()
        if self.ascii_fh:
            self.ascii_fh.write(f"RX: {self._to_ascii(payload)}{suffix}\n")
            self.ascii_fh.flush()

    def close(self) -> None:
        for fh in (self.raw_fh, self.ascii_fh):
            if fh:
                try:
                    fh.close()
                except Exception:
                    pass


# ──────────────────────────────────────────────────────────────────────────────
# PCAP / PCAPNG file capture (shared by all sniff bridges)
# ──────────────────────────────────────────────────────────────────────────────

# PCAPNG block types and the byte-order magic, from the pcapng spec.
_PCAPNG_SHB_TYPE = 0x0A0D0D0A
_PCAPNG_IDB_TYPE = 0x00000001
_PCAPNG_EPB_TYPE = 0x00000006
_PCAPNG_BYTE_ORDER_MAGIC = 0x1A2B3C4D
_PCAPNG_SECTION_LENGTH_UNKNOWN = -1

# Option codes we emit: shb_userappl on the section header, if_tsresol on the
# interface. if_tsresol=6 (microseconds) is the spec default, but stating it
# explicitly keeps the file readable by tools that do not assume the default.
_PCAPNG_OPT_ENDOFOPT = 0
_PCAPNG_OPT_SHB_USERAPPL = 4
_PCAPNG_OPT_IF_TSRESOL = 9


def _pcapng_option(code: int, value: bytes) -> bytes:
    """One pcapng option: code, length, value padded to a 4-byte boundary."""
    padding = (-len(value)) % 4
    return struct.pack("<HH", code, len(value)) + value + b"\x00" * padding


def _pcapng_block(block_type: int, body: bytes) -> bytes:
    """Wrap ``body`` in a pcapng block (total length is repeated at both ends).

    ``body`` must already be padded to a 4-byte boundary; every caller here
    builds it from fixed-size fields plus padded options or packet data.
    """
    total_length = len(body) + 12
    return (
        struct.pack("<II", block_type, total_length)
        + body
        + struct.pack("<I", total_length)
    )


class PcapFileWriter:
    """Write the capture to a ``.pcap``/``.pcapng`` file, alongside the pipe.

    The bridges already build a complete classic-PCAP record per packet (see
    ``protocol.common.Pcap``) and hand it to the Wireshark named pipe, where it
    is discarded when the session ends.  This sink takes the *same* records and
    also puts them on disk, so a capture can be re-opened with Wireshark, run
    through ``tshark``, shared, or kept as a regression fixture — and so the
    tool is usable headless over SSH, with no Wireshark and no pipe reader.

    The output format follows the file name: ``.pcapng`` produces a PCAPNG
    section (SHB + IDB + one EPB per packet), anything else a classic PCAP
    stream, byte-identical to what the pipe receives.  Records are flushed as
    they arrive so the growing file can be tailed live.

    ``path`` may be ``None``, in which case the writer is inert — the bridges
    construct one unconditionally and let :attr:`enabled` decide.
    """

    def __init__(self, path: str = None, linktype: int = 147, force: bool = False):
        self.path = path
        self.linktype = linktype
        self.packet_count = 0
        self.fh = None
        self.pcapng = bool(path) and path.lower().endswith(".pcapng")

        if not path:
            return

        # Unlike the raw/ascii logs, a capture file is truncated rather than
        # appended to: a second PCAP header (or PCAPNG section) landing in the
        # middle of an existing file yields something no dissector will read
        # past.  So an existing file blocks the capture unless --force is given.
        #
        # The message belongs to the caller (``sniff`` runs the same check up
        # front, via refuse_overwrite, so it can abort before flashing the
        # device); this raises quietly rather than warning a second time.
        if os.path.exists(path) and not force:
            raise FileExistsError(path)

        self.fh = open(path, "wb")
        self.fh.write(self._file_header())
        self.fh.flush()
        print_success(
            f"Writing {'PCAPNG' if self.pcapng else 'PCAP'} capture to {path}"
        )

    @property
    def enabled(self) -> bool:
        return self.fh is not None

    # ── Headers ──────────────────────────────────────────────────────────────

    def _file_header(self) -> bytes:
        if not self.pcapng:
            return get_global_header(self.linktype)
        return self._shb() + self._idb()

    def _shb(self) -> bytes:
        options = _pcapng_option(
            _PCAPNG_OPT_SHB_USERAPPL, f"catnip {__version__}".encode("utf-8")
        ) + _pcapng_option(_PCAPNG_OPT_ENDOFOPT, b"")
        body = (
            struct.pack("<IHH", _PCAPNG_BYTE_ORDER_MAGIC, 1, 0)
            + struct.pack("<q", _PCAPNG_SECTION_LENGTH_UNKNOWN)
            + options
        )
        return _pcapng_block(_PCAPNG_SHB_TYPE, body)

    def _idb(self) -> bytes:
        options = _pcapng_option(_PCAPNG_OPT_IF_TSRESOL, b"\x06") + _pcapng_option(
            _PCAPNG_OPT_ENDOFOPT, b""
        )
        body = struct.pack("<HHI", self.linktype, 0, PCAP_MAX_PACKET_SIZE) + options
        return _pcapng_block(_PCAPNG_IDB_TYPE, body)

    @staticmethod
    def _epb(timestamp_us: int, captured: bytes, original_length: int) -> bytes:
        padding = (-len(captured)) % 4
        body = (
            struct.pack(
                "<IIIII",
                0,  # interface ID — the single interface from the IDB
                (timestamp_us >> 32) & 0xFFFFFFFF,
                timestamp_us & 0xFFFFFFFF,
                len(captured),
                original_length,
            )
            + captured
            + b"\x00" * padding
            + _pcapng_option(_PCAPNG_OPT_ENDOFOPT, b"")
        )
        return _pcapng_block(_PCAPNG_EPB_TYPE, body)

    # ── Packets ──────────────────────────────────────────────────────────────

    def write_record(self, record: bytes) -> None:
        """Append one packet, given the classic-PCAP record the pipe receives.

        For a ``.pcap`` file the bytes are written through untouched.  For a
        ``.pcapng`` file the record header is unpacked and re-emitted as an
        Enhanced Packet Block, so both formats carry the same timestamps.

        Write errors are reported once and disable the sink rather than killing
        the capture: a full disk should not cost the user the live session.
        """
        if not self.enabled:
            return
        try:
            if self.pcapng:
                (ts_sec, ts_usec, caplen, origlen) = struct.unpack_from(
                    PCAP_PACKET_HEADER_FORMAT, record
                )
                payload = record[
                    PCAP_PACKET_HEADER_LEN : PCAP_PACKET_HEADER_LEN + caplen
                ]
                self.fh.write(self._epb(ts_sec * 1_000_000 + ts_usec, payload, origlen))
            else:
                self.fh.write(record)
            self.fh.flush()
            self.packet_count += 1
        except (OSError, struct.error) as exc:
            print_warning(f"Capture file write failed ({exc}) — disabling {self.path}")
            self.close(summary=False)

    def close(self, summary: bool = True) -> None:
        if self.fh is None:
            return
        try:
            self.fh.close()
        except Exception:
            pass
        self.fh = None
        if summary:
            print_success(f"Saved {self.packet_count} packet(s) to {self.path}")


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────


# The Cat-Shell port echoes back every byte it receives (cdc2_interrupt_handler
# in the RP2040 firmware), so a reply always arrives with the command in front
# of it.  Left in place, that echo defeats every test on the reply text:
# "STREAM" is found in the echo of `lora_mode stream` whether or not the
# firmware accepted it, and a refused setting reads as an accepted one.
def _shell_reply(response: str, command: str) -> str:
    """The firmware's answer to ``command``, with the echoed command removed.

    Returns "" when nothing but the echo came back — a command that went
    unanswered — and the response untouched when the echo is absent or only
    partial, so a firmware that does not echo is read exactly as it is.
    """
    if response is None:
        return ""
    text = response.strip()
    if text.startswith(command):
        text = text[len(command) :]
    return text.strip()


# How the RP2040 shell opens a line when it refuses a command: ``Error:`` or
# ``ERROR:`` for a rejected value or a failed apply, ``Usage:`` when the
# argument did not parse at all, and ``Unknown command`` for a name this
# firmware build does not have.
_SHELL_ERROR_PREFIXES = ("error", "usage:", "unknown command")


def _shell_error(reply: str) -> str:
    """The first line of ``reply`` that reports a failure, or "" if none does.

    Line by line rather than over the whole reply: applying a configuration
    answers with several lines, and the one that failed is not always first.
    """
    for line in reply.splitlines():
        line = line.strip()
        if line.lower().startswith(_SHELL_ERROR_PREFIXES):
            return line
    return ""


def _send_config_steps(shell: ShellConnection, steps: list) -> bool:
    """Send ``(label, command)`` pairs to Cat-Shell, echoing each reply.

    Returns True when every command was answered and none was refused.  A
    command that fails is reported and the rest are still sent: one lost reply
    on a busy USB CDC link — or one setting the firmware would not take — is
    not a reason to leave the radio half-configured.
    """
    all_ok = True
    for label, cmd in steps:
        reply = _shell_reply(shell.send_command(cmd, timeout=1.5), cmd)
        error = _shell_error(reply)

        if not reply:
            print_warning(f"No response while setting {label}")
            all_ok = False
        elif error:
            print_warning(f"Firmware refused the {label}: {error}")
            all_ok = False
        else:
            # Joined rather than cut to the first line: an apply answers with
            # several, and the one worth seeing — a "WARN: FSK BW too narrow"
            # the firmware silently corrected — is never the first of them.
            summary = " | ".join(
                line.strip() for line in reply.splitlines() if line.strip()
            )
            print_dim(f"{label}: {summary[:100]}")
        time.sleep(_SHELL_CMD_DELAY)

    return all_ok


def select_rf_band(shell_port: str, command: str, label: str) -> bool:
    """Point the shared antenna switch at the radio this capture will use.

    For the captures that never otherwise talk to Cat-Shell — the TI sniffer
    drives ``bridge_port``, Sniffle is driven by its own extcap plugin — so the
    config port is opened for this one command and closed again.

    Never fatal.  A capture on the wrong antenna path still runs, it just sees
    fewer and weaker packets, which is precisely the silent failure this call
    exists to prevent; refusing to capture at all would be the worse trade.
    Returns True when the firmware acknowledged the band.
    """
    if not shell_port:
        print_warning(f"No config port — cannot select the {label} antenna path")
        return False

    shell = ShellConnection(shell_port)
    if not shell.connect():
        print_warning(
            f"Could not open the config port — cannot select the {label} antenna path"
        )
        return False

    try:
        return _send_config_steps(shell, [(f"RF switch ({label})", command)])
    finally:
        shell.disconnect()


# ──────────────────────────────────────────────────────────────────────────────
# Capture integrity: what the firmware knows it dropped
# ──────────────────────────────────────────────────────────────────────────────
#
# The firmware counts two ways the CC1352 stream can lose bytes before they
# ever reach this host (``cc1352_uart_interrupt_handler`` in the firmware's
# ``main.c``): a hardware UART FIFO overrun, and bytes that did not fit in the
# ``rb_cc1352_to_usb`` ring. ``status`` has always reported both and this tool
# never read them, so a capture came with no evidence of its own completeness
# — and at 921600 baud a busy Zigbee/Thread channel does overflow that ring.
#
# Scope is exactly the captures that read from ``bridge_port``: the TI sniffer,
# Sniffle, the AirTag scanner. A LoRa/FSK capture arrives on the SX1262's own
# CDC and never touches that ring, so these counters would sit at zero there
# for the wrong reason — a counter that stayed at zero because nothing flowed
# through it is not evidence that anything was complete, and reporting it as
# such would be the exact false assurance this is meant to remove.

_LOSS_RESET_CMD = "loss_reset"

# Each counter in its own unit, because they are not the same kind of number:
# ring_dropped is bytes actually counted, uart_overrun is FIFO events whose
# byte cost is unknown, and dma_regress (v2 only) is a driver-level anomaly.
_LOSS_UNITS = {
    "ring_dropped": "{value} byte(s) dropped from the bridge ring buffer",
    "uart_overrun": "{value} UART FIFO overrun(s), of unknown size each",
    "dma_regress": "{value} DMA progress regression(s)",
}


def reset_loss_counters(shell_port: str) -> bool:
    """Zero the firmware's loss counters so this capture starts from a known 0.

    Returns True when the firmware acknowledged. False is never fatal: the
    capture runs either way, it only means the closing report will say the
    integrity of this capture is unknown instead of claiming zero loss.
    """
    if not shell_port:
        return False

    shell = ShellConnection(shell_port)
    try:
        if not shell.connect():
            return False
        reply = _shell_reply(
            shell.send_command(_LOSS_RESET_CMD, timeout=2.0), _LOSS_RESET_CMD
        )
        # An empty reply is a command that went unanswered, and an error line
        # is a firmware build without ``loss_reset``. Both mean the counters
        # may still hold whatever a previous capture left in them.
        return bool(reply) and not _shell_error(reply)
    except Exception:
        return False
    finally:
        try:
            shell.disconnect()
        except Exception:
            pass


def describe_loss(counters: dict) -> tuple:
    """``(clean, message)`` for a set of loss counters.

    ``clean`` is True only when every counter the firmware reported is zero —
    the one case in which "nothing was lost" is a statement about evidence
    rather than about the absence of it.
    """
    if not counters:
        return False, "the firmware reported no loss counters"

    lost = {name: value for name, value in counters.items() if value}
    if not lost:
        readings = ", ".join(f"{name}={value}" for name, value in counters.items())
        return True, f"0 bytes lost ({readings})"

    detail = "; ".join(
        _LOSS_UNITS.get(name, "{value} " + name).format(value=value)
        for name, value in lost.items()
    )
    return False, detail


def report_capture_loss(shell_port: str, armed: bool) -> None:
    """Close a capture by saying, in the firmware's own numbers, what it lost.

    ``armed`` is what :func:`reset_loss_counters` returned at the start: without
    that reset the counters may carry another session's losses, so the honest
    answer is that this capture was not measured, not that it was clean.
    """
    if not armed:
        print_dim(
            "Capture integrity: not measured "
            "(the loss counters could not be reset when the capture started)"
        )
        return

    try:
        counters = read_loss_counters(shell_port)
    except KeyboardInterrupt:
        # A second Ctrl+C during the closing query: stop, do not claim a result.
        print_dim("Capture integrity: check interrupted")
        return

    if counters is None:
        print_warning(
            "Capture integrity unknown — the board did not answer `status` "
            "at the end of the capture"
        )
        return

    clean, detail = describe_loss(counters)
    if clean:
        print_success(f"Capture integrity: {detail}")
    else:
        print_warning(f"Capture integrity: {detail}")
        print_dim(
            "Treat this capture as incomplete: data was dropped before it "
            "reached this host, so packets may be missing or truncated."
        )


def _configure_lora(
    shell: ShellConnection,
    frequency: int,
    bandwidth: int,
    spread_factor: int,
    coding_rate: int,
    tx_power: int,
    sync_word: str = "private",
    preamble: int = 12,
    iq: str = "normal",
) -> bool:
    """
    Send all LoRa configuration commands via Cat-Shell and apply them.

    Returns True when every command was answered and none was refused.
    """
    steps = [
        # The RF switch comes first: the firmware boots it on the CC1352's
        # 2.4GHz port, so without this the SX1262 is configured correctly and
        # then listens through the wrong antenna path.
        ("RF switch", sx1262_band_command()),
        # The modulation is selected next because an earlier `sniff fsk` left
        # the firmware with lora_initialized = false, and apply_lora_config()
        # refuses to run in that state — `lora_apply` alone would answer
        # "LoRa not initialized" and the capture would come up silent.
        ("modulation", modulation_command("lora")),
        ("frequency", snifferSxCmd.set_freq(frequency)),
        ("bandwidth", snifferSxCmd.set_bw(bandwidth)),
        ("spread factor", snifferSxCmd.set_sf(spread_factor)),
        ("coding rate", snifferSxCmd.set_cr(coding_rate)),
        ("TX power", snifferSxCmd.set_power(tx_power)),
        ("sync word", snifferSxCmd.set_syncword(sync_word)),
        ("preamble", snifferSxCmd.set_preamble(preamble)),
        ("IQ", snifferSxCmd.set_iq(iq)),
        ("apply", snifferSxCmd.apply_config()),
    ]

    return _send_config_steps(shell, steps)


def _configure_fsk(
    shell: ShellConnection,
    frequency: int,
    bitrate: int,
    fdev: int,
    bandwidth: str,
    tx_power: int,
    preamble: int,
    sync_word: str,
    crc: bool,
    whitening: bool,
    pktlen: str,
    payload: int,
    bt: str,
) -> bool:
    """
    Send all (G)FSK configuration commands via Cat-Shell and apply them.

    Returns True when every command was answered and none was refused.
    """
    steps = [
        # See _configure_lora: the antenna path has to be switched to the
        # SX1262 before any of this matters.
        ("RF switch", sx1262_band_command()),
        ("frequency", snifferSxFskCmd.set_freq(frequency)),
        ("bitrate", snifferSxFskCmd.set_bitrate(bitrate)),
        ("deviation", snifferSxFskCmd.set_fdev(fdev)),
        ("RX bandwidth", snifferSxFskCmd.set_bw(bandwidth)),
        ("TX power", snifferSxFskCmd.set_power(tx_power)),
        ("BT shaping", snifferSxFskCmd.set_bt(bt)),
        ("preamble", snifferSxFskCmd.set_preamble(preamble)),
        ("sync word", snifferSxFskCmd.set_syncword(sync_word)),
        ("packet length", snifferSxFskCmd.set_pktlen(pktlen)),
        ("payload length", snifferSxFskCmd.set_payload(payload)),
        ("CRC", snifferSxFskCmd.set_crc(crc)),
        ("whitening", snifferSxFskCmd.set_whitening(whitening)),
        # `modulation fsk` rather than `fsk_apply`: both end in
        # apply_fsk_config(), but switch_to_fsk() also stops LoRa reception
        # first, and it applies unconditionally — `fsk_apply` is a no-op when
        # the firmware thinks nothing is pending, which would leave the radio
        # in whatever modulation the last session chose.
        ("modulation", modulation_command("fsk")),
    ]

    return _send_config_steps(shell, steps)


def _stop_lora_capture(
    shell: ShellConnection,
    lora: LoRaConnection,
    pipe,
) -> None:
    """
    Switch the RP2040 back to command mode, close ports, and remove the pipe.
    Called from both the normal exit path and any early error path.
    """
    print_info("Switching RP2040 back to command mode...")
    try:
        if shell.connection is None:
            shell.connect()
        stop_cmd = snifferSxCmd.start_command()
        reply = _shell_reply(shell.send_command(stop_cmd, timeout=2.0), stop_cmd)
        # Both halves matter: the firmware quotes the mode names back in its
        # own rejection ("Error: Mode must be 'stream' or 'command'"), so the
        # word alone is not proof the mode was taken.
        if "COMMAND" in reply.upper() and not _shell_error(reply):
            print_success("Command mode restored")
        else:
            print_warning(f"Response to stop: {reply!r}")
    except Exception as exc:
        print_warning(f"Could not restore command mode: {exc}")
    finally:
        for conn in (shell, lora):
            try:
                conn.disconnect()
            except Exception:
                pass
        try:
            pipe.remove()
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# SX1262 session report
# ──────────────────────────────────────────────────────────────────────────────
#
# The SX1262 stream never touches the CC1352 bridge ring buffer, so
# report_capture_loss (above) does not apply to it — that is by design, not
# an oversight. But ``_run_sx_capture`` already computes its own numbers
# (packet/error counts, RSSI/SNR per packet) and used to discard all but the
# error count, which was only ever printed on Ctrl+C. This closes every exit
# path — Ctrl+C, a closed port, a serial error — with what was actually seen.


def _describe_quality(label: str, values: list, unit: str) -> str:
    """``"RSSI: min=-92.0 dBm  median=-80.0 dBm  max=-61.0 dBm"``, or a note
    that nothing was captured to measure."""
    if not values:
        return f"{label}: n/a (no packets)"
    return (
        f"{label}: min={min(values):.1f}{unit}  "
        f"median={statistics.median(values):.1f}{unit}  "
        f"max={max(values):.1f}{unit}"
    )


def print_sx_session_report(
    modulation: str,
    packet_count: int,
    error_count: int,
    unrecognized_count: int,
    truncated_count: int,
    duration_s: float,
    rssi_values: list,
    snr_values: list,
) -> None:
    """Close an SX1262 (LoRa/FSK) capture with what this session measured.

    Unlike ``report_capture_loss``, everything here comes from the host side
    of the stream — the SX1262 has no ring buffer of its own to ask — so this
    is a summary of what arrived, not a statement about what was lost.
    """
    minutes = duration_s / 60 if duration_s > 0 else 0
    rate = packet_count / minutes if minutes > 0 else 0.0

    print_success(f"{modulation} session report")
    print_dim(f"Duration:            {duration_s:.1f}s")
    print_dim(f"Packets:             {packet_count} ({rate:.1f} pkt/min)")
    print_dim(f"Parse errors:        {error_count}")
    print_dim(f"Unrecognized lines:  {unrecognized_count}")
    print_dim(f"Truncated lines:     {truncated_count}")
    print_dim(_describe_quality("RSSI", rssi_values, " dBm"))
    if snr_values:
        print_dim(_describe_quality("SNR", snr_values, " dB"))


# ──────────────────────────────────────────────────────────────────────────────
# SX1262 bridge (LoRa and FSK)
# ──────────────────────────────────────────────────────────────────────────────


def _run_sx_capture(
    device: CatSnifferDevice,
    configure,
    context: dict,
    summary: list,
    modulation: str = "LoRa",
    wireshark: bool = False,
    verbose: bool = False,
    raw_file: str = None,
    ascii_file: str = None,
    pcap_file: str = None,
    force: bool = False,
    wireshark_args: list = None,
):
    """Configure the SX1262 and stream what it receives, in either modulation.

    Data flow
    ─────────
    Cat-Shell ← configuration commands (lora_freq…/fsk_freq…, modulation)
    Cat-LoRa  → received frames as ASCII text lines:
                    "LORA RX: <HEX> | RSSI: <int> | SNR: <int>\\r\\n"
                    "FSK RX: <HEX> | RSSI: <int> | Len: <int>\\r\\n"

    Everything below the radio settings is shared: each line is parsed by
    SnifferSx.Packet, turned into a LoRaTap record and written to the named
    pipe Wireshark reads, to the capture file and to the text logs.  So LoRa
    and FSK differ only in ``configure`` — which shell commands set the modem
    up — and in ``context``, what the LoRaTap header should then claim.

    The RP2040 starts in STREAM mode by default, so the lora_thread wakes on
    the semaphore; ``lora_mode stream`` is sent explicitly after configuration
    to be safe.  It governs both modulations, the firmware keeps only the one
    mode flag.

    Args:
        device:        CatSnifferDevice with shell_port and lora_port.
        configure:     Called with the open ShellConnection; returns False when
                       a configuration command went unanswered or was refused
                       by the firmware.
        context:       Radio settings handed to SnifferSx.Packet for the
                       LoRaTap header.
        summary:       ``(label, value)`` pairs echoed before configuring.
        modulation:    Name used in the progress messages ("LoRa" / "FSK").
        wireshark:     Launch Wireshark when True.
        verbose:       Show packet output in terminal when True.
        raw_file:      Path to append packets as raw hex, or None to disable.
        ascii_file:    Path to append packets as decoded ASCII, or None to disable.
        pcap_file:     Path to write the capture as .pcap/.pcapng, or None to disable.
        force:         Overwrite pcap_file when it already exists.
        wireshark_args: Extra Wireshark command-line arguments, e.g. the ``-d``
                       decode-as rule built by ``lora_decode_as_args``.

    Returns:
        The number of packets captured, or None when the bridge could not be
        started (bad ports, unwritable capture file, no Wireshark on the pipe).
        ``sniff lora``/``sniff fsk`` use it to decide whether there is a capture
        worth opening in Wireshark once the session ends.
    """

    # ── 1. Validate ports ────────────────────────────────────────────────────
    if not device.shell_port:
        print_error(f"No shell_port on device — cannot configure {modulation}")
        return
    if not device.lora_port:
        print_error(f"No lora_port on device — cannot receive the {modulation} stream")
        return

    # ── 2. Open the capture file first: a refused overwrite must abort before
    #       the pipe, the ports and the RP2040 configuration are touched. ─────
    try:
        pcap_writer = PcapFileWriter(pcap_file, LORATAP_DLT, force)
    except (FileExistsError, OSError) as exc:
        print_error(f"Cannot write capture file: {exc}")
        return

    # ── 3. Set up PCAP pipe ───────────────────────────────────────────────────
    pipe = WindowsPipe() if platform.system() == "Windows" else UnixPipe()
    threading.Thread(target=pipe.open, daemon=True).start()

    if wireshark:
        Wireshark(extra_args=wireshark_args).start()

    # ── 4. Open shell and configure ───────────────────────────────────────────
    shell = ShellConnection(port=device.shell_port)
    if not shell.connect():
        print_error(f"Cannot open shell port: {device.shell_port}")
        pcap_writer.close(summary=False)
        pipe.remove()
        return

    print_info(f"Configuring {modulation} via {device.shell_port}...")
    for label, value in summary:
        print_dim(f"{label:<18}{value}")

    if not configure(shell):
        print_warning("Some settings were not confirmed by the firmware — continuing")

    # ── 5. Open Cat-LoRa data port ────────────────────────────────────────────
    lora = LoRaConnection(port=device.lora_port)
    if not lora.connect():
        print_error(f"Cannot open LoRa port: {device.lora_port}")
        pcap_writer.close(summary=False)
        shell.disconnect()
        pipe.remove()
        return

    # Flush any welcome banner the firmware sends on connect
    time.sleep(0.3)
    try:
        lora.connection.reset_input_buffer()
    except Exception:
        pass

    # ── 6. Switch to stream mode ──────────────────────────────────────────────
    # NOTE: Do NOT write bytes to CDC1 afterwards — in stream mode the RP2040
    # lora_thread treats anything on rb_usb_to_sx1262 as payload to transmit,
    # which stops RX for the duration of that TX.  No host-side keepalive is
    # needed either: the thread loops on k_sem_take(K_MSEC(100)) and re-arms
    # reception on its own.
    print_info("Switching RP2040 to stream mode...")
    stream_cmd = snifferSxCmd.start_streaming()
    stream_reply = _shell_reply(shell.send_command(stream_cmd, timeout=2.0), stream_cmd)
    if "STREAM" in stream_reply.upper() and not _shell_error(stream_reply):
        print_success("Stream mode active")
    else:
        print_warning(f"Unexpected stream response: {stream_reply!r} — continuing")

    # ── 7. Wait for Wireshark ─────────────────────────────────────────────────
    if wireshark:
        print_info(f"Waiting for Wireshark (timeout {_WIRESHARK_PIPE_TIMEOUT}s)...")
        if not pipe.ready_event.wait(timeout=_WIRESHARK_PIPE_TIMEOUT):
            print_error("Timed out waiting for Wireshark — aborting")
            pcap_writer.close(summary=False)
            _stop_lora_capture(shell, lora, pipe)
            return

    # ── 8. Streaming loop ─────────────────────────────────────────────────────
    # Determine if we should show verbose output
    # Show output if verbose is True OR if wireshark is False (default behavior)
    show_output = verbose or not wireshark

    if show_output:
        print_success("Capture running — press Ctrl+C to stop")

    # ── Open log files (append) if requested ──────────────────────────────────
    log_writer = PacketLogWriter(raw_file, ascii_file)

    header_written = False
    packet_count = 0
    error_count = 0
    unrecognized_count = 0
    truncated_count = 0
    rssi_values = []
    snr_values = []
    start_time = time.monotonic()

    try:
        while True:
            # Check if connection is still alive before reading
            if not lora.connection or not lora.connection.is_open:
                print_warning("LoRa port closed — device disconnected")
                break

            # readline() returns when it sees \n or after the serial timeout.
            # LoRaConnection.STREAM_TIMEOUT = 0.5 s, so this never blocks long.
            # Bounded to DEFAULT_READLINE_MAX_BYTES since this bypasses the
            # LoRaConnection wrapper (raw .connection access) and would
            # otherwise grow unbounded against a noisy stream with no '\n'.
            try:
                raw = lora.connection.readline(DEFAULT_READLINE_MAX_BYTES)
            except serial.SerialException as exc:
                print_warning(f"Serial error (device disconnected?): {exc}")
                break

            if not raw:
                continue

            # A line that hit the bound without ever finding '\n' — the
            # firmware output ran longer than a real "RX: ..." line ever
            # does, so this is corruption on the wire, not a slow write.
            if len(raw) >= DEFAULT_READLINE_MAX_BYTES and not raw.endswith(b"\n"):
                truncated_count += 1

            # Skip lines that are not packet data
            stripped = raw.strip()
            if not stripped:
                continue
            if _LORA_LINE_PREFIX not in stripped:
                if not any(stripped.startswith(p) for p in _IGNORE_PREFIXES):
                    print_dim(f"(device) {stripped.decode('ascii', errors='replace')}")
                    unrecognized_count += 1
                continue

            try:
                packet = snifferSx.Packet(raw, context=context)

                if not header_written:
                    pipe.write_packet(get_global_header(LORATAP_DLT))
                    header_written = True

                pipe.write_packet(packet.pcap)
                # Same record, second destination: the file survives the session.
                pcap_writer.write_record(packet.pcap)
                packet_count += 1

                rssi_values.append(packet.rssi)
                if not packet.is_fsk:
                    snr_values.append(packet.snr)

                # Persist only the relevant fields to the log file(s).
                # LoRa carries both RSSI and SNR; an FSK frame is reported
                # without one, so logging "SNR: 0" would invent a measurement.
                meta = f"RSSI: {int(packet.rssi)}"
                if not packet.is_fsk:
                    meta += f" | SNR: {int(packet.snr)}"
                log_writer.write(packet.payload, meta=meta)

                if show_output:
                    ascii_str = "".join(
                        chr(b) if 32 <= b < 127 else "." for b in packet.payload
                    )
                    hex_str = packet.payload.hex()
                    quality = f"RSSI={packet.rssi:>7.1f} dBm"
                    if not packet.is_fsk:
                        quality += f"  SNR={packet.snr:>5.1f} dB"
                    console.print(
                        f"[green]  [{packet_count:>5}][/green] "
                        f"len={packet.length:>4}B  "
                        f"{quality}\n"
                        f"         hex={hex_str}\n"
                        f"         ascii=[italic]{ascii_str}[/italic]"
                    )

            except ValueError as exc:
                error_count += 1
                print_warning(f"Parse error #{error_count}: {exc} — raw: {raw[:80]!r}")
            except Exception as exc:
                error_count += 1
                print_warning(f"Unexpected error #{error_count}: {exc}")

    except KeyboardInterrupt:
        print_info("Capture stopped")
    finally:
        log_writer.close()
        pcap_writer.close()
        _stop_lora_capture(shell, lora, pipe)
        # Every exit path — Ctrl+C, a closed port, a serial error — ends with
        # the same statement about what this session actually captured.
        print_sx_session_report(
            modulation,
            packet_count,
            error_count,
            unrecognized_count,
            truncated_count,
            time.monotonic() - start_time,
            rssi_values,
            snr_values,
        )

    return packet_count


def run_sx_bridge(
    device: CatSnifferDevice,
    frequency: int,
    bandwidth: int,
    spread_factor: int,
    coding_rate: int,
    tx_power: int = 20,
    wireshark: bool = False,
    verbose: bool = False,
    sync_word: str = "private",
    preamble: int = 12,
    iq: str = "normal",
    raw_file: str = None,
    ascii_file: str = None,
    pcap_file: str = None,
    force: bool = False,
    wireshark_args: list = None,
):
    """Run the LoRa sniffer bridge for the unified RP2040 firmware.

    Args:
        device:        CatSnifferDevice with shell_port and lora_port.
        frequency:     Hz  (e.g. 915_000_000).
        bandwidth:     kHz (125, 250 or 500).
        spread_factor: 7–12.
        coding_rate:   5–8.
        tx_power:      dBm.
        wireshark:     Launch Wireshark when True.
        verbose:       Show packet output in terminal when True.
        sync_word:     "private", "public" or a raw byte such as "0x2B".
        preamble:      Preamble length in symbols (6-65535).
        iq:            "normal" or "inverted" (LoRaWAN downlinks use inverted).
        raw_file:      Path to append packets as raw hex, or None to disable.
        ascii_file:    Path to append packets as decoded ASCII, or None to disable.
        pcap_file:     Path to write the capture as .pcap/.pcapng, or None to disable.
        force:         Overwrite pcap_file when it already exists.
        wireshark_args: Extra Wireshark command-line arguments, e.g. the ``-d``
                       decode-as rule built by ``lora_decode_as_args``.

    Returns:
        See :func:`_run_sx_capture`, which does the work from here on.
    """
    return _run_sx_capture(
        device,
        configure=lambda shell: _configure_lora(
            shell,
            frequency,
            bandwidth,
            spread_factor,
            coding_rate,
            tx_power,
            sync_word,
            preamble,
            iq,
        ),
        context={
            "frequency": frequency,
            "bandwidth": bandwidth,
            "spread_factor": spread_factor,
            "coding_rate": coding_rate,
            "sync_word": sync_word,
            "preamble": preamble,
            "iq": iq,
        },
        summary=[
            ("Frequency:", f"{frequency / 1e6:.3f} MHz"),
            ("Bandwidth:", f"{bandwidth} kHz"),
            ("Spreading Factor:", f"SF{spread_factor}"),
            ("Coding Rate:", f"4/{coding_rate}"),
            ("TX Power:", f"{tx_power} dBm"),
            ("Sync Word:", sync_word),
            ("Preamble:", f"{preamble} symbols"),
            ("IQ:", iq),
        ],
        modulation="LoRa",
        wireshark=wireshark,
        verbose=verbose,
        raw_file=raw_file,
        ascii_file=ascii_file,
        pcap_file=pcap_file,
        force=force,
        wireshark_args=wireshark_args,
    )


def run_fsk_bridge(
    device: CatSnifferDevice,
    frequency: int,
    bitrate: int = 50000,
    fdev: int = 25000,
    bandwidth: str = "187.2",
    tx_power: int = 14,
    preamble: int = 8,
    sync_word: str = "12AD",
    crc: bool = False,
    whitening: bool = False,
    pktlen: str = "variable",
    payload: int = 255,
    bt: str = "0.5",
    wireshark: bool = False,
    verbose: bool = False,
    raw_file: str = None,
    ascii_file: str = None,
    pcap_file: str = None,
    force: bool = False,
    wireshark_args: list = None,
):
    """Run the (G)FSK sniffer bridge for the unified RP2040 firmware.

    Same radio, same ports and same stream as :func:`run_sx_bridge` — the
    SX1262 is simply put in FSK mode, where it demodulates the sub-GHz traffic
    LoRa cannot see: 802.15.4g/Wi-SUN, many proprietary ISM links, and the
    FSK side of Meshtastic.  The firmware reports those frames on Cat-LoRa as
    "FSK RX: <HEX> | RSSI: <int> | Len: <int>".

    Args:
        device:      CatSnifferDevice with shell_port and lora_port.
        frequency:   Hz (137-1020 MHz).
        bitrate:     bps (600-300000).
        fdev:        Frequency deviation in Hz (600-200000).
        bandwidth:   RX bandwidth in kHz, one of ``FSK_BANDWIDTHS``.
        tx_power:    dBm (-9 to 22).
        preamble:    Preamble length in *bytes* (FSK counts bytes, not symbols).
        sync_word:   Up to 8 sync-word bytes as hex, e.g. "2DD4".
        crc:         Let the modem check the CRC and drop failing frames.
        whitening:   Undo the transmitter's data whitening.
        pktlen:      "variable" (length from the packet header) or "fixed".
        payload:     Payload length for "fixed", maximum length for "variable".
        bt:          Gaussian filter BT: "off" (plain FSK) or 0.3/0.5/0.7/1.0.

    The remaining arguments and the return value are those of
    :func:`run_sx_bridge`.
    """
    return _run_sx_capture(
        device,
        configure=lambda shell: _configure_fsk(
            shell,
            frequency,
            bitrate,
            fdev,
            bandwidth,
            tx_power,
            preamble,
            sync_word,
            crc,
            whitening,
            pktlen,
            payload,
            bt,
        ),
        # Only the frequency means anything to a LoRaTap header here; the
        # bandwidth/SF/sync-word fields are written as "unknown" by
        # SnifferSx.Packet for an FSK frame rather than filled with LoRa
        # settings the radio was never using.
        context={"frequency": frequency},
        summary=[
            ("Frequency:", f"{frequency / 1e6:.3f} MHz"),
            ("Bitrate:", f"{bitrate} bps"),
            ("Deviation:", f"{fdev} Hz"),
            ("RX Bandwidth:", f"{bandwidth} kHz"),
            ("TX Power:", f"{tx_power} dBm"),
            ("Gaussian BT:", bt),
            ("Preamble:", f"{preamble} bytes"),
            ("Sync Word:", sync_word),
            ("Packet Length:", pktlen),
            ("Payload:", f"{payload} bytes"),
            ("CRC:", "on" if crc else "off"),
            ("Whitening:", "on" if whitening else "off"),
        ],
        modulation="FSK",
        wireshark=wireshark,
        verbose=verbose,
        raw_file=raw_file,
        ascii_file=ascii_file,
        pcap_file=pcap_file,
        force=force,
        wireshark_args=wireshark_args,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Zigbee / Thread (TI CC1352) bridge — unchanged
# ──────────────────────────────────────────────────────────────────────────────


def run_bridge(
    device: CatSnifferDevice,
    channel: int = 11,
    wireshark: bool = False,
    profile: str = None,
    raw_file: str = None,
    ascii_file: str = None,
    pcap_file: str = None,
    force: bool = False,
):
    """Run TI sniffer bridge for Zigbee/Thread.

    Args:
        device:     CatSnifferDevice with bridge_port.
        channel:    IEEE 802.15.4 channel (11-26).
        wireshark:  Launch Wireshark when True.
        profile:    Wireshark profile name.
        raw_file:   Path to append packets as raw hex, or None to disable.
        ascii_file: Path to append packets as decoded ASCII, or None to disable.
        pcap_file:  Path to write the capture as .pcap/.pcapng, or None to disable.
        force:      Overwrite pcap_file when it already exists.
    """
    # Opened first so a refused overwrite aborts before the pipe, the serial
    # port and the sniffer configuration are touched.
    try:
        pcap_writer = PcapFileWriter(pcap_file, force=force)
    except (FileExistsError, OSError) as exc:
        print_error(f"Cannot write capture file: {exc}")
        return

    pipe = WindowsPipe() if platform.system() == "Windows" else UnixPipe()
    opening_worker = threading.Thread(target=pipe.open, daemon=True)

    if wireshark:
        Wireshark(profile=profile).start()

    opening_worker.start()

    # The antenna switch is shared with the SX1262 and keeps its position
    # across sessions, so a Zigbee/Thread capture started after `sniff lora`
    # would listen through the LoRa leg unless it asks for its own band.
    select_rf_band(device.shell_port, cc1352_band_command(), "2.4 GHz")

    # From here on the firmware counts what it drops on the way to this host,
    # and the closing report reads it back. Done after the band selection so
    # the two config-port sessions do not overlap.
    loss_armed = reset_loss_counters(device.shell_port)

    serial_worker = Catnip(port=device.bridge_port)
    serial_worker.connect()

    for cmd in snifferTICmd.get_startup_cmd(channel):
        serial_worker.write(cmd)
        time.sleep(0.1)

    if wireshark:
        print_info("Waiting for Wireshark to open the pipe...")
        pipe.ready_event.wait()

    # ── Open log files (append) if requested ──────────────────────────────────
    log_writer = PacketLogWriter(raw_file, ascii_file)

    # Show packets in the terminal when Wireshark is not driving the capture,
    # mirroring the LoRa bridge behaviour.
    show_output = not wireshark
    if show_output:
        print_success("Capture running — press Ctrl+C to stop")

    header_flag = False
    packet_count = 0

    # Both sinks are closed on every exit path — Ctrl+C, a closed port or a
    # serial error — so the capture file is never left open behind a break.
    try:
        while True:
            try:
                # Check if connection is still alive before reading
                if not serial_worker.connection or not serial_worker.connection.is_open:
                    print_warning("Serial port closed — device disconnected")
                    break

                try:
                    data = serial_worker.read_until((END_OF_FRAME + START_OF_FRAME))
                except serial.SerialException as exc:
                    print_warning(f"Serial error (device disconnected?): {exc}")
                    break

                if data:
                    ti_packet = sniffer.Packet((START_OF_FRAME + data), channel)
                    if (
                        ti_packet.category
                        == PacketCategory.DATA_STREAMING_AND_ERROR.value
                    ):
                        if not header_flag:
                            header_flag = True
                            pipe.write_packet(get_global_header())
                        pipe.write_packet(ti_packet.pcap)
                        # Same record, second destination: the file survives the session.
                        pcap_writer.write_record(ti_packet.pcap)
                        packet_count += 1

                        # 802.15.4 (Zigbee/Thread) carries RSSI but no SNR; the TI
                        # firmware reports RSSI as a signed 8-bit dBm value.
                        rssi = ti_packet.rssi
                        rssi = rssi - 256 if rssi > 127 else rssi

                        # Persist only the relevant fields to the log file(s).
                        log_writer.write(ti_packet.payload, meta=f"RSSI: {rssi}")

                        # Terminal output: hex only (no ASCII), unlike LoRa.
                        if show_output:
                            console.print(
                                f"[green]  [{packet_count:>5}][/green] "
                                f"len={len(ti_packet.payload):>4}B  "
                                f"RSSI={rssi:>4} dBm\n"
                                f"         hex={ti_packet.payload.hex()}"
                            )
                time.sleep(0.1)
            except KeyboardInterrupt:
                print_info(f"Stopping TI capture — {packet_count} packet(s)")
                pipe.remove()
                opening_worker.join(timeout=1)
                serial_worker.write(snifferTICmd.stop())
                serial_worker.disconnect()
                break
    finally:
        log_writer.close()
        pcap_writer.close()
        # Every exit path — Ctrl+C, a closed port, a serial error — ends with
        # the same statement about how much of the stream survived.
        report_capture_loss(device.shell_port, loss_armed)


# ──────────────────────────────────────────────────────────────────────────────
# Legacy wrapper
# ──────────────────────────────────────────────────────────────────────────────


def run_sx_bridge_legacy(
    serial_worker: Catnip,
    frequency,
    bandwidth,
    spread_factor,
    coding_rate,
    sync_word,
    preamble_length,
    wireshark: bool = False,
    pcap_file: str = None,
    force: bool = False,
):
    """Legacy bridge — deprecated. Use run_sx_bridge(CatSnifferDevice, ...).

    ``pcap_file``/``force`` mirror :func:`run_sx_bridge` so a capture taken
    through the legacy path is still saved to disk rather than lost with the
    pipe.
    """
    print_warning("Warning: legacy bridge mode (deprecated)")

    try:
        pcap_writer = PcapFileWriter(pcap_file, LORATAP_DLT, force)
    except (FileExistsError, OSError) as exc:
        print_error(f"Cannot write capture file: {exc}")
        return

    pipe = WindowsPipe() if platform.system() == "Windows" else UnixPipe()
    threading.Thread(target=pipe.open, daemon=True).start()
    if wireshark:
        Wireshark().start()
    serial_worker.connect()

    serial_worker.write(bytes(f"set_freq {frequency}\r\n", "utf-8"))
    serial_worker.write(bytes(f"set_bw {bandwidth}\r\n", "utf-8"))
    serial_worker.write(bytes(f"set_sf {spread_factor}\r\n", "utf-8"))
    serial_worker.write(bytes(f"set_cr {coding_rate}\r\n", "utf-8"))
    serial_worker.write(bytes(f"set_pl {preamble_length}\r\n", "utf-8"))
    serial_worker.write(bytes(f"set_sw {sync_word}\r\n", "utf-8"))
    serial_worker.write(bytes(f"set_rx\r\n", "utf-8"))

    if wireshark:
        print_info("Waiting for Wireshark to open the pipe...")
        pipe.ready_event.wait()

    header_flag = False

    try:
        while True:
            try:
                # Check if connection is still alive before reading
                if not serial_worker.connection or not serial_worker.connection.is_open:
                    print_warning("Serial port closed — device disconnected")
                    break

                try:
                    data = serial_worker.readline()
                except serial.SerialException as exc:
                    print_warning(f"Serial error (device disconnected?): {exc}")
                    break

                if data and data.startswith(START_OF_FRAME):
                    packet = snifferSx.Packet(
                        (START_OF_FRAME + data),
                        context={
                            "frequency": frequency,
                            "bandwidth": bandwidth,
                            "spread_factor": spread_factor,
                            "coding_rate": coding_rate,
                            "sync_word": sync_word,
                        },
                    )
                    if not header_flag:
                        header_flag = True
                        pipe.write_packet(get_global_header(LORATAP_DLT))
                    pipe.write_packet(packet.pcap)
                    # Same record, second destination: the file survives the session.
                    pcap_writer.write_record(packet.pcap)
                time.sleep(0.5)
            except KeyboardInterrupt:
                serial_worker.disconnect()
                break
    finally:
        pcap_writer.close()

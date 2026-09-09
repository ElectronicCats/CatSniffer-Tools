import os
import time
import threading
import platform
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
from protocol.sniffer_sx import SnifferSx, LORATAP_DLT
from protocol.sniffer_ti import SnifferTI, PacketCategory
from protocol.common import (
    START_OF_FRAME,
    END_OF_FRAME,
    PCAP_MAX_PACKET_SIZE,
    PCAP_PACKET_HEADER_FORMAT,
    PCAP_PACKET_HEADER_LEN,
    get_global_header,
)

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

    Returns True if every command received a response.
    """
    steps = [
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

    all_ok = True
    for label, cmd in steps:
        response = shell.send_command(cmd, timeout=1.5)
        if response is None:
            print_warning(f"No response while setting {label}")
            all_ok = False
        else:
            print_dim(f"{label}: {response[:80]}")
        time.sleep(_SHELL_CMD_DELAY)

    return all_ok


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
        resp = shell.send_command(snifferSxCmd.start_command(), timeout=2.0)
        if resp is not None and "COMMAND" in resp.upper():
            print_success("Command mode restored")
        else:
            print_warning(f"Response to stop: {resp!r}")
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
# LoRa (SX1262 / RP2040) bridge
# ──────────────────────────────────────────────────────────────────────────────


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
):
    """
    Run the LoRa sniffer bridge for the unified RP2040 firmware.

    Data flow
    ─────────
    Cat-Shell ← configuration commands (lora_freq, lora_sf, lora_apply …)
    Cat-LoRa  → received packets as ASCII text lines:
                    "RX: <HEX> | RSSI: <int> | SNR: <int>\\r\\n"

    Each line is parsed by SnifferSx.Packet (text path), converted to a
    PCAP record, and written to a named pipe for Wireshark.

    The RP2040 starts in STREAM mode by default (see main.c:854) so the
    lora_thread wakes on the semaphore.  We send lora_mode stream explicitly
    after configuration to be safe, and also write a keepalive byte to
    CDC1 every few seconds so the lora_data_sem keeps firing.

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

    Returns:
        The number of packets captured, or None when the bridge could not be
        started (bad ports, unwritable capture file, no Wireshark on the pipe).
        ``sniff lora`` uses it to decide whether there is a capture worth
        opening in Wireshark once the session ends.
    """

    # ── 1. Validate ports ────────────────────────────────────────────────────
    if not device.shell_port:
        print_error("No shell_port on device — cannot configure LoRa")
        return
    if not device.lora_port:
        print_error("No lora_port on device — cannot receive LoRa stream")
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
        Wireshark().start()

    # ── 4. Open shell and configure ───────────────────────────────────────────
    shell = ShellConnection(port=device.shell_port)
    if not shell.connect():
        print_error(f"Cannot open shell port: {device.shell_port}")
        pcap_writer.close(summary=False)
        pipe.remove()
        return

    print_info(f"Configuring LoRa via {device.shell_port}...")
    print_dim(f"Frequency:        {frequency / 1e6:.3f} MHz")
    print_dim(f"Bandwidth:        {bandwidth} kHz")
    print_dim(f"Spreading Factor: SF{spread_factor}")
    print_dim(f"Coding Rate:      4/{coding_rate}")
    print_dim(f"TX Power:         {tx_power} dBm")
    print_dim(f"Sync Word:        {sync_word}")
    print_dim(f"Preamble:         {preamble} symbols")
    print_dim(f"IQ:               {iq}")

    if not _configure_lora(
        shell,
        frequency,
        bandwidth,
        spread_factor,
        coding_rate,
        tx_power,
        sync_word,
        preamble,
        iq,
    ):
        print_warning("Some config commands had no response — continuing")

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
    print_info("Switching RP2040 to stream mode...")
    stream_resp = shell.send_command(snifferSxCmd.start_streaming(), timeout=2.0)
    if stream_resp and "STREAM" in stream_resp.upper():
        print_success("Stream mode active")
    else:
        print_warning(f"Unexpected stream response: {stream_resp!r} — continuing")

    # ── 7. Keepalive thread ───────────────────────────────────────────────────
    # NOTE: Do NOT write bytes to CDC1 in stream mode — the RP2040 lora_thread
    # treats any data on rb_usb_to_sx1262 as payload to transmit, which calls
    # lora_stop_rx() and breaks reception for the duration of that TX.
    # The lora_thread already loops on k_sem_take(K_MSEC(100)), so it keeps
    # lora_start_rx_async() armed without any host-side stimulation.
    _keepalive_stop = threading.Event()

    def _keepalive():
        _keepalive_stop.wait()  # just block until the capture ends

    ka_thread = threading.Thread(target=_keepalive, daemon=True)
    ka_thread.start()

    # ── 8. Wait for Wireshark ─────────────────────────────────────────────────
    if wireshark:
        print_info(f"Waiting for Wireshark (timeout {_WIRESHARK_PIPE_TIMEOUT}s)...")
        if not pipe.ready_event.wait(timeout=_WIRESHARK_PIPE_TIMEOUT):
            print_error("Timed out waiting for Wireshark — aborting")
            _keepalive_stop.set()
            pcap_writer.close(summary=False)
            _stop_lora_capture(shell, lora, pipe)
            return

    # ── 9. Streaming loop ─────────────────────────────────────────────────────
    lora_context = {
        "frequency": frequency,
        "bandwidth": bandwidth,
        "spread_factor": spread_factor,
        "coding_rate": coding_rate,
        "sync_word": sync_word,
        "preamble": preamble,
        "iq": iq,
    }

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

            # Skip lines that are not packet data
            stripped = raw.strip()
            if not stripped:
                continue
            if _LORA_LINE_PREFIX not in stripped:
                if not any(stripped.startswith(p) for p in _IGNORE_PREFIXES):
                    print_dim(f"(device) {stripped.decode('ascii', errors='replace')}")
                continue

            try:
                packet = snifferSx.Packet(raw, context=lora_context)

                if not header_written:
                    pipe.write_packet(get_global_header(LORATAP_DLT))
                    header_written = True

                pipe.write_packet(packet.pcap)
                # Same record, second destination: the file survives the session.
                pcap_writer.write_record(packet.pcap)
                packet_count += 1

                # Persist only the relevant fields to the log file(s).
                # LoRa carries both RSSI and SNR.
                log_writer.write(
                    packet.payload,
                    meta=f"RSSI: {int(packet.rssi)} | SNR: {int(packet.snr)}",
                )

                if show_output:
                    ascii_str = "".join(
                        chr(b) if 32 <= b < 127 else "." for b in packet.payload
                    )
                    hex_str = packet.payload.hex()
                    console.print(
                        f"[green]  [{packet_count:>5}][/green] "
                        f"len={packet.length:>4}B  "
                        f"RSSI={packet.rssi:>7.1f} dBm  "
                        f"SNR={packet.snr:>5.1f} dB\n"
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
        print_info(
            f"Capture stopped — {packet_count} packet(s), {error_count} error(s)"
        )
    finally:
        _keepalive_stop.set()
        log_writer.close()
        pcap_writer.close()
        _stop_lora_capture(shell, lora, pipe)

    return packet_count


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

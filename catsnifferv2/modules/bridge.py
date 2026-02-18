import time
import threading
import platform
import struct

# Internal
from .catsniffer import (
    CatSnifferDevice,
    Catsniffer,
    ShellConnection,
    LoRaConnection,
)
from .pipes import UnixPipe, WindowsPipe, Wireshark
from protocol.sniffer_sx import SnifferSx
from protocol.sniffer_ti import SnifferTI, PacketCategory
from protocol.common import START_OF_FRAME, END_OF_FRAME, get_global_header

# External
from rich.console import Console

console = Console()
sniffer    = SnifferTI()
snifferSx  = SnifferSx()
snifferTICmd  = sniffer.Commands()
snifferSxCmd  = snifferSx.Commands()

# Delay between shell commands (seconds) — RP2040 needs a small gap
_SHELL_CMD_DELAY = 0.15

# Seconds to wait for Wireshark to open the pipe
_WIRESHARK_PIPE_TIMEOUT = 30

# The RP2040 firmware (lora_rx_cb) emits lines beginning with this prefix
# on the Cat-LoRa port.
_LORA_LINE_PREFIX = b"RX:"

# The firmware also sends a welcome banner on Cat-LoRa at startup and after
# lora_mode changes — we skip those silently.
_IGNORE_PREFIXES = (b"LoRa Control Port", b"LoRa mode set")


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
) -> bool:
    """
    Send all LoRa configuration commands via Cat-Shell and apply them.

    Returns True if every command received a response.
    """
    steps = [
        ("frequency",     snifferSxCmd.set_freq(frequency)),
        ("bandwidth",     snifferSxCmd.set_bw(bandwidth)),
        ("spread factor", snifferSxCmd.set_sf(spread_factor)),
        ("coding rate",   snifferSxCmd.set_cr(coding_rate)),
        ("TX power",      snifferSxCmd.set_power(tx_power)),
        ("apply",         snifferSxCmd.apply()),
    ]

    all_ok = True
    for label, cmd in steps:
        response = shell.send_command(cmd, timeout=1.5)
        if response is None:
            console.print(f"  [yellow][!] No response while setting {label}[/yellow]")
            all_ok = False
        else:
            console.print(f"  [dim]{label}: {response[:80]}[/dim]")
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
    console.print("[cyan][*] Switching RP2040 back to command mode...[/cyan]")
    try:
        if shell.connection is None:
            shell.connect()
        resp = shell.send_command(snifferSxCmd.start_command(), timeout=2.0)
        if resp is not None and "COMMAND" in resp.upper():
            console.print("[green][✓] Command mode restored[/green]")
        else:
            console.print(f"[yellow][!] Response to stop: {resp!r}[/yellow]")
    except Exception as exc:
        console.print(f"[yellow][!] Could not restore command mode: {exc}[/yellow]")
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
    """

    # ── 1. Validate ports ────────────────────────────────────────────────────
    if not device.shell_port:
        console.print("[red][X] No shell_port on device — cannot configure LoRa[/red]")
        return
    if not device.lora_port:
        console.print("[red][X] No lora_port on device — cannot receive LoRa stream[/red]")
        return

    # ── 2. Set up PCAP pipe ───────────────────────────────────────────────────
    pipe = WindowsPipe() if platform.system() == "Windows" else UnixPipe()
    threading.Thread(target=pipe.open, daemon=True).start()

    if wireshark:
        Wireshark().run()

    # ── 3. Open shell and configure ───────────────────────────────────────────
    shell = ShellConnection(port=device.shell_port)
    if not shell.connect():
        console.print(f"[red][X] Cannot open shell port: {device.shell_port}[/red]")
        pipe.remove()
        return

    console.print(f"\n[cyan][*] Configuring LoRa via {device.shell_port}...[/cyan]")
    console.print(f"    Frequency:        {frequency / 1e6:.3f} MHz")
    console.print(f"    Bandwidth:        {bandwidth} kHz")
    console.print(f"    Spreading Factor: SF{spread_factor}")
    console.print(f"    Coding Rate:      4/{coding_rate}")
    console.print(f"    TX Power:         {tx_power} dBm\n")

    if not _configure_lora(shell, frequency, bandwidth, spread_factor,
                            coding_rate, tx_power):
        console.print("[yellow][!] Some config commands had no response — continuing[/yellow]")

    # ── 4. Open Cat-LoRa data port ────────────────────────────────────────────
    lora = LoRaConnection(port=device.lora_port)
    if not lora.connect():
        console.print(f"[red][X] Cannot open LoRa port: {device.lora_port}[/red]")
        shell.disconnect()
        pipe.remove()
        return

    # Flush any welcome banner the firmware sends on connect
    time.sleep(0.3)
    try:
        lora.connection.reset_input_buffer()
    except Exception:
        pass

    # ── 5. Switch to stream mode ──────────────────────────────────────────────
    console.print(f"[cyan][*] Switching RP2040 to stream mode...[/cyan]")
    stream_resp = shell.send_command(snifferSxCmd.start_streaming(), timeout=2.0)
    if stream_resp and "STREAM" in stream_resp.upper():
        console.print("[green][✓] Stream mode active[/green]")
    else:
        console.print(
            f"[yellow][!] Unexpected stream response: {stream_resp!r} — continuing[/yellow]"
        )

    # ── 6. Keepalive thread ───────────────────────────────────────────────────
    # The RP2040's lora_thread only calls lora_start_rx_async() when the
    # semaphore fires, which happens when the host writes bytes to CDC1.
    # We send a single null byte every 2 s to keep the semaphore alive and
    # ensure the radio stays in RX mode.
    _keepalive_stop = threading.Event()

    def _keepalive():
        while not _keepalive_stop.is_set():
            try:
                lora.connection.write(b"\x00")
                lora.connection.flush()
            except Exception:
                pass
            _keepalive_stop.wait(timeout=2.0)

    ka_thread = threading.Thread(target=_keepalive, daemon=True)
    ka_thread.start()

    # ── 7. Wait for Wireshark ─────────────────────────────────────────────────
    if wireshark:
        console.print(
            f"[cyan][*] Waiting for Wireshark (timeout {_WIRESHARK_PIPE_TIMEOUT}s)...[/cyan]"
        )
        if not pipe.ready_event.wait(timeout=_WIRESHARK_PIPE_TIMEOUT):
            console.print("[red][X] Timed out waiting for Wireshark — aborting[/red]")
            _keepalive_stop.set()
            _stop_lora_capture(shell, lora, pipe)
            return

    # ── 8. Streaming loop ─────────────────────────────────────────────────────
    lora_context = {
        "frequency":     frequency,
        "bandwidth":     bandwidth,
        "spread_factor": spread_factor,
        "coding_rate":   coding_rate,
    }

    # Determine if we should show verbose output
    # Show output if verbose is True OR if wireshark is False (default behavior)
    show_output = verbose or not wireshark

    if show_output:
        console.print("\n[green][*] Capture running — press Ctrl+C to stop[/green]\n")

    header_written = False
    packet_count   = 0
    error_count    = 0

    try:
        while True:
            # readline() returns when it sees \n or after the serial timeout.
            # LoRaConnection.STREAM_TIMEOUT = 0.5 s, so this never blocks long.
            raw = lora.connection.readline()

            if not raw:
                continue

            # Skip lines that are not packet data
            stripped = raw.strip()
            if not stripped:
                continue
            if not stripped.startswith(_LORA_LINE_PREFIX):
                if not any(stripped.startswith(p) for p in _IGNORE_PREFIXES):
                    console.print(f"[dim]  (device) {stripped.decode('ascii', errors='replace')}[/dim]")
                continue

            try:
                packet = snifferSx.Packet(raw, context=lora_context)

                if not header_written:
                    pipe.write_packet(get_global_header(148))
                    header_written = True

                pipe.write_packet(packet.pcap)
                packet_count += 1

                if show_output:
                    console.print(
                        f"[green]  [{packet_count:>5}][/green] "
                        f"len={packet.length:>4}B  "
                        f"RSSI={packet.rssi:>7.1f} dBm  "
                        f"SNR={packet.snr:>5.1f} dB  "
                        f"payload={packet.payload.hex()[:32]}"
                        f"{'…' if len(packet.payload) > 16 else ''}"
                    )

            except ValueError as exc:
                error_count += 1
                console.print(
                    f"[yellow][!] Parse error #{error_count}: {exc} "
                    f"— raw: {raw[:80]!r}[/yellow]"
                )
            except Exception as exc:
                error_count += 1
                console.print(f"[yellow][!] Unexpected error #{error_count}: {exc}[/yellow]")

    except KeyboardInterrupt:
        console.print(
            f"\n[cyan][*] Capture stopped — "
            f"{packet_count} packet(s), {error_count} error(s)[/cyan]"
        )
    finally:
        _keepalive_stop.set()
        _stop_lora_capture(shell, lora, pipe)


# ──────────────────────────────────────────────────────────────────────────────
# Zigbee / Thread (TI CC1352) bridge — unchanged
# ──────────────────────────────────────────────────────────────────────────────

def run_bridge(
    device: CatSnifferDevice,
    channel: int = 11,
    wireshark: bool = False,
    profile: str = None,
):
    """Run TI sniffer bridge for Zigbee/Thread."""
    pipe = WindowsPipe() if platform.system() == "Windows" else UnixPipe()
    opening_worker = threading.Thread(target=pipe.open, daemon=True)

    if wireshark:
        Wireshark(profile=profile).run()

    opening_worker.start()

    serial_worker = Catsniffer(port=device.bridge_port)
    serial_worker.connect()

    for cmd in snifferTICmd.get_startup_cmd(channel):
        serial_worker.write(cmd)
        time.sleep(0.1)

    if wireshark:
        console.print("[*] Waiting for Wireshark to open the pipe...")
        pipe.ready_event.wait()

    header_flag = False

    while True:
        try:
            data = serial_worker.read_until((END_OF_FRAME + START_OF_FRAME))
            if data:
                ti_packet = sniffer.Packet((START_OF_FRAME + data), channel)
                if ti_packet.category == PacketCategory.DATA_STREAMING_AND_ERROR.value:
                    if not header_flag:
                        header_flag = True
                        pipe.write_packet(get_global_header())
                    pipe.write_packet(ti_packet.pcap)
            time.sleep(0.1)
        except KeyboardInterrupt:
            console.print("\n[*] Stopping TI capture...")
            pipe.remove()
            opening_worker.join(timeout=1)
            serial_worker.write(snifferTICmd.stop())
            serial_worker.disconnect()
            break


# ──────────────────────────────────────────────────────────────────────────────
# Legacy wrapper
# ──────────────────────────────────────────────────────────────────────────────

def run_sx_bridge_legacy(
    serial_worker: Catsniffer,
    frequency,
    bandwidth,
    spread_factor,
    coding_rate,
    sync_word,
    preamble_length,
    wireshark: bool = False,
):
    """Legacy bridge — deprecated. Use run_sx_bridge(CatSnifferDevice, ...)."""
    console.print("[yellow][!] Warning: legacy bridge mode (deprecated)[/yellow]")

    pipe = WindowsPipe() if platform.system() == "Windows" else UnixPipe()
    threading.Thread(target=pipe.open, daemon=True).start()
    if wireshark:
        Wireshark().run()
    serial_worker.connect()

    serial_worker.write(bytes(f"set_freq {frequency}\r\n", "utf-8"))
    serial_worker.write(bytes(f"set_bw {bandwidth}\r\n", "utf-8"))
    serial_worker.write(bytes(f"set_sf {spread_factor}\r\n", "utf-8"))
    serial_worker.write(bytes(f"set_cr {coding_rate}\r\n", "utf-8"))
    serial_worker.write(bytes(f"set_pl {preamble_length}\r\n", "utf-8"))
    serial_worker.write(bytes(f"set_sw {sync_word}\r\n", "utf-8"))
    serial_worker.write(bytes(f"set_rx\r\n", "utf-8"))

    if wireshark:
        console.print("[*] Waiting for Wireshark to open the pipe...")
        pipe.ready_event.wait()

    header_flag = False

    while True:
        try:
            data = serial_worker.readline()
            if data and data.startswith(START_OF_FRAME):
                packet = snifferSx.Packet(
                    (START_OF_FRAME + data),
                    context={
                        "frequency":     frequency,
                        "bandwidth":     bandwidth,
                        "spread_factor": spread_factor,
                        "coding_rate":   coding_rate,
                    },
                )
                if not header_flag:
                    header_flag = True
                    pipe.write_packet(get_global_header(148))
                pipe.write_packet(packet.pcap)
            time.sleep(0.5)
        except KeyboardInterrupt:
            serial_worker.disconnect()
            break
import time
import threading
import platform

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
sniffer = SnifferTI()
snifferSx = SnifferSx()
snifferTICmd = sniffer.Commands()
snifferSxCmd = snifferSx.Commands()


def run_sx_bridge(
    device: CatSnifferDevice,
    frequency: int,
    bandwidth: int,
    spread_factor: int,
    coding_rate: int,
    tx_power: int = 20,
    wireshark: bool = False,
):
    """
    Run LoRa sniffer bridge.

    Args:
        device: CatSnifferDevice with shell_port and lora_port
        frequency: Frequency in Hz (e.g., 915000000)
        bandwidth: Bandwidth in kHz (125, 250, 500)
        spread_factor: Spreading factor (7-12)
        coding_rate: Coding rate (5-8)
        tx_power: TX power in dBm
        wireshark: Whether to launch Wireshark
    """
    if platform.system() == "Windows":
        pipe = WindowsPipe()
    else:
        pipe = UnixPipe()

    opening_worker = threading.Thread(target=pipe.open, daemon=True)
    ws = Wireshark()
    if wireshark:
        ws.run()
    opening_worker.start()

    # Setup shell connection for configuration
    shell = ShellConnection(port=device.shell_port)
    if not shell.connect():
        console.print(
            f"[red][X] Failed to connect to shell port: {device.shell_port}[/red]"
        )
        return

    # Setup LoRa connection for data stream
    lora = LoRaConnection(port=device.lora_port)
    if not lora.connect():
        console.print(
            f"[red][X] Failed to connect to LoRa port: {device.lora_port}[/red]"
        )
        shell.disconnect()
        return

    # Send configuration via shell port
    console.print(f"[*] Configuring LoRa parameters...")
    shell.send_command(snifferSxCmd.set_freq(frequency))
    shell.send_command(snifferSxCmd.set_bw(bandwidth))
    shell.send_command(snifferSxCmd.set_sf(spread_factor))
    shell.send_command(snifferSxCmd.set_cr(coding_rate))
    shell.send_command(snifferSxCmd.set_power(tx_power))

    # Apply configuration
    shell.send_command(snifferSxCmd.apply())
    time.sleep(0.2)

    # Start streaming mode
    shell.send_command(snifferSxCmd.start_streaming())
    console.print(f"[*] LoRa streaming started")

    # Wait for pipe to be ready before starting to stream data
    if wireshark:
        console.print("[*] Waiting for Wireshark to open the pipe...")
        pipe.ready_event.wait()

    header_flag = False

    while True:
        try:
            data = lora.readline()
            if data:
                if data.startswith(START_OF_FRAME):
                    packet = snifferSx.Packet(
                        (START_OF_FRAME + data),
                        context={
                            "frequency": frequency,
                            "bandwidth": bandwidth,
                            "spread_factor": spread_factor,
                            "coding_rate": coding_rate,
                        },
                    )
                    if not header_flag:
                        header_flag = True
                        pipe.write_packet(get_global_header(148))
                    pipe.write_packet(packet.pcap)

            time.sleep(0.1)
        except KeyboardInterrupt:
            console.print("\n[*] Stopping LoRa capture...")
            shell.send_command(snifferSxCmd.start_command())
            shell.disconnect()
            lora.disconnect()
            pipe.remove()
            break


def run_bridge(
    device: CatSnifferDevice,
    channel: int = 11,
    wireshark: bool = False,
    profile: str = None,
):
    """
    Run TI sniffer bridge for Zigbee/Thread.

    Args:
        device: CatSnifferDevice with bridge_port
        channel: IEEE 802.15.4 channel (11-26)
        wireshark: Whether to launch Wireshark
        profile: Wireshark configuration profile name
    """
    if platform.system() == "Windows":
        pipe = WindowsPipe()
    else:
        pipe = UnixPipe()

    opening_worker = threading.Thread(target=pipe.open, daemon=True)

    ws = None
    if wireshark:
        ws = Wireshark(profile=profile)
        ws.run()

    opening_worker.start()

    # Use bridge port for TI protocol
    serial_worker = Catsniffer(port=device.bridge_port)
    serial_worker.connect()

    startup = snifferTICmd.get_startup_cmd(channel)
    for cmd in startup:
        serial_worker.write(cmd)
        time.sleep(0.1)

    # Wait for pipe to be ready before starting to stream data
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


# Legacy wrapper for backward compatibility during transition
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
    """Legacy bridge function - deprecated, use run_sx_bridge with CatSnifferDevice."""
    console.print("[yellow][!] Warning: Using legacy bridge mode[/yellow]")

    if platform.system() == "Windows":
        pipe = WindowsPipe()
    else:
        pipe = UnixPipe()

    opening_worker = threading.Thread(target=pipe.open, daemon=True)
    ws = Wireshark()
    if wireshark:
        ws.run()
    opening_worker.start()
    serial_worker.connect()

    # Use old-style bytes commands for legacy mode
    serial_worker.write(bytes(f"set_freq {frequency}\r\n", "utf-8"))
    serial_worker.write(bytes(f"set_bw {bandwidth}\r\n", "utf-8"))
    serial_worker.write(bytes(f"set_sf {spread_factor}\r\n", "utf-8"))
    serial_worker.write(bytes(f"set_cr {coding_rate}\r\n", "utf-8"))
    serial_worker.write(bytes(f"set_pl {preamble_length}\r\n", "utf-8"))
    serial_worker.write(bytes(f"set_sw {sync_word}\r\n", "utf-8"))
    serial_worker.write(bytes(f"set_rx\r\n", "utf-8"))

    # Wait for pipe to be ready before starting to stream data
    if wireshark:
        console.print("[*] Waiting for Wireshark to open the pipe...")
        pipe.ready_event.wait()

    header_flag = False

    while True:
        try:
            data = serial_worker.readline()
            if data:
                if data.startswith(START_OF_FRAME):
                    packet = snifferSx.Packet(
                        (START_OF_FRAME + data),
                        context={
                            "frequency": frequency,
                            "bandwidth": bandwidth,
                            "spread_factor": spread_factor,
                            "coding_rate": coding_rate,
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

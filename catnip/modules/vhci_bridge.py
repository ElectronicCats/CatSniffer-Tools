#!/usr/bin/env python3
"""
vhci_bridge.py - CatSniffer VHCI Bridge

Exposes CatSniffer hardware as a complete Linux HCI controller (hciX).
All standard Bluetooth tools work transparently (hcitool, gatttool, bluetoothctl).

Usage:
    sudo python3 vhci_bridge.py -p /dev/ttyACM0

Requirements:
    - CatSniffer with Sniffle-compatible firmware
    - Linux kernel with VHCI support
    - Root privileges (for /dev/vhci access)
"""

import os
import sys
import time
import argparse
import logging
import signal
from serial.tools.list_ports import comports

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vhci.bridge import VHCIBridge
from vhci.constants import *

from rich.console import Console
from rich.logging import RichHandler

console = Console()


def find_catsniffer():
    """Auto-detect CatSniffer serial port"""
    # CatSniffer v3: VID=0x2E8A (Raspberry Pi), PID=0x00C0
    catsniffer_ports = [
        i[0]
        for i in comports()
        if i.vid == 0x2E8A
        and i.pid == 0x00C0
        and i.manufacturer
        and "arduino" in i.manufacturer.lower()
    ]

    if catsniffer_ports:
        return catsniffer_ports[0]

    # Fallback: look for common CP210x or CH340
    for port in comports():
        if port.vid in (0x10C4, 0x1A86):  # CP210x or CH340
            return port[0]

    return None


def setup_logging(verbose=False):
    """Configure logging"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_time=False)],
    )
    return logging.getLogger("vhci")


def main():
    parser = argparse.ArgumentParser(
        description="CatSniffer VHCI Bridge - Expose CatSniffer as hciX device",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    sudo python3 vhci_bridge.py -p /dev/ttyACM0
    sudo python3 vhci_bridge.py --auto
    sudo python3 vhci_bridge.py -p /dev/ttyACM0 -v  # Verbose

After starting, use standard tools:
    hciconfig -a           # Show device info
    hcitool -i hci1 lescan # Scan for devices
    gatttool -i hci1 -b <MAC> -I  # GATT operations
        """,
    )

    parser.add_argument("-p", "--port", help="Serial port (e.g., /dev/ttyACM0)")
    parser.add_argument("--auto", action="store_true", help="Auto-detect CatSniffer")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    parser.add_argument(
        "--baud", type=int, default=2000000, help="Baud rate (default: 2000000)"
    )

    args = parser.parse_args()

    # Check root
    if os.geteuid() != 0:
        console.print(
            "[yellow]Warning: Root privileges required for VHCI access[/yellow]"
        )
        console.print("[yellow]Run with sudo[/yellow]")

    # Find port
    if args.auto or not args.port:
        port = find_catsniffer()
        if not port:
            console.print("[red]Error: CatSniffer not found[/red]")
            console.print("Specify port with -p or check connection")
            sys.exit(1)
        console.print(f"[green]Found CatSniffer: {port}[/green]")
    else:
        port = args.port

    # Setup logging
    log = setup_logging(args.verbose)

    # Create bridge
    bridge = VHCIBridge(port, log)

    # Signal handlers
    def signal_handler(sig, frame):
        console.print("\n[yellow]Shutting down...[/yellow]")
        bridge.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start bridge
    try:
        bridge.start()
    except Exception as e:
        console.print(f"[red]Failed to start bridge: {e}[/red]")
        sys.exit(1)

    console.print(f"[green]Bridge running![/green]")
    console.print(f"[green]Device should appear as hciX[/green]")
    console.print(f"[green]Check with: hciconfig -a[/green]")
    console.print("")
    console.print("[dim]Press Ctrl+C to stop[/dim]")

    # Main loop
    try:
        bridge.run()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()


if __name__ == "__main__":
    main()

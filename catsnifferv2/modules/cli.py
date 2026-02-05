#! /usr/bin/env python3

# Kevin Leon @ Electronic Cats
# Original Creation Date: Dec 19, 2025
# This code is beerware; if you see me (or any other Electronic Cats
# member) at the local, and you've found our code helpful,
# please buy us a round!
# Distributed as-is; no warranty is given.

import logging

# Internal
from .catnip import Catnip
from .pipes import Wireshark
from .bridge import run_bridge, run_sx_bridge
from .catsniffer import (
    SniffingFirmware,
    SniffingBaseFirmware,
    Catsniffer,
    CatSnifferDevice,
    catsniffer_get_device,
    catsniffer_get_devices,
)

# External
import click
from rich.logging import RichHandler
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.style import Style

# APP Information
CLI_NAME = "Catsniffer"
VERSION_NUMBER = "3.0.0"
AUTHOR = "JahazielLem"
COMPANY = "Electronic Cats - PWNLab"

# Defining styles for reuse
STYLES = {
    "header": Style(color="cyan", bold=True),
    "success": Style(color="green", bold=True),
    "warning": Style(color="yellow", bold=True),
    "error": Style(color="red", bold=True),
    "info": Style(color="blue", bold=True),
    "device": Style(color="cyan"),
    "prompt": Style(color="magenta", bold=True),
}

# Prompt
PROMPT_ICON = "󰄛"
PROMPT_DESCRIPTION = (
    "PyCat-Sniffer CLI - For sniffing the TI CC1352 device communication interfaces."
)

__version__ = "3.0"

catnip = Catnip()
wireshark = Wireshark()
console = Console()

logger = logging.getLogger("rich")
FORMAT = "%(message)s"
logging.basicConfig(
    level="WARNING", format=FORMAT, datefmt="[%X]", handlers=[RichHandler()]
)

def print_header():
    """Print the ASCII art header"""
    ascii_art = f"""      :-:              :--       |
      ++++=.        .=++++       |
      =+++++===++===++++++       |
      -++++++++++++++++++-       |  Module:  {CLI_NAME}
 .:   =++---++++++++---++=   :.  |  Author:  {AUTHOR}
 ::---+++.   -++++-   .+++---::  |  Version: {VERSION_NUMBER}
::1..:-++++:   ++++   :++++-::.::|  Company: {COMPANY}
.:...:=++++++++++++++++++=:...:. |
 :---.  -++++++++++++++-  .---:  |
 ..        .:------:.        ..  |"""
    
    # Apply color to the ASCII art
    colored_ascii = f"[cyan bold]{ascii_art}[/cyan bold]"
    
    # Create a panel for the header
    header_panel = Panel(
        colored_ascii,
        title=PROMPT_DESCRIPTION,
        border_style=STYLES["header"],
        title_align="left",
        padding=(1, 2),
    )
    console.print(header_panel)

def print_success(message):
    """Print a success message"""
    console.print(f"[green]✓[/green] {message}", style=STYLES["success"])


def print_warning(message):
    """Print a warning message"""
    console.print(f"[yellow]⚠[/yellow] {message}", style=STYLES["warning"])


def print_error(message):
    """Print an error message"""
    console.print(f"[red]✗[/red] {message}", style=STYLES["error"])


def print_info(message):
    """Print an info message"""
    console.print(f"[blue]ℹ[/blue] {message}", style=STYLES["info"])

def get_device_or_exit(device_id=None):
    """Get CatSniffer device or exit with error."""
    device = catsniffer_get_device(device_id)
    if device is None:
        print_error("No CatSniffer device found!")
        console.print("    Make sure your CatSniffer is connected.")
        exit(1)
    if not device.is_valid():
        print_warning(f"Not all ports detected for {device}")
        console.print(f"    Bridge: {device.bridge_port}")
        console.print(f"    LoRa:   {device.lora_port}")
        console.print(f"    Shell:  {device.shell_port}")
    return device


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--verbose", is_flag=True, help="Show Verbose mode")
def cli(verbose):
    """CatSniffer: All in one catsniffer tools environment."""
    if verbose:
        logger.level = logging.INFO
    pass


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--verbose", is_flag=True, help="Show Verbose mode")
def sniff(verbose):
    """Sniffer protocol control"""
    if verbose:
        logger.level = logging.INFO
    pass


@sniff.command(SniffingFirmware.BLE.name.lower())
@click.option(
    "--device",
    "-d",
    default=None,
    type=int,
    help="Device ID (for multiple CatSniffers)",
)
def sniff_ble(device):
    """Sniffing BLE with Sniffle firmware"""
    dev = get_device_or_exit(device)
    cat = Catsniffer(dev.bridge_port)
    if cat.check_sniffle_firmware():
        print_info("Firmware found!")
    else:
        print_warning("Firmware not found! - Flashing Sniffle")
        if not catnip.find_flash_firmware(SniffingBaseFirmware.BLE.value, dev):
            return

    print_info("Now you can open Sniffle extcap from Wireshark")


@sniff.command(SniffingFirmware.ZIGBEE.name.lower())
@click.option("-ws", is_flag=True, help="Open Wireshark")
@click.option(
    "--channel", "-c", required=True, type=click.IntRange(11, 26), help="Zigbee channel"
)
@click.option(
    "--device",
    "-d",
    default=None,
    type=int,
    help="Device ID (for multiple CatSniffers)",
)
def sniff_zigbee(ws, channel, device):
    """Sniffing Zigbee with Sniffer TI firmware"""
    dev = get_device_or_exit(device)
    cat = Catsniffer(dev.bridge_port)
    if cat.check_ti_firmware():
        print_info("Firmware found!")
    else:
        print_warning("Firmware not found! - Flashing Sniffer TI")
        if not catnip.find_flash_firmware(SniffingBaseFirmware.ZIGBEE.value, dev):
            return

    print_info(f"[{dev}] Sniffing Zigbee at channel: {channel}")
    run_bridge(dev, channel, ws)


@sniff.command(SniffingFirmware.THREAD.name.lower())
@click.option("-ws", is_flag=True, help="Open Wireshark")
@click.option(
    "--channel", "-c", required=True, type=click.IntRange(11, 26), help="Thread channel"
)
@click.option(
    "--device",
    "-d",
    default=None,
    type=int,
    help="Device ID (for multiple CatSniffers)",
)
def sniff_thread(ws, channel, device):
    """Sniffing Thread with Sniffer TI firmware"""
    dev = get_device_or_exit(device)
    cat = Catsniffer(dev.bridge_port)
    if cat.check_ti_firmware():
        print_info("Firmware found!")
    else:
        print_warning("Firmware not found! - Flashing Sniffer TI")
        if not catnip.find_flash_firmware(SniffingBaseFirmware.THREAD.value, dev):
            return

    print_info(f"[{dev}] Sniffing Thread at channel: {channel}")
    run_bridge(dev, channel, ws)


@sniff.command(SniffingFirmware.LORA.name.lower())
@click.option("-ws", is_flag=True, help="Open Wireshark")
@click.option(
    "--frequency",
    "-freq",
    default=915000000,
    type=int,
    help="Frequency in Hz (e.g., 915000000 for 915 MHz)",
)
@click.option(
    "--bandwidth",
    "-bw",
    default=125,
    type=click.Choice(["125", "250", "500"]),
    help="Bandwidth in kHz",
)
@click.option(
    "--spread_factor",
    "-sf",
    default=7,
    type=click.IntRange(7, 12),
    help="Spreading Factor (7-12)",
)
@click.option(
    "--coding_rate",
    "-cr",
    default=5,
    type=click.IntRange(5, 8),
    help="Coding Rate (5-8)",
)
@click.option(
    "--tx_power",
    "-pw",
    default=20,
    type=int,
    help="TX Power in dBm",
)
@click.option(
    "--device",
    "-d",
    default=None,
    type=int,
    help="Device ID (for multiple CatSniffers)",
)
def sniff_lora(
    ws,
    frequency,
    bandwidth,
    spread_factor,
    coding_rate,
    tx_power,
    device,
):
    """Sniffing LoRa with Sniffer SX1262 firmware"""
    dev = get_device_or_exit(device)

    # Convert bandwidth from string to int
    bw_int = int(bandwidth)

    print_info(f"[{dev}] Sniffing LoRa with configuration:")
    console.print(f"  Frequency:       {frequency} Hz ({frequency / 1000000:.3f} MHz)")
    console.print(f"  Bandwidth:       {bw_int} kHz")
    console.print(f"  Spreading Factor: SF{spread_factor}")
    console.print(f"  Coding Rate:     4/{coding_rate}")
    console.print(f"  TX Power:        {tx_power} dBm")

    run_sx_bridge(
        dev,
        frequency,
        bw_int,
        spread_factor,
        coding_rate,
        tx_power,
        ws,
    )


@cli.command()
def cativity() -> None:
    """IQ Activity Monitor (Not implemented yet)"""
    print_info("Monitoring IQ activity")


@cli.command()
@click.argument("firmware", required=False)
@click.option(
    "--device",
    "-d",
    default=None,
    type=int,
    help="Device ID (for multiple CatSniffers). If not specified, first device will be selected.",
)
def flash(firmware, device, list) -> None:
    """Flash CC1352 Firmware or list available firmware images"""
    # If no device is specified, we get all connected devices.
    if device is None:
        devs = catsniffer_get_devices()
        if not devs:
            print_error("No CatSniffer devices found!")
            console.print("    Make sure your CatSniffer is connected.")
            exit(1)
        
        # Select the first default device
        dev = devs[0]
        print_warning(f"No device specified. Using first device: {dev}")
    else:
        # If an ID is specified, retrieve that specific device.
        dev = catsniffer_get_device(device)
        if dev is None:
            print_error(f"CatSniffer device with ID {device} not found!")
            console.print("    Use 'devices' command to list available devices.")
            exit(1)
    
    # Verify that the device is valid
    if not dev.is_valid():
        print_warning(f"Not all ports detected for {dev}")
        console.print(f"    Bridge: {dev.bridge_port}")
        console.print(f"    LoRa:   {dev.lora_port}")
        console.print(f"    Shell:  {dev.shell_port}")
    
    print_info(f"Flashing firmware: {firmware} to device: {dev}")
    if not catnip.find_flash_firmware(firmware, dev):
        print_error(f"Error flashing: {firmware}")

@cli.command()
def devices() -> None:
    """List connected CatSniffer devices"""
    devs = catsniffer_get_devices()
    if not devs:
        print_warning("No CatSniffer devices found.")
        return

    # Add a table to display devicesclear
    table = Table(title=f"Found {len(devs)} CatSniffer device(s)", box=box.ROUNDED)
    table.add_column("Device", style=STYLES["device"], justify="left")
    table.add_column("Cat-Bridge (CC1352)", style="cyan", justify="left")
    table.add_column("Cat-LoRa (SX1262)", style="cyan", justify="left")
    table.add_column("Cat-Shell (Config)", style="cyan", justify="left")

    for dev in devs:
        bridge_status = dev.bridge_port or "[red]Not found[/red]"
        lora_status = dev.lora_port or "[red]Not found[/red]"
        shell_status = dev.shell_port or "[red]Not found[/red]"
        
        table.add_row(str(dev), bridge_status, lora_status, shell_status)

    console.print()
    console.print(table)


def main_cli() -> None:
    print_header()
    cli.add_command(sniff)
    cli()

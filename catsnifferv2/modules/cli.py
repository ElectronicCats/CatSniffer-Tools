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

# APP Information
CLI_NAME = "Catsniffer"
VERSION_NUMBER = "3.0.0"
AUTHOR = "JahazielLem"
COMPANY = "Electronic Cats - PWNLab"
# Prompt
PROMPT_ICON = "󰄛"
PROMPT_DESCRIPTION = (
    "PyCat-Sniffer CLI - For sniffing the TI CC1352 device communication interfaces."
)
PROMPT_HEADER = f"""
\x1b[36;1m      :-:              :--       |
      ++++=.        .=++++       |
      =+++++===++===++++++       |
      -++++++++++++++++++-       |  Module:  {CLI_NAME}
 .:   =++---++++++++---++=   :.  |  Author:  {AUTHOR}
 ::---+++.   -++++-   .+++---::  |  Version: {VERSION_NUMBER}
::1..:-++++:   ++++   :++++-::.::|  Company: {COMPANY}
.:...:=++++++++++++++++++=:...:. |
 :---.  -++++++++++++++-  .---:  |
 ..        .:------:.        ..  |\x1b[0m

"""

__version__ = "3.0"

catnip = Catnip()
wireshark = Wireshark()
console = Console()

logger = logging.getLogger("rich")
FORMAT = "%(message)s"
logging.basicConfig(
    level="WARNING", format=FORMAT, datefmt="[%X]", handlers=[RichHandler()]
)


def get_device_or_exit(device_id=None):
    """Get CatSniffer device or exit with error."""
    device = catsniffer_get_device(device_id)
    if device is None:
        console.print("[red][X] No CatSniffer device found![/red]")
        console.print("    Make sure your CatSniffer is connected.")
        exit(1)
    if not device.is_valid():
        console.print(f"[yellow][!] Warning: Not all ports detected for {device}[/yellow]")
        console.print(f"    Bridge: {device.bridge_port}")
        console.print(f"    LoRa:   {device.lora_port}")
        console.print(f"    Shell:  {device.shell_port}")
    return device


@click.group()
@click.option("--verbose", is_flag=True, help="Show Verbose mode")
def cli(verbose):
    """CatSniffer: All in one catsniffer tools environment."""
    if verbose:
        logger.level = logging.INFO
    pass


@click.group()
@click.option("--verbose", is_flag=True, help="Show Verbose mode")
def sniff(verbose):
    """Sniffer protocol control"""
    if verbose:
        logger.level = logging.INFO
    pass


@sniff.command(SniffingFirmware.BLE.name.lower())
@click.option("--device", "-d", default=None, type=int, help="Device ID (for multiple CatSniffers)")
def sniff_ble(device):
    """Sniffing BLE with Sniffle firmware"""
    dev = get_device_or_exit(device)
    cat = Catsniffer(dev.bridge_port)
    if cat.check_sniffle_firmware():
        logger.info(f"[*] Firmware found!")
    else:
        logger.info(f"[-] Firmware not found! - Flashing Sniffle")
        if not catnip.find_flash_firmware(SniffingBaseFirmware.BLE.value, dev):
            return

    print("[*] Now you can open Sniffle extcap from Wireshark")


@sniff.command(SniffingFirmware.ZIGBEE.name.lower())
@click.option("-ws", is_flag=True, help="Open Wireshark")
@click.option(
    "--channel", "-c", required=True, type=click.IntRange(11, 26), help="Zigbee channel"
)
@click.option("--device", "-d", default=None, type=int, help="Device ID (for multiple CatSniffers)")
def sniff_zigbee(ws, channel, device):
    """Sniffing Zigbee with Sniffer TI firmware"""
    dev = get_device_or_exit(device)
    cat = Catsniffer(dev.bridge_port)
    if cat.check_ti_firmware():
        logger.info(f"[*] Firmware found!")
    else:
        logger.info(f"[-] Firmware not found! - Flashing Sniffer TI")
        if not catnip.find_flash_firmware(SniffingBaseFirmware.ZIGBEE.value, dev):
            return

    print(f"[* {dev}] Sniffing Zigbee at channel: {channel}")
    run_bridge(dev, channel, ws)


@sniff.command(SniffingFirmware.THREAD.name.lower())
@click.option("-ws", is_flag=True, help="Open Wireshark")
@click.option(
    "--channel", "-c", required=True, type=click.IntRange(11, 26), help="Thread channel"
)
@click.option("--device", "-d", default=None, type=int, help="Device ID (for multiple CatSniffers)")
def sniff_thread(ws, channel, device):
    """Sniffing Thread with Sniffer TI firmware"""
    dev = get_device_or_exit(device)
    cat = Catsniffer(dev.bridge_port)
    if cat.check_ti_firmware():
        logger.info(f"[*] Firmware found!")
    else:
        logger.info(f"[-] Firmware not found! - Flashing Sniffer TI")
        if not catnip.find_flash_firmware(SniffingBaseFirmware.THREAD.value, dev):
            return

    print(f"[* {dev}] Sniffing Thread at channel: {channel}")
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
@click.option("--device", "-d", default=None, type=int, help="Device ID (for multiple CatSniffers)")
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

    print(f"[* {dev}] Sniffing LoRa with configuration:")
    print(f"  Frequency:       {frequency} Hz ({frequency / 1000000:.3f} MHz)")
    print(f"  Bandwidth:       {bw_int} kHz")
    print(f"  Spreading Factor: SF{spread_factor}")
    print(f"  Coding Rate:     4/{coding_rate}")
    print(f"  TX Power:        {tx_power} dBm")

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
    logger.info("[*] Monitoring IQ activity")


@cli.command()
@click.argument("firmware")
@click.option("--device", "-d", default=None, type=int, help="Device ID (for multiple CatSniffers)")
def flash(firmware, device) -> None:
    """Flash CC1352 Firmware"""
    dev = get_device_or_exit(device)
    logger.info(f"[*] Flashing firmware: {firmware}")
    if not catnip.find_flash_firmware(firmware, dev):
        logger.info(f"[X] Error flashing: {firmware}")


@cli.command()
def releases() -> None:
    """Show Firmware releases"""
    catnip.show_releases()


@cli.command()
def devices() -> None:
    """List connected CatSniffer devices"""
    devs = catsniffer_get_devices()
    if not devs:
        console.print("[yellow]No CatSniffer devices found.[/yellow]")
        return

    console.print(f"\n[bold]Found {len(devs)} CatSniffer device(s):[/bold]\n")
    for dev in devs:
        console.print(f"[cyan]{dev}[/cyan]")
        console.print(f"  Cat-Bridge (CC1352): {dev.bridge_port or '[red]Not found[/red]'}")
        console.print(f"  Cat-LoRa (SX1262):   {dev.lora_port or '[red]Not found[/red]'}")
        console.print(f"  Cat-Shell (Config):  {dev.shell_port or '[red]Not found[/red]'}")
        console.print()


def main_cli() -> None:
    print(PROMPT_HEADER)
    cli.add_command(sniff)
    cli()

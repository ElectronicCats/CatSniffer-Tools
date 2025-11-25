import asyncio
import signal

# Internal
from .catnip import Catnip
from .pipes import Wireshark
from .bridge import run_bridge
from .catsniffer import (
    SniffingFirmware,
    SniffingBaseFirmware,
    Catsniffer,
    catsniffer_get_port,
)

# External
import click
from rich.console import Console

__version__ = "1.0"

console = Console()
cat = Catsniffer()
catnip = Catnip()
wireshark = Wireshark()


@click.group()
def cli():
    """CatSniffer: All in one catsniffer tools environment."""
    pass


@click.group()
def sniff():
    """Sniffer protocol control"""
    pass


@sniff.command(SniffingFirmware.BLE.name.lower())
def sniff_ble():
    """Sniffing BLE with Sniffle firmware"""
    if cat.check_sniffle_firmware():
        console.log(f"[*] Firmware found!", style="green")
    else:
        console.log(f"[-] Firmware not found! - Flashing Sniffle", style="yellow")
        if not catnip.find_flash_firmware(SniffingBaseFirmware.BLE.value):
            return

    console.log("[*] Now you can open Sniffle extcap from Wireshark", style="cyan")


@sniff.command(SniffingFirmware.ZIGBEE.name.lower())
@click.option("-ws", is_flag=True, help="Open Wireshark")
@click.option(
    "--channel", "-c", required=True, type=click.IntRange(11, 26), help="Zigbee chanel"
)
def sniff_zigbee(ws, channel):
    """Sniffing Zigbee with Sniffer TI firmware"""
    if cat.check_ti_firmware():
        console.log(f"[*] Firmware found!", style="green")
    else:
        console.log(f"[-] Firmware not found! - Flashing Sniffer TI", style="yellow")
        if not catnip.find_flash_firmware(SniffingBaseFirmware.ZIGBEE.value):
            return

    console.log(f"[*] Sniffing Zigbee at channel: {channel}", style="cyan")
    run_bridge(cat, channel, ws)


@sniff.command(SniffingFirmware.THREAD.name.lower())
@click.option("-ws", is_flag=True, help="Open Wireshark")
@click.option(
    "--channel", "-c", required=True, type=click.IntRange(11, 26), help="Thread chanel"
)
def sniff_thread(ws, channel):
    """Sniffing Thread with Sniffer TI firmware"""
    if cat.check_ti_firmware():
        console.log(f"[*] Firmware found!", style="green")
    else:
        console.log(f"[-] Firmware not found! - Flashing Sniffer TI", style="yellow")
        if not catnip.find_flash_firmware(SniffingBaseFirmware.THREAD.value):
            return
    console.log(f"[*] Sniffing Thread at channel: {channel}", style="cyan")
    run_bridge(cat, channel, ws)


@cli.command()
def cativity() -> None:
    """IQ Activity Monitor"""
    console.log("[*] Monitoring IQ activity")


@cli.command()
@click.argument("firmware")
@click.option("--firmware", "-f", default="sniffle", help="Firmware name or path.")
def flash(firmware) -> None:
    """Flash firmware"""
    console.log(f"[*] Flashing firmware: {firmware}")
    if not catnip.find_flash_firmware(firmware):
        console.log(f"[X] Error flashing: {firmware}", style="red")


@cli.command()
def releases() -> None:
    """Show Firmware releases"""
    catnip.show_releases()


def main_cli() -> None:
    cli.add_command(sniff)
    cli()

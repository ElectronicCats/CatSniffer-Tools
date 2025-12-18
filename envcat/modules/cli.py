import logging

# Internal
from .catnip import Catnip
from .pipes import Wireshark
from .bridge import run_bridge, run_sx_bridge
from .catsniffer import (
    SniffingFirmware,
    SniffingBaseFirmware,
    Catsniffer,
    catsniffer_get_port,
)

# External
import click
from rich.logging import RichHandler

__version__ = "1.0"

catnip = Catnip()
wireshark = Wireshark()

logger = logging.getLogger("rich")
FORMAT = "%(message)s"
logging.basicConfig(
    level="WARNING", format=FORMAT, datefmt="[%X]", handlers=[RichHandler()]
)


@click.group()
def cli():
    """CatSniffer: All in one catsniffer tools environment."""
    pass


@click.group()
@click.option("--verbose", is_flag=True, help="Show Verbose mode")
def sniff(verbose):
    """Sniffer protocol control"""
    if verbose:
        logger.level = logging.INFO
    pass


@sniff.command(SniffingFirmware.BLE.name.lower())
def sniff_ble():
    """Sniffing BLE with Sniffle firmware"""
    cat = Catsniffer()
    if cat.check_sniffle_firmware():
        logger.info(f"[*] Firmware found!")
    else:
        logger.info(f"[-] Firmware not found! - Flashing Sniffle")
        if not catnip.find_flash_firmware(SniffingBaseFirmware.BLE.value):
            return

    logger.info("[*] Now you can open Sniffle extcap from Wireshark")


@sniff.command(SniffingFirmware.ZIGBEE.name.lower())
@click.option("-ws", is_flag=True, help="Open Wireshark")
@click.option(
    "--channel", "-c", required=True, type=click.IntRange(11, 26), help="Zigbee channel"
)
@click.option("--port", "-p", default=catsniffer_get_port(), help="Catsniffer Path")
def sniff_zigbee(ws, channel, port):
    """Sniffing Zigbee with Sniffer TI firmware"""
    cat = Catsniffer(port)
    if cat.check_ti_firmware():
        logger.info(f"[*] Firmware found!")
    else:
        logger.info(f"[-] Firmware not found! - Flashing Sniffer TI")
        if not catnip.find_flash_firmware(SniffingBaseFirmware.ZIGBEE.value, port):
            return

    logger.info(f"[* {port}] Sniffing Zigbee at channel: {channel}")
    run_bridge(cat, channel, ws)


@sniff.command(SniffingFirmware.THREAD.name.lower())
@click.option("-ws", is_flag=True, help="Open Wireshark")
@click.option(
    "--channel", "-c", required=True, type=click.IntRange(11, 26), help="Thread channel"
)
@click.option("--port", "-p", default=catsniffer_get_port(), help="Catsniffer Path")
def sniff_thread(ws, channel, port):
    """Sniffing Thread with Sniffer TI firmware"""
    cat = Catsniffer(port)
    if cat.check_ti_firmware():
        logger.info(f"[*] Firmware found!")
    else:
        logger.info(f"[-] Firmware not found! - Flashing Sniffer TI")
        if not catnip.find_flash_firmware(SniffingBaseFirmware.THREAD.value, port):
            return
    logger.info(f"[* {port}] Sniffing Thread at channel: {channel}")
    run_bridge(cat, channel, ws)


@sniff.command(SniffingFirmware.LORA.name.lower())
@click.option("-ws", is_flag=True, help="Open Wireshark")
@click.option(
    "--frequency",
    "-freq",
    default=916,
    type=float,
    help="Frequency in MHz. Range 443 - 490 MHz or 868 - 960.0 MHz",
)
@click.option(
    "--bandwidth",
    "-bw",
    default=8,
    type=click.IntRange(0, 9),
    help="Bandwidth Index: 0:7.8 - 1:10.4 - 2:15.6 - 3:20.8 - 4:31.25 - 5:41.7 - 6:65.5 - 7:125 - 8:250 - 9:500",
)
@click.option(
    "--spread_factor",
    "-sf",
    default=11,
    type=click.IntRange(6, 12),
    help="Spreading Factor",
)
@click.option(
    "--coding_rate", "-cr", default=5, type=click.IntRange(5, 8), help="Coding Rate"
)
@click.option("--sync_word", "-sw", default=0x12, help="Sync Word")
@click.option("--preamble_length", "-pl", default=8, help="Preamble Length")
@click.option("--port", "-p", default=catsniffer_get_port(), help="Catsniffer Path")
def sniff_zigbee(
    ws,
    frequency,
    bandwidth,
    spread_factor,
    coding_rate,
    sync_word,
    preamble_length,
    port,
):
    """Sniffing LoRa with Sniffer SX1262 firmware"""
    cat = Catsniffer(port)
    logger.info(
        f"[* {port}] Sniffing LoRa with configuration: \nFrequency: {frequency}\nBandwidth: {bandwidth}\nSpreading Factor: {spread_factor}\nCoding Rate: {coding_rate}\nSync Word: {sync_word}\nPreamble Length: {preamble_length}"
    )
    run_sx_bridge(
        cat,
        frequency,
        bandwidth,
        spread_factor,
        coding_rate,
        sync_word,
        preamble_length,
        ws,
    )


@cli.command()
def cativity() -> None:
    """IQ Activity Monitor (Not implemented yet)"""
    logger.info("[*] Monitoring IQ activity")


@cli.command()
@click.argument("firmware")
@click.option("--firmware", "-f", default="sniffle", help="Firmware name or path.")
@click.option("--port", "-p", default=catsniffer_get_port(), help="Catsniffer Path")
def flash(firmware, port) -> None:
    """Flash CC1352 Firmware"""
    logger.info(f"[*] Flashing firmware: {firmware}")
    if not catnip.find_flash_firmware(firmware, port):
        logger.info(f"[X] Error flashing: {firmware}")


@cli.command()
def releases() -> None:
    """Show Firmware releases"""
    catnip.show_releases()


def main_cli() -> None:
    cli.add_command(sniff)
    cli()

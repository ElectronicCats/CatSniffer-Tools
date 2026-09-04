"""``catnip cativity`` - IQ activity monitor command."""

# Internal
from ...firmware.flasher import Flasher
from ...core.device_utils import get_device_or_exit, send_identify_command
from ...core.catnip import Catnip

# External
import click
import time

from ...utils.cli_options import device_option
from ...utils.output import (
    console,
    print_success,
    print_warning,
    print_error,
    print_info,
)


@click.command()
@device_option()
@click.option(
    "--channel", "-c", type=click.IntRange(11, 26), help="Fixed channel (11-26)"
)
@click.option("--topology", "-t", is_flag=True, help="Show network topology")
@click.option(
    "--protocol",
    "-p",
    default="all",
    type=click.Choice(["all", "zigbee", "thread"]),
    help="Protocol filter",
)
def cativity(device, channel, topology, protocol):
    """IQ Activity Monitor"""
    from ..cativity.runner import CativityRunner

    dev = get_device_or_exit(device)
    cat = Catnip(dev.bridge_port)

    # Verify firmware
    print_info("Checking for Sniffer TI firmware...")
    if cat.check_firmware_by_metadata("ti_sniffer", dev.shell_port):
        print_success("Sniffer TI firmware found (via metadata)!")
    elif cat.check_ti_firmware():
        print_success("Sniffer TI firmware found (via direct communication)!")
    else:
        print_warning("Sniffer TI firmware not found! - Flashing Sniffer TI")
        # Initialize Flasher for flashing
        flasher_flash = Flasher()
        if not flasher_flash.find_flash_firmware("ti_sniffer", dev):
            print_error("Failed to flash Sniffer TI firmware")
            return

        print_info("Waiting for device to initialize...")
        time.sleep(0.5)

    # Send identification command to help identify which device was flashed
    send_identify_command(dev)

    print_info(f"[{dev}] Starting Cativity analysis...")
    runner = CativityRunner(dev, console=console)
    runner.run(channel=channel, topology=topology, protocol=protocol)

"""``catnip lora`` - LoRa SX1262 tools."""

# Internal
from ...core.device_utils import get_device_or_exit

# External
import click

from ...utils.cli_options import device_option
from ...utils.output import (
    print_error,
    print_info,
)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def lora():
    """LoRa SX1262 tools"""
    pass


@lora.command("spectrum")
@device_option()
@click.option(
    "-b",
    "--baudrate",
    type=int,
    default=115200,
    help="Baudrate (default: 115200)",
)
@click.option(
    "--start-freq",
    type=click.FloatRange(150, 960),
    default=150,
    help="Starting frequency in MHz, 150-960 (default: 150)",
)
@click.option(
    "--end-freq",
    type=click.FloatRange(150, 960),
    default=960,
    help="End frequency in MHz, 150-960 (default: 960)",
)
@click.option(
    "--offset",
    type=click.IntRange(-100, 100),
    default=-15,
    help="RSSI offset in dBm (default: -15)",
)
def lora_spectrum(device, baudrate, start_freq, end_freq, offset):
    """Live Spectrum Scanner for SX1262 - Real-time frequency spectrum analyzer"""
    from ..sx1262.spectrum import SpectrumScan

    # Get device or exit with error
    dev = get_device_or_exit(device)

    # The spectral scan is driven by the RP2040 text shell (CDC2), not the
    # LoRa data stream: it sends set_start_freq/set_end_freq/start and reads
    # back the FREQ/SCAN frames on that same port.
    port = dev.shell_port
    if not port:
        print_error("Shell port not found for device! Required for spectrum scan.")
        return

    print_info(f"Using device: {dev}")
    print_info(f"Starting spectrum scan: {start_freq}-{end_freq} MHz")

    scanner = SpectrumScan(port=port, baudrate=baudrate)

    try:
        scanner.run(start_freq=start_freq, end_freq=end_freq, rssi_offset=offset)
    except KeyboardInterrupt:
        scanner.stop_task()

"""``catnip lora`` - LoRa SX1262 tools."""

# Internal
from ...core.device_utils import get_device_or_exit

# External
import click

from ...utils.cli_options import device_option
from ...utils.output import (
    console,
    print_dim,
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


def _sync_word_option(ctx, param, value):
    """Accept the firmware's own sync word spec: private|public|0xNN."""
    from protocol.sniffer_sx import normalize_syncword

    try:
        arg, _ = normalize_syncword(value)
    except ValueError as exc:
        raise click.BadParameter(str(exc))
    return arg


def _sweep_list(name):
    """Click callback for one of ``scan``'s comma-separated sweep lists.

    The parsers live in ``scan.py``, next to the ranges they enforce, and are
    resolved when an option is actually parsed rather than at import time — the
    same lazy pattern the rest of this group uses to keep ``catnip --help``
    from dragging in the scanner and the plotting stack behind it.
    """

    def callback(ctx, param, value):
        from ..sx1262 import scan

        parse = getattr(scan, name)
        try:
            return parse(value)
        except ValueError as exc:
            raise click.BadParameter(str(exc))

    return callback


@lora.command("scan")
@device_option()
@click.option(
    "--freq",
    "-f",
    "frequencies",
    default="915",
    callback=_sweep_list("parse_frequencies"),
    help=(
        "Frequencies to sweep, comma separated, in MHz (868.1,915) or Hz "
        "(915000000). Default: 915"
    ),
)
@click.option(
    "--sf",
    "spread_factors",
    default="7,8,9,10,11,12",
    callback=_sweep_list("parse_spread_factors"),
    help="Spreading factors to sweep, comma separated (7-12). Default: all",
)
@click.option(
    "--bw",
    "bandwidths",
    default="125,250,500",
    callback=_sweep_list("parse_bandwidths"),
    help="Bandwidths to sweep in kHz, comma separated (125,250,500). Default: all",
)
@click.option(
    "--dwell",
    type=click.FloatRange(0.2, 120),
    default=3.0,
    help=(
        "Seconds to listen on each combination (default: 3). A single "
        "SF12/BW125 frame is over a second on air — give the slow end more"
    ),
)
@click.option(
    "--passes",
    type=click.IntRange(0, 1000),
    default=1,
    help="Number of full sweeps; 0 repeats until Ctrl+C (default: 1)",
)
@click.option(
    "--sync-word",
    "-sw",
    default="private",
    callback=_sync_word_option,
    help=(
        "LoRa sync word: 'private' (0x12), 'public' (0x34, LoRaWAN) or any raw "
        "byte as 0xNN (e.g. 0x2B for Meshtastic). Default: private."
    ),
)
def lora_scan(
    device, frequencies, spread_factors, bandwidths, dwell, passes, sync_word
):
    """Sweep SF/BW/frequency combinations and count packets on each.

    A LoRa receiver only demodulates a frame whose spreading factor, bandwidth,
    frequency and sync word it already matches, so finding the settings of an
    unknown transmitter means trying them.  This does the trying: the host
    retunes the SX1262 between combinations while the firmware keeps streaming,
    and the live table shows which combination is hearing anything.

    \b
    Examples:
        catnip lora scan                          # 915 MHz, every SF and BW
        catnip lora scan --dwell 8                # slow traffic, longer look
        catnip lora scan -f 868.1,868.3,868.5     # the EU channels
        catnip lora scan --sf 7,9 --bw 125        # narrow the search
        catnip lora scan -sw 0x2B -f 906.875      # look for Meshtastic
        catnip lora scan --passes 0               # keep sweeping until Ctrl+C
    """
    from ..sx1262.scan import LoraScanner, build_combos, sweep_duration

    dev = get_device_or_exit(device)

    combos = build_combos(frequencies, bandwidths, spread_factors)
    estimate = sweep_duration(combos, dwell, passes)

    print_info(f"[{dev}] Sweeping {len(combos)} LoRa combination(s)")
    print_dim(f"Frequencies:  {', '.join(f'{f / 1e6:.3f} MHz' for f in frequencies)}")
    print_dim(f"Bandwidths:   {', '.join(str(b) for b in bandwidths)} kHz")
    print_dim(f"Spread:       {', '.join(f'SF{s}' for s in spread_factors)}")
    print_dim(f"Sync word:    {sync_word}")
    print_dim(f"Dwell:        {dwell:g} s")
    print_dim(
        "Estimated:    until Ctrl+C"
        if not estimate
        else f"Estimated:    {estimate / 60:.1f} min ({passes} pass(es))"
    )

    scanner = LoraScanner(
        dev,
        combos,
        dwell=dwell,
        passes=passes,
        sync_word=sync_word,
        console=console,
    )
    scanner.run()

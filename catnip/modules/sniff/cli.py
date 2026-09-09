"""``catnip sniff`` - sniffing commands (BLE, Zigbee, Thread, LoRa, AirTag)."""

import logging
import platform
import re
import subprocess

# Internal
from ..core.bridge import run_bridge, run_sx_bridge
from ..core.catnip import SniffingBaseFirmware, SniffingFirmware
from ..core.device_session import device_session
from ..core.device_utils import get_device_or_exit
from ..core.extcap import find_putty_path, run_extcap_directly
from ..core.usb_connection import open_serial_port
from ..firmware.flasher import Flasher
from protocol.sniffer_sx import normalize_syncword

# External
import click
import serial

from ..utils.cli_options import (
    ascii_file_option,
    device_option,
    force_option,
    pcap_file_option,
    raw_file_option,
)
from ..utils.output import (
    console,
    print_success,
    print_error,
    print_info,
    print_dim,
    print_warning,
    refuse_overwrite,
)

logger = logging.getLogger("rich")


def _capture_file_is_writable(pcap_file: str, force: bool) -> bool:
    """Check ``-w`` before the capture starts, not once it is under way.

    The bridge refuses to clobber an existing capture file anyway, but by then
    the device has been flashed, the port opened and the radio configured — so
    the same check runs here first and the command exits having done nothing.
    """
    return refuse_overwrite(pcap_file, force=force, mode="block")


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("-v", "--verbose", is_flag=True, help="Show Verbose mode")
def sniff(verbose):
    """Sniffer protocol control"""
    if verbose:
        logger.level = logging.INFO
    pass


@sniff.command(SniffingFirmware.BLE.name.lower())
@device_option()
@click.option(
    "--wireshark",
    "-ws",
    is_flag=True,
    help="Open Wireshark with Sniffle extcap plugin",
)
@click.option(
    "--channel",
    "-c",
    default=37,
    type=click.IntRange(37, 39),
    help="BLE advertising channel (37, 38, 39)",
)
@click.option(
    "--mode",
    "-m",
    default="conn_follow",
    type=click.Choice(["conn_follow", "passive_scan", "active_scan"]),
    help="Sniffle mode",
)
def sniff_ble(device, wireshark, channel, mode):
    """Sniffing BLE with Sniffle firmware.

    \b
    Examples:
        catnip sniff ble                    # ready for manual Wireshark setup
        catnip sniff ble --wireshark        # auto-open Wireshark
        catnip sniff ble -c 39 -m passive_scan
    """
    with device_session(
        device,
        required_firmware=SniffingBaseFirmware.BLE.value,
        flasher=Flasher(),
        verify_retries=2,
    ) as dev:
        if wireshark:
            # Always use the direct method when --wireshark is specified
            success = run_extcap_directly(dev.bridge_port, channel, mode)

            if not success:
                print_error(
                    "Could not open Wireshark automatically using direct method"
                )
                print_info("\nYou can try manual configuration:")
                print_info("1. Open Wireshark manually")
                print_info("2. Press Ctrl+E for Capture Options")
                print_info("3. Select 'sniffle' interface")
                print_info(f"4. Configure port: {dev.bridge_port}")
        else:
            print_info("Sniffle firmware is ready!")
            print_info("\nTo capture with Wireshark:")
            print_info(f"1. Open Wireshark and select 'sniffle' interface")
            print_info(f"2. Configure serial port: {dev.bridge_port}")
            print_info(f"3. Set channel: {channel}")
            print_info(f"4. Set mode: {mode}")


@sniff.command(SniffingFirmware.ZIGBEE.name.lower())
@click.option("-ws", is_flag=True, help="Open Wireshark")
@click.option(
    "--channel", "-c", required=True, type=click.IntRange(11, 26), help="Zigbee channel"
)
@device_option()
@raw_file_option()
@ascii_file_option()
@pcap_file_option()
@force_option()
def sniff_zigbee(ws, channel, device, raw_file, ascii_file, pcap_file, force):
    """Sniffing Zigbee with Sniffer TI firmware.

    \b
    Examples:
        catnip sniff zigbee -c 15
        catnip sniff zigbee -c 15 -ws              # open Wireshark
        catnip sniff zigbee -c 15 -r capture.raw   # save raw log to file
        catnip sniff zigbee -c 15 -w capture.pcap  # save a capture for tshark
    """
    if not _capture_file_is_writable(pcap_file, force):
        raise SystemExit(1)

    with device_session(
        device,
        required_firmware="ti_sniffer",
        flasher=Flasher(),
        post_flash_wait=0.5,
        verify_retries=0,
    ) as dev:
        print_info(f"[{dev}] Sniffing Zigbee at channel: {channel}")
        if raw_file:
            print_dim(f"Raw log:          {raw_file}")
        if ascii_file:
            print_dim(f"ASCII log:        {ascii_file}")
        if pcap_file:
            print_dim(f"Capture file:     {pcap_file}")
        run_bridge(
            dev,
            channel,
            ws,
            profile="Zigbee",
            raw_file=raw_file,
            ascii_file=ascii_file,
            pcap_file=pcap_file,
            force=force,
        )


@sniff.command(SniffingFirmware.THREAD.name.lower())
@click.option("-ws", is_flag=True, help="Open Wireshark")
@click.option(
    "--channel", "-c", required=True, type=click.IntRange(11, 26), help="Thread channel"
)
@device_option()
@raw_file_option()
@ascii_file_option()
@pcap_file_option()
@force_option()
def sniff_thread(ws, channel, device, raw_file, ascii_file, pcap_file, force):
    """Sniffing Thread with Sniffer TI firmware.

    \b
    Examples:
        catnip sniff thread -c 15
        catnip sniff thread -c 15 -ws              # open Wireshark
        catnip sniff thread -c 15 -w capture.pcap  # save a capture for tshark
    """
    if not _capture_file_is_writable(pcap_file, force):
        raise SystemExit(1)

    with device_session(
        device,
        required_firmware="ti_sniffer",
        flasher=Flasher(),
        post_flash_wait=0.5,
        verify_retries=0,
    ) as dev:
        print_info(f"[{dev}] Sniffing Thread at channel: {channel}")
        if raw_file:
            print_dim(f"Raw log:          {raw_file}")
        if ascii_file:
            print_dim(f"ASCII log:        {ascii_file}")
        if pcap_file:
            print_dim(f"Capture file:     {pcap_file}")
        run_bridge(
            dev,
            channel,
            ws,
            profile="Thread",
            raw_file=raw_file,
            ascii_file=ascii_file,
            pcap_file=pcap_file,
            force=force,
        )


def _validate_sync_word(ctx, param, value):
    """Accept the firmware's own sync word spec: private|public|0xNN."""
    try:
        arg, _ = normalize_syncword(value)
    except ValueError as exc:
        raise click.BadParameter(str(exc))
    return arg


@sniff.command(SniffingFirmware.LORA.name.lower())
@click.option("-ws", is_flag=True, help="Open Wireshark")
@click.option("-v", "--verbose", is_flag=True, help="Show verbose output in terminal")
@click.option(
    "--frequency",
    "-freq",
    default=915000000,
    type=click.IntRange(150000000, 960000000),
    help="Frequency in Hz, 150-960 MHz (e.g., 915000000 for 915 MHz)",
)
@click.option(
    "--bandwidth",
    "-bw",
    # The default has to be one of the *strings* in the Choice: Click 8.0/8.1
    # match the default against the choices without coercing it, so an int 125
    # made `sniff lora` unusable without an explicit -bw ("125 is not one of
    # '125', '250', '500'").  Click >=8.2 stringifies first and hid the bug.
    # `bw_int` below converts it back for the bridge.
    default="125",
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
    type=click.IntRange(-9, 22),
    help="TX Power in dBm (-9 to 22, SX1262 hardware range)",
)
@device_option()
@click.option(
    "--sync-word",
    "-sw",
    default="private",
    callback=_validate_sync_word,
    help=(
        "LoRa sync word: 'public' (0x34, LoRaWAN), 'private' (0x12) or any raw "
        "byte as 0xNN (e.g. 0x2B for Meshtastic). Default: private."
    ),
)
@click.option(
    "--preamble",
    "-pre",
    default=12,
    type=click.IntRange(6, 65535),
    help="Preamble length in symbols (6-65535). Default: 12.",
)
@click.option(
    "--iq",
    default="normal",
    type=click.Choice(["normal", "inverted"]),
    help="IQ polarity. LoRaWAN downlinks need 'inverted'. Default: normal.",
)
@raw_file_option(
    help="Save captured packets as raw hex to FILE (RX: <hex> | RSSI: <rssi> | SNR: <snr>)"
)
@ascii_file_option(
    help="Save captured packets as decoded ASCII to FILE (RX: <ascii> | RSSI: <rssi> | SNR: <snr>)"
)
@pcap_file_option()
@force_option()
def sniff_lora(
    ws,
    verbose,
    frequency,
    bandwidth,
    spread_factor,
    coding_rate,
    tx_power,
    device,
    sync_word,
    preamble,
    iq,
    raw_file,
    ascii_file,
    pcap_file,
    force,
):
    """Sniffing LoRa with Sniffer SX1262 firmware.

    \b
    Examples:
        catnip sniff lora                          # defaults: 915MHz, SF7, BW125
        catnip sniff lora -freq 868000000 -sf 9
        catnip sniff lora -ws                      # open Wireshark
        catnip sniff lora -sw 0x2B -pre 16         # Meshtastic sync word
        catnip sniff lora -sw public --iq inverted # LoRaWAN downlinks
        catnip sniff lora -w capture.pcapng        # save a capture for tshark
    """
    if not _capture_file_is_writable(pcap_file, force):
        raise SystemExit(1)

    dev = get_device_or_exit(device)

    # Convert bandwidth from string to int
    bw_int = int(bandwidth)

    print_info(f"[{dev}] Sniffing LoRa with configuration:")
    print_dim(f"Frequency:        {frequency} Hz ({frequency / 1000000:.3f} MHz)")
    print_dim(f"Bandwidth:        {bw_int} kHz")
    print_dim(f"Spreading Factor: SF{spread_factor}")
    print_dim(f"Coding Rate:      4/{coding_rate}")
    print_dim(f"TX Power:         {tx_power} dBm")
    print_dim(f"Sync Word:        {sync_word}")
    print_dim(f"Preamble:         {preamble} symbols")
    print_dim(f"IQ:               {iq}")
    if raw_file:
        print_dim(f"Raw log:          {raw_file}")
    if ascii_file:
        print_dim(f"ASCII log:        {ascii_file}")
    if pcap_file:
        print_dim(f"Capture file:     {pcap_file}")

    run_sx_bridge(
        dev,
        frequency,
        bw_int,
        spread_factor,
        coding_rate,
        tx_power,
        ws,
        verbose,
        sync_word,
        preamble,
        iq,
        raw_file,
        ascii_file,
        pcap_file,
        force,
    )


_AIRTAG_BAUDRATE = 9600

# Log-distance path-loss model: distance = 10 ** ((txPowerAt1m - rssi) / (10 * n)).
# There is no calibration data for the AirTag's actual TX power, so
# txPowerAt1m/n are just typical BLE-beacon defaults — treat the result as an
# order-of-magnitude estimate, not a measurement.
_AIRTAG_TX_POWER_AT_1M = -59  # dBm, RSSI expected at 1 meter
_AIRTAG_PATH_LOSS_EXPONENT = 2.0  # ~2 free space, ~3-4 indoors/obstructed

_AIRTAG_LINE_RE = re.compile(
    r"Airtag detected! -> (?P<addr>\S+) RSSI:(?P<rssi>-?\d+) Status: (?P<status>.+)"
)


def _estimate_distance_m(rssi: int) -> float:
    """Rough distance estimate (meters) from RSSI via the log-distance path-loss model."""
    return 10 ** ((_AIRTAG_TX_POWER_AT_1M - rssi) / (10 * _AIRTAG_PATH_LOSS_EXPONENT))


def _stream_airtag_scanner(port: str) -> None:
    ser = open_serial_port(port, baudrate=_AIRTAG_BAUDRATE, timeout=0.5)
    if ser is None:
        print_error(f"Could not open {port} at {_AIRTAG_BAUDRATE} baud")
        return

    print_success(
        f"Listening on {port} at {_AIRTAG_BAUDRATE} baud — press Ctrl+C to stop"
    )

    detections = 0
    try:
        while True:
            try:
                raw = ser.readline()
            except serial.SerialException as exc:
                print_warning(f"Serial error (device disconnected?): {exc}")
                break

            if not raw:
                continue

            line = raw.decode("ascii", errors="replace").strip()
            if not line:
                continue

            match = _AIRTAG_LINE_RE.search(line)
            if not match:
                print_dim(line)
                continue

            detections += 1
            rssi = int(match.group("rssi"))
            distance_m = _estimate_distance_m(rssi)
            console.print(
                f"[green][{detections:>4}][/green] AirTag [bold]{match.group('addr')}[/bold]  "
                f"RSSI=[cyan]{rssi:>4} dBm[/cyan]  "
                f"~distance=[yellow]{distance_m:.1f} m[/yellow]  "
                f"({match.group('status')})"
            )
    except KeyboardInterrupt:
        print_info(f"Stopped — {detections} AirTag detection(s) captured")
    finally:
        ser.close()


@sniff.command(SniffingFirmware.AIRTAG_SCANNER.name.lower())
@device_option()
@click.option(
    "--putty", is_flag=True, help="Open PuTTY with serial configuration instead"
)
def sniff_airtag_scanner(device, putty):
    """Sniffing Airtag Scanner firmware.

    Prints each detected AirTag directly in this terminal, along with its
    RSSI and an approximate distance estimate.

    \b
    Examples:
        catnip sniff airtag_scanner
        catnip sniff airtag_scanner --putty    # auto-open PuTTY at 9600 baud instead
    """
    # Must match ALIAS_TO_OFFICIAL_ID in fw_aliases.py
    official_id = "airtag_scanner_cc1352p7"

    with device_session(
        device,
        required_firmware=official_id,
        flasher=Flasher(),
        verify_retries=0,
    ) as dev:
        if putty:
            putty_path = find_putty_path()
            if not putty_path:
                print_error(
                    "PuTTY not found! Make sure it is installed and in your PATH."
                )
                if platform.system() == "Linux":
                    print_info(
                        "On Linux, you can install it with: sudo apt install putty"
                    )
                elif platform.system() == "Darwin":
                    print_info("On macOS, you can install it with: brew install putty")
                return

            print_info(f"Opening PuTTY on {dev.bridge_port} at 9600 baud...")
            try:
                # putty -serial [port] -sercfg 9600,8,n,1,n
                cmd = [
                    putty_path,
                    "-serial",
                    dev.bridge_port,
                    "-sercfg",
                    "9600,8,n,1,n",
                ]
                subprocess.Popen(cmd)
                print_success("PuTTY launched successfully!")
            except Exception as e:
                print_error(f"Failed to launch PuTTY: {str(e)}")
        else:
            _stream_airtag_scanner(dev.bridge_port)

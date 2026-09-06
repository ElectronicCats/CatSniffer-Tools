"""``catnip sniff`` - sniffing commands (BLE, Zigbee, Thread, LoRa, AirTag)."""

import logging
import platform
import subprocess

# Internal
from ..core.bridge import run_bridge, run_sx_bridge
from ..core.catnip import SniffingBaseFirmware, SniffingFirmware
from ..core.device_session import device_session
from ..core.device_utils import get_device_or_exit
from ..core.extcap import find_putty_path, run_extcap_directly
from ..firmware.flasher import Flasher

# External
import click

from ..utils.cli_options import ascii_file_option, device_option, raw_file_option
from ..utils.output import (
    print_success,
    print_error,
    print_info,
    print_dim,
)

logger = logging.getLogger("rich")


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
def sniff_zigbee(ws, channel, device, raw_file, ascii_file):
    """Sniffing Zigbee with Sniffer TI firmware.

    \b
    Examples:
        catnip sniff zigbee -c 15
        catnip sniff zigbee -c 15 -ws              # open Wireshark
        catnip sniff zigbee -c 15 -r capture.raw   # save raw log to file
    """
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
        run_bridge(
            dev,
            channel,
            ws,
            profile="Zigbee",
            raw_file=raw_file,
            ascii_file=ascii_file,
        )


@sniff.command(SniffingFirmware.THREAD.name.lower())
@click.option("-ws", is_flag=True, help="Open Wireshark")
@click.option(
    "--channel", "-c", required=True, type=click.IntRange(11, 26), help="Thread channel"
)
@device_option()
@raw_file_option()
@ascii_file_option()
def sniff_thread(ws, channel, device, raw_file, ascii_file):
    """Sniffing Thread with Sniffer TI firmware.

    \b
    Examples:
        catnip sniff thread -c 15
        catnip sniff thread -c 15 -ws              # open Wireshark
    """
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
        run_bridge(
            dev,
            channel,
            ws,
            profile="Thread",
            raw_file=raw_file,
            ascii_file=ascii_file,
        )


@sniff.command(SniffingFirmware.LORA.name.lower())
@click.option("-ws", is_flag=True, help="Open Wireshark")
@click.option("-v", "--verbose", is_flag=True, help="Show verbose output in terminal")
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
@device_option()
@click.option(
    "--sync-word",
    "-sw",
    default="private",
    type=click.Choice(["public", "private"]),
    help="LoRa sync word: 'public' (0x34, LoRaWAN) or 'private' (0x12). Default: private.",
)
@raw_file_option(
    help="Save captured packets as raw hex to FILE (RX: <hex> | RSSI: <rssi> | SNR: <snr>)"
)
@ascii_file_option(
    help="Save captured packets as decoded ASCII to FILE (RX: <ascii> | RSSI: <rssi> | SNR: <snr>)"
)
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
    raw_file,
    ascii_file,
):
    """Sniffing LoRa with Sniffer SX1262 firmware.

    \b
    Examples:
        catnip sniff lora                          # defaults: 915MHz, SF7, BW125
        catnip sniff lora -freq 868000000 -sf 9
        catnip sniff lora -ws                      # open Wireshark
    """
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
    if raw_file:
        print_dim(f"Raw log:          {raw_file}")
    if ascii_file:
        print_dim(f"ASCII log:        {ascii_file}")

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
        raw_file,
        ascii_file,
    )


@sniff.command(SniffingFirmware.AIRTAG_SCANNER.name.lower())
@device_option()
@click.option("--putty", is_flag=True, help="Open PuTTY with serial configuration")
def sniff_airtag_scanner(device, putty):
    """Sniffing Airtag Scanner firmware.

    \b
    Examples:
        catnip sniff airtag_scanner
        catnip sniff airtag_scanner --putty    # auto-open PuTTY at 9600 baud
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
            print_info("Airtag Scanner firmware is ready!")
            print_info(
                f"\nConnect to {dev.bridge_port} at 9600 baud to see the output."
            )

"""``catnip sniff`` - sniffing commands (BLE, Zigbee, Thread, LoRa, AirTag)."""

import logging
import platform
import subprocess
import time

# Internal
from ..core.bridge import run_bridge, run_sx_bridge
from ..core.catnip import Catnip, SniffingBaseFirmware, SniffingFirmware
from ..core.device_utils import get_device_or_exit, send_identify_command
from ..core.extcap import find_putty_path, run_extcap_directly
from ..firmware.flasher import Flasher

# External
import click

from ..utils.output import (
    print_success,
    print_warning,
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
@click.option(
    "--device",
    "-d",
    default=None,
    type=int,
    help="Device ID (for multiple CatSniffers)",
)
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
    """Sniffing BLE with Sniffle firmware"""
    flasher = Flasher()
    dev = get_device_or_exit(device)

    # Verify firmware
    cat = Catnip(dev.bridge_port)

    # Notify user that we are checking for firmware
    print_info("Checking for Sniffle firmware...")

    # Try verification with metadata
    firmware_found = False

    if cat.check_firmware_by_metadata("sniffle", dev.shell_port):
        print_success("Sniffle firmware found (via metadata)!")
        firmware_found = True
    elif cat.check_sniffle_firmware_smart(dev.shell_port):
        print_success("Sniffle firmware found (via direct communication)!")
        firmware_found = True

    if not firmware_found:
        print_warning("Sniffle firmware not found! - Flashing Sniffle")

        # Flash firmware
        if not flasher.find_flash_firmware(SniffingBaseFirmware.BLE.value, dev):
            print_error("Failed to flash Sniffle firmware")
            return

        # LONGER WAIT AND VERIFICATION RETRIES
        print_info("Waiting for device to initialize after flashing...")
        time.sleep(1)

        # Retry verification several times
        verified = False
        for attempt in range(3):
            print_info(f"Verifying firmware (attempt {attempt + 1}/3)...")

            # Create a new Catnip instance to avoid connection issues
            cat = Catnip(dev.bridge_port)

            # Flush serial buffers before verification
            try:
                cat.connect()
                if cat.connection:
                    cat.connection.reset_input_buffer()
                    cat.connection.reset_output_buffer()
                    cat.disconnect()
            except:
                pass

            if cat.check_firmware_by_metadata("sniffle", dev.shell_port):
                print_success("Sniffle firmware verified successfully (via metadata)!")
                verified = True
                break
            elif cat.check_sniffle_firmware_smart(dev.shell_port):
                print_success(
                    "Sniffle firmware verified successfully (via direct communication)!"
                )
                verified = True
                break

            time.sleep(0.5)

        if not verified:
            print_error("Firmware verification failed after multiple attempts!")
            print_info("The device may still work, but metadata is not set.")
            print_info(
                "You can try running: catnip sniff ble -d 1 again in a few seconds."
            )
            # We don't return, allow to continue anyway

    # Send identification command to help identify which device was flashed
    send_identify_command(dev)

    if wireshark:
        # Always use the direct method when --wireshark is specified
        success = run_extcap_directly(dev.bridge_port, channel, mode)

        if not success:
            print_error("Could not open Wireshark automatically using direct method")
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
@click.option(
    "--device",
    "-d",
    default=None,
    type=int,
    help="Device ID (for multiple CatSniffers)",
)
@click.option(
    "--raw",
    "-r",
    "raw_file",
    default=None,
    type=click.Path(dir_okay=False, writable=True),
    help="Save captured packets as raw hex to FILE (RX: <hex> | RSSI: <rssi>)",
)
@click.option(
    "-ascii",
    "--ascii",
    "ascii_file",
    default=None,
    type=click.Path(dir_okay=False, writable=True),
    help="Save captured packets as decoded ASCII to FILE (RX: <ascii> | RSSI: <rssi>)",
)
def sniff_zigbee(ws, channel, device, raw_file, ascii_file):
    """Sniffing Zigbee with Sniffer TI firmware"""
    flasher = Flasher()
    dev = get_device_or_exit(device)
    cat = Catnip(dev.bridge_port)
    # Verify firmware with metadata (preferred)
    print_info("Checking for Sniffer TI firmware...")
    if cat.check_firmware_by_metadata("ti_sniffer", dev.shell_port):
        print_success("Sniffer TI firmware found (via metadata)!")
    elif cat.check_ti_firmware():
        print_success("Sniffer TI firmware found (via direct communication)!")
    else:
        print_warning("Sniffer TI firmware not found! - Flashing Sniffer TI")
        if not flasher.find_flash_firmware("ti_sniffer", dev):
            return

        print_info("Waiting for device to initialize...")
        time.sleep(0.5)

    # Send identification command to help identify which device was flashed
    send_identify_command(dev)

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
@click.option(
    "--device",
    "-d",
    default=None,
    type=int,
    help="Device ID (for multiple CatSniffers)",
)
@click.option(
    "--raw",
    "-r",
    "raw_file",
    default=None,
    type=click.Path(dir_okay=False, writable=True),
    help="Save captured packets as raw hex to FILE (RX: <hex> | RSSI: <rssi>)",
)
@click.option(
    "-ascii",
    "--ascii",
    "ascii_file",
    default=None,
    type=click.Path(dir_okay=False, writable=True),
    help="Save captured packets as decoded ASCII to FILE (RX: <ascii> | RSSI: <rssi>)",
)
def sniff_thread(ws, channel, device, raw_file, ascii_file):
    """Sniffing Thread with Sniffer TI firmware"""
    flasher = Flasher()
    dev = get_device_or_exit(device)
    cat = Catnip(dev.bridge_port)
    # Verify firmware with metadata (preferred)
    print_info("Checking for Sniffer TI firmware...")
    if cat.check_firmware_by_metadata("ti_sniffer", dev.shell_port):
        print_success("Sniffer TI firmware found (via metadata)!")
    elif cat.check_ti_firmware():
        print_success("Sniffer TI firmware found (via direct communication)!")
    else:
        print_warning("Sniffer TI firmware not found! - Flashing Sniffer TI")
        if not flasher.find_flash_firmware("ti_sniffer", dev):
            return

        print_info("Waiting for device to initialize...")
        time.sleep(0.5)

    # Send identification command to help identify which device was flashed
    send_identify_command(dev)

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
@click.option(
    "--device",
    "-d",
    default=None,
    type=int,
    help="Device ID (for multiple CatSniffers)",
)
@click.option(
    "--sync-word",
    "-sw",
    default="private",
    type=click.Choice(["public", "private"]),
    help="LoRa sync word: 'public' (0x34, LoRaWAN) or 'private' (0x12). Default: private.",
)
@click.option(
    "--raw",
    "-r",
    "raw_file",
    default=None,
    type=click.Path(dir_okay=False, writable=True),
    help="Save captured packets as raw hex to FILE (RX: <hex> | RSSI: <rssi> | SNR: <snr>)",
)
@click.option(
    "-ascii",
    "--ascii",
    "ascii_file",
    default=None,
    type=click.Path(dir_okay=False, writable=True),
    help="Save captured packets as decoded ASCII to FILE (RX: <ascii> | RSSI: <rssi> | SNR: <snr>)",
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
    """Sniffing LoRa with Sniffer SX1262 firmware"""
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
@click.option(
    "--device",
    "-d",
    default=None,
    type=int,
    help="Device ID (for multiple CatSniffers)",
)
@click.option("--putty", is_flag=True, help="Open PuTTY with serial configuration")
def sniff_airtag_scanner(device, putty):
    """Sniffing Airtag Scanner firmware"""
    flasher = Flasher()
    dev = get_device_or_exit(device)

    # Verify firmware
    cat = Catnip(dev.bridge_port)

    # Notify user that we are checking for firmware
    print_info("Checking for Airtag Scanner firmware...")

    # Define the official ID for Airtag Scanner
    # This must match ALIAS_TO_OFFICIAL_ID in fw_aliases.py
    official_id = "airtag_scanner_cc1352p7"

    # Try verification with metadata
    firmware_found = False

    if cat.check_firmware_by_metadata(official_id, dev.shell_port):
        print_success("Airtag Scanner firmware found (via metadata)!")
        firmware_found = True

    if not firmware_found:
        print_warning("Airtag Scanner firmware not found! - Flashing Airtag Scanner")

        # Flash firmware
        if not flasher.find_flash_firmware(official_id, dev):
            print_error("Failed to flash Airtag Scanner firmware")
            return

        # Wait for device to initialize
        print_info("Waiting for device to initialize after flashing...")
        time.sleep(1)

        # Verify
        if cat.check_firmware_by_metadata(official_id, dev.shell_port):
            print_success("Airtag Scanner firmware verified successfully!")
        else:
            print_warning("Firmware verification failed, but continuing...")

    # Send identification command to help identify which device was flashed
    send_identify_command(dev)

    if putty:
        putty_path = find_putty_path()
        if not putty_path:
            print_error("PuTTY not found! Make sure it is installed and in your PATH.")
            if platform.system() == "Linux":
                print_info("On Linux, you can install it with: sudo apt install putty")
            elif platform.system() == "Darwin":
                print_info("On macOS, you can install it with: brew install putty")
            return

        print_info(f"Opening PuTTY on {dev.bridge_port} at 9600 baud...")
        try:
            # putty -serial [port] -sercfg 9600,8,n,1,n
            cmd = [putty_path, "-serial", dev.bridge_port, "-sercfg", "9600,8,n,1,n"]
            subprocess.Popen(cmd)
            print_success("PuTTY launched successfully!")
        except Exception as e:
            print_error(f"Failed to launch PuTTY: {str(e)}")
    else:
        print_info("Airtag Scanner firmware is ready!")
        print_info(f"\nConnect to {dev.bridge_port} at 9600 baud to see the output.")

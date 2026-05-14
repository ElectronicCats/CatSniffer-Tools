#! /usr/bin/env python3

# Electronic Cats
# Original Creation Date: Dec 19, 2025
# This code is beerware; if you see me (or any other Electronic Cats
# member) at the local, and you've found our code helpful,
# please buy us a round!
# Distributed as-is; no warranty is given.

import logging
import os
import tempfile
import threading
import sys
import queue

# Internal
from ..utils._version import __version__
from ..firmware.flasher import Flasher
from ..firmware.verify import run_verification
from .pipes import Wireshark, UnixPipe, WindowsPipe
from .bridge import run_bridge, run_sx_bridge
from .catnip import (
    SniffingFirmware,
    SniffingBaseFirmware,
    Catnip,
    CatSnifferDevice,
    catnip_get_device,
    catnip_get_devices,
)
from .usb_connection import ShellConnection, CATSNIFFER_VID, CATSNIFFER_PID

# External
import click
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich import box

from ..utils.output import (
    console,
    STYLES,
    print_success,
    print_warning,
    print_error,
    print_info,
    print_dim,
    print_empty_line,
    print_title,
    print_subtitle,
    print_example,
    print_alias_item,
)

import subprocess
import platform
import time
from pathlib import Path

# APP Information
VERSION_NUMBER = __version__
COMPANY = "Electronic Cats - PWNLAB"
_FUNNY_PHRASES = [
    "Catching packets, not mice.",
    "Your RF spy in the sky.",
    "Sniffing the air so you don't have to.",
    "Making invisible waves visible.",
    "The only cat that loves antennas.",
    "Packet sniffer. Not a drug.",
    "Who said curiosity killed the cat?",
    "Zigbee, Thread, LoRa — we don't discriminate.",
    "Turning radio waves into trust issues.",
    "Your neighbor's smart bulb has secrets.",
    "Legally (probably) sniffing since 2024.",
    "Because plaintext is a lifestyle choice.",
    "RF doesn't lie. People do.",
    "We sniff, you learn.",
    "Not all heroes wear capes. Some carry antennas.",
    "What even is encryption?",
    "The air is full of data. Help yourself.",
    "Meow. That was a Zigbee beacon.",
    "If it transmits, we see it.",
    "BLE, LoRa, Thread — all your protocols belong to us.",
    "Your Meshtastic network is not as private as you think.",
    "802.15.4 never had a chance.",
    "From 433MHz to 2.4GHz, we catch them all.",
    "LoRa? More like LoRa-caught.",
    "Sub-GHz whisperer.",
]

import random as _random

FUNNY_PHRASE = _random.choice(_FUNNY_PHRASES)

wireshark = Wireshark()

logger = logging.getLogger("rich")
FORMAT = "%(message)s"
logging.basicConfig(
    level="WARNING", format=FORMAT, datefmt="[%X]", handlers=[RichHandler(markup=True)]
)


def print_header(module=None):
    """Print the ASCII art header"""
    if module:
        label = f"catnip {module}"
    elif platform.system() != "Windows" and os.geteuid() == 0:
        label = "catnip: (root)"
    else:
        label = "catnip"

    ascii_art = f"""      :=--             --=-       |
      -====-         -=====       |
      :===================-       |
       ===================:       |
  -   :==--===========--==-   -   |  {label}
 -===:===-   :=====-   -==-.-=--  |  v{VERSION_NUMBER}
--    ====-   :===-   -====    -- |  {FUNNY_PHRASE}
-=:   :===================-   .=- |
 ---=-- -===============-  -=---  |
 ---       --=======--        --  |"""

    colored_ascii = f"[cyan bold]{ascii_art}[/cyan bold]"

    header_panel = Panel(
        colored_ascii,
        title=f"[cyan]{COMPANY}[/cyan]",
        border_style=STYLES["header"],
        title_align="left",
        padding=(1, 2),
    )
    console.print(header_panel)


def get_device_or_exit(device_id=None):
    """Get CatSniffer device or exit with error."""
    device = catnip_get_device(device_id)
    if device is None:
        print_error("No CatSniffer device found!")
        print_dim("Make sure your CatSniffer is connected.")
        exit(1)
    if not device.is_valid():
        print_warning(f"Not all ports detected for {device}")
        print_dim(f"Bridge: {device.bridge_port}")
        print_dim(f"LoRa:   {device.lora_port}")
        print_dim(f"Shell:  {device.shell_port}")
    return device


def find_wireshark_path():
    """Find Wireshark executable path."""
    system = platform.system()

    if system == "Windows":
        paths = [
            Path("C:\\Program Files\\Wireshark\\Wireshark.exe"),
            Path("C:\\Program Files (x86)\\Wireshark\\Wireshark.exe"),
        ]
    elif system == "Linux":
        paths = [
            Path("/usr/bin/wireshark"),
            Path("/usr/local/bin/wireshark"),
        ]
    elif system == "Darwin":
        paths = [
            Path("/Applications/Wireshark.app/Contents/MacOS/Wireshark"),
        ]
    else:
        return None

    for path in paths:
        if path.exists():
            return str(path)
    return None


def find_putty_path():
    """Find PuTTY executable path."""
    system = platform.system()

    if system == "Windows":
        paths = [
            Path("C:\\Program Files\\PuTTY\\putty.exe"),
            Path("C:\\Program Files (x86)\\PuTTY\\putty.exe"),
        ]
    elif system in ["Linux", "Darwin"]:
        paths = [
            Path("/usr/bin/putty"),
            Path("/usr/local/bin/putty"),
            Path("/opt/homebrew/bin/putty"),  # macOS Homebrew
        ]
    else:
        return None

    for path in paths:
        if path.exists():
            return str(path)

    # Also search in PATH
    which_cmd = "where" if system == "Windows" else "which"
    try:
        result = subprocess.run([which_cmd, "putty"], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    except:
        pass

    return None


def open_wireshark_sniffle_simple(port, channel=37):
    """Simple method to open Wireshark with Sniffle."""
    wireshark_path = find_wireshark_path()

    if not wireshark_path:
        print_error("Wireshark not found!")
        return False

    # Simple method: open Wireshark and give instructions
    print_info("Opening Wireshark...")
    print_info("Please configure manually:")
    print_info("\n1. In Wireshark, go to Capture → Options")
    print_info("2. Select 'sniffle' from the interface list")
    print_info("3. Click the gear/cog icon next to it")
    print_info(f"4. Set Serial Port to: {port}")
    print_info(f"5. Set Advertising Channel to: {channel}")
    print_info("6. Click 'Start'")

    try:
        # Only open Wireshark
        cmd = [wireshark_path]
        process = subprocess.Popen(cmd)

        # Give detailed instructions after opening
        time.sleep(1)  # Give Wireshark time to open

        print_info("\n" + "=" * 50)
        print_info("MANUAL CONFIGURATION REQUIRED")
        print_info("=" * 50)
        print_info("After Wireshark opens:")
        print_info("1. Press Ctrl+E to open Capture Options")
        print_info("2. Find 'sniffle' in the list (usually near the bottom)")
        print_info("3. Click the configuration button (gear icon)")
        print_info(f"4. Enter serial port: {port}")
        print_info(f"5. Select channel: {channel}")
        print_info("6. Click 'OK' then 'Start'")

        return True

    except Exception as e:
        print_error(f"Failed to open Wireshark: {str(e)}")
        return False


def run_extcap_directly(port, channel=37, mode="conn_follow", **kwargs):
    """Run Sniffle extcap directly and bridge it to Wireshark."""
    try:
        system = platform.system()

        # 1. Set up PCAP pipes
        # pipe_ws: The pipe Wireshark will read from
        # pipe_plugin: The pipe the plugin will write to
        pipe_ws = WindowsPipe() if system == "Windows" else UnixPipe()

        # Use a unique name for the internal plugin pipe to avoid conflicts
        plugin_pipe_name = f"sniffle_plugin_{os.getpid()}"
        if system == "Windows":
            pipe_plugin = WindowsPipe(path=f"\\\\.\\pipe\\{plugin_pipe_name}")
        else:
            temp_dir = tempfile.gettempdir()
            pipe_plugin = UnixPipe(path=os.path.join(temp_dir, plugin_pipe_name))

        # 2. Open pipes in background threads
        threading.Thread(target=pipe_ws.open, daemon=True).start()
        # Plugin pipe needs to be opened for READING by catnip
        if system == "Windows":
            threading.Thread(target=pipe_plugin.open, daemon=True).start()
        else:
            # On Linux, open() blocks, so we do it in a thread
            threading.Thread(target=pipe_plugin.open, args=("rb",), daemon=True).start()

        # 3. Command to run the plugin
        extcap_path = find_extcap_plugin("sniffle_extcap")
        if not extcap_path:
            pipe_ws.remove()
            pipe_plugin.remove()
            return False

        # Use sys.executable for .py files, or call .exe directly on Windows
        if extcap_path.endswith(".py"):
            cmd = [sys.executable, extcap_path]
        else:
            cmd = [extcap_path]

        cmd.extend(
            [
                "--capture",
                "--extcap-interface",
                "sniffle",
                "--fifo",
                pipe_plugin.pipe_path,
                "--serport",
                port,
                "--mode",
                mode,
                "--advchan",
                str(channel),
            ]
        )

        # 4. Start the plugin FIRST
        print_info(f"Starting Sniffle extcap...")
        extcap_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False
        )

        # 5. Bridge worker: Cache the header and then relay
        stop_event = threading.Event()
        header_captured = threading.Event()
        cached_data = []

        # Thread to relay stderr to console for debugging
        def stderr_worker():
            try:
                for line in extcap_proc.stderr:
                    if line:
                        print_dim(f"[extcap] {line.decode().strip()}")
            except Exception:
                pass

        threading.Thread(target=stderr_worker, daemon=True).start()

        def bridge_worker():
            try:
                # Wait for plugin to connect and send the initial header
                if not pipe_plugin.ready_event.wait(timeout=30):
                    return

                # Read initial PCAP header; on Windows read() is non-blocking so loop
                while not stop_event.is_set():
                    first_chunk = pipe_plugin.read(4096)
                    if first_chunk:
                        cached_data.append(first_chunk)
                        header_captured.set()
                        break
                    if extcap_proc.poll() is not None:
                        return
                    time.sleep(0.01)

                # Now wait for Wireshark to be ready (this is set after launching Wireshark)
                pipe_ws.ready_event.wait(timeout=35)

                # Send cached header
                for chunk in cached_data:
                    pipe_ws.write_packet(chunk)
                cached_data.clear()

                while not stop_event.is_set():
                    data = pipe_plugin.read(4096)
                    if not data:
                        # If no data, check if plugin is still alive
                        if extcap_proc.poll() is not None:
                            print_warning("Plugin process terminated")
                            break
                        # Short sleep to avoid CPU spinning
                        time.sleep(0.01)
                        continue

                    # If Wireshark is gone, stop bridging
                    if ws.wireshark_process and ws.wireshark_process.poll() is not None:
                        break

                    pipe_ws.write_packet(data)
            except Exception as e:
                print_error(f"Bridge error: {str(e)}")
                pass

        threading.Thread(target=bridge_worker, daemon=True).start()

        # 6. Wait for the plugin to emit the header before launching Wireshark
        print_info("Waiting for sniffer data...")
        if not header_captured.wait(timeout=15):
            print_error("Timed out waiting for sniffer header")
            stop_event.set()
            extcap_proc.terminate()
            pipe_ws.remove()
            pipe_plugin.remove()
            return False

        # 7. NOW launch Wireshark
        ws = Wireshark()
        ws.start()

        # 8. Wait for Wireshark connection
        print_info("Connecting to Wireshark...")
        if not pipe_ws.ready_event.wait(timeout=30):
            print_error("Timed out waiting for Wireshark to connect")
            stop_event.set()
            extcap_proc.terminate()
            pipe_ws.remove()
            pipe_plugin.remove()
            return False

        print_success("Capture running automatically!")

        # 9. Wait for Wireshark to close
        ws.join()

        # Cleanup
        stop_event.set()
        extcap_proc.terminate()
        pipe_ws.remove()
        pipe_plugin.remove()

        return True

    except Exception as e:
        print_error(f"Automatic capture failed: {str(e)}")
        return False


def find_extcap_plugin(plugin_name):
    """Find extcap plugin in Wireshark directories."""
    system = platform.system()

    if system == "Windows":
        paths = [
            Path("C:\\Program Files\\Wireshark\\extcap") / f"{plugin_name}.exe",
            Path("C:\\Program Files (x86)\\Wireshark\\extcap") / f"{plugin_name}.exe",
        ]
    elif system in ["Linux", "Darwin"]:
        paths = [
            Path.home() / ".local/lib/wireshark/extcap" / f"{plugin_name}.py",
            Path("/usr/lib/wireshark/extcap") / f"{plugin_name}.py",
            Path("/usr/local/lib/wireshark/extcap") / f"{plugin_name}.py",
        ]

    for path in paths:
        if path.exists():
            return str(path)

    # Also search in PATH
    which_cmd = "where" if system == "Windows" else "which"
    try:
        result = subprocess.run(
            [which_cmd, f"{plugin_name}.py"], capture_output=True, text=True
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except:
        pass

    return None


@click.group("catnip", context_settings={"help_option_names": ["-h", "--help"]})
@click.option("-v", "--verbose", is_flag=True, help="Show Verbose mode")
def cli(verbose):
    """CatSniffer: All in one catnip tools environment."""
    if verbose:
        logger.level = logging.INFO
    pass


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
    flasher = Flasher()
    """Sniffing BLE with Sniffle firmware"""
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
def sniff_zigbee(ws, channel, device):
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
    run_bridge(dev, channel, ws, profile="Zigbee")


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
    run_bridge(dev, channel, ws, profile="Thread")


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


def send_identify_command(device):
    """Send identification command to device to help identify it visually."""
    if not device.shell_port:
        print_warning("Shell port not available for identification!")
        return False

    print_info(f"Sending identification command to {device}...")

    try:
        shell = ShellConnection(port=device.shell_port, timeout=1.0)
        with shell:
            response = shell.send_command("identify", timeout=1.0)
            if response:
                print_info(f"Device response: {response}")

        print_success(f"Identification command sent to device #{device.device_id}!")
        return True

    except Exception as e:
        print_warning(f"Could not send identification command: {str(e)}")
        return False


@cli.command()
@click.argument("firmware", required=False)
@click.option(
    "--device",
    "-d",
    default=None,
    type=int,
    help="Device ID (for multiple CatSniffers). If not specified, first device will be selected.",
)
@click.option(
    "--list",
    "-l",
    is_flag=True,
    help="List available firmware images to flash",
)
@click.option(
    "--full",
    is_flag=True,
    help="Show full descriptions without truncation in the list",
)
def flash(firmware, device, list, full) -> None:
    """Flash CC1352 Firmware or list available firmware images"""

    from ..firmware.fw_aliases import get_official_id

    # Initialize Flasher to manage firmware operations
    flasher = Flasher()

    # If listing available firmwares is requested
    if list:
        print_title("Available Firmware Images:")

        try:
            # Get the list of local firmwares
            firmwares = flasher.get_local_firmware()

            if not firmwares:
                print_warning("No firmware images found locally.")
                print_empty_line()
                print_info("Run the CLI once to download the latest firmware images.")
                return

            # Create table to display firmwares
            table = Table(box=box.ROUNDED, show_header=True)
            table.add_column("Alias", style="green bold", min_width=15)
            table.add_column("Firmware Name", style="cyan", min_width=30)
            table.add_column("Description", style="white", min_width=70)

            # Get descriptions
            descriptions = flasher.parse_descriptions()

            # Map aliases to complete firmware
            firmware_to_alias = {}
            alias_usage_count = {}

            # Generate automatic aliases based on common names
            for fw in sorted(firmwares):
                fw_lower = fw.lower()
                fw_name_without_ext = os.path.splitext(fw)[0]

                # Check if it matches any centralized alias or official ID
                alias = get_official_id(fw_name_without_ext)
                if alias:
                    firmware_to_alias[fw] = alias
                    alias_usage_count[alias] = alias_usage_count.get(alias, 0) + 1
                    continue

            # Display each firmware with its alias
            for fw in sorted(firmwares):
                if fw in firmware_to_alias:
                    continue  # Already has predefined alias

                fw_lower = fw.lower()
                fw_name_without_ext = os.path.splitext(fw)[0]

                # Special handling for airtag files
                if "airtag" in fw_lower:
                    if "scanner" in fw_lower:
                        alias_candidate = "airtag_scanner"
                    elif "spoofer" in fw_lower:
                        alias_candidate = "airtag_spoofer"
                    else:
                        alias_candidate = "airtag"
                else:
                    # Extract keywords from firmware name
                    words = (
                        fw_name_without_ext.replace("_", " ").replace("-", " ").split()
                    )

                    # Filter common words/noise
                    common_words = {
                        "cc1352",
                        "cc1352p",
                        "cc1352p7",
                        "cc1352p2",
                        "v1",
                        "v2",
                        "v3",
                        "v10",
                        "v20",
                        "hex",
                        "uf2",
                        "firmware",
                        "sniffer",
                        "sniff",
                        "fw",
                        "for",
                        "and",
                        "the",
                        "with",
                    }

                    keywords = [
                        w for w in words if w.lower() not in common_words and len(w) > 2
                    ]

                    # Build alias from keywords
                    if keywords:
                        # Use the first meaningful keyword
                        alias_candidate = keywords[0].lower()

                        # If it's too long, truncate it
                        if len(alias_candidate) > 15:
                            alias_candidate = alias_candidate[:12] + "..."
                    else:
                        # If no keywords, use name without extension (truncated)
                        alias_candidate = fw_name_without_ext[:15]
                        if len(fw_name_without_ext) > 15:
                            alias_candidate = alias_candidate[:12] + "..."

                # Make sure the alias is unique
                base_alias = alias_candidate
                counter = 1
                while alias_candidate in alias_usage_count:
                    alias_candidate = f"{base_alias}_{counter}"
                    counter += 1

                firmware_to_alias[fw] = alias_candidate
                alias_usage_count[alias_candidate] = 1

            # Display each firmware with its alias
            for fw in sorted(firmwares):
                fw_lower = fw.lower()

                # Get alias
                alias = firmware_to_alias.get(fw, "firmware")

                # Get description
                desc = descriptions.get(fw_lower, "No description available")

                # Truncate description if it's too long (unless --full is specified)
                if not full and len(desc) > 70:
                    desc = desc[:67] + "..."

                table.add_row(f"[green]{alias}[/green]", fw, desc)

            console.print(table)

            # Show most useful aliases
            print_title("Recommended Aliases by Protocol:")

            print_subtitle("BLE:")
            print_alias_item("ble / sniffle", "Sniffle BLE sniffer", pad=18)
            print_alias_item("airtag-scanner", "Apple Airtag Scanner", pad=18)
            print_alias_item("airtag-spoofer", "Apple Airtag Spoofer", pad=18)
            print_alias_item("justworks", "JustWorks scanner", pad=18)

            print_subtitle("Zigbee/Thread/15.4 (TI Sniffer):")
            print_alias_item(
                "zigbee", "Texas Instruments multiprotocol sniffer", pad=18
            )
            print_alias_item("thread", "(same as zigbee - supports both)", pad=18)
            print_alias_item("15.4", "(same as zigbee - supports 802.15.4)", pad=18)
            print_alias_item("ti", "Texas Instruments sniffer", pad=18)
            print_alias_item("multiprotocol", "TI multiprotocol firmware", pad=18)

            # Use Information
            print_title("Usage Examples:")
            print_example(
                "catnip.py flash zigbee", "         (TI multiprotocol sniffer)"
            )
            print_example("catnip.py flash thread", "        (same TI firmware)")
            print_example("catnip.py flash ble", "           (Sniffle BLE)")
            print_example("catnip.py flash lora-sniffer", "  (LoRa Sniffer)")
            print_example("catnip.py flash airtag-scanner", "(Apple Airtag)")
            print_example("catnip.py flash --device 1 zigbee")

            return

        except Exception as e:
            print_error(f"Error listing firmwares: {str(e)}")
            import traceback

            traceback.print_exc()
            return

    # If flash is requested but no firmware is specified
    if firmware is None:
        print_error("No firmware specified!")
        print_empty_line()
        print_info(
            "Use 'catnip flash --list' to see available firmware images and aliases."
        )
        print_info("Or specify a firmware name: catnip flash <firmware_name_or_alias>")
        exit(1)

    # If the input is a valid file path, we skip alias resolution to avoid confusion
    if os.path.exists(firmware):
        print_info(f"Flashing from custom path: {firmware}")
    else:
        # Check if it's a known alias
        official_id = get_official_id(firmware)
        if official_id and official_id != firmware:
            print_info(f"Alias '{firmware}' resolved to: {official_id}")

    # If no device is specified, get all connected devices
    if device is None:
        devs = catnip_get_devices()
        if not devs:
            print_error("No CatSniffer devices found!")
            print_dim("Make sure your CatSniffer is connected.")
            exit(1)

        # Select the first device by default
        dev = devs[0]
        print_warning(f"No device specified. Using first device: {dev}")
    else:
        # If an ID is specified, get that specific device
        dev = catnip_get_device(device)
        if dev is None:
            print_error(f"CatSniffer device with ID {device} not found!")
            print_dim("Use 'devices' command to list available devices.")
            exit(1)

    # Verify that the device is valid
    if not dev.is_valid():
        print_warning(f"Not all ports detected for {dev}")
        print_dim(f"Bridge: {dev.bridge_port}")
        print_dim(f"LoRa:   {dev.lora_port}")
        print_dim(f"Shell:  {dev.shell_port}")

    print_info(f"Flashing firmware: {firmware} to device: {dev}")

    flash_result = flasher.find_flash_firmware(firmware, dev)

    if not flash_result:
        print_error(f"Error flashing: {firmware}")
        print_warning("Troubleshooting tips:")
        print_dim("1. Use 'catnip flash --list' to see all available firmwares")
        print_dim(
            "2. Available aliases: ble, zigbee, thread, lora-sniffer, airtag-scanner"
        )
        print_dim("3. Use the exact filename from the list")
        print_dim("4. Note: 'zigbee' alias maps to TI multiprotocol firmware")
        return

    print_info("Waiting for device to restart...")
    time.sleep(1)
    print_success("Device restart complete. Firmware is ready to use!")

    # Send identification command to help identify which device was flashed
    send_identify_command(dev)


@cli.command()
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Show raw USB port info for each interface (useful for diagnosing Windows port mapping).",
)
def devices(debug: bool) -> None:
    """List connected CatSniffer devices"""
    devs = catnip_get_devices()
    if not devs:
        print_warning("No CatSniffer devices found.")
        if debug:
            _print_raw_port_debug()
        return

    # Add a table to display devices
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

    print_empty_line()
    console.print(table)

    if debug:
        _print_raw_port_debug()


def _print_raw_port_debug() -> None:
    """Print raw pyserial port info for all CatSniffer interfaces."""
    from serial.tools import list_ports

    cat_ports = [
        p
        for p in list_ports.comports()
        if p.vid == CATSNIFFER_VID and p.pid == CATSNIFFER_PID
    ]

    if not cat_ports:
        console.print("[red]No CatSniffer USB interfaces visible to pyserial.[/red]")
        return

    raw = Table(title="Raw USB port info (debug)", box=box.SIMPLE)
    raw.add_column("Port", style="cyan")
    raw.add_column("Description")
    raw.add_column("HWID")
    raw.add_column("Location")
    raw.add_column("Interface")
    raw.add_column("Serial#")

    for p in sorted(cat_ports, key=lambda x: x.device):
        raw.add_row(
            p.device,
            p.description or "",
            p.hwid or "",
            p.location or "",
            getattr(p, "interface", None) or "",
            p.serial_number or "",
        )

    console.print(raw)


@cli.command()
@click.option(
    "--device",
    "-d",
    default=None,
    type=int,
    help="Device ID (for multiple CatSniffers)",
)
def identify(device) -> None:
    """Send identification command to CatSniffer device"""
    dev = get_device_or_exit(device)

    if not dev.shell_port:
        print_error("Shell port not available for this device!")
        exit(1)

    print_info(f"Sending 'Identify' command to {dev} on port {dev.shell_port}...")

    try:
        shell = ShellConnection(port=dev.shell_port, timeout=1.0)
        with shell:
            response = shell.send_command("identify", timeout=1.0)
            if response:
                print_info(f"Response: {response}")

        print_success("Identification command sent successfully!")

    except Exception as e:
        print_error(f"Failed to send identification command: {str(e)}")
        exit(1)


@cli.command()
@click.option(
    "--test-all",
    is_flag=True,
    help="Run all tests including LoRa configuration and communication",
)
@click.option("--device", "-d", type=int, help="Test only a specific device (by ID)")
@click.option("--quiet", "-q", is_flag=True, help="Show only summary results")
def verify(test_all, device, quiet):
    """
    Verify CatSniffer device functionality

    Tests all connected CatSniffers and verifies:
    - Basic shell commands (help, status, lora_config, lora_mode)
    - LoRa configuration (frequency, SF, BW, etc.)
    - LoRa communication (TEST, TXTEST, TX commands)

    Use --test-all for comprehensive testing.
    """
    # Check dependencies
    try:
        import usb.core
        import usb.util
        import serial
    except ImportError as e:
        print_error(f"Dependency missing: {e}")
        print_warning("Install missing dependencies:")
        print_dim("pip install pyusb pyserial")
        return 1

    # Run verification
    success, results = run_verification(
        test_all=test_all, device_id=device, quiet=quiet
    )

    # Print final message
    if success:
        print_success("Verification completed successfully!")
        if test_all:
            print_success("All devices are fully functional and ready for use!")
        else:
            print_success(
                "Basic functionality verified. Use --test-all for comprehensive testing."
            )
        sys.exit(0)
    else:
        print_error("Verification failed!")
        print_warning("Troubleshooting tips:")
        print_dim(
            "1. Make sure all 3 USB endpoints are connected (Bridge, LoRa, Shell)"
        )
        print_dim("2. Try reconnecting the USB cable")
        print_dim("3. Check if the correct firmware is flashed")
        print_dim("4. Verify serial port permissions (Linux/Mac)")
        sys.exit(1)


@click.command()
@click.option(
    "--device",
    "-d",
    default=None,
    type=int,
    help="Device ID (for multiple CatSniffers)",
)
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
    from ..protocols.cativity.runner import CativityRunner

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


# ===================== Meshtastic Commands =====================


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def meshtastic():
    """Meshtastic protocol tools"""
    pass


@meshtastic.command("decode")
@click.option(
    "-i",
    "--input",
    required=True,
    help="Hex-encoded payload (raw packet data starting with dest, sender, etc.)",
)
@click.option(
    "-k",
    "--key",
    default="1PG7OiApB1nwvP+rz05pAQ==",
    help="Base64-encoded AES key. Use 'ham' or 'nokey' for open channels",
)
def meshtastic_decode(input, key):
    """Decrypt and decode a hex-encoded Meshtastic packet"""
    try:
        from ..protocols.meshtastic import MeshtasticDecoder
    except ImportError as e:
        print_error(
            f"The 'meshtastic' library is required for this command. (Error: {e})"
        )
        print_empty_line()
        print_warning("This library should be bundled with the package.")
        print_info("If it's missing, you can install it manually:")
        print_dim("pip install meshtastic protobuf pyyaml")
        sys.exit(1)

    try:
        decoder = MeshtasticDecoder(key=key)
        decrypted_hex, result = decoder.decode(input)
        print(f"Decrypted raw (hex): {decrypted_hex}")
        print(result)
    except Exception as e:
        print_error(f"Error: {e}")
        sys.exit(1)


@meshtastic.command("live")
@click.option(
    "-d",
    "--device",
    default=None,
    type=int,
    help="Device ID (for multiple CatSniffers)",
)
@click.option(
    "-baud",
    "--baudrate",
    type=int,
    default=115200,
    help="Baudrate (default: 115200)",
)
@click.option(
    "-f",
    "--frequency",
    type=float,
    default=906.875,
    help="Frequency in MHz (default: 906.875)",
)
@click.option(
    "-ps",
    "--preset",
    type=click.Choice(
        [
            "defcon33",
            "ShortTurbo",
            "ShortSlow",
            "ShortFast",
            "MediumSlow",
            "MediumFast",
            "LongSlow",
            "LongFast",
            "LongMod",
            "VLongSlow",
        ]
    ),
    default="LongFast",
    help="Channel preset (default: LongFast)",
)
def meshtastic_live(device, baudrate, frequency, preset):
    """Live Meshtastic decoder - Capture and decode packets in real-time"""
    try:
        from ..protocols.meshtastic import MeshtasticLiveDecoder
    except ImportError as e:
        print_error(
            f"The 'meshtastic' library is required for this command. (Error: {e})"
        )
        print_empty_line()
        print_warning("This library should be bundled with the package.")
        print_info("If it's missing, you can install it manually:")
        print_dim("pip install meshtastic protobuf pyyaml")
        sys.exit(1)

    # Get device or exit with error
    dev = get_device_or_exit(device)

    # Use the LoRa port from the device
    port = dev.lora_port
    if not port:
        print_error("LoRa port not found for device!")
        return

    # Use the Shell port for configuration
    shell_port = dev.shell_port
    if not shell_port:
        print_error("Shell port not found for device! Required for configuration.")
        return

    decoder = MeshtasticLiveDecoder(port, baudrate)

    freq_hz = int(frequency * 1_000_000)
    print_info(f"Using device: {dev}")
    print_info(f"Configuring radio: {frequency} MHz ({freq_hz} Hz), preset: {preset}")

    # Configure radio using shell port with correct commands
    if not decoder.configure_radio(freq_hz, preset, shell_port):
        print_error("Failed to configure radio")
        return

    print_info("Starting capture... Press Ctrl+C to stop")
    decoder.start()

    try:
        decoder.process_packets()
    except KeyboardInterrupt:
        print_info("Shutting down...")
    finally:
        decoder.stop()


@meshtastic.command("dashboard")
@click.option(
    "-d",
    "--device",
    default=None,
    type=int,
    help="Device ID (for multiple CatSniffers)",
)
@click.option(
    "-baud",
    "--baudrate",
    type=int,
    default=115200,
    help="Baudrate (default: 115200)",
)
@click.option(
    "-f",
    "--frequency",
    type=float,
    default=906.875,
    help="Frequency in MHz (default: 906.875)",
)
@click.option(
    "-ps",
    "--preset",
    type=click.Choice(
        [
            "defcon33",
            "ShortTurbo",
            "ShortSlow",
            "ShortFast",
            "MediumSlow",
            "MediumFast",
            "LongSlow",
            "LongFast",
            "LongMod",
            "VLongSlow",
        ]
    ),
    default="LongFast",
    help="Channel preset (default: LongFast)",
)
def meshtastic_dashboard(device, baudrate, frequency, preset):
    """Meshtastic Chat TUI - Beautiful terminal dashboard for Meshtastic"""
    import asyncio

    try:
        from ..protocols.meshtastic.core import configure_meshtastic_radio
        from ..protocols.meshtastic import MeshtasticChatApp, Monitor
    except ImportError as e:
        print_error(
            f"The 'meshtastic' library is required for this command. (Error: {e})"
        )
        print_empty_line()
        print_warning("This library should be bundled with the package.")
        print_info("If it's missing, you can install it manually:")
        print_dim("pip install meshtastic protobuf pyyaml")
        sys.exit(1)

    # Get device or exit with error
    dev = get_device_or_exit(device)

    # Use the LoRa port from the device
    port = dev.lora_port
    if not port:
        print_error("LoRa port not found for device!")
        return

    # Use the Shell port for configuration
    shell_port = dev.shell_port
    if not shell_port:
        print_error("Shell port not found for device! Required for configuration.")
        return

    print_info(f"Using device: {dev}")

    # Create monitor
    rx_queue = queue.Queue()
    mon = Monitor(port, baudrate, rx_queue)
    mon.start()

    # Configure radio using shell port securely
    print_info("Configuring radio...")
    freq_hz = int(frequency * 1_000_000)

    if not configure_meshtastic_radio(shell_port, freq_hz, preset):
        print_error("Failed to configure radio")
        mon.stop()
        return

    try:
        app = MeshtasticChatApp(monitor=mon, preset=preset, freq=str(frequency))
        asyncio.run(app.run_async())
    finally:
        mon.stop()


@meshtastic.command("config")
@click.argument("file")
def meshtastic_config(file):
    """Extract PSKs and config info from a Meshtastic JSONC config file"""
    try:
        from ..protocols.meshtastic import MeshtasticConfigExtractor
    except ImportError as e:
        print_error(
            f"The 'meshtastic' library is required for this command. (Error: {e})"
        )
        print_empty_line()
        print_warning("This library should be bundled with the package.")
        print_info("If it's missing, you can install it manually:")
        print_dim("pip install meshtastic protobuf pyyaml")
        sys.exit(1)

    extractor = MeshtasticConfigExtractor(file)
    if extractor.load():
        extractor.print_all()
    else:
        sys.exit(1)


# ===================== LoRa Commands =====================


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def lora():
    """LoRa SX1262 tools"""
    pass


@lora.command("spectrum")
@click.option(
    "-d",
    "--device",
    default=None,
    type=int,
    help="Device ID (for multiple CatSniffers)",
)
@click.option(
    "-b",
    "--baudrate",
    type=int,
    default=115200,
    help="Baudrate (default: 115200)",
)
@click.option(
    "--start-freq",
    type=float,
    default=150,
    help="Starting frequency in MHz (default: 150)",
)
@click.option(
    "--end-freq",
    type=float,
    default=960,
    help="End frequency in MHz (default: 960)",
)
@click.option(
    "--offset",
    type=int,
    default=-15,
    help="RSSI offset in dBm (default: -15)",
)
def lora_spectrum(device, baudrate, start_freq, end_freq, offset):
    """Live Spectrum Scanner for SX1262 - Real-time frequency spectrum analyzer"""
    from ..protocols.sx1262.spectrum import SpectrumScan

    # Get device or exit with error
    dev = get_device_or_exit(device)

    # Use the LoRa port from the device
    port = dev.lora_port
    if not port:
        print_error("LoRa port not found for device!")
        return

    print_info(f"Using device: {dev}")
    print_info(f"Starting spectrum scan: {start_freq}-{end_freq} MHz")

    scanner = SpectrumScan(port=port, baudrate=baudrate)

    try:
        scanner.run(start_freq=start_freq, end_freq=end_freq, rssi_offset=offset)
    except KeyboardInterrupt:
        scanner.stop_task()


# ===================== VHCI Bridge Commands =====================


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def vhci():
    """VHCI Bridge - Expose CatSniffer as hciX.

    Requires sudo and the hci_vhci kernel module.

    \b
        sudo modprobe hci_vhci
        sudo python3 catnip.py vhci start
    """
    pass


@vhci.command("start")
@click.option(
    "--device",
    "-d",
    default=None,
    type=int,
    help="Device ID (for multiple CatSniffers)",
)
@click.option(
    "--baud",
    default=2000000,
    type=int,
    show_default=True,
    help="Baud rate for serial port",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose (DEBUG) logging")
def vhci_start(device, baud, verbose):
    """Start the VHCI bridge — CatSniffer appears as hciX.

    Requires root privileges and the hci_vhci kernel module:

    \b
        sudo modprobe hci_vhci
        sudo catnip vhci start
        hciconfig -a

    Compatible tools: bluetoothctl, btmgmt, btmon, bleak, bettercap.
    """
    import signal
    from ..protocols.vhci import VHCIBridge

    if os.geteuid() != 0 and not os.access("/dev/vhci", os.R_OK | os.W_OK):
        print_warning(
            "Insufficient permissions for /dev/vhci access. Try running with sudo or check group membership."
        )

    if not os.path.exists("/dev/vhci"):
        print_error("/dev/vhci not found. Load the kernel module first:")
        print_dim("sudo modprobe hci_vhci")
        sys.exit(1)

    # Resolve device
    if device is not None:
        dev = catnip_get_device(device)
        if dev is None:
            print_error(f"CatSniffer device #{device} not found.")
            sys.exit(1)
        if not dev.bridge_port:
            print_error(f"Device #{device} has no Cat-Bridge port detected.")
            sys.exit(1)
        print_info(f"Using device {dev}, port: {dev.bridge_port}")
    else:
        devs = catnip_get_devices()
        if devs and devs[0].bridge_port:
            dev = devs[0]
            print_info(f"Auto-detected CatSniffer: {dev}, port: {dev.bridge_port}")
        else:
            print_error("CatSniffer not found. Connect a device or specify -d.")
            sys.exit(1)

    # Firmware check
    cat = Catnip(dev.bridge_port)
    print_info("Checking for Sniffle firmware...")
    if cat.check_firmware_by_metadata("sniffle", dev.shell_port):
        print_success("Sniffle firmware found!")
    else:
        print_warning("Sniffle firmware not found — flashing now...")
        flasher = Flasher()
        if not flasher.find_flash_firmware("sniffle", dev):
            print_error("Failed to flash Sniffle firmware. Aborting.")
            sys.exit(1)
        print_info("Waiting for device to initialize...")
        time.sleep(1)
        if cat.check_firmware_by_metadata("sniffle", dev.shell_port):
            print_success("Sniffle firmware verified!")
        else:
            print_warning("Firmware verification failed, continuing anyway...")

    # Logging
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_time=False)],
    )
    log = logging.getLogger("vhci")

    bridge = VHCIBridge(dev.bridge_port, log)

    def _shutdown(sig, frame):
        print_warning("Shutting down VHCI bridge...")
        bridge.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        bridge.start()
    except Exception as e:
        print_error(f"Failed to start bridge: {e}")
        sys.exit(1)

    print_success("Bridge running. Device should appear as hciX.")
    print_dim("Check with: hciconfig -a   |   Press Ctrl+C to stop")

    try:
        bridge.run()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()


@vhci.command("check")
def vhci_check():
    """Check VHCI bridge prerequisites (kernel module, /dev/vhci, root, packages)."""
    import subprocess as _sp

    all_ok = True

    # Permissions check
    if os.access("/dev/vhci", os.R_OK | os.W_OK):
        print_success("  permissions  : OK (access to /dev/vhci)")
    elif os.geteuid() == 0:
        print_success("  root         : OK")
    else:
        print_warning(
            "  permissions  : Insufficient — bridge may fail to open /dev/vhci"
        )
        all_ok = False

    # Kernel module
    try:
        result = _sp.run(["lsmod"], capture_output=True, text=True, timeout=5)
        if "hci_vhci" in result.stdout:
            print_success("  hci_vhci     : loaded")
        else:
            print_warning("  hci_vhci     : NOT loaded — run: sudo modprobe hci_vhci")
            all_ok = False
    except Exception:
        print_error("  hci_vhci     : could not run lsmod")
        all_ok = False

    # /dev/vhci
    if os.path.exists("/dev/vhci"):
        print_success("  /dev/vhci    : exists")
    else:
        print_warning("  /dev/vhci    : missing — run: sudo modprobe hci_vhci")
        all_ok = False

    # BlueZ (bluetoothctl)
    try:
        _sp.run(["bluetoothctl", "--version"], capture_output=True, timeout=3)
        print_success("  bluetoothctl : found")
    except FileNotFoundError:
        print_warning("  bluetoothctl : not found — install bluez")
        all_ok = False
    except Exception:
        print_warning("  bluetoothctl : check failed")

    # btmon
    try:
        _sp.run(["btmon", "--version"], capture_output=True, timeout=3)
        print_success("  btmon        : found")
    except FileNotFoundError:
        print_dim("  btmon        : not found (optional — install bluez-utils)")
    except Exception:
        pass

    # bleak (Python)
    try:
        import bleak  # noqa: F401

        print_success("  bleak        : installed")
    except ImportError:
        print_dim("  bleak        : not installed (optional — pip install bleak)")

    # CatSniffer device
    devs = catnip_get_devices()
    if devs:
        for dev in devs:
            port = dev.bridge_port or "?"
            print_success(f"  CatSniffer   : {dev}  bridge={port}")
    else:
        print_warning("  CatSniffer   : no device detected")
        all_ok = False

    print_empty_line()
    if all_ok:
        if os.access("/dev/vhci", os.R_OK | os.W_OK):
            print_success("All prerequisites met. Run: catnip vhci start")
        else:
            print_success("All prerequisites met. Run: sudo catnip vhci start")
    else:
        print_warning("Some prerequisites are missing. See above.")


# ===================== Firmware Update Commands =====================


@cli.command()
@click.option(
    "--device",
    "-d",
    default=None,
    type=int,
    help="Device ID (for multiple CatSniffers)",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Force update even if firmware versions match",
)
def update(device, force):
    """Check and update RP2040 firmware to match the latest release.

    Verifies that the RP2040 firmware version is compatible with the tool
    and the latest firmware release. If outdated, automatically updates
    the device.

    If the device is not detected, provides instructions to manually
    enter Boot Mode for recovery.
    """
    from ..firmware.fw_update import (
        check_and_update_rp2040,
        force_update_rp2040,
        get_tool_version,
    )

    print_info(f"CatSniffer Firmware Update - Tool v{get_tool_version()}")
    print_empty_line()

    # Initialize Flasher for release management
    flasher_inst = Flasher()

    # Get device if specified
    dev = None
    if device is not None:
        dev = catnip_get_device(device)
        if dev is None:
            print_warning(f"Device #{device} not found, will check for Boot Mode...")
    else:
        dev = catnip_get_device()

    if force:
        print_info("Force mode enabled — will update regardless of version")
        result = force_update_rp2040(device=dev, flasher=flasher_inst)
    else:
        result = check_and_update_rp2040(device=dev, flasher=flasher_inst)

    if result:
        print_success("Firmware update check complete!")
    else:
        print_error("Firmware update could not be completed.")
        print_empty_line()
        print_dim("Use 'catnip update --force' to force an update.")


# ===================== CC1352 Restore Command =====================


@click.command()
@click.argument("firmware", required=False, default=None)
@click.option(
    "--device",
    "-d",
    default=None,
    type=int,
    help="Device ID (for shell access to trigger BOOTSEL)",
)
@click.option(
    "--tapid",
    default="0x1BB7702F",
    help="CC1352 JTAG TAPID (default: CC1352P7)",
)
def restore(firmware, device, tapid):
    """Restore CC1352 when bootloader is broken.

    Uses RP2040 as CMSIS-DAP JTAG programmer via OpenOCD to flash
    the CC1352 directly. Requires OpenOCD installed.

    If no firmware is specified, uses the default CatSniffer firmware
    from the catnip release.

    \b
    Example:
        catnip restore                    # default CatSniffer firmware
        catnip restore firmware.hex       # custom firmware
        catnip restore firmware.hex -d 1  # specific device
    """
    from ..firmware.restore import restore_cc1352

    # If no device is specified, get all connected devices
    if device is None:
        devs = catnip_get_devices()
        if not devs:
            print_error("No CatSniffer devices found!")
            print_dim("Make sure your CatSniffer is connected.")
            exit(1)

        # Select the first device by default
        dev = devs[0]
        print_warning(f"No device specified. Using first device: {dev}")
    else:
        # If an ID is specified, get that specific device
        dev = catnip_get_device(device)
        if dev is None:
            print_error(f"CatSniffer device with ID {device} not found!")
            print_dim("Use 'devices' command to list available devices.")
            exit(1)

    flasher_inst = Flasher()

    success = restore_cc1352(
        hex_path=firmware,
        device=dev,
        flasher=flasher_inst,
        tapid=tapid,
    )

    if not success:
        print_error("Restore failed. Check the output above for details.")


# ===================== Shell Completion Commands =====================


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def completion():
    """Install shell tab completion for catnip."""
    pass


@completion.command("install")
@click.option(
    "--shell",
    type=click.Choice(["bash", "zsh", "fish"]),
    default=None,
    help="Shell to install completion for (auto-detected if omitted)",
)
def completion_install(shell):
    """Install tab completion for your shell.

    Run this once, then restart your shell (or source your rc file).

    \b
        catnip completion install          # auto-detect shell
        catnip completion install --shell zsh
    """
    if platform.system() == "Windows":
        print_error("Shell completion is not supported on Windows.")
        sys.exit(1)

    import subprocess as _sp
    from pathlib import Path

    # Auto-detect shell
    if shell is None:
        shell_env = os.environ.get("SHELL", "")
        if "zsh" in shell_env:
            shell = "zsh"
        elif "fish" in shell_env:
            shell = "fish"
        elif "bash" in shell_env:
            shell = "bash"
        else:
            print_error("Could not detect shell. Use --shell bash|zsh|fish.")
            sys.exit(1)
        print_info(f"Detected shell: {shell}")

    env_var = "_CATNIP_COMPLETE"

    # Absolute path to this script and the Python interpreter running it.
    # We always want completions to call "python /abs/path/to/catnip.py" so
    # that they work regardless of whether catnip is on PATH.
    script_abs = str(Path(sys.argv[0]).resolve())
    python_abs = str(Path(sys.executable).resolve())
    # The full command string that the completion script will execute
    cmd_to_call = f"{python_abs} {script_abs}"

    if shell == "bash":
        target = (
            Path.home()
            / ".local"
            / "share"
            / "bash-completion"
            / "completions"
            / "catnip"
        )
        source_flag = "bash_source"
        rc_note = None
    elif shell == "zsh":
        target = Path.home() / ".zfunc" / "_catnip"
        source_flag = "zsh_source"
        rc_note = "fpath=(~/.zfunc $fpath)\nautoload -Uz compinit && compinit"
    elif shell == "fish":
        target = Path.home() / ".config" / "fish" / "completions" / "catnip.fish"
        source_flag = "fish_source"
        rc_note = None

    try:
        result = _sp.run(
            [python_abs, script_abs],
            env={**os.environ, env_var: source_flag},
            capture_output=True,
            text=True,
        )
        script = result.stdout
    except Exception as e:
        print_error(f"Failed to generate completion script: {e}")
        sys.exit(1)

    if not script.strip():
        print_error(
            "Empty completion script generated.\n"
            "Make sure you are running this command via:\n"
            f"  python {script_abs} completion install"
        )
        sys.exit(1)

    # ------------------------------------------------------------------ #
    # Post-process: replace the bare 'catnip' program name that Click      #
    # embeds in the script with the full "python /abs/path/catnip.py"      #
    # invocation.  We handle every pattern Click 7.x / 8.x can emit.      #
    # ------------------------------------------------------------------ #
    if shell == "zsh":
        # 1. #compdef directive — register for all the names a user might type
        script = script.replace(
            "#compdef catnip", "#compdef catnip catnip.py ./catnip.py"
        )
        # 2. The guard that aborts when the command is not found in $commands[].
        #    We neutralise it because we use an absolute path, not a PATH entry.
        script = script.replace(
            "(( ! $+commands[catnip] ))",
            "false",  # 'false' evaluates to 1 so the (( )) block never returns
        )
        # 3. The line that actually calls the program to obtain completions.
        #    Click 8 emits:  _CATNIP_COMPLETE=zsh_complete catnip
        script = script.replace(
            f"{env_var}=zsh_complete catnip", f"{env_var}=zsh_complete {cmd_to_call}"
        )
        # 4. The compdef registration at the bottom of the script
        script = script.replace(
            "compdef _catnip_completion catnip",
            f"compdef _catnip_completion catnip catnip.py ./catnip.py",
        )

        # 5. Append an explicit wrapper so that "python catnip.py <TAB>" and
        #    "./catnip.py <TAB>" also trigger completion.  zsh matches on the
        #    last component of $words[1], so we register a catch-all that
        #    delegates to our function.
        extra = (
            "\n"
            "# Enable completion when invoked as 'python catnip.py' or './catnip.py'\n"
            "_catnip_completion_python_wrapper() {\n"
            "  local script_name=${words[2]:t}  # basename of the script argument\n"
            "  if [[ $script_name == catnip.py ]]; then\n"
            f"    (( ! $+functions[_catnip_completion] )) && source {target}\n"
            '    words=(catnip "${words[@]:2}")\n'
            "    (( CURRENT-- ))\n"
            "    _catnip_completion\n"
            "  else\n"
            "    _files\n"
            "  fi\n"
            "}\n"
            "compdef _catnip_completion_python_wrapper python python3\n"
        )
        script += extra

    elif shell == "bash":
        # Click 8 emits:  _CATNIP_COMPLETE=bash_complete catnip
        script = script.replace(
            f"{env_var}=bash_complete catnip", f"{env_var}=bash_complete {cmd_to_call}"
        )
        # Register for both 'catnip' and 'catnip.py'
        script = script.replace(
            "complete -F _catnip_completion catnip",
            "complete -F _catnip_completion catnip catnip.py",
        )
        # Append a wrapper that intercepts 'python catnip.py <TAB>'
        extra = (
            "\n"
            "# Enable completion when invoked as 'python catnip.py'\n"
            "_catnip_completion_python_wrapper() {\n"
            "    local cur script_arg\n"
            '    cur="${COMP_WORDS[COMP_CWORD]}"\n'
            '    script_arg="${COMP_WORDS[1]}"\n'
            '    if [[ "$(basename "$script_arg")" == "catnip.py" ]]; then\n'
            "        # Rebuild COMP_WORDS without the leading 'python' / path\n"
            '        local new_words=(catnip "${COMP_WORDS[@]:2}")\n'
            '        COMP_WORDS=("${new_words[@]}")\n'
            "        COMP_CWORD=$(( COMP_CWORD - 1 ))\n"
            "        _catnip_completion\n"
            "    fi\n"
            "}\n"
            "complete -F _catnip_completion_python_wrapper python python3\n"
        )
        script += extra

    elif shell == "fish":
        # Fish uses a different mechanism; just replace the bare program name
        script = script.replace(
            f"{env_var}=fish_complete catnip", f"{env_var}=fish_complete {cmd_to_call}"
        )

    # Write script
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(script)
    print_success(f"Completion script written to: {target}")

    # zsh needs fpath entry in .zshrc
    if rc_note:
        zshrc = Path.home() / ".zshrc"
        existing = zshrc.read_text() if zshrc.exists() else ""
        if "~/.zfunc" not in existing and ".zfunc" not in existing:
            with zshrc.open("a") as f:
                f.write(f"\n# catnip tab completion\n{rc_note}\n")
            print_success(f"Added fpath entry to {zshrc}")
        else:
            print_dim("~/.zfunc already in fpath — skipping .zshrc edit")

    print_empty_line()
    if shell == "bash":
        print_info("Restart your shell or run:")
        print_example(f"source {target}")
    elif shell == "zsh":
        print_info("Restart your shell or run:")
        print_example("source ~/.zshrc && compinit -u")
    elif shell == "fish":
        print_info("Completion is active immediately in new fish sessions.")


@click.command("setup-env")
def setup_env():
    """Setup environment: install udev rules and add user to groups.

    Requires root privileges (sudo). This command installs the necessary
    udev rules for CatSniffer devices and VHCI, and adds the current
    user to the 'dialout' and 'bluetooth' groups.
    """
    if platform.system() != "Windows" and os.geteuid() != 0:
        print_error("Root privileges required. Please run with sudo:")
        print_dim(f"sudo {sys.argv[0]} setup-env")
        sys.exit(1)

    # 1. Install udev rules
    rules_content = """# Permission to VHCI (Bluetooth Virtual)
KERNEL=="vhci", MODE="0660", GROUP="bluetooth", TAG+="uaccess"

# Permission to CatSniffer (RP2040)
SUBSYSTEM=="tty", ATTRS{idVendor}=="2e8a", ATTRS{idProduct}=="00c0", MODE="0660", GROUP="dialout", TAG+="uaccess"
"""
    rules_path = Path("/etc/udev/rules.d/99-catsniffer.rules")
    try:
        rules_path.write_text(rules_content)
        print_success(f"Udev rules installed to {rules_path}")
    except Exception as e:
        print_error(f"Failed to install udev rules: {e}")

    # 2. Add user to groups
    # Get the real user (since we are likely running with sudo)
    real_user = os.environ.get("SUDO_USER")
    if not real_user:
        # Fallback if SUDO_USER is not set
        import getpass

        real_user = getpass.getuser()

    groups = ["dialout", "bluetooth"]
    for group in groups:
        try:
            subprocess.run(["usermod", "-aG", group, real_user], check=True)
            print_success(f"User '{real_user}' added to group '{group}'")
        except subprocess.CalledProcessError:
            print_warning(
                f"Could not add user '{real_user}' to group '{group}' (does it exist?)"
            )
        except Exception as e:
            print_error(f"Error adding user to group {group}: {e}")

    # 3. Reload udev rules
    try:
        subprocess.run(["udevadm", "control", "--reload-rules"], check=True)
        subprocess.run(["udevadm", "trigger"], check=True)
        print_success("Udev rules reloaded")
    except Exception as e:
        print_warning(f"Could not reload udev rules automatically: {e}")

    print_success("Environment setup complete!")
    print_info("Please log out and log back in for group changes to take effect.")


def main_cli() -> None:
    if not os.environ.get("_CATNIP_COMPLETE"):
        module = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
        print_header(module)
    cli.add_command(sniff)
    cli.add_command(cativity)
    cli.add_command(meshtastic)
    cli.add_command(restore)
    cli.add_command(lora)
    if platform.system() == "Linux":
        cli.add_command(vhci)
        cli.add_command(setup_env)
    cli.add_command(verify)
    if platform.system() in ["Linux", "Darwin"]:
        cli.add_command(completion)
    cli(prog_name="catnip")

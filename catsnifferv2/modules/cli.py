#! /usr/bin/env python3

# Kevin Leon @ Electronic Cats
# Original Creation Date: Dec 19, 2025
# This code is beerware; if you see me (or any other Electronic Cats
# member) at the local, and you've found our code helpful,
# please buy us a round!
# Distributed as-is; no warranty is given.

import logging
import os
import tempfile

# Internal
from .catnip import Catnip
from .verify import run_verification
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
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.style import Style

import subprocess
import platform
import time
from pathlib import Path

# APP Information
CLI_NAME = "Catsniffer"
VERSION_NUMBER = "3.0.0"
AUTHOR = "JahazielLem"
COMPANY = "Electronic Cats - PWNLAB"

# Defining styles for reuse
STYLES = {
    "header": Style(color="cyan", bold=True),
    "success": Style(color="green", bold=True),
    "warning": Style(color="yellow", bold=True),
    "error": Style(color="red", bold=True),
    "info": Style(color="blue", bold=True),
    "device": Style(color="cyan"),
    "prompt": Style(color="magenta", bold=True),
}

# Prompt
PROMPT_ICON = "🐱"
PROMPT_DESCRIPTION = (
    "PyCat-Sniffer CLI - For sniffing the TI CC1352 device communication interfaces."
)

__version__ = "3.0"

catnip = Catnip()
wireshark = Wireshark()
console = Console()

logger = logging.getLogger("rich")
FORMAT = "%(message)s"
logging.basicConfig(
    level="WARNING", format=FORMAT, datefmt="[%X]", handlers=[RichHandler()]
)


def print_header():
    """Print the ASCII art header"""
    ascii_art = f"""      :-:              :--       |
      ++++=.        .=++++       |
      =+++++===++===++++++       |
      -++++++++++++++++++-       |
 .:   =++---++++++++---++=   :.  |  Module:  {CLI_NAME}
 ::---+++.   -++++-   .+++---::  |  Version: {VERSION_NUMBER}
::1..:-++++:   ++++   :++++-::.::|  Company: {COMPANY}
.:...:=++++++++++++++++++=:...:. |
 :---.  -++++++++++++++-  .---:  |
 ..        .:------:.        ..  |"""

    # Apply color to the ASCII art
    colored_ascii = f"[cyan bold]{ascii_art}[/cyan bold]"

    # Create a panel for the header
    header_panel = Panel(
        colored_ascii,
        title=PROMPT_DESCRIPTION,
        border_style=STYLES["header"],
        title_align="left",
        padding=(1, 2),
    )
    console.print(header_panel)


def print_success(message):
    """Print a success message"""
    console.print(f"[green]✓[/green] {message}", style=STYLES["success"])


def print_warning(message):
    """Print a warning message"""
    console.print(f"[yellow]⚠[/yellow] {message}", style=STYLES["warning"])


def print_error(message):
    """Print an error message"""
    console.print(f"[red]✗[/red] {message}", style=STYLES["error"])


def print_info(message):
    """Print an info message"""
    console.print(f"[blue]ℹ[/blue] {message}", style=STYLES["info"])


def get_device_or_exit(device_id=None):
    """Get CatSniffer device or exit with error."""
    device = catsniffer_get_device(device_id)
    if device is None:
        print_error("No CatSniffer device found!")
        console.print("    Make sure your CatSniffer is connected.")
        exit(1)
    if not device.is_valid():
        print_warning(f"Not all ports detected for {device}")
        console.print(f"    Bridge: {device.bridge_port}")
        console.print(f"    LoRa:   {device.lora_port}")
        console.print(f"    Shell:  {device.shell_port}")
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
    """Run Sniffle extcap directly and connect Wireshark to FIFO."""
    try:
        # Create temporary FIFO
        temp_dir = tempfile.gettempdir()
        fifo_path = os.path.join(temp_dir, f"sniffle_fifo_{os.getpid()}")

        if os.path.exists(fifo_path):
            os.remove(fifo_path)

        os.mkfifo(fifo_path)

        # Command to run the plugin
        extcap_path = find_extcap_plugin("sniffle_extcap")
        if not extcap_path:
            return False

        cmd = [
            "python3",
            extcap_path,
            "--capture",
            "--extcap-interface",
            "sniffle",
            "--fifo",
            fifo_path,
            "--serport",
            port,
            "--mode",
            mode,
            "--advchan",
            str(channel),
        ]

        # Run in background
        print_info(f"Starting Sniffle extcap...")
        extcap_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        # Wait for initialization
        time.sleep(3)

        if extcap_proc.poll() is not None:
            # The process ended, there was an error
            stdout, stderr = extcap_proc.communicate()
            print_error(f"Extcap error: {stderr.decode()[:200]}")
            os.remove(fifo_path)
            return False

        # Now open Wireshark connected to the FIFO
        wireshark_path = find_wireshark_path()
        if not wireshark_path:
            os.remove(fifo_path)
            return False

        wireshark_cmd = [wireshark_path, "-k", "-i", fifo_path]
        print_info(f"Opening Wireshark connected to FIFO...")
        wireshark_proc = subprocess.Popen(wireshark_cmd)

        # Wait for Wireshark to finish
        wireshark_proc.wait()

        # Cleanup
        extcap_proc.terminate()
        if os.path.exists(fifo_path):
            os.remove(fifo_path)

        return True

    except Exception as e:
        print_error(f"Direct method failed: {str(e)}")
        # Cleanup FIFO if it exists
        if "fifo_path" in locals() and os.path.exists(fifo_path):
            os.remove(fifo_path)
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


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("-v", "--verbose", is_flag=True, help="Show Verbose mode")
def cli(verbose):
    """CatSniffer: All in one catsniffer tools environment."""
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
    """Sniffing BLE with Sniffle firmware"""
    dev = get_device_or_exit(device)

    # Verify firmware
    cat = Catsniffer(dev.bridge_port)

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
        if not catnip.find_flash_firmware(SniffingBaseFirmware.BLE.value, dev):
            print_error("Failed to flash Sniffle firmware")
            return

        # LONGER WAIT AND VERIFICATION RETRIES
        print_info("Waiting for device to initialize after flashing...")
        time.sleep(4)  # Generous wait

        # Retry verification several times
        verified = False
        for attempt in range(3):
            print_info(f"Verifying firmware (attempt {attempt + 1}/3)...")

            # Create a new Catsniffer instance to avoid connection issues
            cat = Catsniffer(dev.bridge_port)

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

            time.sleep(2)  # Wait before retrying

        if not verified:
            print_error("Firmware verification failed after multiple attempts!")
            print_info("The device may still work, but metadata is not set.")
            print_info(
                "You can try running: catsniffer sniff ble -d 1 again in a few seconds."
            )
            # We don't return, allow to continue anyway

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
    dev = get_device_or_exit(device)
    cat = Catsniffer(dev.bridge_port)
    # Verify firmware with metadata (preferred)
    print_info("Checking for Sniffer TI firmware...")
    if cat.check_firmware_by_metadata("ti_sniffer", dev.shell_port):
        print_success("Sniffer TI firmware found (via metadata)!")
    elif cat.check_ti_firmware():
        print_success("Sniffer TI firmware found (via direct communication)!")
    else:
        print_warning("Sniffer TI firmware not found! - Flashing Sniffer TI")
        if not catnip.find_flash_firmware("ti_sniffer", dev):
            return

        print_info("Waiting for device to initialize...")
        time.sleep(3)

    print_info(f"[{dev}] Sniffing Zigbee at channel: {channel}")

    run_bridge(dev, channel, ws)


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
    dev = get_device_or_exit(device)
    cat = Catsniffer(dev.bridge_port)
    # Verify firmware with metadata (preferred)
    print_info("Checking for Sniffer TI firmware...")
    if cat.check_firmware_by_metadata("ti_sniffer", dev.shell_port):
        print_success("Sniffer TI firmware found (via metadata)!")
    elif cat.check_ti_firmware():
        print_success("Sniffer TI firmware found (via direct communication)!")
    else:
        print_warning("Sniffer TI firmware not found! - Flashing Sniffer TI")
        if not catnip.find_flash_firmware("ti_sniffer", dev):
            return

        print_info("Waiting for device to initialize...")
        time.sleep(3)

    print_info(f"[{dev}] Sniffing Thread at channel: {channel}")
    run_bridge(dev, channel, ws)


@sniff.command(SniffingFirmware.LORA.name.lower())
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

    print_info(f"[{dev}] Sniffing LoRa with configuration:")
    console.print(f"  Frequency:       {frequency} Hz ({frequency / 1000000:.3f} MHz)")
    console.print(f"  Bandwidth:       {bw_int} kHz")
    console.print(f"  Spreading Factor: SF{spread_factor}")
    console.print(f"  Coding Rate:     4/{coding_rate}")
    console.print(f"  TX Power:        {tx_power} dBm")

    run_sx_bridge(
        dev,
        frequency,
        bw_int,
        spread_factor,
        coding_rate,
        tx_power,
        ws,
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
    dev = get_device_or_exit(device)

    # Verify firmware
    cat = Catsniffer(dev.bridge_port)

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
        if not catnip.find_flash_firmware(official_id, dev):
            print_error("Failed to flash Airtag Scanner firmware")
            return

        # Wait for device to initialize
        print_info("Waiting for device to initialize after flashing...")
        time.sleep(4)

        # Verify
        if cat.check_firmware_by_metadata(official_id, dev.shell_port):
            print_success("Airtag Scanner firmware verified successfully!")
        else:
            print_warning("Firmware verification failed, but continuing...")

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
def flash(firmware, device, list) -> None:
    """Flash CC1352 Firmware or list available firmware images"""

    from .fw_aliases import get_official_id

    # Initialize Catnip to manage firmware operations
    catnip = Catnip()

    # If listing available firmwares is requested
    if list:
        console.print("\n[cyan bold]Available Firmware Images:[/cyan bold]\n")

        try:
            # Get the list of local firmwares
            firmwares = catnip.get_local_firmware()

            if not firmwares:
                print_warning("No firmware images found locally.")
                console.print(
                    "\nRun the CLI once to download the latest firmware images."
                )
                return

            # Create table to display firmwares
            table = Table(box=box.ROUNDED, show_header=True)
            table.add_column("Alias", style="green bold", min_width=15)
            table.add_column("Firmware Name", style="cyan", min_width=30)
            table.add_column("Type", style="yellow", min_width=12)
            table.add_column("Protocols", style="magenta", min_width=15)
            table.add_column("Description", style="white", min_width=40)

            # Get descriptions
            descriptions = catnip.parse_descriptions()

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

                # Determine type based on the name
                if "sniffle" in fw_lower or "ble" in fw_lower:
                    fw_type = "BLE"
                    protocols = "BLE"
                elif "sniffer_fw" in fw_lower or "sniffer_fw_cc1352" in fw_lower:
                    fw_type = "TI Sniffer"
                    protocols = "Zigbee/Thread/15.4"
                elif "zigbee" in fw_lower:
                    fw_type = "Zigbee"
                    protocols = "Zigbee"
                elif "thread" in fw_lower:
                    fw_type = "Thread"
                    protocols = "Thread"
                elif "lora" in fw_lower:
                    if "cad" in fw_lower:
                        fw_type = "LoRa CAD"
                        protocols = "LoRa"
                    elif "cli" in fw_lower:
                        fw_type = "LoRa CLI"
                        protocols = "LoRa"
                    elif "freq" in fw_lower:
                        fw_type = "LoRa Freq"
                        protocols = "LoRa"
                    elif "sniffer" in fw_lower:
                        fw_type = "LoRa Sniffer"
                        protocols = "LoRa"
                    else:
                        fw_type = "LoRa"
                        protocols = "LoRa"
                elif "airtag" in fw_lower:
                    if "scanner" in fw_lower:
                        fw_type = "Airtag Scanner"
                        protocols = "BLE"
                    elif "spoofer" in fw_lower:
                        fw_type = "Airtag Spoofer"
                        protocols = "BLE"
                    else:
                        fw_type = "Airtag"
                        protocols = "BLE"
                elif "15.4" in fw_lower or "154" in fw_lower:
                    fw_type = "15.4"
                    protocols = "15.4"
                elif "justworks" in fw_lower:
                    fw_type = "JustWorks"
                    protocols = "BLE"
                elif "free_dap" in fw_lower:
                    fw_type = "Debugger"
                    protocols = "Debug"
                elif "serial" in fw_lower:
                    fw_type = "Serial"
                    protocols = "Serial"
                elif "meshtastic" in fw_lower:
                    fw_type = "Meshtastic"
                    protocols = "LoRa"
                else:
                    fw_type = "Other"
                    protocols = "Various"

                # Get description
                desc = descriptions.get(fw_lower, "No description available")

                # Truncate description if it's too long
                if len(desc) > 50:
                    desc = desc[:47] + "..."

                table.add_row(f"[green]{alias}[/green]", fw, fw_type, protocols, desc)

            console.print(table)

            # Show most useful aliases
            console.print("\n[cyan bold]Recommended Aliases by Protocol:[/cyan bold]")

            console.print("\n  [yellow]BLE:[/yellow]")
            console.print(
                "    [green]ble[/green] / [green]sniffle[/green]     → Sniffle BLE sniffer"
            )
            console.print("    [green]airtag-scanner[/green] → Apple Airtag Scanner")
            console.print("    [green]airtag-spoofer[/green] → Apple Airtag Spoofer")
            console.print("    [green]justworks[/green]     → JustWorks scanner")

            console.print("\n  [yellow]Zigbee/Thread/15.4 (TI Sniffer):[/yellow]")
            console.print(
                "    [green]zigbee[/green]  → Texas Instruments multiprotocol sniffer"
            )
            console.print(
                "    [green]thread[/green]  → (same as zigbee - supports both)"
            )
            console.print(
                "    [green]15.4[/green]    → (same as zigbee - supports 802.15.4)"
            )
            console.print("    [green]ti[/green]      → Texas Instruments sniffer")
            console.print(
                "    [green]multiprotocol[/green] → TI multiprotocol firmware"
            )

            console.print("\n  [yellow]LoRa (RP2040):[/yellow]")
            console.print(
                "    [green]lora-sniffer[/green] → LoRa Sniffer for Wireshark"
            )
            console.print(
                "    [green]lora-cli[/green]    → LoRa Command Line Interface"
            )
            console.print(
                "    [green]lora-cad[/green]    → LoRa Channel Activity Detector"
            )
            console.print(
                "    [green]lora-freq[/green]   → LoRa Frequency Spectrum analyzer"
            )

            # Use Information
            console.print("\n[cyan bold]Usage Examples:[/cyan bold]")
            console.print(
                "  [green]catsniffer flash zigbee[/green]          (TI multiprotocol sniffer)"
            )
            console.print(
                "  [green]catsniffer flash thread[/green]         (same TI firmware)"
            )
            console.print(
                "  [green]catsniffer flash ble[/green]            (Sniffle BLE)"
            )
            console.print(
                "  [green]catsniffer flash lora-sniffer[/green]   (LoRa Sniffer)"
            )
            console.print(
                "  [green]catsniffer flash airtag-scanner[/green] (Apple Airtag)"
            )
            console.print("  [green]catsniffer flash --device 1 zigbee[/green]")

            return

        except Exception as e:
            print_error(f"Error listing firmwares: {str(e)}")
            import traceback

            traceback.print_exc()
            return

    # If flash is requested but no firmware is specified
    if firmware is None:
        print_error("No firmware specified!")
        console.print(
            "\nUse 'catsniffer flash --list' to see available firmware images and aliases."
        )
        console.print(
            "Or specify a firmware name: catsniffer flash <firmware_name_or_alias>"
        )
        exit(1)

    # First, check if it's a known alias
    official_id = get_official_id(firmware)
    if official_id and official_id != firmware:
        print_info(f"Alias '{firmware}' resolved to: {official_id}")

    # If no device is specified, get all connected devices
    if device is None:
        devs = catsniffer_get_devices()
        if not devs:
            print_error("No CatSniffer devices found!")
            console.print("    Make sure your CatSniffer is connected.")
            exit(1)

        # Select the first device by default
        dev = devs[0]
        print_warning(f"No device specified. Using first device: {dev}")
    else:
        # If an ID is specified, get that specific device
        dev = catsniffer_get_device(device)
        if dev is None:
            print_error(f"CatSniffer device with ID {device} not found!")
            console.print("    Use 'devices' command to list available devices.")
            exit(1)

    # Verify that the device is valid
    if not dev.is_valid():
        print_warning(f"Not all ports detected for {dev}")
        console.print(f"    Bridge: {dev.bridge_port}")
        console.print(f"    LoRa:   {dev.lora_port}")
        console.print(f"    Shell:  {dev.shell_port}")

    print_info(f"Flashing firmware: {firmware} to device: {dev}")

    flash_result = catnip.find_flash_firmware(firmware, dev)

    if not flash_result:
        print_error(f"Error flashing: {firmware}")
        console.print(f"\n[yellow]Troubleshooting tips:[/yellow]")
        console.print(
            f"1. Use [green]catsniffer flash --list[/green] to see all available firmwares"
        )
        console.print(
            f"2. Available aliases: ble, zigbee, thread, lora-sniffer, airtag-scanner"
        )
        console.print(f"3. Use the exact filename from the list")
        console.print(f"4. Note: 'zigbee' alias maps to TI multiprotocol firmware")
        return

    print_info("Waiting for device to restart...")
    time.sleep(4)
    print_success("Device restart complete. Firmware is ready to use!")


@cli.command()
def help_firmware() -> None:
    """Show detailed information about available firmware images"""
    console.print("\n[cyan bold]Firmware Flash Help[/cyan bold]\n")
    console.print("To see all available firmware images:")
    console.print("  [green]catsniffer flash --list[/green]\n")

    console.print("To flash a specific firmware:")
    console.print("  [green]catsniffer flash <firmware_name>[/green]\n")

    console.print("Examples of firmware names:")
    console.print("  • sniffle_cc1352p7_1M.hex - BLE Sniffer (Sniffle firmware)")
    console.print("  • cc1352_sniffer_zigbee.hex - Zigbee Sniffer")
    console.print("  • cc1352_sniffer_thread.hex - Thread Sniffer")
    console.print("  • cc1352_sniffer_lora.hex - LoRa Sniffer\n")

    console.print("To specify a device (if multiple are connected):")
    console.print("  [green]catsniffer flash --device 1 <firmware_name>[/green]\n")

    console.print("[yellow]Note:[/yellow] Firmware images are automatically downloaded")
    console.print("on first run and can be updated by running the CLI daily.")


@cli.command()
def devices() -> None:
    """List connected CatSniffer devices"""
    devs = catsniffer_get_devices()
    if not devs:
        print_warning("No CatSniffer devices found.")
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

    console.print()
    console.print(table)


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
        console.print("\n[yellow]Install missing dependencies:[/yellow]")
        console.print("  pip install pyusb pyserial")
        return 1

    # Run verification
    success, results = run_verification(
        test_all=test_all, device_id=device, quiet=quiet
    )

    # Print final message
    if success:
        print_success("Verification completed successfully!")
        if test_all:
            console.print(
                "\n[green]✓ All devices are fully functional and ready for use![/green]"
            )
        else:
            console.print(
                "\n[green]✓ Basic functionality verified. Use --test-all for comprehensive testing.[/green]"
            )
        return 0
    else:
        print_error("Verification failed!")
        console.print("\n[yellow]Troubleshooting tips:[/yellow]")
        console.print(
            "1. Make sure all 3 USB endpoints are connected (Bridge, LoRa, Shell)"
        )
        console.print("2. Try reconnecting the USB cable")
        console.print("3. Check if the correct firmware is flashed")
        console.print("4. Verify serial port permissions (Linux/Mac)")
        return 1


def main_cli() -> None:
    print_header()
    cli.add_command(sniff)
    cli.add_command(help_firmware)
    cli.add_command(verify)
    cli()

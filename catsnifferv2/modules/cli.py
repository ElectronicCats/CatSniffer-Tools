#! /usr/bin/env python3

# Kevin Leon @ Electronic Cats
# Original Creation Date: Dec 19, 2025
# This code is beerware; if you see me (or any other Electronic Cats
# member) at the local, and you've found our code helpful,
# please buy us a round!
# Distributed as-is; no warranty is given.

import logging
import os

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
PROMPT_ICON = "󰄛"
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


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--verbose", is_flag=True, help="Show Verbose mode")
def cli(verbose):
    """CatSniffer: All in one catsniffer tools environment."""
    if verbose:
        logger.level = logging.INFO
    pass


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--verbose", is_flag=True, help="Show Verbose mode")
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
def sniff_ble(device):
    """Sniffing BLE with Sniffle firmware"""
    dev = get_device_or_exit(device)
    cat = Catsniffer(dev.bridge_port)
    if cat.check_sniffle_firmware():
        print_info("Firmware found!")
    else:
        print_warning("Firmware not found! - Flashing Sniffle")
        if not catnip.find_flash_firmware(SniffingBaseFirmware.BLE.value, dev):
            return

    print_info("Now you can open Sniffle extcap from Wireshark")


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
    if cat.check_ti_firmware():
        print_info("Firmware found!")
    else:
        print_warning("Firmware not found! - Flashing Sniffer TI")
        if not catnip.find_flash_firmware(SniffingBaseFirmware.ZIGBEE.value, dev):
            return

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
    if cat.check_ti_firmware():
        print_info("Firmware found!")
    else:
        print_warning("Firmware not found! - Flashing Sniffer TI")
        if not catnip.find_flash_firmware(SniffingBaseFirmware.THREAD.value, dev):
            return

    print_info(f"[{dev}] Sniffing Thread at channel: {channel}")
    run_bridge(dev, channel, ws)


@sniff.command(SniffingFirmware.LORA.name.lower())
@click.option("-ws", is_flag=True, help="Open Wireshark")
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


@cli.command()
def cativity() -> None:
    """IQ Activity Monitor (Not implemented yet)"""
    print_info("Monitoring IQ activity")


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

    # Alias dictionary for common firmwares
    PREDEFINED_ALIASES = {
        # Short aliases for the most used firmwares
        "ble": "sniffle",
        "zigbee": "cc1352_sniffer_zigbee",
        "thread": "cc1352_sniffer_thread",
        "lora": "cc1352_sniffer_lora",
        "15.4": "cc1352_sniffer_154",
        "base": "cc1352_base",
        "sniffle": "sniffle_cc1352p7_1M",
        "sniffle-full": "sniffle_cc1352p7_1M.hex",
        "zigbee-full": "cc1352_sniffer_zigbee.hex",
        "thread-full": "cc1352_sniffer_thread.hex",
        "lora-full": "cc1352_sniffer_lora.hex",
    }

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
            table.add_column("Alias", style="green bold")
            table.add_column("Firmware Name", style="cyan")
            table.add_column("Type", style="yellow")
            table.add_column("Description", style="white")

            # Get descriptions
            descriptions = catnip.parse_descriptions()

            # Map aliases to complete firmware
            firmware_to_alias = {}
            alias_usage_count = {}

            # Generate automatic aliases based on common names
            for fw in sorted(firmwares):
                fw_lower = fw.lower()
                fw_name_without_ext = os.path.splitext(fw)[0]

                # Check if it matches any predefined alias
                for alias, target in PREDEFINED_ALIASES.items():
                    if target.lower() in fw_lower:
                        firmware_to_alias[fw] = alias
                        alias_usage_count[alias] = alias_usage_count.get(alias, 0) + 1
                        break

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
                elif "zigbee" in fw_lower:
                    fw_type = "Zigbee"
                elif "thread" in fw_lower:
                    fw_type = "Thread"
                elif "lora" in fw_lower:
                    if "cad" in fw_lower:
                        fw_type = "LoRa CAD"
                    elif "cli" in fw_lower:
                        fw_type = "LoRa CLI"
                    elif "freq" in fw_lower:
                        fw_type = "LoRa Freq"
                    elif "sniffer" in fw_lower:
                        fw_type = "LoRa Sniffer"
                    else:
                        fw_type = "LoRa"
                elif "airtag" in fw_lower:
                    if "scanner" in fw_lower:
                        fw_type = "Airtag Scanner"
                    elif "spoofer" in fw_lower:
                        fw_type = "Airtag Spoofer"
                    else:
                        fw_type = "Airtag"
                elif "15.4" in fw_lower or "154" in fw_lower:
                    fw_type = "15.4"
                elif "base" in fw_lower or "cc1352" in fw_lower:
                    fw_type = "Base"
                elif "justworks" in fw_lower:
                    fw_type = "JustWorks"
                elif "free_dap" in fw_lower:
                    fw_type = "Debugger"
                elif "serial" in fw_lower:
                    fw_type = "Serial"
                elif "meshtastic" in fw_lower:
                    fw_type = "Meshtastic"
                else:
                    fw_type = "Other"

                # Get description
                desc = descriptions.get(fw_lower, "No description available")

                # Truncate description if it's too long
                if len(desc) > 50:
                    desc = desc[:47] + "..."

                table.add_row(f"[green]{alias}[/green]", fw, fw_type, desc)

            console.print(table)

            # Show most useful aliases
            console.print("\n[cyan bold]Recommended Aliases:[/cyan bold]")

            # Group aliases by type
            aliases_by_type = {}
            for fw, alias in firmware_to_alias.items():
                fw_lower = fw.lower()

                if "sniffle" in fw_lower or "ble" in fw_lower:
                    cat = "BLE"
                elif "airtag" in fw_lower:
                    cat = "Airtag"
                elif "lora" in fw_lower:
                    cat = "LoRa"
                elif "zigbee" in fw_lower:
                    cat = "Zigbee"
                elif "thread" in fw_lower:
                    cat = "Thread"
                elif "justworks" in fw_lower:
                    cat = "JustWorks"
                else:
                    cat = "Other"

                if cat not in aliases_by_type:
                    aliases_by_type[cat] = []
                aliases_by_type[cat].append(f"{alias} → {os.path.splitext(fw)[0]}")

            # Display organized aliases
            for cat in sorted(aliases_by_type.keys()):
                if aliases_by_type[cat]:
                    console.print(f"\n  [yellow]{cat}:[/yellow]")
                    for item in sorted(aliases_by_type[cat])[
                        :5
                    ]:  # Show max 5 per category
                        console.print(f"    {item}")

            # Usage information
            console.print("\n[cyan bold]Usage Examples:[/cyan bold]")
            console.print(
                "  [green]catsniffer flash ble[/green]         (uses 'sniffle' alias)"
            )
            console.print(
                "  [green]catsniffer flash zigbee[/green]      (uses 'zigbee' alias)"
            )
            console.print(
                "  [green]catsniffer flash sniffle-full[/green]  (full sniffle filename)"
            )
            console.print("  [green]catsniffer flash --device 1 thread[/green]")

            return

        except Exception as e:
            print_error(f"Error listing firmwares: {str(e)}")
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
    original_firmware = firmware
    if firmware in PREDEFINED_ALIASES:
        firmware = PREDEFINED_ALIASES[firmware]
        print_info(f"Alias '{original_firmware}' resolved to: {firmware}")

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

    if not catnip.find_flash_firmware(firmware, dev):
        print_error(f"Error flashing: {firmware}")
        console.print(f"\n[yellow]Troubleshooting tips:[/yellow]")
        console.print(
            f"1. Use [green]catsniffer flash --list[/green] to see all available firmwares"
        )
        console.print(f"2. Available aliases: ble, zigbee, thread, lora, 15.4, base")
        console.print(f"3. Try the exact filename from the list")


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

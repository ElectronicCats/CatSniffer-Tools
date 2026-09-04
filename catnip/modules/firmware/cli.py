"""``catnip flash|verify|update|restore`` - firmware commands.

Registered one by one on the root group (they are not a Click group), see
section 3.2 of ``CLI_REFACTOR_PLAN.md``.
"""

import os
import sys
import time

# Internal
from .flasher import Flasher
from .verify import run_verification
from ..core.catnip import catnip_get_device, catnip_get_devices
from ..core.device_utils import send_identify_command

# External
import click
from rich.table import Table
from rich import box

from ..utils.cli_options import device_option
from ..utils.output import (
    console,
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


@click.command()
@click.argument("firmware", required=False)
@device_option(
    help="Device ID (for multiple CatSniffers). If not specified, first device will be selected."
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

    from .fw_aliases import get_official_id

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


@click.command()
@click.option(
    "--test-all",
    is_flag=True,
    help="Run all tests including LoRa configuration and communication",
)
@device_option(help="Test only a specific device (by ID)")
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
        sys.exit(1)

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


# ===================== Firmware Update Commands =====================


@click.command()
@device_option()
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
    from .fw_update import (
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
@device_option(help="Device ID (for shell access to trigger BOOTSEL)")
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
    from .restore import restore_cc1352

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

#! /usr/bin/env python3

# Electronic Cats
# Original Creation Date: Dec 19, 2025
# This code is beerware; if you see me (or any other Electronic Cats
# member) at the local, and you've found our code helpful,
# please buy us a round!
# Distributed as-is; no warranty is given.

import logging
import os
import sys

# Internal
from ..utils._version import __version__
from ..firmware.flasher import Flasher
from ..firmware.verify import run_verification
from .device_utils import get_device_or_exit, send_identify_command
from .catnip import catnip_get_device, catnip_get_devices
from .usb_connection import ShellConnection, CATSNIFFER_VID, CATSNIFFER_PID

# Command groups assembled by build_cli()
from ..sniff.cli import sniff as _sniff
from ..protocols.cli.cativity import cativity as _cativity
from ..protocols.cli.meshtastic import meshtastic as _meshtastic
from ..protocols.cli.sx1262 import lora as _lora
from ..protocols.cli.vhci import vhci as _vhci

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


@click.group("catnip", context_settings={"help_option_names": ["-h", "--help"]})
@click.option("-v", "--verbose", is_flag=True, help="Show Verbose mode")
def cli(verbose):
    """CatSniffer: All in one catnip tools environment."""
    if verbose:
        logger.level = logging.INFO
    pass


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
    except OSError as e:
        print_error(f"Failed to generate completion script: {e}")
        sys.exit(1)

    if not script.strip():
        print_error(
            "Empty completion script generated.\n"
            "Make sure you are running this command via:\n"
            f"  python {script_abs} completion install"
        )
        if result.stderr.strip():
            print_dim(result.stderr.strip())
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
        # Click <=8.0 emits:  _CATNIP_COMPLETE=bash_complete catnip
        # Click >=8.1 emits:  _CATNIP_COMPLETE=bash_complete $1
        script = script.replace(
            f"{env_var}=bash_complete catnip", f"{env_var}=bash_complete {cmd_to_call}"
        )
        script = script.replace(
            f"{env_var}=bash_complete $1", f"{env_var}=bash_complete {cmd_to_call}"
        )
        # Register for both 'catnip' and 'catnip.py' (Click 8.1 adds -o nosort)
        script = script.replace(
            "complete -F _catnip_completion catnip",
            "complete -F _catnip_completion catnip catnip.py",
        )
        script = script.replace(
            "complete -o nosort -F _catnip_completion catnip",
            "complete -o nosort -F _catnip_completion catnip catnip.py",
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
        # Fish uses a different mechanism; just replace the bare program name.
        # Click <=8.0 puts it right after the env var, >=8.1 after COMP_CWORD.
        script = script.replace(
            f"{env_var}=fish_complete catnip", f"{env_var}=fish_complete {cmd_to_call}"
        )
        script = script.replace(
            "COMP_CWORD=(commandline -t) catnip)",
            f"COMP_CWORD=(commandline -t) {cmd_to_call})",
        )
        # Also complete when invoked as './catnip.py'
        script += (
            "\ncomplete --no-files --command catnip.py "
            '--arguments "(_catnip_completion)"\n'
        )

    # Write script
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(script, encoding="utf-8")
    except OSError as e:
        print_error(f"could not write completion script to {target}: {e}")
        sys.exit(1)
    print_success(f"Completion script written to: {target}")

    # zsh needs fpath entry in .zshrc
    if rc_note:
        zshrc = Path.home() / ".zshrc"
        try:
            existing = zshrc.read_text(encoding="utf-8") if zshrc.exists() else ""
        except OSError as e:
            print_error(f"could not read {zshrc}: {e}")
            sys.exit(1)
        if "~/.zfunc" not in existing and ".zfunc" not in existing:
            try:
                if zshrc.exists():
                    backup = zshrc.with_name(".zshrc.bak-catnip")
                    backup.write_text(existing, encoding="utf-8")
                with zshrc.open("a", encoding="utf-8") as f:
                    f.write(f"\n# catnip tab completion\n{rc_note}\n")
            except OSError as e:
                print_error(f"could not update {zshrc}: {e}")
                sys.exit(1)
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


def build_cli() -> click.Group:
    """Register every command on the root group and return it assembled.

    Kept apart from :func:`main_cli` so the command tree can be inspected
    without running it (tests, snapshot dumps).
    """
    cli.add_command(_sniff)
    cli.add_command(_cativity)
    cli.add_command(_meshtastic)
    cli.add_command(restore)
    cli.add_command(_lora)
    if platform.system() == "Linux":
        cli.add_command(_vhci)
        cli.add_command(setup_env)
    cli.add_command(verify)
    if platform.system() in ["Linux", "Darwin"]:
        cli.add_command(completion)
    return cli


def main_cli() -> None:
    if not os.environ.get("_CATNIP_COMPLETE"):
        module = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
        print_header(module)
    build_cli()(prog_name="catnip")

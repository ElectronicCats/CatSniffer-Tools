"""
Firmware Update Module for CatSniffer RP2040
=============================================

This module handles automatic firmware version verification and update
for the RP2040 microcontroller on the CatSniffer board.

Workflow:
    1. Fetch latest software version from CatSniffer-Tools GitHub releases
    2. Compare local tool version against the remote software version
    3. Query the device FW version via the 'fw_version' shell command
    4. Compare device FW against the expected firmware release (CatSniffer-Firmware)
    5. If FW outdated: send 'reboot' to enter boot mode and flash UF2
    6. If device not detected: instruct user to enter Boot Mode manually

Compatibility example:
    Software: 3.3.1.0 (from CatSniffer-Tools repo)
    Firmware: v3.1.0.0 (from CatSniffer-Firmware repo)

Shell commands used:
    - fw_version: Returns firmware version info from the RP2040
    - reboot: Puts the RP2040 into UF2 boot mode
"""

import os
import re
import time
import glob
import shutil
import logging
from typing import Optional, Dict, Tuple

import requests

from ..core.catnip import (
    ShellConnection,
    CatSnifferDevice,
    catnip_get_devices,
    catnip_get_device,
    SHELL_CMD_FW_VERSION,
    SHELL_CMD_REBOOT,
    CATSNIFFER_VID,
    CATSNIFFER_PID,
)

from ..utils._version import __version__ as TOOL_VERSION
from ..utils.output import (
    console,
    print_success,
    print_warning,
    print_error,
    print_info,
    print_dim,
    print_empty_line,
    print_title,
    print_error_section,
    print_success_section,
    print_instruction_step,
)

logger = logging.getLogger("rich")

# GitHub API URL for the latest CatSniffer-Tools software release
GITHUB_TOOLS_RELEASE_URL = (
    "https://api.github.com/repos/ElectronicCats/CatSniffer-Tools/releases/latest"
)


def get_tool_version() -> str:
    """Return the current local tool version string."""
    return TOOL_VERSION


def get_latest_software_version() -> Optional[str]:
    """
    Fetch the latest software version from CatSniffer-Tools GitHub releases.

    Queries the GitHub API for the latest release tag of the
    ElectronicCats/CatSniffer-Tools repository.

    Returns:
        Version string (e.g., '3.3.1.0') stripped of 'v' prefix, or None on error
    """
    try:
        response = requests.get(GITHUB_TOOLS_RELEASE_URL, timeout=5)
        response.raise_for_status()
        data = response.json()
        tag = data.get("tag_name", "")
        # Strip 'v' prefix if present (e.g., "v3.3.1.0" → "3.3.1.0")
        return tag.lstrip("v") if tag else None
    except requests.exceptions.ConnectionError:
        logger.warning("[!] No internet connection — cannot check software version")
        return None
    except requests.exceptions.RequestException as e:
        logger.warning(f"[!] Error fetching software version: {e}")
        return None
    except Exception as e:
        logger.warning(f"[!] Unexpected error checking software version: {e}")
        return None


def _parse_version(version: str) -> tuple:
    """Convert a version string like '3.3.1.0' into a comparable tuple of ints."""
    try:
        return tuple(int(x) for x in version.lstrip("v").split("."))
    except (ValueError, AttributeError):
        return (0,)


def is_software_up_to_date(local_version: str, remote_version: str) -> bool:
    """
    Compare the local tool version against the latest remote release.

    Args:
        local_version: Local tool version (e.g., '3.0.0')
        remote_version: Remote release version (e.g., '3.3.1.0')

    Returns:
        True if local version matches remote, False otherwise
    """
    if not local_version or not remote_version:
        return False

    return _parse_version(local_version) == _parse_version(remote_version)


def is_software_dev_version(local_version: str, remote_version: str) -> bool:
    """
    Check if the local version is ahead of the latest release (dev/test build).

    Args:
        local_version: Local tool version (e.g., '3.4.0.0')
        remote_version: Remote release version (e.g., '3.3.1.0')

    Returns:
        True if local version is strictly greater than remote, False otherwise
    """
    if not local_version or not remote_version:
        return False

    return _parse_version(local_version) > _parse_version(remote_version)


def get_device_fw_version(shell_port: str) -> Optional[Dict[str, str]]:
    """
    Query the RP2040 firmware version via the shell port.

    Sends the 'fw_version' command and parses the multiline response:
        FW: dev-373e0cd-clean
        Git: 373e0cd(clean)
        Built: 2026-02-28T05:44:25Z
        Compiler: GNU 12.2.0

    Args:
        shell_port: Path to the shell serial port (e.g., /dev/ttyACM2)

    Returns:
        dict with keys 'fw', 'git', 'built', 'compiler', or None on failure
    """
    shell = None
    try:
        shell = ShellConnection(port=shell_port, timeout=2.0)
        if not shell.connect():
            logger.warning("[!] Could not connect to shell port for fw_version")
            return None

        # Flush buffers
        if shell.connection:
            if hasattr(shell.connection, "reset_input_buffer"):
                shell.connection.reset_input_buffer()
            if hasattr(shell.connection, "reset_output_buffer"):
                shell.connection.reset_output_buffer()

        response = shell.send_command(SHELL_CMD_FW_VERSION, timeout=3.0)
        shell.disconnect()

        if not response:
            return None

        return parse_fw_version_response(response)

    except Exception as e:
        logger.error(f"[X] Error querying fw_version: {e}")
        if shell:
            try:
                shell.disconnect()
            except Exception:
                pass
        return None


def parse_fw_version_response(response: str) -> Optional[Dict[str, str]]:
    """
    Parse the fw_version command response into a dictionary.

    Expected format:
        FW: <version>
        Git: <hash>
        Built: <timestamp>
        Compiler: <compiler info>

    Args:
        response: Raw string response from fw_version command

    Returns:
        dict with parsed fields, or None if parsing fails
    """
    if not response:
        return None

    result = {}
    for line in re.split(r"[\r\n]+", response):
        line = line.strip()
        if not line:
            continue

        # Match "Key: Value" pattern
        match = re.match(r"^(\w+):\s*(.+)$", line)
        if match:
            key = match.group(1).lower()
            value = match.group(2).strip()
            result[key] = value

    # Must have at least the 'fw' field
    if "fw" not in result:
        return None

    return result


def get_expected_fw_tag(flasher) -> Optional[str]:
    """
    Get the expected firmware version tag from the Flasher release manager.

    Args:
        flasher: Flasher instance with loaded release metadata

    Returns:
        Release tag string (e.g., 'v3.1.0.0') or None
    """
    tag = getattr(flasher, "release_tag", None)
    return tag


def is_fw_compatible(device_fw: Dict[str, str], expected_tag: str) -> bool:
    """
    Check if the device firmware is compatible with the expected release tag.

    Compatibility is determined by checking if the release tag version
    appears in the device firmware version string. For example:
    - Device FW: "v3.1.0.0" is compatible with tag "v3.1.0.0"
    - Device FW: "dev-373e0cd-clean" is NOT compatible with tag "v3.1.0.0"

    Also checks the UF2 firmware naming convention:
    - UF2 name: "catnip-v3.1.0.0.uf2" → tag "v3.1.0.0"

    Args:
        device_fw: dict from parse_fw_version_response
        expected_tag: Release tag (e.g., 'v3.1.0.0')

    Returns:
        True if compatible, False otherwise
    """
    if not device_fw or not expected_tag:
        return False

    fw_version = device_fw.get("fw", "")

    # Direct match: FW string contains the release tag
    if expected_tag in fw_version:
        return True

    # Strip 'v' prefix for comparison (e.g., "v3.1.0.0" → "3.1.0.0")
    tag_no_v = expected_tag.lstrip("v")
    if tag_no_v in fw_version:
        return True

    return False


def find_uf2_firmware(flasher) -> Optional[str]:
    """
    Find the UF2 firmware file path in the local release folder.

    Args:
        flasher: Flasher instance with loaded release metadata

    Returns:
        Absolute path to the UF2 file, or None if not found
    """
    try:
        release_path = flasher.get_releases_path()
        if not os.path.exists(release_path):
            return None

        for filename in os.listdir(release_path):
            if filename.lower().endswith(".uf2"):
                return os.path.join(release_path, filename)

        return None
    except Exception as e:
        logger.error(f"[X] Error finding UF2 firmware: {e}")
        return None


def find_rp2040_mount_point() -> Optional[str]:
    """
    Find the RP2040 mass storage mount point when in boot mode.

    When the RP2040 is in UF2 boot mode, it appears as a USB mass storage
    device named 'RPI-RP2'.

    Returns:
        Mount point path (e.g., '/media/user/RPI-RP2') or None
    """
    import platform

    system = platform.system()

    if system == "Linux":
        # Check common mount points
        search_paths = [
            "/media/*/RPI-RP2",
            "/run/media/*/RPI-RP2",
            "/mnt/RPI-RP2",
        ]
        for pattern in search_paths:
            matches = glob.glob(pattern)
            if matches:
                return matches[0]

    elif system == "Darwin":  # macOS
        mount_path = "/Volumes/RPI-RP2"
        if os.path.exists(mount_path):
            return mount_path

    elif system == "Windows":
        # Check all drive letters for RPI-RP2 volume
        import string

        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            try:
                if os.path.exists(drive):
                    # Check volume label
                    label_path = os.path.join(drive, "INFO_UF2.TXT")
                    if os.path.exists(label_path):
                        return drive
            except Exception:
                continue

    return None


def flash_rp2040_uf2(uf2_path: str) -> bool:
    """
    Flash the RP2040 by copying the UF2 file to its mass storage device.

    The RP2040, when in boot mode, appears as a USB mass storage device.
    Copying a UF2 file to this device triggers the firmware update.

    Args:
        uf2_path: Path to the UF2 firmware file

    Returns:
        True if the copy was successful, False otherwise
    """
    if not os.path.exists(uf2_path):
        print_error(f"UF2 file not found: {uf2_path}")
        return False

    mount_point = find_rp2040_mount_point()
    if not mount_point:
        print_error("RP2040 boot device not found!")
        print_warning("The device must be in UF2 Boot Mode.")
        return False

    try:
        dest = os.path.join(mount_point, os.path.basename(uf2_path))
        print_info(f"Copying UF2 firmware to {mount_point}...")
        shutil.copy2(uf2_path, dest)
        print_success("UF2 firmware copied successfully!")
        return True
    except Exception as e:
        print_error(f"Error copying UF2 firmware: {e}")
        return False


def enter_boot_mode(shell_port: str) -> bool:
    """
    Send the 'reboot' command to put the RP2040 into UF2 boot mode.

    Args:
        shell_port: Path to the shell serial port

    Returns:
        True if the command was sent successfully, False otherwise
    """
    shell = None
    try:
        shell = ShellConnection(port=shell_port, timeout=2.0)
        if not shell.connect():
            print_error("Could not connect to shell port")
            return False

        # Flush buffers
        if shell.connection:
            if hasattr(shell.connection, "reset_input_buffer"):
                shell.connection.reset_input_buffer()
            if hasattr(shell.connection, "reset_output_buffer"):
                shell.connection.reset_output_buffer()

        print_info("Sending reboot command to enter Boot Mode...")
        response = shell.send_command(SHELL_CMD_REBOOT, timeout=2.0)

        # The device will reboot, so the connection may drop — that's expected
        try:
            shell.disconnect()
        except Exception:
            pass

        return True

    except Exception as e:
        logger.error(f"[X] Error entering boot mode: {e}")
        if shell:
            try:
                shell.disconnect()
            except Exception:
                pass
        return False


def _print_boot_mode_instructions():
    """Print instructions for manually entering RP2040 boot mode."""
    print_error_section("DEVICE NOT DETECTED — Manual Action Required")
    print_warning("The CatSniffer USB endpoints were not found.")
    print_warning("This may indicate corrupted or missing firmware.")
    print_empty_line()
    print_title("To recover the device, follow these steps:")
    print_empty_line()
    print_instruction_step(
        1,
        "[bold]Hold down[/bold] the button [bold cyan]RESET1[/bold cyan] on the CatSniffer",
    )
    print_instruction_step(
        2, "Press [bold cyan]SW1[/bold cyan] button on the CatSniffer"
    )
    print_instruction_step(
        3,
        "While holding [bold cyan]SW1[/bold cyan], [bold]release[/bold] [bold cyan]RESET1[/bold cyan] on the CatSniffer",
    )
    print_instruction_step(4, "Release the [bold cyan]SW1[/bold cyan] button")
    print_instruction_step(
        5, "The CatSniffer should appear as a USB drive named [bold]RPI-RP2[/bold]"
    )
    print_instruction_step(
        6,
        "[bold]Copy[/bold] the [bold green].uf2[/bold green] file directly to the RPI-RP2 drive.",
    )
    print_empty_line()


def check_and_update_rp2040(device: CatSnifferDevice = None, flasher=None) -> bool:
    """
    Main orchestration function for RP2040 firmware update.

    Flow:
        1. Check local tool version against latest CatSniffer-Tools release
        2. Get expected FW tag from CatSniffer-Firmware release (via Flasher)
        3. Detect device (check 3 USB endpoints)
        4. If device detected: query fw_version and compare against expected FW
        5. If FW outdated: send reboot → wait for boot mode → flash UF2
        6. If device NOT detected: print manual Boot Mode instructions

    Args:
        device: CatSnifferDevice instance (auto-detected if None)
        flasher: Flasher instance (created if None)

    Returns:
        True if firmware is up-to-date or successfully updated, False otherwise
    """
    # Step 1: Get tool version and check against remote
    tool_ver = get_tool_version()
    print_info(f"Local Tool Version: {tool_ver}")

    remote_sw_ver = get_latest_software_version()
    if remote_sw_ver:
        print_info(f"Latest Software Release: {remote_sw_ver}")
        if is_software_up_to_date(tool_ver, remote_sw_ver):
            print_success("Tool is up-to-date")
        elif is_software_dev_version(tool_ver, remote_sw_ver):
            print_warning(
                f"Development version detected! Local: {tool_ver} > Latest release: {remote_sw_ver}"
            )
            print_warning(
                "This build is ahead of the latest release and may be unstable."
            )
            print_warning(
                "Use it for testing only — firmware compatibility is not guaranteed."
            )
        else:
            print_warning(
                f"Tool is outdated! Local: {tool_ver} → Latest: {remote_sw_ver}"
            )
            print_warning("Please update the CatSniffer-Tools to ensure compatibility.")
    else:
        print_dim("Could not check latest software version (offline?)")

    # Step 2: Get expected firmware version from CatSniffer-Firmware release
    if flasher is None:
        from .flasher import Flasher

        flasher = Flasher()

    expected_fw_tag = get_expected_fw_tag(flasher)
    if not expected_fw_tag:
        print_warning("Could not determine expected firmware version")
        print_dim("Release metadata may not be loaded.")
        return False

    print_info(f"Expected Firmware Version: {expected_fw_tag}")

    # Show compatibility pairing
    print_empty_line()
    print_title("Compatibility Check:")
    print_dim(
        f"Software: [cyan]{remote_sw_ver or tool_ver}[/cyan] ↔ "
        f"Firmware: [cyan]{expected_fw_tag}[/cyan]"
    )
    print_empty_line()

    # Step 3: Detect device
    if device is None:
        device = catnip_get_device()

    if device is None:
        # No device detected — check if RP2040 is already in boot mode
        print_warning("No CatSniffer device detected")

        mount_point = find_rp2040_mount_point()
        if mount_point:
            print_success(f"RP2040 Boot Mode detected at: {mount_point}")
            uf2_path = find_uf2_firmware(flasher)
            if uf2_path:
                print_info(f"Flashing UF2: {os.path.basename(uf2_path)}")
                return flash_rp2040_uf2(uf2_path)
            else:
                print_error("No UF2 firmware found in release folder!")
                return False
        else:
            _print_boot_mode_instructions()
            return False

    print_success(f"Device detected: {device}")
    print_dim(f"Bridge: {device.bridge_port}")
    print_dim(f"LoRa:   {device.lora_port}")
    print_dim(f"Shell:  {device.shell_port}")

    # Step 4: Query device FW version
    if not device.shell_port:
        print_warning("Shell port not available, cannot query FW version")
        return False

    print_info("Querying device firmware version...")
    device_fw = get_device_fw_version(device.shell_port)

    if device_fw is None:
        print_warning("Could not read firmware version from device")
        print_dim("The device may have corrupted firmware.")
        return False

    print_info(f"Device FW Version: {device_fw.get('fw', 'unknown')}")
    if device_fw.get("git"):
        print_dim(f"Git: {device_fw['git']}")
    if device_fw.get("built"):
        print_dim(f"Built: {device_fw['built']}")

    # Step 5: Compare device FW against expected firmware release
    if is_fw_compatible(device_fw, expected_fw_tag):
        print_success(f"Firmware is compatible with release {expected_fw_tag}")
        return True

    # Firmware is outdated
    print_warning(
        f"Firmware mismatch! Device: {device_fw.get('fw', '?')} ≠ Expected: {expected_fw_tag}"
    )

    return _perform_rp2040_update(device, flasher)


def force_update_rp2040(device: CatSnifferDevice = None, flasher=None) -> bool:
    """
    Force update the RP2040 firmware regardless of version compatibility.

    Args:
        device: CatSnifferDevice instance (auto-detected if None)
        flasher: Flasher instance (created if None)

    Returns:
        True if successfully updated, False otherwise
    """
    if flasher is None:
        from .flasher import Flasher

        flasher = Flasher()

    expected_tag = get_expected_fw_tag(flasher)
    print_info(f"Force updating to release: {expected_tag or 'latest'}")

    if device is None:
        device = catnip_get_device()

    if device is None:
        # Check for boot mode
        mount_point = find_rp2040_mount_point()
        if mount_point:
            print_success(f"RP2040 Boot Mode detected at: {mount_point}")
            uf2_path = find_uf2_firmware(flasher)
            if uf2_path:
                return flash_rp2040_uf2(uf2_path)
            else:
                print_error("No UF2 firmware found!")
                return False
        else:
            _print_boot_mode_instructions()
            return False

    return _perform_rp2040_update(device, flasher)


def _perform_rp2040_update(device: CatSnifferDevice, flasher) -> bool:
    """
    Perform the actual RP2040 firmware update sequence.

    1. Find UF2 firmware
    2. Enter boot mode via reboot command
    3. Wait for RP2040 mass storage
    4. Flash UF2

    Args:
        device: CatSnifferDevice with valid shell_port
        flasher: Flasher instance

    Returns:
        True on success, False on failure
    """
    # Find UF2 firmware
    uf2_path = find_uf2_firmware(flasher)
    if not uf2_path:
        print_error("No UF2 firmware found in release folder!")
        print_dim("Run the CLI to download the latest release first.")
        return False

    print_info(f"UF2 firmware: {os.path.basename(uf2_path)}")

    # Enter boot mode
    if not device.shell_port:
        print_warning("Shell port not available to send reboot command")
        _print_boot_mode_instructions()
        return False

    if not enter_boot_mode(device.shell_port):
        print_warning("Could not send reboot command")
        _print_boot_mode_instructions()
        return False

    # Wait for RP2040 to appear as mass storage
    print_info("Waiting for RP2040 boot device to appear...")
    mount_point = None
    for i in range(15):  # Wait up to ~15 seconds
        time.sleep(1)
        mount_point = find_rp2040_mount_point()
        if mount_point:
            break
        if i % 3 == 2:
            print_dim(f"Still waiting... ({i + 1}s)")

    if not mount_point:
        print_error("RP2040 boot device did not appear!")
        _print_boot_mode_instructions()
        return False

    print_success(f"RP2040 Boot Mode detected at: {mount_point}")

    # Flash UF2
    if flash_rp2040_uf2(uf2_path):
        print_success_section("RP2040 Firmware Updated Successfully!")
        print_dim("The device will reboot automatically.")
        print_dim("Wait a few seconds before using other commands.")
        return True
    else:
        return False

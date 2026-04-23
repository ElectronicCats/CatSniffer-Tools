"""
CC1352 Restore Module for CatSniffer
=====================================

Recovers a CC1352 when the serial bootloader is broken (e.g., after
flashing firmware without proper CCFG bootloader configuration).

Uses the RP2040 as a CMSIS-DAP JTAG programmer via OpenOCD.

Flow:
    1. Put RP2040 into BOOTSEL mode (shell 'reboot' or manual)
    2. Load free_dap CMSIS-DAP firmware onto RP2040
    3. Use OpenOCD to flash CC1352 via JTAG
    4. Put RP2040 into BOOTSEL again (manual — free_dap has no shell)
    5. Restore RP2040 bridge firmware

Requirements:
    - OpenOCD installed (stock package includes CMSIS-DAP support)
      Linux: sudo apt install openocd
      macOS: brew install openocd
      Windows: choco install openocd
"""

import os
import sys
import time
import shutil
import subprocess
import tempfile
from typing import Optional

import requests

from .fw_update import (
    find_rp2040_mount_point,
    enter_boot_mode,
)

from .output import (
    console,
    print_success,
    print_warning,
    print_error,
    print_info,
    print_step,
    print_section,
    print_empty_line,
    print_instruction_block,
    print_detail_message,
)


# free_dap is in the same release as the bridge firmware (v3.1.0.0)
FREE_DAP_RELEASE_URL = (
    "https://api.github.com/repos/ElectronicCats/CatSniffer-Firmware"
    "/releases/tags/v3.1.0.0"
)
FREE_DAP_FILENAME = "free_dap_catsniffer.uf2"

# CC1352 JTAG TAPIDs
TAPID_CC1352P7 = "0x1BB7702F"
TAPID_CC1352P1 = "0x0BB4102F"

# CMSIS-DAP USB identifiers
CMSIS_DAP_VID_PID = "6666:9930"

# Default CC1352 firmware to restore (from catnip release)
DEFAULT_CC1352_FW = "sniffer_fw_Catsniffer_v3.x.hex"

# OpenOCD settings
OPENOCD_SPEED = 500  # kHz — tested working, higher may fail

# Cache directory for downloaded firmware
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".catnip", "restore_cache")


def _bundled_openocd() -> Optional[str]:
    """Return path to OpenOCD bundled inside a PyInstaller Windows package, or None."""
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None
    candidate = os.path.join(meipass, "openocd.exe")
    return candidate if os.path.exists(candidate) else None


def _bundled_scripts_dir() -> Optional[str]:
    """Return path to the OpenOCD scripts dir bundled inside a PyInstaller package, or None."""
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None
    candidate = os.path.join(meipass, "openocd_scripts")
    return candidate if os.path.exists(candidate) else None


def check_openocd() -> Optional[str]:
    """Check if OpenOCD is available and return its path."""
    path = _bundled_openocd() or shutil.which("openocd")
    if not path:
        return None
    try:
        result = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=5
        )
        version_line = result.stderr.split("\n")[0] if result.stderr else "unknown"
        print_info(f"OpenOCD: {version_line}")
        return path
    except Exception:
        return path


def _download_asset(url: str, dest: str) -> bool:
    """Download a file from URL."""
    try:
        print_info(f"Downloading {os.path.basename(dest)}...")
        response = requests.get(url, timeout=30, stream=True, allow_redirects=True)
        response.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        size = os.path.getsize(dest)
        print_success(f"Downloaded ({size:,} bytes)")
        return True
    except Exception as e:
        print_error(f"Download failed: {e}")
        return False


def get_free_dap_path() -> Optional[str]:
    """Get path to free_dap UF2, downloading from GitHub release if needed."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cached = os.path.join(CACHE_DIR, FREE_DAP_FILENAME)

    if os.path.exists(cached) and os.path.getsize(cached) > 1000:
        print_info(f"Using cached {FREE_DAP_FILENAME}")
        return cached

    # Fetch download URL from release API
    try:
        resp = requests.get(FREE_DAP_RELEASE_URL, timeout=10)
        resp.raise_for_status()
        for asset in resp.json().get("assets", []):
            if asset["name"] == FREE_DAP_FILENAME:
                if _download_asset(asset["browser_download_url"], cached):
                    return cached
    except Exception as e:
        print_error(f"Cannot fetch free_dap release: {e}")

    return None


def get_bridge_uf2_path(flasher=None) -> Optional[str]:
    """
    Get path to bridge UF2 firmware.
    First checks catnip's local release folder, then downloads if needed.
    """
    # Check catnip's release folder first
    if flasher:
        try:
            release_path = flasher.get_releases_path()
            if os.path.exists(release_path):
                for f in os.listdir(release_path):
                    if f.endswith(".uf2") and "catsniffer" in f.lower():
                        path = os.path.join(release_path, f)
                        print_info(f"Bridge UF2: {f}")
                        return path
        except Exception:
            pass

    # Fallback: check cache
    os.makedirs(CACHE_DIR, exist_ok=True)
    for f in os.listdir(CACHE_DIR):
        if f.endswith(".uf2") and "catsniffer" in f.lower() and "free_dap" not in f:
            return os.path.join(CACHE_DIR, f)

    return None


def get_default_cc1352_firmware(flasher=None) -> Optional[str]:
    """Find the default CatSniffer CC1352 firmware from catnip's release folder."""
    if flasher:
        try:
            release_path = flasher.get_releases_path()
            path = os.path.join(release_path, DEFAULT_CC1352_FW)
            if os.path.exists(path):
                return path
        except Exception:
            pass

    # Search in all release folders
    catnip_dir = os.path.join(os.path.expanduser("~"), ".catnip")
    if os.path.exists(catnip_dir):
        for d in os.listdir(catnip_dir):
            path = os.path.join(catnip_dir, d, DEFAULT_CC1352_FW)
            if os.path.exists(path):
                return path

    return None


def create_openocd_config(tapid: str = TAPID_CC1352P7) -> Optional[str]:
    """Create a temporary OpenOCD target config with the correct TAPID."""
    stock_cfg = None

    # Bundled scripts take priority (PyInstaller Windows package)
    bundled = _bundled_scripts_dir()
    if bundled:
        candidate = os.path.join(bundled, "target", "ti_cc13x2.cfg")
        if os.path.exists(candidate):
            stock_cfg = candidate

    if not stock_cfg:
        for path in [
            "/usr/share/openocd/scripts/target/ti_cc13x2.cfg",
            "/usr/local/share/openocd/scripts/target/ti_cc13x2.cfg",
            # macOS Homebrew
            "/opt/homebrew/share/openocd/scripts/target/ti_cc13x2.cfg",
        ]:
            if os.path.exists(path):
                stock_cfg = path
                break

    if not stock_cfg:
        print_error("Cannot find ti_cc13x2.cfg in OpenOCD scripts")
        return None

    with open(stock_cfg, "r") as f:
        content = f.read()

    # Replace default TAPID with the correct one
    content = content.replace("0x0BB4102F", tapid)
    content = content.replace("0x0bb4102f", tapid.lower())

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".cfg", prefix="ti_cc13x2_", delete=False
    )
    tmp.write(content)
    tmp.close()
    return tmp.name


def erase_cc1352_jtag(openocd_path: str, config_path: str) -> bool:
    """Erase CC1352 flash via JTAG, preserving bootloader (sector 0/CCFG).

    Erases sectors 1-last so the serial bootloader in CCFG remains intact.
    After this, catnip flash can program new firmware via serial.
    """
    print_info("Erasing CC1352 flash (preserving bootloader)...")

    cmd = [openocd_path]
    # When using the bundled OpenOCD, point it to the bundled scripts directory
    # so it can resolve interface/cmsis-dap.cfg and target configs correctly.
    scripts_dir = _bundled_scripts_dir()
    if scripts_dir:
        cmd += ["-s", scripts_dir]
    cmd += [
        "-f",
        "interface/cmsis-dap.cfg",
        "-c",
        "cmsis_dap_backend hid",
        "-c",
        "transport select jtag",
        "-c",
        f"adapter speed {OPENOCD_SPEED}",
        "-f",
        config_path,
        "-c",
        "init; halt; flash erase_sector 0 1 last; shutdown",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        output = result.stderr

        if "Error" in output and "erase" in output.lower():
            for line in output.split("\n"):
                if "Error" in line:
                    console.print(f"[red]  {line.strip()}[/red]")
            return False

        print_success("CC1352 flash erased — bootloader preserved")
        return True
    except subprocess.TimeoutExpired:
        print_error("OpenOCD timed out (60s)")
        return False
    except Exception as e:
        print_error(str(e))
        return False


def wait_for_bootsel(timeout: int = 30) -> Optional[str]:
    """Wait for RP2040 BOOTSEL drive to appear."""
    print_info("Waiting for BOOTSEL drive...")
    for i in range(timeout):
        mount = find_rp2040_mount_point()
        if mount:
            print_success(f"BOOTSEL at {mount}")
            return mount
        time.sleep(1)
        if i == 10:
            print_warning("Still waiting... make sure RP2040 is in BOOT mode")
    print_error("BOOTSEL not detected")
    return None


def wait_for_cmsis_dap(timeout: int = 10) -> bool:
    """Wait for CMSIS-DAP device to appear on USB."""
    print_info("Waiting for CMSIS-DAP probe...")
    for _ in range(timeout):
        try:
            # Linux/macOS
            result = subprocess.run(
                ["lsusb"], capture_output=True, text=True, timeout=5
            )
            if CMSIS_DAP_VID_PID in result.stdout:
                print_success("CMSIS-DAP probe ready")
                return True
        except FileNotFoundError:
            # Windows — check with OpenOCD directly
            return True  # Assume available, OpenOCD will error if not
        except Exception:
            pass
        time.sleep(1)
    print_error("CMSIS-DAP not detected")
    return False


def restore_cc1352(
    hex_path: Optional[str] = None,
    device=None,
    flasher=None,
    tapid: str = TAPID_CC1352P7,
) -> bool:
    """
    Full CC1352 restore procedure.

    Args:
        hex_path: Path to .hex firmware (None = use default CatSniffer firmware)
        device: CatSnifferDevice (optional, for shell access to RP2040)
        flasher: Flasher instance (optional, for finding bridge UF2)
        tapid: JTAG TAPID for the CC1352 variant

    Returns:
        True if CC1352 was successfully restored
    """
    print_section("CatSniffer CC1352 Restore via JTAG")

    # --- Prerequisites ---
    openocd = check_openocd()
    if not openocd:
        print_error("OpenOCD not installed.")
        print_detail_message("Install: sudo apt install openocd (Linux)")
        print_detail_message("         brew install openocd (macOS)")
        return False

    if not hex_path:
        hex_path = get_default_cc1352_firmware(flasher)
        if hex_path:
            print_info(f"Using default firmware: {os.path.basename(hex_path)}")
        else:
            print_error("No firmware specified and default not found.")
            print_detail_message("Run: catnip flash --list to download firmware first,")
            print_detail_message("or specify a .hex file: catnip restore firmware.hex")
            return False

    if not os.path.exists(hex_path):
        print_error(f"File not found: {hex_path}")
        return False

    free_dap = get_free_dap_path()
    if not free_dap:
        return False

    bridge_uf2 = get_bridge_uf2_path(flasher)

    config = create_openocd_config(tapid)
    if not config:
        return False

    # --- Step 1: Load CMSIS-DAP onto RP2040 ---
    print_step(1, 4, "Load JTAG programmer onto RP2040")
    print_empty_line()

    # Try shell 'reboot' command first (works if bridge firmware is running)
    # Auto-detect device if not provided
    if device is None:
        from .catnip import catnip_get_device as _get_device

        device = _get_device()

    shell_port = None
    if device and hasattr(device, "shell_port") and device.shell_port:
        shell_port = device.shell_port

    if shell_port:
        print_info(f"Sending 'reboot' to RP2040 via {shell_port}...")
        try:
            enter_boot_mode(shell_port)
        except Exception:
            pass
        mount = wait_for_bootsel(timeout=15)
    else:
        print_instruction_block(
            "Put RP2040 in BOOTSEL mode:",
            [
                "1. Hold BOOT button on CatSniffer",
                "2. Press and release RESET",
                "3. Release BOOT",
            ],
        )
        print_empty_line()
        mount = wait_for_bootsel(timeout=30)

    if not mount:
        _cleanup(config)
        return False

    print_info(f"Copying CMSIS-DAP firmware to {mount}...")
    try:
        shutil.copy2(free_dap, os.path.join(mount, FREE_DAP_FILENAME))
    except Exception as e:
        print_error(f"Copy failed: {e}")
        _cleanup(config)
        return False

    time.sleep(3)
    if not wait_for_cmsis_dap():
        _cleanup(config)
        return False

    # --- Step 2: Erase CC1352 flash (preserve bootloader) ---
    print_empty_line()
    print_step(2, 4, "Erase CC1352 flash via JTAG")

    success = erase_cc1352_jtag(openocd, config)
    _cleanup(config)

    if not success:
        print_empty_line()
        print_error("CC1352 erase failed.")
        print_detail_message("The RP2040 still has CMSIS-DAP firmware.")
        print_detail_message("Put it in BOOTSEL and copy the bridge UF2 to restore.")
        return False

    # --- Step 3: Restore RP2040 bridge ---
    print_empty_line()
    print_step(3, 4, "Restore RP2040 bridge firmware")
    print_empty_line()
    print_instruction_block(
        "Put RP2040 in BOOTSEL mode again:",
        [
            "1. Disconnect USB cable",
            "2. Hold BOOT button",
            "3. Reconnect USB while holding BOOT",
            "4. Release BOOT",
        ],
    )
    print_empty_line()

    mount = wait_for_bootsel(timeout=30)

    if not mount or not bridge_uf2:
        if not bridge_uf2:
            print_warning("Bridge UF2 not found locally.")
            print_detail_message("Run: catnip update --force after BOOTSEL restore.")
        return False

    print_info(f"Restoring bridge: {os.path.basename(bridge_uf2)}...")
    try:
        shutil.copy2(bridge_uf2, os.path.join(mount, os.path.basename(bridge_uf2)))
        time.sleep(5)
        print_success("Bridge firmware restored!")
    except Exception as e:
        print_error(f"Copy failed: {e}")
        return False

    # --- Step 4: Flash firmware via serial bootloader ---
    print_empty_line()
    print_step(4, 4, "Flash CC1352 firmware via serial")
    print_info("Waiting for CatSniffer to reconnect...")
    time.sleep(5)

    # Use catnip flash to program via serial bootloader
    try:
        from .catnip import catnip_get_device

        dev = catnip_get_device()
        if not dev:
            print_warning("CatSniffer not detected. Flash manually:")
            print_detail_message(f"catnip flash {hex_path}")
            return True  # Erase succeeded, just need manual flash

        print_info(f"Flashing {os.path.basename(hex_path)} via serial...")
        if flasher is None:
            from .flasher import Flasher

            flasher = Flasher()
        result = flasher.find_flash_firmware(hex_path, dev)
        if result:
            print_empty_line()
            print_success("CC1352 restore complete!")
            return True
        else:
            print_warning("Serial flash may have failed.")
            print_detail_message(f"Try manually: catnip flash {hex_path}")
            return True  # Erase worked
    except Exception as e:
        print_warning(f"Auto-flash failed: {e}")
        print_detail_message(f"Flash manually: catnip flash {hex_path}")
        return True  # Erase + bridge restore succeeded


def _cleanup(config_path: Optional[str]):
    """Remove temporary OpenOCD config file."""
    if config_path:
        try:
            os.unlink(config_path)
        except Exception:
            pass

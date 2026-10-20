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
    Software: 3.3.3.0 (from CatSniffer-Tools repo)
    Firmware: v3.1.0.0 (from CatSniffer-Firmware repo)

Shell commands used:
    - fw_version: Returns firmware version info from the RP2040
    - reboot: Puts the RP2040 into UF2 boot mode
"""

import os
import re
import time
import glob
import platform
import shutil
import logging
from dataclasses import dataclass
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
        Version string (e.g., '3.3.3.0') stripped of 'v' prefix, or None on error
    """
    try:
        response = requests.get(GITHUB_TOOLS_RELEASE_URL, timeout=5)
        response.raise_for_status()
        data = response.json()
        tag = data.get("tag_name", "")
        # Strip 'v' prefix if present (e.g., "v3.3.3.0" → "3.3.3.0")
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
    """Convert a version string like '3.3.3.0' into a comparable tuple of ints.

    Padded to four components, because the tool and the releases do not
    always spell the trailing zero: without the padding ``3.3.3`` sorts
    *below* ``3.3.3.0`` and an up-to-date build reports itself as outdated.
    """
    try:
        parts = [int(x) for x in version.lstrip("v").split(".")]
    except (ValueError, AttributeError):
        return (0, 0, 0, 0)
    parts = (parts + [0, 0, 0, 0])[:4]
    return tuple(parts)


def is_software_up_to_date(local_version: str, remote_version: str) -> bool:
    """
    Compare the local tool version against the latest remote release.

    Args:
        local_version: Local tool version (e.g., '3.0.0')
        remote_version: Remote release version (e.g., '3.3.3.0')

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
        remote_version: Remote release version (e.g., '3.3.3.0')

    Returns:
        True if local version is strictly greater than remote, False otherwise
    """
    if not local_version or not remote_version:
        return False

    return _parse_version(local_version) > _parse_version(remote_version)


def get_device_fw_version(
    shell_port: str, attempts: int = 3
) -> Optional[Dict[str, str]]:
    """
    Query the RP2040 firmware version via the shell port.

    Sends the 'fw_version' command and parses the multiline response:
        FW: dev-373e0cd-clean
        Git: 373e0cd(clean)
        Built: 2026-02-28T05:44:25Z
        Compiler: GNU 12.2.0

    Retried, because one silent reply is not evidence of anything: the shell
    is a CDC ACM port that another catnip process (or an extcap left running)
    can hold for a moment, and the first command after the port is opened can
    come back empty while the link settles. A single miss used to be reported
    as "the device may have corrupted firmware" and stopped the update on a
    perfectly healthy board.

    Args:
        shell_port: Path to the shell serial port (e.g., /dev/ttyACM2)
        attempts: how many times to ask before giving up

    Returns:
        dict with keys 'fw', 'git', 'built', 'compiler', or None on failure
    """
    for attempt in range(1, attempts + 1):
        parsed = _read_fw_version_once(shell_port)
        if parsed is not None:
            return parsed
        if attempt < attempts:
            logger.warning(
                f"[!] No fw_version reply, retrying ({attempt}/{attempts - 1})"
            )
            time.sleep(0.4)
    return None


def _read_fw_version_once(shell_port: str) -> Optional[Dict[str, str]]:
    """One fw_version round-trip; None when the board did not answer."""
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


def find_board_mount_point(board) -> Optional[str]:
    """Mount point of the board's UF2 bootloader volume, or None."""
    volume = board.uf2_volume if board else "RPI-RP2"
    system = platform.system()
    if system == "Linux":
        for pattern in (
            f"/media/*/{volume}",
            f"/run/media/*/{volume}",
            f"/mnt/{volume}",
        ):
            matches = glob.glob(pattern)
            if matches:
                return matches[0]
    elif system == "Darwin":
        path = f"/Volumes/{volume}"
        if os.path.exists(path):
            return path
    elif system == "Windows":
        return find_rp2040_mount_point()
    return None


def find_any_board_mount_point():
    """(board, mount_point) of whichever board bootloader volume is mounted."""
    from .board import BOARDS

    for board in BOARDS.values():
        mount = find_board_mount_point(board)
        if mount:
            return board, mount
    return None, None


def find_board_uf2(flasher, board, tag: Optional[str] = None) -> Optional[str]:
    """UF2 asset for this board generation in the local release folder.

    With a ``tag``, only the file that names that release counts. The release
    folder is named after whichever tag the repo marks "latest", so it can
    easily hold an *older* UF2 for the other generation's board — and since
    the name only has to carry ``uf2_pattern`` to match, flashing it would
    leave the board reporting the very version that triggered the update.
    """
    wanted = None
    if tag:
        wanted = (tag.lower(), tag.lstrip("vV").lower())
    try:
        release_path = flasher.get_releases_path()
        if os.path.isdir(release_path):
            for filename in sorted(os.listdir(release_path)):
                name = filename.lower()
                if not name.endswith(".uf2") or board.uf2_pattern not in name:
                    continue
                if wanted and not any(w in name for w in wanted):
                    continue
                return os.path.join(release_path, filename)
    except Exception as e:
        logger.error(f"[X] Error finding UF2 firmware: {e}")
    return None


def resolve_board_uf2(flasher, board, tag: Optional[str] = None) -> Optional[str]:
    """
    Path to the UF2 that belongs to this board, downloading it if needed.

    The lookup is driven by ``board.uf2_pattern``, and by ``tag`` when the
    caller knows which release it is updating to: the exact asset first, then
    a download, and only then any UF2 already on disk for this board — an
    older local image still boots the board, but the caller is told it is not
    the release it asked for.

    Only a board that accepts unnamed images falls back to "any .uf2 in the
    release folder": copying a UF2 built for the other generation onto a
    bootloader volume is exactly the mistake this function exists to prevent.
    """
    path = find_board_uf2(flasher, board, tag)
    if path:
        return path
    try:
        path = flasher.fetch_board_uf2(board)
    except Exception as e:
        logger.warning(f"[!] Could not fetch the {board.generation} UF2: {e}")
        path = None
    if path:
        return path
    if tag:
        path = find_board_uf2(flasher, board)
        if path:
            return path
    if board.accepts_unnamed_images:
        return find_uf2_firmware(flasher)
    return None


def expected_tag_for_board(flasher, board) -> Optional[str]:
    """
    Release tag the given board should be running.

    Releases are tagged per generation (``board.tag_prefix``), and the board's
    own release line is *asked*, every time. ``flasher.release_tag`` is not an
    answer to this question: it is restored from the name of the local release
    folder (``~/.catnip/release_<tag>``) and only changes when the catalogue is
    downloaded, so preferring it compares the board against the release it
    already has — and no newer one can ever be found. It is kept as the
    offline fallback, which is the one case where a stale tag beats nothing.
    """
    try:
        rel = flasher.get_release_for_board(board)
    except Exception as e:
        logger.warning(f"[!] Could not list releases for {board.generation}: {e}")
        rel = None

    tag = rel.get("tag_name") if rel else None
    if tag:
        return tag

    cached = get_expected_fw_tag(flasher)
    if cached and cached.startswith(board.tag_prefix):
        print_dim(
            f"Could not reach the release list; using the local catalogue tag "
            f"{cached}, which may be behind."
        )
        return cached
    return None


def board_from_fw_info(device_fw: Optional[Dict[str, str]]):
    """BoardInfo for a parsed fw_version reply, or None when it does not say."""
    from .board import parse_board_line

    if not device_fw:
        return None
    return parse_board_line(
        f"FW: {device_fw.get('fw', '')}\r\nBoard: {device_fw.get('board', '')}"
    )


def _print_unknown_board(board_text: Optional[str] = None) -> None:
    """Explain a refusal to act on a board whose generation is unknown."""
    print_error("Could not determine the CatSniffer board generation")
    if board_text:
        print_dim(f"The device answered: Board: {board_text}")
    print_dim(
        "Nothing was flashed and the board was not rebooted: a v3 image on a "
        "v2 board disables the CC1352 bootloader."
    )
    print_dim("Re-run with --board v2 or --board v3 if you know which board this is.")


def confirm_reboot(board, tag) -> bool:
    """Ask before rebooting a board into its bootloader."""
    try:
        answer = input(
            f"Reboot the {board.label} into its {board.uf2_volume} bootloader and flash {tag}? [y/N] "
        )
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")


# Firmware is versioned ``vA.X.Y.Z``: A names the board the image is built
# for, then major.minor.patch. The lookarounds make the match all-or-nothing,
# so a five-component string is *not* silently read as a four-component one.
# Anything that names no such version (a dev build like "dev-373e0cd-clean")
# has no place in an ordering and parses to None.
_FW_VERSION_RE = re.compile(r"(?<![\d.])v?(\d+)\.(\d+)\.(\d+)\.(\d+)(?![\d.])")

FW_VERSION_FIELDS = ("board", "major", "minor", "patch")


def parse_fw_version(text: Optional[str]) -> Optional[Tuple[int, int, int, int]]:
    """The ``(A, X, Y, Z)`` a firmware version names, or None when it names none.

    Suffixed release builds ("v3.1.0.0-dirty") still parse: what matters is
    the version they are built from. None is never "version zero" — it means
    *not comparable*, and callers must not order against it.
    """
    if not text:
        return None
    match = _FW_VERSION_RE.search(str(text).strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def format_fw_version(version: Optional[Tuple[int, ...]]) -> str:
    """A parsed version back as ``vA.X.Y.Z``, for messages."""
    return "v" + ".".join(str(part) for part in version) if version else "unknown"


@dataclass(frozen=True)
class UpdateDecision:
    """What comparing the device against the release says to do, and why.

    The five outcomes are deliberately distinct: three of them flash, one
    refuses, and one does nothing — and "the device is newer than the
    release" must never collapse into "the versions differ, so flash", which
    is a downgrade.
    """

    action: str  # up-to-date | update | ahead | unknown | incompatible
    reason: str
    current: Optional[Tuple[int, int, int, int]] = None
    expected: Optional[Tuple[int, int, int, int]] = None

    @property
    def needs_update(self) -> bool:
        """True when flashing the release is the right thing to do."""
        return self.action in ("update", "unknown")

    @property
    def is_refusal(self) -> bool:
        """True when the release must not be flashed on this board at all."""
        return self.action == "incompatible"


def decide_fw_update(
    device_fw: Optional[Dict[str, str]], expected_tag: Optional[str], board=None
) -> UpdateDecision:
    """Decide whether the release tag should replace what the device runs.

    Ordering is on the parsed ``(A, X, Y, Z)`` tuple, never on substrings:
    ``"v3.1.0.0" in "v3.1.0.0"`` happens to be right, but the same test calls
    a device running v3.2.0.0 "mismatched" against a v3.1.0.0 release and
    downgrades it.

    ``A`` is checked against the board before anything else is compared: a
    release from another board's line is refused outright (its UF2 targets a
    different MCU), and a device running another line's firmware is reflashed
    with its own regardless of how the remaining numbers order.
    """
    expected = parse_fw_version(expected_tag)
    if expected is None:
        return UpdateDecision(
            "unknown",
            f"release tag '{expected_tag or 'none'}' does not name a vA.X.Y.Z version",
        )

    if board is not None and expected[0] != board.firmware_series:
        return UpdateDecision(
            "incompatible",
            f"release {format_fw_version(expected)} is built for a v{expected[0]} "
            f"board, and this is a CatSniffer {board.label}",
            expected=expected,
        )

    raw_current = (device_fw or {}).get("fw", "")
    current = parse_fw_version(raw_current)
    if current is None:
        return UpdateDecision(
            "unknown",
            f"device reports '{raw_current or 'nothing'}', which names no "
            "vA.X.Y.Z version (a development build)",
            expected=expected,
        )

    if board is not None and current[0] != board.firmware_series:
        return UpdateDecision(
            "update",
            f"device runs {format_fw_version(current)}, firmware for a "
            f"v{current[0]} board, but this is a CatSniffer {board.label}",
            current=current,
            expected=expected,
        )

    if current == expected:
        return UpdateDecision(
            "up-to-date",
            f"device already runs {format_fw_version(expected)}",
            current=current,
            expected=expected,
        )
    if current > expected:
        return UpdateDecision(
            "ahead",
            f"device runs {format_fw_version(current)}, newer than the latest "
            f"release {format_fw_version(expected)}",
            current=current,
            expected=expected,
        )
    return UpdateDecision(
        "update",
        f"{format_fw_version(current)} → {format_fw_version(expected)}",
        current=current,
        expected=expected,
    )


def is_fw_compatible(device_fw: Dict[str, str], expected_tag: str) -> bool:
    """True when the device already runs exactly the expected release.

    A thin reading of :func:`decide_fw_update`: "ahead" is not "compatible"
    here, because this answers "does it match the release", not "should it be
    flashed" — :func:`decide_fw_update` is what decides that.
    """
    return decide_fw_update(device_fw, expected_tag).action == "up-to-date"


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


def flash_rp2040_uf2(uf2_path: str, mount_point: Optional[str] = None) -> bool:
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

    if not mount_point:
        mount_point = find_rp2040_mount_point() or find_any_board_mount_point()[1]
    if not mount_point:
        print_error("RP2040 boot device not found!")
        print_warning("The device must be in UF2 Boot Mode.")
        return False

    dest = os.path.join(mount_point, os.path.basename(uf2_path))
    print_info(f"Copying UF2 firmware to {mount_point}...")

    # The desktop automounter (udisks2 on Linux, AutoPlay on Windows,
    # diskarbitrationd on macOS) can take a moment to finish granting write
    # access right after the boot volume first appears, so a "Permission
    # denied" immediately after detecting the mount point is often
    # transient rather than a real access problem — retry it briefly before
    # giving up.
    attempts = 5
    for attempt in range(1, attempts + 1):
        try:
            # Plain copyfileobj + explicit fsync, not shutil.copy2(): the
            # RP2040 reboots and unmounts RPI-RP2 as soon as it has received
            # the image, which can race copy2's post-copy copystat()
            # (mtime/permissions) and raise even though the firmware itself
            # copied fine. fsync also guarantees the bytes actually left the
            # page cache for the device before we report success, instead of
            # relying on a cache flush that may not happen before the volume
            # disappears.
            with open(uf2_path, "rb") as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
            print_success("UF2 firmware copied successfully!")
            return True
        except PermissionError as e:
            if attempt == attempts:
                print_error(f"Error copying UF2 firmware: {e}")
                print_dim(
                    "The boot volume may still be settling permissions after mount; "
                    "try running the command again."
                )
                return False
            print_dim(f"Volume not writable yet, retrying ({attempt}/{attempts})...")
            time.sleep(0.5)
        except Exception as e:
            print_error(f"Error copying UF2 firmware: {e}")
            return False

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


def check_and_update_rp2040(
    device: CatSnifferDevice = None, flasher=None, force: bool = False, board=None
) -> bool:
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
        force: reflash even when the version already matches
        board: BoardInfo override for when detection cannot name the board

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

    # What is on disk, which is not what the board is held against: the
    # folder is named after whichever tag was downloaded last. The release
    # that decides is resolved once the board is known (step 4b), so a
    # missing one here is not yet a reason to stop.
    cached_fw_tag = get_expected_fw_tag(flasher)
    if cached_fw_tag:
        print_dim(f"Local firmware catalogue: {cached_fw_tag}")

    # Step 3: Detect device
    if device is None:
        device = catnip_get_device()

    if device is None:
        # No device detected — check if RP2040 is already in boot mode
        print_warning("No CatSniffer device detected")

        boot_board, mount_point = find_any_board_mount_point()
        if mount_point:
            label = boot_board.label if boot_board else "Boot"
            print_success(f"{label} boot volume detected at: {mount_point}")
            uf2_path = (
                resolve_board_uf2(flasher, boot_board)
                if boot_board is not None
                else find_uf2_firmware(flasher)
            )
            if uf2_path:
                print_info(f"Flashing UF2: {os.path.basename(uf2_path)}")
                return flash_rp2040_uf2(uf2_path, mount_point)
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
        print_error("The device did not answer 'fw_version'")
        print_dim(f"Nothing was flashed. The shell port is {device.shell_port}.")
        print_dim(
            "Most often the port is held by another process — close any running "
            "'catnip sniff', Wireshark extcap or serial monitor and try again."
        )
        print_dim(
            "If it never answers, the firmware may be corrupted: 'catnip update --force'."
        )
        return False

    print_info(f"Device FW Version: {device_fw.get('fw', 'unknown')}")
    if device_fw.get("git"):
        print_dim(f"Git: {device_fw['git']}")
    if device_fw.get("built"):
        print_dim(f"Built: {device_fw['built']}")

    # Step 4b: the board generation decides the release tag scheme, the UF2
    # asset and the bootloader volume. Each generation has its own release
    # line, so an unknown board means there is nothing safe to flash.
    if board is None:
        board = board_from_fw_info(device_fw)
    if board is None:
        _print_unknown_board(device_fw.get("board"))
        return False
    console.print(f"[cyan][*] Board: {board.label}[/cyan]")

    expected_fw_tag = expected_tag_for_board(flasher, board)
    if not expected_fw_tag:
        console.print(
            f"[yellow][!] No {board.generation} firmware release found (tags "
            f"{board.tag_prefix}X.Y.Z). Nothing to update; the board was not "
            "rebooted.[/yellow]"
        )
        return False
    console.print(
        f"[cyan][*] Latest {board.generation} Firmware Release: {expected_fw_tag}[/cyan]"
    )

    # The pairing only means something now that the release line is the
    # board's own; printed against the catalogue tag it was one generation's
    # firmware next to another generation's board.
    print_empty_line()
    print_title("Compatibility Check:")
    print_dim(
        f"Software: [cyan]{remote_sw_ver or tool_ver}[/cyan] ↔ "
        f"Firmware: [cyan]{expected_fw_tag}[/cyan] on a CatSniffer {board.label}"
    )
    print_empty_line()

    # Step 5: Compare device FW against expected firmware release
    decision = decide_fw_update(device_fw, expected_fw_tag, board)

    if decision.is_refusal:
        print_error(f"Refusing to flash: {decision.reason}")
        print_dim("The board was not rebooted and nothing was written.")
        return False

    if decision.action == "up-to-date":
        print_success(f"Firmware is up to date ({decision.reason})")
        return True

    if decision.action == "ahead":
        # Differing is not the same as being behind: flashing here would
        # *downgrade* a board that is deliberately running a newer build.
        print_success(f"Firmware is newer than the release — {decision.reason}")
        print_dim("Nothing to update. Use 'catnip update --force' to reflash anyway.")
        return True

    if decision.action == "unknown":
        print_warning(f"Cannot compare versions: {decision.reason}")
        print_dim(f"The release is {expected_fw_tag}; confirm below to flash it.")
    else:
        print_warning(f"Firmware is outdated! {decision.reason}")

    return _perform_rp2040_update(
        device, flasher, board=board, tag=expected_fw_tag, force=force
    )


def force_update_rp2040(
    device: CatSnifferDevice = None, flasher=None, board=None
) -> bool:
    """
    Force update the RP2040 firmware regardless of version compatibility.

    Args:
        device: CatSnifferDevice instance (auto-detected if None)
        flasher: Flasher instance (created if None)
        board: BoardInfo override for when detection cannot name the board

    Returns:
        True if successfully updated, False otherwise
    """
    if flasher is None:
        from .flasher import Flasher

        flasher = Flasher()

    if device is None:
        device = catnip_get_device()

    if device is None:
        # Check for boot mode
        boot_board, mount_point = find_any_board_mount_point()
        if mount_point:
            label = boot_board.label if boot_board else "Boot"
            print_success(f"{label} boot volume detected at: {mount_point}")
            uf2_path = (
                resolve_board_uf2(flasher, boot_board)
                if boot_board is not None
                else find_uf2_firmware(flasher)
            )
            if uf2_path:
                return flash_rp2040_uf2(uf2_path, mount_point)
            else:
                print_error("No UF2 firmware found!")
                return False
        else:
            _print_boot_mode_instructions()
            return False

    if board is None:
        from .board import detect_board

        board = detect_board(device.shell_port)
    if board is None:
        # --force exists for devices stuck with broken firmware, so this is
        # the one place where refusing hurts. It still refuses: the shell is
        # the only thing that can name the generation, and flashing the wrong
        # UF2 is worse than not flashing. --board says which board it is.
        _print_unknown_board(None)
        return False

    # Only now is the release line known: the repo's "latest" tag may belong
    # to the other generation, and naming it here would promise an image this
    # board will never be given.
    expected_tag = expected_tag_for_board(flasher, board)
    print_info(
        f"Force updating the {board.label} to release: {expected_tag or 'latest local'}"
    )
    return _perform_rp2040_update(
        device, flasher, board=board, tag=expected_tag, force=True
    )


def _perform_rp2040_update(
    device: CatSnifferDevice, flasher, board=None, tag=None, force=False
) -> bool:
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
    if board is None:
        _print_unknown_board(None)
        return False
    # Find the UF2 for this board generation; never reboot without one
    uf2_path = resolve_board_uf2(flasher, board, tag)
    if not uf2_path:
        print_error(f"No {board.generation} UF2 firmware found in release folder!")
        print_dim(
            "The board was not rebooted. Run the CLI to download the latest release first."
        )
        return False

    print_info(f"UF2 firmware: {os.path.basename(uf2_path)}")
    if tag and tag.lstrip("vV").lower() not in os.path.basename(uf2_path).lower():
        # Flashing this still leaves the board off the release, so say so now
        # rather than letting the next 'catnip update' report the same gap.
        print_warning(
            f"This image does not name release {tag}; the board may still report "
            "an older version afterwards."
        )
    if not force and not confirm_reboot(board, tag or os.path.basename(uf2_path)):
        print_warning("Update cancelled; the board was not rebooted.")
        return False

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
    print_info(f"Waiting for the {board.uf2_volume} boot volume to appear...")
    mount_point = None
    for i in range(15):  # Wait up to ~15 seconds
        time.sleep(1)
        mount_point = find_board_mount_point(board)
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
    if flash_rp2040_uf2(uf2_path, mount_point):
        print_success_section("RP2040 Firmware Updated Successfully!")
        print_dim("The device will reboot automatically.")
        print_dim("Wait a few seconds before using other commands.")
        return True
    else:
        return False

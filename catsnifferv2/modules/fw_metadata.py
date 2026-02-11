"""
Firmware Metadata Module for CatSniffer
========================================

This module interacts with the firmware metadata system implemented
in the RP2040 (Zephyr) to manage the CC1352 firmware ID stored in
the NVS (Non-Volatile Storage) flash memory.

Available Shell Commands:
- cc1352_fw_id get        → Get current ID
- cc1352_fw_id set <id>   → Set ID
- cc1352_fw_id clear      → Clear ID
- cc1352_fw_id list       → List official IDs

Official IDs supported by the firmware:
- sniffle
- ti_sniffer
- catsniffer_v3
- airtag_spoofer_cc1352p7
- airtag_scanner_cc1352p7
"""

import time
import re
from typing import Optional, Tuple, Dict
import logging

logger = logging.getLogger("rich")

# Mapping of firmware names to official IDs - IMPROVED VERSION
FIRMWARE_ID_MAP = {
    # BLE Firmwares
    "sniffle": "sniffle",
    "sniffle_cc1352p7_1m": "sniffle",
    "sniffle_cc1352p7_1m.hex": "sniffle",
    "sniffle_cc1352p7_1M": "sniffle",
    "sniffle_cc1352p7_1M.hex": "sniffle",
    # TI Sniffer (Zigbee/Thread/15.4)
    "ti_sniffer": "ti_sniffer",
    "sniffer": "ti_sniffer",
    "sniffer_fw_cc1352p_7_v1.10.hex": "ti_sniffer",
    "sniffer_fw_CC1352P_7_v1.10.hex": "ti_sniffer",
    "cc1352_sniffer_zigbee": "ti_sniffer",
    "cc1352_sniffer_zigbee.hex": "ti_sniffer",
    "cc1352_sniffer_thread": "ti_sniffer",
    "cc1352_sniffer_thread.hex": "ti_sniffer",
    # CatSniffer V3
    "catsniffer_v3": "catsniffer_v3",
    # Airtag
    "airtag_spoofer": "airtag_spoofer_cc1352p7",
    "airtag_spoofer_cc1352p7": "airtag_spoofer_cc1352p7",
    "airtag_spoofer_cc1352p7.hex": "airtag_spoofer_cc1352p7",
    "airtag_scanner": "airtag_scanner_cc1352p7",
    "airtag_scanner_cc1352p7": "airtag_scanner_cc1352p7",
    "airtag_scanner_cc1352p7.hex": "airtag_scanner_cc1352p7",
}

# Lowercase version for case-insensitive search
FIRMWARE_ID_MAP_LOWERCASE = {k.lower(): v for k, v in FIRMWARE_ID_MAP.items()}

# Sort keys by descending length to prioritize most specific matches
SORTED_KEYS = sorted(FIRMWARE_ID_MAP_LOWERCASE.keys(), key=len, reverse=True)


class FirmwareMetadata:
    """
    Client to interact with the firmware metadata system.

    Uses the CatSniffer Shell port to send commands and read responses.
    """

    def __init__(self, shell_connection):
        """
        Args:
            shell_connection: Already initialized ShellConnection object
        """
        self.shell = shell_connection

    def get_firmware_id(self) -> Optional[str]:
        """
        Retrieves the CC1352 firmware ID stored in the RP2040 flash.

        Returns:
            str: Firmware ID (e.g., "sniffle", "ti_sniffer")
            None: If no ID is stored or error occurred

        Example:
            >>> fw_id = metadata.get_firmware_id()
            >>> print(fw_id)  # "sniffle"
        """
        try:
            response = self.shell.send_command("cc1352_fw_id get", timeout=2.0)

            if not response:
                logger.debug("No response to get command")
                return None

            logger.debug(f"Get response: {response[:100]}")

            # Expected response: "OK cc1352_fw_id=sniffle type=official"
            # or: "OK cc1352_fw_id=unset"
            match = re.search(r"cc1352_fw_id=(\S+)", response)
            if match:
                fw_id = match.group(1)
                if fw_id == "unset":
                    logger.debug("Firmware ID is unset")
                    return None
                logger.debug(f"Found firmware ID: {fw_id}")
                return fw_id

            return None

        except Exception as e:
            logger.debug(f"Error in get_firmware_id: {e}")
            return None

    def set_firmware_id(self, fw_id: str) -> bool:
        """
        Sets the CC1352 firmware ID in the RP2040 flash.

        Args:
            fw_id: Firmware ID to set (max 31 characters)
                   Allowed characters: a-z A-Z 0-9 _ - .

        Returns:
            bool: True if set successfully, False on error

        Example:
            >>> success = metadata.set_firmware_id("sniffle")
            >>> print(success)  # True
        """
        if not fw_id or len(fw_id) >= 32:
            logger.debug(f"Invalid firmware ID length: {len(fw_id) if fw_id else 0}")
            return False

        # Validate allowed characters
        if not re.match(r"^[a-zA-Z0-9_\-\.]+$", fw_id):
            logger.debug(f"Invalid characters in firmware ID: {fw_id}")
            return False

        try:
            command = f"cc1352_fw_id set {fw_id}"
            logger.debug(f"Sending command: {command}")

            response = self.shell.send_command(command, timeout=3.0)

            if not response:
                logger.debug("No response to set command")
                return False

            logger.debug(f"Set response: {response[:100]}")

            # Expected response: "OK cc1352_fw_id=sniffle (official)"
            # Or simply "OK" in some versions
            success = "OK" in response and fw_id in response

            if success:
                logger.debug(f"Successfully set firmware ID to {fw_id}")
            else:
                logger.debug(f"Failed to set firmware ID. Response: {response}")

            return success

        except Exception as e:
            logger.debug(f"Error in set_firmware_id: {e}")
            return False

    @staticmethod
    def normalize_firmware_name(firmware_name: str) -> Optional[str]:
        """
        Converts a firmware name to its corresponding official ID.

        Args:
            firmware_name: Firmware filename or alias

        Returns:
            str: Official firmware ID or None if not found

        Example:
            >>> fw_id = FirmwareMetadata.normalize_firmware_name("sniffle_cc1352p7_1M.hex")
            >>> print(fw_id)  # "sniffle"
        """
        if not firmware_name:
            return None

        # Convert to lowercase for searching
        fw_lower = firmware_name.lower()

        # Remove extension if exists
        if "." in fw_lower:
            fw_lower = fw_lower.rsplit(".", 1)[0]

        # DEBUG: Log what we are normalizing
        logger.debug(f"Normalizing firmware name: '{firmware_name}' -> '{fw_lower}'")

        # 1. Exact match (insensitive)
        if fw_lower in FIRMWARE_ID_MAP_LOWERCASE:
            result = FIRMWARE_ID_MAP_LOWERCASE[fw_lower]
            logger.debug(f"Exact match: {fw_lower} -> {result}")
            return result

        # 2. Partial match ordered by descending length
        for key in SORTED_KEYS:
            if key in fw_lower or fw_lower in key:
                result = FIRMWARE_ID_MAP_LOWERCASE[key]
                logger.debug(
                    f"Partial match: {fw_lower} matched key '{key}' -> {result}"
                )
                return result

        # 3. Specific heuristics
        if "sniffle" in fw_lower and "airtag" not in fw_lower:
            logger.debug(f"Heuristic: sniffle detected in {fw_lower}")
            return "sniffle"

        if any(x in fw_lower for x in ["sniffer", "zigbee", "thread", "15.4", "ti_"]):
            logger.debug(f"Heuristic: TI sniffer detected in {fw_lower}")
            return "ti_sniffer"

        if "airtag" in fw_lower:
            if "spoof" in fw_lower:
                logger.debug(f"Heuristic: airtag spoofer detected")
                return "airtag_spoofer_cc1352p7"
            elif "scan" in fw_lower:
                logger.debug(f"Heuristic: airtag scanner detected")
                return "airtag_scanner_cc1352p7"

        # 4. Fallback: cleaned and validated base name
        # Remove non-allowed characters and truncate
        clean_name = re.sub(r"[^a-zA-Z0-9_\-.]", "_", fw_lower)[:31]
        if clean_name:
            logger.debug(f"Fallback: using clean name '{clean_name}'")
            return clean_name

        logger.debug("No normalization possible")
        return None


def check_firmware_by_metadata(shell_connection, expected_fw_id: str) -> bool:
    """
    Verifies if the current firmware matches the expected one using metadata.

    Args:
        shell_connection: ShellConnection object
        expected_fw_id: Expected firmware ID (e.g., "sniffle", "ti_sniffer")

    Returns:
        bool: True if it matches, False otherwise

    Example:
        >>> shell = ShellConnection(port="/dev/ttyACM2")
        >>> shell.connect()
        >>> is_sniffle = check_firmware_by_metadata(shell, "sniffle")
        >>> print(is_sniffle)  # True
    """
    try:
        metadata = FirmwareMetadata(shell_connection)
        current_id = metadata.get_firmware_id()

        if not current_id:
            logger.debug(f"No firmware ID found in metadata")
            return False

        result = current_id == expected_fw_id
        logger.debug(
            f"Metadata check: current='{current_id}', expected='{expected_fw_id}' -> {result}"
        )
        return result

    except Exception as e:
        logger.debug(f"Error in check_firmware_by_metadata: {e}")
        return False


def update_firmware_metadata_after_flash(shell_connection, firmware_name: str) -> bool:
    """
    Updates metadata after flashing a firmware.

    This function should be called AFTER successfully flashing a firmware
    to register the ID in the RP2040 flash memory.

    Args:
        shell_connection: ShellConnection object
        firmware_name: Name of the flashed firmware

    Returns:
        bool: True if updated successfully

    Example:
        >>> shell = ShellConnection(port="/dev/ttyACM2")
        >>> shell.connect()
        >>> update_firmware_metadata_after_flash(shell, "sniffle_cc1352p7_1M.hex")
        True
    """
    logger.debug(f"Updating metadata for firmware: {firmware_name}")

    # Normalize name to official ID
    fw_id = FirmwareMetadata.normalize_firmware_name(firmware_name)

    if not fw_id:
        # If normalization fails, use basic name without extension
        fw_id = firmware_name.lower()
        if "." in fw_id:
            fw_id = fw_id.rsplit(".", 1)[0]
        # Truncate to 31 characters and clean non-allowed characters
        fw_id = re.sub(r"[^a-zA-Z0-9_\-.]", "_", fw_id)[:31]
        logger.debug(f"Fallback: using sanitized name '{fw_id}'")

    metadata = FirmwareMetadata(shell_connection)
    result = metadata.set_firmware_id(fw_id)

    if result:
        logger.debug(f"Successfully set firmware ID to {fw_id}")
    else:
        logger.debug(f"Failed to set firmware ID to {fw_id}")

    return result

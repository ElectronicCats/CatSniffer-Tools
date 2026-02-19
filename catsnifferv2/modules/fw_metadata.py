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

from .fw_aliases import get_official_id


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
        """
        if not firmware_name:
            return None

        # Use centralized alias resolver
        return get_official_id(firmware_name)


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


def _sanitize_firmware_name(name: str) -> str:
    """
    Sanitize a firmware name to create a valid ID.

    Args:
        name: Raw firmware name

    Returns:
        Sanitized ID string
    """
    if not name or not name.strip():
        return "unknown_firmware"

    # Convert to lowercase
    sanitized = name.lower()

    # Remove extension if present
    if "." in sanitized:
        sanitized = sanitized.rsplit(".", 1)[0]

    # Replace dots with underscores for consistency
    sanitized = sanitized.replace(".", "_")

    # Replace any non-allowed characters with underscore
    sanitized = re.sub(r"[^a-zA-Z0-9_\-]", "_", sanitized)

    # Remove leading/trailing underscores and hyphens
    sanitized = sanitized.strip("_-")

    # Ensure we have a valid ID after sanitization
    if not sanitized:
        return "unknown_firmware"

    # Truncate to max length
    if len(sanitized) > 31:
        sanitized = sanitized[:31]

    return sanitized


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

    if firmware_name is None:
        logger.debug("firmware_name is None, cannot update metadata")
        return False

    # Normalize name to official ID
    fw_id = FirmwareMetadata.normalize_firmware_name(firmware_name)

    if not fw_id:
        # If normalization fails, sanitize the name
        fw_id = _sanitize_firmware_name(firmware_name)
        logger.debug(f"Fallback: using sanitized name '{fw_id}'")

    metadata = FirmwareMetadata(shell_connection)

    result = metadata.set_firmware_id(fw_id)

    if result:
        logger.debug(f"Successfully set firmware ID to {fw_id}")
    else:
        logger.debug(f"Failed to set firmware ID to {fw_id}")

    return result


def clear_firmware_metadata(shell_connection) -> bool:
    """
    Clears the firmware metadata (sets to unset).

    Args:
        shell_connection: ShellConnection object

    Returns:
        bool: True if cleared successfully
    """
    try:
        metadata = FirmwareMetadata(shell_connection)
        response = shell_connection.send_command("cc1352_fw_id clear", timeout=3.0)

        if response and "OK" in response:
            logger.debug("Successfully cleared firmware metadata")
            return True
        else:
            logger.debug(f"Failed to clear firmware metadata: {response}")
            return False
    except Exception as e:
        logger.debug(f"Error clearing firmware metadata: {e}")
        return False


def list_official_firmware_ids(shell_connection) -> Optional[list]:
    """
    Lists all official firmware IDs supported by the RP2040.

    Args:
        shell_connection: ShellConnection object

    Returns:
        list: List of official IDs or None if error
    """
    try:
        response = shell_connection.send_command("cc1352_fw_id list", timeout=3.0)

        if not response:
            return None

        # Parse response - format: "OK <id1> <id2> ..."
        if response.startswith("OK "):
            ids = response[3:].strip().split()
            return ids
        return None
    except Exception as e:
        logger.debug(f"Error listing firmware IDs: {e}")
        return None

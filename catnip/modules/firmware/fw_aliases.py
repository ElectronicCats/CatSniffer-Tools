"""
Centralized Firmware Alias Management for CatSniffer
===================================================

This module provides a unified way to handle firmware aliases and map them
to official firmware IDs and filenames. This ensures consistency between
flashing and sniffing commands.
"""

from typing import Optional, Dict, List

# Official Firmware IDs (Must match RP2040/src/fw_metadata.c)
OFFICIAL_FW_IDS = [
    "sniffle",
    "ti_sniffer",
    "catnip_v3",
    "airtag_spoofer_cc1352p7",
    "airtag_scanner_cc1352p7",
    "justworks_scanner_cc1352p7",
]

# Map user-friendly aliases to official IDs
ALIAS_TO_OFFICIAL_ID = {
    # BLE
    "ble": "sniffle",
    "sniffle": "sniffle",
    "justworks": "justworks_scanner_cc1352p7",
    # TI Sniffer (Zigbee, Thread, 15.4)
    "zigbee": "ti_sniffer",
    "thread": "ti_sniffer",
    "15.4": "ti_sniffer",
    "ti": "ti_sniffer",
    "multiprotocol": "ti_sniffer",
    "sniffer": "ti_sniffer",
    # Airtag
    "airtag_scanner": "airtag_scanner_cc1352p7",
    "airtag_spoofer": "airtag_spoofer_cc1352p7",
    "airtag-scanner": "airtag_scanner_cc1352p7",
    "airtag-spoofer": "airtag_spoofer_cc1352p7",
    # CatSniffer V3
    "catnip_v3": "catnip_v3",
    "v3": "catnip_v3",
}

# Map official IDs to specific file patterns/basenames
# This is used when searching for files to flash.
OFFICIAL_ID_TO_FILENAME = {
    "sniffle": "sniffle_cc1352p7_1M",
    "ti_sniffer": "sniffer_fw_Catsniffer_v3.x",
    "airtag_spoofer_cc1352p7": "airtag_spoofer_CC1352P_7",
    "airtag_scanner_cc1352p7": "airtag_scanner_CC1352P_7",
    "catnip_v3": "catsniffer-v3",
    "justworks_scanner_cc1352p7": "justworks_scanner",
}


def get_official_id(alias_or_name: str) -> Optional[str]:
    """
    Resolve an alias or partial firmware name to an official ID.

    Args:
        alias_or_name: User alias (e.g., 'zigbee') or filename (e.g., 'sniffle_cc1352.hex')

    Returns:
        Official ID constant or None if not found
    """
    if not alias_or_name:
        return None

    name_lower = alias_or_name.lower().strip()

    # 1. Exact alias match
    if name_lower in ALIAS_TO_OFFICIAL_ID:
        return ALIAS_TO_OFFICIAL_ID[name_lower]

    # 2. Check if it's already an official ID
    if name_lower in OFFICIAL_FW_IDS:
        return name_lower

    # 3. Pattern matching for filenames
    if "sniffle" in name_lower:
        return "sniffle"
    if any(x in name_lower for x in ["catsniffer-v3.1."]):
        return "rp2040_boot"
    if any(x in name_lower for x in ["sniffer", "zigbee", "thread", "15.4"]):
        return "ti_sniffer"
    if "airtag" in name_lower:
        if "spoof" in name_lower:
            return "airtag_spoofer_cc1352p7"
        if "scan" in name_lower:
            return "airtag_scanner_cc1352p7"

    return None


def get_filename_pattern(official_id: str) -> Optional[str]:
    """Get the preferred filename pattern for an official ID."""
    return OFFICIAL_ID_TO_FILENAME.get(official_id)

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
    "ble_spam_cc1352p_7",
]

# Map user-friendly aliases to official IDs
ALIAS_TO_OFFICIAL_ID = {
    # BLE
    "ble": "sniffle",
    "sniffle": "sniffle",
    "justworks": "justworks_scanner_cc1352p7",
    # BLE Spam (multi-vendor advertising spam)
    "ble_spam": "ble_spam_cc1352p_7",
    "ble-spam": "ble_spam_cc1352p_7",
    "blespam": "ble_spam_cc1352p_7",
    "spam": "ble_spam_cc1352p_7",
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
# These are the CatSniffer v3 (CC1352P7) images.
OFFICIAL_ID_TO_FILENAME = {
    "sniffle": "sniffle_cc1352p7_1M",
    "ti_sniffer": "sniffer_fw_Catsniffer_v3.x",
    "airtag_spoofer_cc1352p7": "airtag_spoofer_CC1352P_7",
    "airtag_scanner_cc1352p7": "airtag_scanner_CC1352P_7",
    "catnip_v3": "catsniffer-v3",
    "justworks_scanner_cc1352p7": "justworks_scanner",
    # No v2 image: BLE Spam ships only for the CC1352P7 (v3). Keep it out of
    # the v2 table below so a P7 image is never flashed onto a P1 board.
    "ble_spam_cc1352p_7": "ble_spam_CC1352P_7",
}

# Per board generation. A v2 (SAMD21 + CC1352P1) can only take CC1352P1
# images; IDs missing here have no v2 image and must never fall back to the
# v3 file (a P7 image disables the P1 bootloader).
OFFICIAL_ID_TO_FILENAME_BY_BOARD = {
    "v3": OFFICIAL_ID_TO_FILENAME,
    "v2": {
        # Sniffle is mirrored from the nccgroup release, which builds both
        # variants; the rest come from the CatSniffer-Firmware v2.X.Y.Z
        # releases, whose CC1352P1 images spell the variant "CC1352P1"
        # (the v3 bundle spells the same field "CC1352P_7").
        "sniffle": "sniffle_cc1352p1_cc2652p1_1M",
        "airtag_scanner_cc1352p7": "airtag_scanner_CC1352P1",
        "airtag_spoofer_cc1352p7": "airtag_spoofer_CC1352P1",
        "justworks_scanner_cc1352p7": "justworks_scanner_CC1352P1",
        "catnip_v2": "catsniffer-v2",
    },
}


# Several aliases resolve to the same official ID; this is the one worth
# printing back to a user. Showing the raw ID instead spells a variant that
# may not be the board's own: 'airtag_scanner_cc1352p7' is the ID of the
# image a v2 board flashes as airtag_scanner_CC1352P1.hex.
OFFICIAL_ID_TO_DISPLAY_ALIAS = {
    "sniffle": "ble",
    "ti_sniffer": "zigbee",
    "airtag_scanner_cc1352p7": "airtag-scanner",
    "airtag_spoofer_cc1352p7": "airtag-spoofer",
    "justworks_scanner_cc1352p7": "justworks",
    "ble_spam_cc1352p_7": "ble_spam",
}


def get_display_alias(official_id: str) -> str:
    """The user-facing alias for an official ID (the ID itself as fallback)."""
    return OFFICIAL_ID_TO_DISPLAY_ALIAS.get(official_id, official_id)


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
    if "catsniffer-v2" in name_lower:
        return "catnip_v2"
    # Before the generic "sniffer" rule: the justworks images are named
    # justworks_scanner_*, which matches none of the branches below and used
    # to leave the file with no official ID at all.
    if "justworks" in name_lower:
        return "justworks_scanner_cc1352p7"
    # Before the generic "sniffer" rule too: the image is named
    # ble_spam_CC1352P_7 and must not be mistaken for a TI sniffer.
    if "ble_spam" in name_lower or "blespam" in name_lower:
        return "ble_spam_cc1352p_7"
    if any(x in name_lower for x in ["sniffer", "zigbee", "thread", "15.4"]):
        return "ti_sniffer"
    if "airtag" in name_lower:
        if "spoof" in name_lower:
            return "airtag_spoofer_cc1352p7"
        if "scan" in name_lower:
            return "airtag_scanner_cc1352p7"

    return None


def get_filename_pattern(
    official_id: str, board_generation: str = "v3"
) -> Optional[str]:
    """
    Get the preferred filename pattern for an official ID on a board
    generation ("v2" or "v3"). Returns None when the board has no image for
    that ID; callers must not fall back to another generation's file.
    """
    table = OFFICIAL_ID_TO_FILENAME_BY_BOARD.get(board_generation or "v3", {})
    return table.get(official_id)


def official_ids_for_board(board_generation: str) -> List[str]:
    """Official IDs that have an image for the given board generation."""
    return list(
        OFFICIAL_ID_TO_FILENAME_BY_BOARD.get(board_generation or "v3", {}).keys()
    )

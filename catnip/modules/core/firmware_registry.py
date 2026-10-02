"""Declarative firmware registry with capability metadata.

Wraps the id/alias/filename tables in ``modules.firmware.fw_aliases`` (kept
as-is — it already encodes the exact alias-resolution heuristics existing
tests rely on) with a ``capabilities`` set per firmware, so callers can ask
"which firmware supports sniffing BLE" instead of hardcoding official ids
across the CLI (see analisis-bombercat-vs-catnip.md, section 2).
"""

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional

from ..firmware import fw_aliases

# Capabilities a firmware image may declare.
CAP_SNIFF_BLE = "sniff_ble"
CAP_SNIFF_ZIGBEE = "sniff_zigbee"
CAP_SNIFF_THREAD = "sniff_thread"
CAP_AIRTAG_SCAN = "airtag_scan"
CAP_AIRTAG_SPOOF = "airtag_spoof"
CAP_JUSTWORKS = "justworks"


@dataclass(frozen=True)
class Firmware:
    """One registry entry: an official firmware id plus what it can do."""

    id: str
    display: str
    description: str
    capabilities: FrozenSet[str] = frozenset()

    def can(self, capability: str) -> bool:
        return capability in self.capabilities

    def filename_for(self, board_generation: str = "v3") -> Optional[str]:
        """Filename pattern for this firmware on a given board generation,
        or None if this firmware has no image for that generation."""
        return fw_aliases.get_filename_pattern(self.id, board_generation)


FIRMWARE_REGISTRY: Dict[str, Firmware] = {
    "sniffle": Firmware(
        id="sniffle",
        display="Sniffle",
        description="BLE sniffer/relay firmware",
        capabilities=frozenset({CAP_SNIFF_BLE}),
    ),
    "ti_sniffer": Firmware(
        id="ti_sniffer",
        display="TI Multiprotocol Sniffer",
        description="Texas Instruments sniffer (Zigbee/Thread/802.15.4)",
        capabilities=frozenset({CAP_SNIFF_ZIGBEE, CAP_SNIFF_THREAD}),
    ),
    "justworks_scanner_cc1352p7": Firmware(
        id="justworks_scanner_cc1352p7",
        display="JustWorks Scanner",
        description="BLE JustWorks pairing scanner",
        capabilities=frozenset({CAP_JUSTWORKS}),
    ),
    "airtag_scanner_cc1352p7": Firmware(
        id="airtag_scanner_cc1352p7",
        display="AirTag Scanner",
        description="Apple AirTag scanner",
        capabilities=frozenset({CAP_AIRTAG_SCAN}),
    ),
    "airtag_spoofer_cc1352p7": Firmware(
        id="airtag_spoofer_cc1352p7",
        display="AirTag Spoofer",
        description="Apple AirTag spoofer",
        capabilities=frozenset({CAP_AIRTAG_SPOOF}),
    ),
    "catnip_v3": Firmware(
        id="catnip_v3",
        display="CatSniffer v3 default",
        description="Default/bootloader-safe image for CatSniffer v3 boards",
        capabilities=frozenset(),
    ),
    "catnip_v2": Firmware(
        id="catnip_v2",
        display="CatSniffer v2 default",
        description="Default image for CatSniffer v2 boards",
        capabilities=frozenset(),
    ),
}


def get_firmware(official_id: str) -> Optional[Firmware]:
    """Look up a registry entry by its official firmware id (not an alias)."""
    return FIRMWARE_REGISTRY.get(official_id)


def resolve(alias_or_name: str) -> Optional[Firmware]:
    """Resolve a user-facing alias or filename to its registry entry."""
    official_id = fw_aliases.get_official_id(alias_or_name)
    if official_id is None:
        return None
    return FIRMWARE_REGISTRY.get(official_id)


def firmwares_with_capability(capability: str) -> List[Firmware]:
    """All registered firmwares that declare a given capability."""
    return [fw for fw in FIRMWARE_REGISTRY.values() if fw.can(capability)]


# Capability -> suggested `catnip sniff <name>` command. Shared by `flash`'s
# post-flash hint and `status`'s honest next-steps (see
# analisis-bombercat-vs-catnip.md, section 3 and section 7).
CAPABILITY_NEXT_STEP: Dict[str, str] = {
    CAP_SNIFF_BLE: "catnip sniff ble",
    CAP_SNIFF_ZIGBEE: "catnip sniff zigbee -c 15",
    CAP_SNIFF_THREAD: "catnip sniff thread -c 15",
    CAP_AIRTAG_SCAN: "catnip sniff airtag_scanner",
}


def next_steps_for(firmware: Firmware) -> List[str]:
    """Suggested `catnip sniff ...` commands for a firmware's capabilities."""
    return [cmd for cap, cmd in CAPABILITY_NEXT_STEP.items() if firmware.can(cap)]

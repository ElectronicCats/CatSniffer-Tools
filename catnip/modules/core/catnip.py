import enum

# Internal
from .firmware_verifier import FirmwareVerifier
from .usb_connection import (
    CatSnifferDevice,
    BridgeConnection,
    LoRaConnection,
    ShellConnection,
    find_devices,
    find_device,
    get_bridge_port,
    DEFAULT_BAUDRATE,
    DEFAULT_COMPORT,
    DEFAULT_TIMEOUT,
    DEFAULT_WRITE_TIMEOUT,
    DEFAULT_READLINE_MAX_BYTES,
    CATSNIFFER_VID,
    CATSNIFFER_PID,
)

# Re-exported for callers that import these names from catnip
__all__ = [
    "CatSnifferDevice",
    "BridgeConnection",
    "LoRaConnection",
    "ShellConnection",
    "SerialConnection",
    "find_devices",
    "find_device",
    "get_bridge_port",
    "catnip_get_devices",
    "catnip_get_device",
    "catnip_get_port",
    "DEFAULT_BAUDRATE",
    "DEFAULT_COMPORT",
    "DEFAULT_TIMEOUT",
    "DEFAULT_WRITE_TIMEOUT",
    "DEFAULT_READLINE_MAX_BYTES",
    "CATSNIFFER_VID",
    "CATSNIFFER_PID",
    "SniffingFirmware",
    "SniffingBaseFirmware",
    "Catnip",
]

# Shell commands for bootloader control
SHELL_CMD_BOOT = "boot"
SHELL_CMD_EXIT = "exit"

# Shell commands for firmware update
SHELL_CMD_FW_VERSION = "fw_version"
SHELL_CMD_REBOOT = "reboot"


# Supported Sniffer protocols
class SniffingFirmware(enum.Enum):
    BLE = enum.auto()  # Sniffle Firmware
    ZIGBEE = enum.auto()  # TI Sniffer Firmware
    THREAD = enum.auto()  # TI Sniffer Firmware
    JWORKS = enum.auto()  # Just works
    LORA = enum.auto()
    AIRTAG_SCANNER = enum.auto()


class SniffingBaseFirmware(enum.Enum):
    BLE = "sniffle"
    ZIGBEE = "sniffer"
    THREAD = "sniffer"
    JWORKS = "justworks"
    LORA = "lora"
    AIRTAG_SCANNER = "airtag_scanner"


# ── Backward-compatible aliases ───────────────────────────────────────────────

# SerialConnection kept as alias for code that still imports it from here
SerialConnection = BridgeConnection


def catnip_get_devices():
    return find_devices()


def catnip_get_device(device_id=None):
    return find_device(device_id)


def catnip_get_port():
    return get_bridge_port()


# ── Main sniffer class ────────────────────────────────────────────────────────


class Catnip(BridgeConnection):
    """Main CatSniffer class for bridge port (CC1352) communication."""

    def __init__(self, port=None):
        super().__init__(port=port or get_bridge_port())

    # ── Deprecated verification methods ─────────────────────────────────
    #
    # These used to hold the firmware-verification logic directly (mixing
    # plain bridge I/O with business logic — see "Responsabilidades difusas"
    # in analisis-bombercat-vs-catnip.md, section 2). The logic now lives in
    # FirmwareVerifier; these wrappers stay only so existing callers
    # (protocols/cli/cativity.py, protocols/cli/vhci.py) keep working.
    # New code should use FirmwareVerifier directly instead.

    def check_flag(self, flag, timeout=2) -> bool:
        return FirmwareVerifier(self.port)._check_flag(flag, timeout=timeout)

    def check_ti_firmware(self, timeout=2) -> bool:
        return FirmwareVerifier(self.port)._check_ti_firmware(timeout=timeout)

    def check_firmware_by_metadata(
        self, expected_fw_id: str, shell_port: str = None
    ) -> bool:
        return FirmwareVerifier(self.port, shell_port).verify_metadata(expected_fw_id)

    def check_sniffle_firmware_smart(
        self, shell_port: str = None, timeout=3, max_retries=2
    ) -> bool:
        return FirmwareVerifier(self.port, shell_port).verify("sniffle").verified

    def check_sniffle_firmware(self, timeout=3, max_retries=2) -> bool:
        return FirmwareVerifier(self.port)._check_sniffle_firmware(
            timeout=timeout, max_retries=max_retries
        )

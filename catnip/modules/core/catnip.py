import enum
import time

# Internal
from protocol.sniffer_ti import SnifferTI
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
    "CATSNIFFER_VID",
    "CATSNIFFER_PID",
    "SniffingFirmware",
    "SniffingBaseFirmware",
    "Catnip",
]

# External
import serial

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
    FSK = enum.auto()
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

    def check_flag(self, flag, timeout=2) -> bool:
        if not self.connect():
            return False
        conn = self.connection
        if conn is None:
            return False
        conn.timeout = timeout
        self.write(SnifferTI().Commands().stop())
        self.write(SnifferTI().Commands().ping())
        got = self.read(16)
        result = got[7:8].hex() == "40" or flag in got
        self.disconnect()
        return result

    def check_ti_firmware(self, timeout=2) -> bool:
        return self.check_flag(flag=b"TI Packet", timeout=timeout)

    def check_firmware_by_metadata(
        self, expected_fw_id: str, shell_port: str = None
    ) -> bool:
        """
        Verify firmware using the RP2040 metadata system.

        Queries the firmware ID stored in RP2040 flash via the shell port.
        More reliable than direct CC1352 communication because it does not
        depend on the CC1352 being responsive.
        """
        from ..firmware.fw_metadata import FirmwareMetadata

        if shell_port is None:
            return False

        try:
            shell = ShellConnection(port=shell_port)
            if not shell.connect():
                return False

            metadata = FirmwareMetadata(shell)
            current_id = metadata.get_firmware_id()
            shell.disconnect()

            return bool(current_id) and current_id == expected_fw_id

        except Exception:
            return False

    def check_sniffle_firmware_smart(
        self, shell_port: str = None, timeout=3, max_retries=2
    ) -> bool:
        """
        Check for Sniffle firmware: metadata first, direct communication fallback.
        """
        if shell_port and self.check_firmware_by_metadata("sniffle", shell_port):
            return True

        # Ensure port is closed before direct communication attempt
        try:
            if self.connection and self.connection.is_open:
                self.disconnect()
            time.sleep(0.2)
        except Exception:
            pass

        return self.check_sniffle_firmware(timeout, max_retries)

    def check_sniffle_firmware(self, timeout=3, max_retries=2) -> bool:
        """
        Check for Sniffle firmware by sending CMD_MARKER and validating the response.
        """
        from base64 import b64encode, b64decode
        from binascii import Error as BAError

        flag = [0x24]
        b0 = (len(flag) + 3) // 3
        msg = b64encode(bytes([b0, *flag])) + b"\r\n"

        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    time.sleep(1)

                if not self.connect():
                    continue

                conn = self.connection
                if conn is None:
                    continue

                conn.timeout = timeout

                try:
                    conn.reset_input_buffer()
                    conn.reset_output_buffer()
                except Exception:
                    self.disconnect()
                    continue

                self.write(msg)
                time.sleep(0.2)

                start = time.time()
                pkt = b""
                while time.time() - start < timeout:
                    try:
                        line = self.readline()
                        if line:
                            pkt = line
                            break
                    except Exception:
                        pass
                    time.sleep(0.05)

                if not pkt:
                    self.disconnect()
                    continue

                try:
                    decoded = b64decode(pkt.rstrip())
                    self.disconnect()
                    if len(decoded) >= 3:
                        return True
                except (BAError, ValueError):
                    self.disconnect()
                    continue

            except serial.SerialException:
                try:
                    self.disconnect()
                except Exception:
                    pass
            except Exception:
                try:
                    self.disconnect()
                except Exception:
                    pass
            finally:
                try:
                    if self.connection and self.connection.is_open:
                        self.disconnect()
                except Exception:
                    pass

        return False

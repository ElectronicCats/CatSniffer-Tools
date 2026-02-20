"""
CatSniffer TUI Testbench Constants

Device identifiers, timeouts, and command definitions.
"""
from enum import Enum
from typing import Dict, List

# USB Identifiers
CATSNIFFER_VID = 0x1209
CATSNIFFER_PID = 0xBABB

# Serial Settings
DEFAULT_BAUDRATE = 115200
BOOTLOADER_BAUDRATE = 500000

# Timeouts (seconds)
COMMAND_TIMEOUT = 2.0
CONNECT_TIMEOUT = 1.0
HOTPLUG_SCAN_INTERVAL = 3.0
SMOKE_TEST_STEP_TIMEOUT = 3.0

# Endpoint Names
ENDPOINT_BRIDGE = "Cat-Bridge"  # CDC0 - CC1352 HCI UART
ENDPOINT_LORA = "Cat-LoRa"      # CDC1 - SX1262 LoRa/FSK
ENDPOINT_SHELL = "Cat-Shell"    # CDC2 - Config/Debug shell

ENDPOINT_LABELS: Dict[str, str] = {
    ENDPOINT_BRIDGE: "CDC0",
    ENDPOINT_LORA: "CDC1",
    ENDPOINT_SHELL: "CDC2",
}

# CDC2 Shell Commands
CDC2_COMMANDS = {
    # Mode/Band
    "boot": "boot",
    "exit": "exit",
    "band1": "band1",  # 2.4GHz
    "band2": "band2",  # Sub-GHz
    "band3": "band3",  # LoRa
    "reboot": "reboot",
    "status": "status",

    # LoRa Config
    "lora_freq": "lora_freq",
    "lora_sf": "lora_sf",
    "lora_bw": "lora_bw",
    "lora_cr": "lora_cr",
    "lora_power": "lora_power",
    "lora_mode": "lora_mode",
    "lora_preamble": "lora_preamble",
    "lora_syncword": "lora_syncword",
    "lora_iq": "lora_iq",
    "lora_config": "lora_config",
    "lora_apply": "lora_apply",

    # FSK Config
    "fsk_freq": "fsk_freq",
    "fsk_bitrate": "fsk_bitrate",
    "fsk_fdev": "fsk_fdev",
    "fsk_bw": "fsk_bw",
    "fsk_power": "fsk_power",
    "fsk_preamble": "fsk_preamble",
    "fsk_syncword": "fsk_syncword",
    "fsk_crc": "fsk_crc",
    "fsk_config": "fsk_config",
    "fsk_apply": "fsk_apply",

    # Modulation
    "modulation": "modulation",

    # CC1352 FW ID
    "cc1352_fw_id": "cc1352_fw_id",
}

# CDC1 LoRa Commands (command mode)
CDC1_LORA_COMMANDS = [
    "TEST",
    "TXTEST",
    "TX",
]

# CDC1 FSK Commands
CDC1_FSK_COMMANDS = [
    "FSKTEST",
    "FSKTX",
    "FSKRX",
]

# Greeting strings for identification
GREETING_SHELL = "Catsniffer Firmware Ready - Config Port"
GREETING_LORA = "LoRa Control Port"


class DeviceHealth(Enum):
    """Device health status."""
    HEALTHY = "healthy"      # All 3 endpoints
    PARTIAL = "partial"      # Missing endpoints but has shell
    CRITICAL = "critical"    # Missing shell port


class EndpointState(Enum):
    """Endpoint connection state."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class CommandStatus(Enum):
    """Command execution status."""
    PASS = "PASS"
    FAIL = "FAIL"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


class TerminalMode(Enum):
    """Interactive terminal modes."""
    LINE = "line"
    HEX = "hex"
    RAW = "raw"


# Log settings
LOG_BUFFER_SIZE = 10000
LOG_EXPORT_DIR = "logs"

# Smoke test configuration
SMOKE_TEST_PASS_THRESHOLD = 9  # 9 out of 11 steps must pass
MAX_CONCURRENT_SMOKE_TESTS = 3

import struct
import binascii

START_OF_FRAME = b"\x40\x53"
END_OF_FRAME = b"\x40\x45"
CONST_FRECUENCY = 65536  # 2^16 -> 16 bits -> MHz
PACKET_PDU_LEN = 5
PCAP_GLOBAL_HEADER_FORMAT = "<LHHIILL"
PCAP_PACKET_HEADER_FORMAT = "<llll"
PCAP_MAGIC_NUMBER = 0xA1B2C3D4
PCAP_VERSION_MAJOR = 2
PCAP_VERSION_MINOR = 4
PCAP_MAX_PACKET_SIZE = 0x0000FFFF


# =============================================================================
# RF API Types (matches TI firmware phy_rf_api.h)
# =============================================================================
class RfApi:
    PROPRIETARY = 0
    PROPRIETARY_15_4_G = 1
    IEEE_802_15_4 = 2
    BLE_5_1M = 3
    WBMS = 4


# =============================================================================
# Wireshark Protocol IDs for PCAP (matches catsniffer_rpi dissector)
# =============================================================================
class WiresharkProtocol:
    GENERIC = 0
    IEEE_802_15_4_G = 1
    IEEE_802_15_4 = 2
    BLE = 3
    WBMS = 4


# =============================================================================
# PHY Table for CC1352P (maps PHY number to configuration)
# Based on TI SmartRF Packet Sniffer 2 firmware phy_tables.c
# =============================================================================
PHY_TABLE = {
    # 802.15.4g modes (Sub-GHz)
    0:  {"name": "802.15.4g 50kbps 868MHz", "api": RfApi.PROPRIETARY_15_4_G, "default_freq_mhz": 868.0, "band": "868", "protocol": WiresharkProtocol.IEEE_802_15_4_G, "data_rate": "50kbps"},
    1:  {"name": "802.15.4g 50kbps 433MHz", "api": RfApi.PROPRIETARY_15_4_G, "default_freq_mhz": 433.0, "band": "433", "protocol": WiresharkProtocol.IEEE_802_15_4_G, "data_rate": "50kbps"},
    2:  {"name": "802.15.4g 5kbps SLR 868MHz", "api": RfApi.PROPRIETARY_15_4_G, "default_freq_mhz": 868.0, "band": "868", "protocol": WiresharkProtocol.IEEE_802_15_4_G, "data_rate": "5kbps"},
    3:  {"name": "802.15.4g 5kbps SLR 433MHz", "api": RfApi.PROPRIETARY_15_4_G, "default_freq_mhz": 433.0, "band": "433", "protocol": WiresharkProtocol.IEEE_802_15_4_G, "data_rate": "5kbps"},
    4:  {"name": "Wi-SUN #1a 50kbps", "api": RfApi.PROPRIETARY_15_4_G, "default_freq_mhz": 920.6, "band": "915", "protocol": WiresharkProtocol.IEEE_802_15_4_G, "data_rate": "50kbps"},
    5:  {"name": "Wi-SUN #1b 50kbps", "api": RfApi.PROPRIETARY_15_4_G, "default_freq_mhz": 920.8, "band": "915", "protocol": WiresharkProtocol.IEEE_802_15_4_G, "data_rate": "50kbps"},
    6:  {"name": "Wi-SUN #2a 100kbps", "api": RfApi.PROPRIETARY_15_4_G, "default_freq_mhz": 920.9, "band": "915", "protocol": WiresharkProtocol.IEEE_802_15_4_G, "data_rate": "100kbps"},
    7:  {"name": "Wi-SUN #2b 100kbps", "api": RfApi.PROPRIETARY_15_4_G, "default_freq_mhz": 921.1, "band": "915", "protocol": WiresharkProtocol.IEEE_802_15_4_G, "data_rate": "100kbps"},
    8:  {"name": "Wi-SUN #3 150kbps", "api": RfApi.PROPRIETARY_15_4_G, "default_freq_mhz": 920.8, "band": "915", "protocol": WiresharkProtocol.IEEE_802_15_4_G, "data_rate": "150kbps"},
    9:  {"name": "Wi-SUN #4a 200kbps", "api": RfApi.PROPRIETARY_15_4_G, "default_freq_mhz": 920.8, "band": "915", "protocol": WiresharkProtocol.IEEE_802_15_4_G, "data_rate": "200kbps"},
    10: {"name": "Wi-SUN #4b 200kbps", "api": RfApi.PROPRIETARY_15_4_G, "default_freq_mhz": 921.1, "band": "915", "protocol": WiresharkProtocol.IEEE_802_15_4_G, "data_rate": "200kbps"},
    11: {"name": "ZigBee R23 100kbps EU", "api": RfApi.PROPRIETARY_15_4_G, "default_freq_mhz": 868.3, "band": "868", "protocol": WiresharkProtocol.IEEE_802_15_4_G, "data_rate": "100kbps"},
    12: {"name": "ZigBee R23 500kbps NA", "api": RfApi.PROPRIETARY_15_4_G, "default_freq_mhz": 915.0, "band": "915", "protocol": WiresharkProtocol.IEEE_802_15_4_G, "data_rate": "500kbps"},
    13: {"name": "802.15.4g 200kbps 915MHz", "api": RfApi.PROPRIETARY_15_4_G, "default_freq_mhz": 915.0, "band": "915", "protocol": WiresharkProtocol.IEEE_802_15_4_G, "data_rate": "200kbps"},
    # Proprietary modes
    14: {"name": "Prop 50kbps 868MHz", "api": RfApi.PROPRIETARY, "default_freq_mhz": 868.0, "band": "868", "protocol": WiresharkProtocol.GENERIC, "data_rate": "50kbps"},
    15: {"name": "Prop 50kbps 433MHz", "api": RfApi.PROPRIETARY, "default_freq_mhz": 433.0, "band": "433", "protocol": WiresharkProtocol.GENERIC, "data_rate": "50kbps"},
    16: {"name": "Prop 5kbps SLR 868MHz", "api": RfApi.PROPRIETARY, "default_freq_mhz": 868.0, "band": "868", "protocol": WiresharkProtocol.GENERIC, "data_rate": "5kbps"},
    17: {"name": "Prop 5kbps SLR 433MHz", "api": RfApi.PROPRIETARY, "default_freq_mhz": 433.0, "band": "433", "protocol": WiresharkProtocol.GENERIC, "data_rate": "5kbps"},
    # Standard 2.4GHz modes
    18: {"name": "IEEE 802.15.4 2.4GHz", "api": RfApi.IEEE_802_15_4, "default_freq_mhz": 2405.0, "band": "2400", "protocol": WiresharkProtocol.IEEE_802_15_4, "data_rate": "250kbps"},
    19: {"name": "BLE 5 1Mbps", "api": RfApi.BLE_5_1M, "default_freq_mhz": 2402.0, "band": "2400", "protocol": WiresharkProtocol.BLE, "data_rate": "1Mbps"},
}

# Legacy compatibility - PHY 18 is standard IEEE 802.15.4
BYTE_IEEE802145 = b"\x12"  # PHY number 18

# =============================================================================
# Wi-SUN PHY mode to PHY number mapping
# =============================================================================
WISUN_MODE_TO_PHY = {
    "1a": 4,
    "1b": 5,
    "2a": 6,
    "2b": 7,
    "3": 8,
    "4a": 9,
    "4b": 10,
}

# =============================================================================
# ZigBee R23 region to PHY number mapping
# =============================================================================
ZIGBEE_R23_REGION_TO_PHY = {
    "eu": 11,  # 100kbps, 868 MHz
    "na": 12,  # 500kbps, 915 MHz
}

# =============================================================================
# Channel Tables for Different Bands
# =============================================================================

# IEEE 802.15.4 2.4 GHz channels (11-26)
CHANNEL_RANGE_IEEE802154 = [
    (channel, (2405.0 + (5 * (channel - 11)))) for channel in range(11, 27)
]

# Legacy alias for backwards compatibility
CHANNEL_RANGE_IEEE802145 = CHANNEL_RANGE_IEEE802154

# Wi-SUN FAN 1.0 NA channel plan (902-928 MHz, 200kHz spacing)
CHANNEL_RANGE_WISUN_NA = [
    (ch, 902.2 + (0.2 * ch)) for ch in range(0, 129)
]

# Wi-SUN FAN 1.0 EU channel plan (863-870 MHz, 100kHz spacing)
CHANNEL_RANGE_WISUN_EU = [
    (ch, 863.1 + (0.1 * ch)) for ch in range(0, 69)
]

# 868 MHz band single channel (Europe)
CHANNEL_RANGE_868 = [(0, 868.3)]

# 915 MHz band channels (902-928 MHz, North America)
CHANNEL_RANGE_915 = [
    (ch, 902.2 + (0.4 * ch)) for ch in range(0, 64)
]

# 433 MHz band single channel
CHANNEL_RANGE_433 = [(0, 433.05)]

# BLE advertising channels
CHANNEL_RANGE_BLE = [
    (37, 2402.0),
    (38, 2426.0),
    (39, 2480.0),
]


def get_channel_table_for_phy(phy_number: int) -> list:
    """Get the appropriate channel table for a PHY number.

    Args:
        phy_number: PHY number (0-19 for CC1352P)

    Returns:
        List of (channel, frequency_mhz) tuples
    """
    if phy_number not in PHY_TABLE:
        return CHANNEL_RANGE_IEEE802154

    band = PHY_TABLE[phy_number]["band"]
    if band == "2400":
        if PHY_TABLE[phy_number]["api"] == RfApi.BLE_5_1M:
            return CHANNEL_RANGE_BLE
        return CHANNEL_RANGE_IEEE802154
    elif band == "915":
        return CHANNEL_RANGE_915
    elif band == "868":
        return CHANNEL_RANGE_868
    elif band == "433":
        return CHANNEL_RANGE_433
    else:
        return CHANNEL_RANGE_IEEE802154


def get_frequency_for_channel(channel: int, phy_number: int = 18) -> float:
    """Get frequency in MHz for a given channel and PHY.

    Args:
        channel: Channel number
        phy_number: PHY number (default 18 = IEEE 802.15.4 2.4GHz)

    Returns:
        Frequency in MHz
    """
    channel_table = get_channel_table_for_phy(phy_number)
    for _channel, freq in channel_table:
        if _channel == channel:
            return freq
    # Default to first channel or PHY default frequency
    if channel_table:
        return channel_table[0][1]
    if phy_number in PHY_TABLE:
        return PHY_TABLE[phy_number]["default_freq_mhz"]
    return 2405.0


def get_phy_info(phy_number: int) -> dict:
    """Get PHY configuration information.

    Args:
        phy_number: PHY number

    Returns:
        Dictionary with PHY configuration or None if invalid
    """
    return PHY_TABLE.get(phy_number)


def list_available_phys() -> list:
    """List all available PHY configurations.

    Returns:
        List of (phy_number, name, band, data_rate) tuples
    """
    return [
        (num, info["name"], info["band"], info["data_rate"])
        for num, info in sorted(PHY_TABLE.items())
    ]


# =============================================================================
# PCAP Helpers
# =============================================================================

def get_global_header(interface=147):
    """Generate PCAP global header.

    Args:
        interface: Link layer type (147 = IEEE 802.15.4 with FCS)

    Returns:
        PCAP global header bytes
    """
    global_header = struct.pack(
        PCAP_GLOBAL_HEADER_FORMAT,
        PCAP_MAGIC_NUMBER,
        PCAP_VERSION_MAJOR,
        PCAP_VERSION_MINOR,
        0,  # Reserved
        0,  # Reserved
        PCAP_MAX_PACKET_SIZE,
        interface,
    )
    return global_header


class Pcap:
    """PCAP packet wrapper for Wireshark integration."""

    def __init__(self, packet: bytes, timestamp_seconds: float):
        self.packet = packet
        self.timestamp_seconds = timestamp_seconds
        self.pcap_packet = self.pack()

    def pack(self):
        int_timestamp = int(self.timestamp_seconds)
        timestamp_offset = int((self.timestamp_seconds - int_timestamp) * 1_000_000)
        return (
            struct.pack(
                PCAP_PACKET_HEADER_FORMAT,
                int_timestamp,
                timestamp_offset,
                len(self.packet),  # Snapshot Length
                len(self.packet),  # Packet Length
            )
            + self.packet
        )

    def packet_to_hex(self):
        return self.packet.hex()

    def get_pcap(self):
        return self.pcap_packet

    def pcap_hex(self):
        return binascii.hexlify(self.pcap_packet).decode("utf-8")

    def __str__(self) -> str:
        return f"{self.packet}"

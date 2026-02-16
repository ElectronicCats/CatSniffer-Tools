"""
TI Sniffer Protocol Handler for CatSniffer

Supports all PHY modes from TI SmartRF Packet Sniffer 2 firmware including:
- Wi-SUN modes #1a, #1b, #2a, #2b, #3, #4a, #4b
- ZigBee R23 sub-1 GHz (100kbps EU, 500kbps NA)
- IEEE 802.15.4g generic modes
- Proprietary Sub-GHz modes
- Standard IEEE 802.15.4 (2.4 GHz)
- BLE 5
"""

import enum
import struct
import time

from .common import (
    START_OF_FRAME,
    END_OF_FRAME,
    PACKET_PDU_LEN,
    CHANNEL_RANGE_IEEE802154,
    PHY_TABLE,
    RfApi,
    WiresharkProtocol,
    get_frequency_for_channel,
    get_channel_table_for_phy,
    Pcap,
)


class PacketCategory(enum.Enum):
    RESERVED = 0x0
    COMMAND = 0x1
    COMMAND_RESPONSE = 0x2
    DATA_STREAMING_AND_ERROR = 0x3


def calculate_frequency(frequency: float) -> bytes:
    """Calculate frequency bytes for TI firmware.

    The firmware expects 4 bytes:
    - 2 bytes: integer part of frequency in MHz (little-endian)
    - 2 bytes: fractional part as 16-bit value (little-endian)

    Args:
        frequency: Frequency in MHz (e.g., 868.3 or 2405.0)

    Returns:
        4-byte frequency value for CFG_FREQUENCY command
    """
    integer_value = int(frequency)
    fractional_value = int((frequency - integer_value) * 65536)
    frequency_int_bytes = integer_value.to_bytes(2, byteorder="little")
    frequency_frac_bytes = fractional_value.to_bytes(2, byteorder="little")
    return frequency_int_bytes + frequency_frac_bytes


def convert_channel_to_freq(channel: int, phy_number: int = 18) -> float:
    """Convert channel number to frequency in MHz.

    Args:
        channel: Channel number
        phy_number: PHY number (default 18 = IEEE 802.15.4 2.4GHz)

    Returns:
        Frequency in MHz
    """
    return get_frequency_for_channel(channel, phy_number)


class TIBaseCommand:
    """Base class for TI sniffer command packets."""

    class ByteCommands(enum.Enum):
        PING = 0x40
        START = 0x41
        STOP = 0x42
        PAUSE = 0x43
        RESUME = 0x44
        CFG_FREQUENCY = 0x45
        CFG_PHY = 0x47
        CFG_WBMS_NETWORK = 0x50
        CFG_WBMS_NETWORK_TIMING = 0x51
        CFG_BLE_INITIATOR_ADDR = 0x70

    def __init__(self, cmd, data=b"") -> None:
        self.cmd = cmd
        self.data = data
        self.packet = self.__pack()

    def calculate_fcs(self) -> bytes:
        """Calculate Frame Check Sequence (simple checksum)."""
        if type(self.cmd) == int:
            self.cmd = self.cmd.to_bytes(1, byteorder="little")
        core_bytes = sum(self.cmd + len(self.data).to_bytes(2, byteorder="little"))
        if self.data != b"":
            core_bytes += sum(self.data)
        checksum = core_bytes & 0xFF
        return checksum.to_bytes(1, byteorder="little")

    def __pack(self):
        """Pack command into bytes for transmission."""
        if type(self.cmd) == int:
            self.cmd = self.cmd.to_bytes(1, byteorder="little")
        return b"".join([
            START_OF_FRAME,
            self.cmd,
            len(self.data).to_bytes(2, byteorder="little"),
            self.data,
            self.calculate_fcs(),
            END_OF_FRAME,
        ])

    def __str__(self):
        return f"TISnifferPacket.PacketCommand(cmd={self.cmd}, data={self.data}, packet={self.packet})"


class SnifferTI:
    """TI Sniffer protocol handler."""

    class Commands:
        """Command generators for TI sniffer firmware."""

        @staticmethod
        def ping() -> bytes:
            """Generate PING command."""
            return TIBaseCommand(TIBaseCommand.ByteCommands.PING.value).packet

        @staticmethod
        def start() -> bytes:
            """Generate START command."""
            return TIBaseCommand(TIBaseCommand.ByteCommands.START.value).packet

        @staticmethod
        def stop() -> bytes:
            """Generate STOP command."""
            return TIBaseCommand(TIBaseCommand.ByteCommands.STOP.value).packet

        @staticmethod
        def pause() -> bytes:
            """Generate PAUSE command."""
            return TIBaseCommand(TIBaseCommand.ByteCommands.PAUSE.value).packet

        @staticmethod
        def resume() -> bytes:
            """Generate RESUME command."""
            return TIBaseCommand(TIBaseCommand.ByteCommands.RESUME.value).packet

        @staticmethod
        def config_freq_mhz(freq_mhz: float) -> bytes:
            """Configure frequency directly in MHz.

            Args:
                freq_mhz: Frequency in MHz (e.g., 868.3, 915.0, 2405.0)

            Returns:
                CFG_FREQUENCY command packet
            """
            frequency_bytes = calculate_frequency(freq_mhz)
            return TIBaseCommand(
                TIBaseCommand.ByteCommands.CFG_FREQUENCY.value, frequency_bytes
            ).packet

        @staticmethod
        def config_freq(channel: int, phy_number: int = 18) -> bytes:
            """Configure frequency by channel number for a given PHY.

            Args:
                channel: Channel number
                phy_number: PHY number (default 18 = IEEE 802.15.4 2.4GHz)

            Returns:
                CFG_FREQUENCY command packet
            """
            freq_mhz = convert_channel_to_freq(channel, phy_number)
            return SnifferTI.Commands.config_freq_mhz(freq_mhz)

        @staticmethod
        def config_phy(phy_number: int = 18) -> bytes:
            """Configure PHY mode.

            PHY numbers for CC1352P:
                0-13: 802.15.4g modes (Sub-GHz)
                    4-10: Wi-SUN modes #1a, #1b, #2a, #2b, #3, #4a, #4b
                    11: ZigBee R23 100kbps EU (868 MHz)
                    12: ZigBee R23 500kbps NA (915 MHz)
                14-17: Proprietary modes
                18: IEEE 802.15.4 2.4GHz (standard Zigbee/Thread)
                19: BLE 5 1Mbps

            Args:
                phy_number: PHY number (0-19 for CC1352P)

            Returns:
                CFG_PHY command packet
            """
            return TIBaseCommand(
                TIBaseCommand.ByteCommands.CFG_PHY.value,
                bytes([phy_number])
            ).packet

        @staticmethod
        def config_ble_initiator_addr(address: bytes) -> bytes:
            """Configure BLE initiator address for connection following.

            Args:
                address: 6-byte BLE address

            Returns:
                CFG_BLE_INITIATOR_ADDR command packet
            """
            if len(address) != 6:
                raise ValueError("BLE address must be 6 bytes")
            return TIBaseCommand(
                TIBaseCommand.ByteCommands.CFG_BLE_INITIATOR_ADDR.value,
                address
            ).packet

        @staticmethod
        def get_startup_cmd(channel: int = 11, phy_number: int = 18) -> list:
            """Get startup command sequence for a given PHY and channel.

            Args:
                channel: Channel number
                phy_number: PHY number (default 18 = IEEE 802.15.4 2.4GHz)

            Returns:
                List of command packets to initialize sniffer
            """
            startup_cmds = [
                SnifferTI.Commands.ping(),
                SnifferTI.Commands.stop(),
                SnifferTI.Commands.config_phy(phy_number),
                SnifferTI.Commands.config_freq(channel, phy_number),
                SnifferTI.Commands.start(),
            ]
            return startup_cmds

        @staticmethod
        def get_startup_cmd_freq(freq_mhz: float, phy_number: int) -> list:
            """Get startup command sequence with direct frequency.

            Args:
                freq_mhz: Frequency in MHz
                phy_number: PHY number

            Returns:
                List of command packets to initialize sniffer
            """
            startup_cmds = [
                SnifferTI.Commands.ping(),
                SnifferTI.Commands.stop(),
                SnifferTI.Commands.config_phy(phy_number),
                SnifferTI.Commands.config_freq_mhz(freq_mhz),
                SnifferTI.Commands.start(),
            ]
            return startup_cmds

    class Packet:
        """TI sniffer data packet parser."""

        def __init__(self, packet_bytes: bytes, channel: int = 11, phy_number: int = 18):
            """Initialize packet parser.

            Args:
                packet_bytes: Raw packet bytes from firmware
                channel: Channel number for metadata
                phy_number: PHY number for protocol detection
            """
            self.packet_bytes = packet_bytes
            self.channel = channel
            self.phy_number = phy_number
            self.type = 0x00
            self.category = 0x00
            self.length = 0
            self.payload = None
            self.pcap = None
            self.rssi = 0
            self.status = 0
            self.conn_info = 0
            self.connect_evt = 0
            self.dissect()

        def unpack_packet_info(self, info) -> None:
            """Unpack the packet info byte.

            Category: 2 bits (bits 6-7)
            Type: 6 bits (bits 0-5)
            """
            self.category = (info >> 6) & 0b11
            self.type = info & 0b00111111

        def get_protocol_byte(self) -> bytes:
            """Get Wireshark protocol byte based on PHY number."""
            if self.phy_number in PHY_TABLE:
                return bytes([PHY_TABLE[self.phy_number]["protocol"]])
            return bytes([WiresharkProtocol.IEEE_802_15_4])

        def get_phy_byte(self) -> bytes:
            """Get PHY byte for Wireshark based on RF API."""
            if self.phy_number in PHY_TABLE:
                api = PHY_TABLE[self.phy_number]["api"]
                # Map RF API to Wireshark PHY values
                phy_map = {
                    RfApi.PROPRIETARY: 0x01,
                    RfApi.PROPRIETARY_15_4_G: 0x02,
                    RfApi.IEEE_802_15_4: 0x03,
                    RfApi.BLE_5_1M: 0x05,
                    RfApi.WBMS: 0x06,
                }
                return bytes([phy_map.get(api, 0x03)])
            return b"\x03"

        def get_frequency_khz(self) -> int:
            """Get frequency in kHz for PCAP metadata."""
            freq_mhz = get_frequency_for_channel(self.channel, self.phy_number)
            return int(freq_mhz * 1000)

        def dissect(self) -> None:
            """Dissect packet and create PCAP data."""
            (_, pkt_info, self.length) = struct.unpack_from("<HBH", self.packet_bytes)
            self.unpack_packet_info(pkt_info)

            metadata_payload = self.packet_bytes[PACKET_PDU_LEN:-2]
            self.rssi = metadata_payload[-2]
            self.status = metadata_payload[-1]
            self.payload = self.packet_bytes[10:-4]

            # Build PCAP packet with correct protocol info
            version = b"\x00"
            interfaceType = b"\x00"
            interfaceId = bytes.fromhex("0300")
            protocol = self.get_protocol_byte()
            phy = self.get_phy_byte()
            freq_khz = self.get_frequency_khz()

            packet = (
                version
                + self.length.to_bytes(2, "little")
                + interfaceType
                + interfaceId
                + protocol
                + phy
                + freq_khz.to_bytes(4, "little")
                + int(self.channel).to_bytes(2, "little")
                + self.rssi.to_bytes(1, "little")
                + self.status.to_bytes(1, "little")
                + version  # padding
                + version  # padding
                + self.payload
            )
            pcap_file = Pcap(packet, time.time())
            self.pcap = pcap_file.get_pcap()

        def hex_digest(self, packet_bytes: bytes) -> str:
            """Convert bytes to hex string with spaces."""
            string_hex = packet_bytes.hex()
            return " ".join([string_hex[i : i + 2] for i in range(0, len(string_hex), 2)])

        # Legacy method name for backwards compatibility
        def hex_digiest(self, packet_bytes: bytes) -> str:
            return self.hex_digest(packet_bytes)

        def __str__(self):
            return f"Packet Info: Type ({self.type}) Category ({self.category})\n{self.hex_digest(self.payload)}"

    def __init__(self):
        pass

import enum
import struct
import binascii
import time

START_OF_FRAME = b"\x40\x53"
END_OF_FRAME = b"\x40\x45"
BYTE_IEEE802145 = b"\x12"
CHANNEL_RANGE_IEEE802145 = [
    (channel, (2405.0 + (5 * (channel - 11)))) for channel in range(11, 27)
]
CONST_FRECUENCY = 65536  # 2^16 -> 16 bits -> MHz
PACKET_PDU_LEN = 5
PCAP_GLOBAL_HEADER_FORMAT = "<LHHIILL"
PCAP_PACKET_HEADER_FORMAT = "<llll"
PCAP_MAGIC_NUMBER = 0xA1B2C3D4
PCAP_VERSION_MAJOR = 2
PCAP_VERSION_MINOR = 4
PCAP_MAX_PACKET_SIZE = 0x0000FFFF


def get_global_header(interface=147):
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
    def __init__(self, packet: bytes, timestamp_seconds: float):
        self.packet = packet
        self.timestamp_seconds = timestamp_seconds
        self.pcap_packet = self.pack()

    def pack(self):
        int_timestamp = int(self.timestamp_seconds)
        timestamp_offset = int((self.timestamp_seconds - int_timestamp) / 1_000_000)
        return (
            struct.pack(
                PCAP_PACKET_HEADER_FORMAT,  # Block Type
                int_timestamp,  # timestamp_seconds,
                timestamp_offset,  # timestamp_offset,
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


class PacketCategory(enum.Enum):
    RESERVED = 0x0
    COMMAND = 0x1
    COMMAND_RESPONSE = 0x2
    DATA_STREAMING_AND_ERROR = 0x3


def calculate_frequency(frequency) -> bytes:
    integer_value = int(frequency)
    fractional_value = int((integer_value - integer_value) * CONST_FRECUENCY)
    frequency_int_bytes = integer_value.to_bytes(2, byteorder="little")
    frequency_frac_bytes = fractional_value.to_bytes(2, byteorder="little")
    return frequency_int_bytes + frequency_frac_bytes


def convert_channel_to_freq(channel) -> bytes:
    for _channel in CHANNEL_RANGE_IEEE802145:
        if _channel[0] == channel:
            return _channel[1]
    return calculate_frequency(CHANNEL_RANGE_IEEE802145[0][1])


class TIBaseCommand:
    class ByteCommands(enum.Enum):
        PING = 0x40
        START = 0x41
        STOP = 0x42
        PAUSE = 0x43
        RESUME = 0x44
        CFG_FREQUENCY = 0x45
        CFG_PHY = 0x47

    def __init__(self, cmd, data=b"") -> None:
        self.cmd = cmd
        self.data = data
        self.packet = self.__pack()

    def calculate_fcs(self) -> bytes:
        if type(self.cmd) == int:
            self.cmd = self.cmd.to_bytes(1, byteorder="little")
        core_bytes = sum(self.cmd + len(self.data).to_bytes(2, byteorder="little"))
        if self.data != b"":
            core_bytes += sum(self.data)

        checksum = core_bytes & 0xFF
        return checksum.to_bytes(1, byteorder="little")

    def __pack(self):
        if type(self.cmd) == int:
            self.cmd = self.cmd.to_bytes(1, byteorder="little")
        return b"".join(
            [
                START_OF_FRAME,
                self.cmd,
                len(self.data).to_bytes(2, byteorder="little"),
                self.data,
                self.calculate_fcs(),
                END_OF_FRAME,
            ]
        )

    def __str__(self):
        return f"TISnifferPacket.PacketCommand(cmd={self.cmd}, data={self.data}, packet={self.packet})"


class SnifferTI:
    class Commands:
        def __init__(self):
            pass

        def ping(self) -> bytes:
            return TIBaseCommand(TIBaseCommand.ByteCommands.PING.value).packet

        def start(self) -> bytes:
            return TIBaseCommand(TIBaseCommand.ByteCommands.START.value).packet

        def stop(self) -> bytes:
            return TIBaseCommand(TIBaseCommand.ByteCommands.STOP.value).packet

        def pause(self) -> bytes:
            return TIBaseCommand(TIBaseCommand.ByteCommands.PAUSE.value).packet

        def resume(self) -> bytes:
            return TIBaseCommand(TIBaseCommand.ByteCommands.RESUME.value).packet

        def config_freq(self, channel) -> bytes:
            frequency = convert_channel_to_freq(channel=channel)
            frequency_bytes = calculate_frequency(frequency)
            return TIBaseCommand(
                TIBaseCommand.ByteCommands.CFG_FREQUENCY.value, frequency_bytes
            ).packet

        def config_phy(self) -> bytes:
            return TIBaseCommand(
                TIBaseCommand.ByteCommands.CFG_PHY.value, BYTE_IEEE802145
            ).packet

        def get_startup_cmd(self, channel=11):
            startup_cmds = [
                SnifferTI.Commands().ping(),
                SnifferTI.Commands().stop(),
                SnifferTI.Commands().config_phy(),
                SnifferTI.Commands().config_freq(channel=channel),
                SnifferTI.Commands().start(),
            ]
            return startup_cmds

    class Packet:
        def __init__(self, packet_bytes: bytes, channel: int = 11):
            self.packet_bytes = packet_bytes
            self.channel = channel
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
            """Unpack the packet info.
            Parameters:
            packet_info (bytes): The packet info to unpack.
            Returns: (packet_category, packet_type)
            Category: 2 bits -> Index: 6-7
            Type:     6 bits -> Index: 0-5"""
            self.category = (info >> 6) & 0b11
            self.type = info & 0b00111111

        def dissect(self) -> None:
            (_, pkt_info, self.length) = struct.unpack_from("<HBH", self.packet_bytes)
            self.unpack_packet_info(pkt_info)
            metadata_payload = self.packet_bytes[PACKET_PDU_LEN:-2]
            self.rssi = metadata_payload[-2]
            self.status = metadata_payload[-1]
            self.payload = self.packet_bytes[10:-4]
            version = b"\x00"
            interfaceType = b"\x00"
            interfaceId = bytes.fromhex("0300")
            protocol = b"\x02"
            phy = bytes.fromhex("03")
            packet = (
                version
                + self.length.to_bytes(2, "little")
                + interfaceType
                + interfaceId
                + protocol
                + phy
                + int(convert_channel_to_freq(self.channel)).to_bytes(4, "little")
                + int(self.channel).to_bytes(2, "little")
                + self.rssi.to_bytes(1, "little")
                + self.status.to_bytes(1, "little")
                + version
                + version
                + self.payload
            )
            pcap_file = Pcap(packet, time.time())
            self.pcap = pcap_file.get_pcap()

        def hex_digiest(self, packet_bytes: bytes) -> str:
            string_hex = packet_bytes.hex()
            return " ".join(
                [string_hex[i : i + 2] for i in range(0, len(string_hex), 2)]
            )

        def __str__(self):
            return f"Packet Info: Type ({self.type}) Category ({self.category})\n{self.hex_digiest(self.payload)}"

    def __init__(self):
        pass

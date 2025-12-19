import struct
import time
from .common import *


class SnifferSx:
    class Commands:
        def __init__(self):
            pass

        def set_freq(self, frequency: float) -> bytes:
            return bytes(f"set_freq {frequency}\r\n", "utf-8")

        def set_bw(self, bandwidth: float) -> bytes:
            return bytes(f"set_bw {bandwidth}\r\n", "utf-8")

        def set_sf(self, spreading_factor: float) -> bytes:
            return bytes(f"set_sf {spreading_factor}\r\n", "utf-8")

        def set_cr(self, coding_rate: float) -> bytes:
            return bytes(f"set_cr {coding_rate}\r\n", "utf-8")

        def set_pl(self, preamble_length: float) -> bytes:
            return bytes(f"set_pl {preamble_length}\r\n", "utf-8")

        def set_sw(self, sync_word: float) -> bytes:
            return bytes(f"set_sw {sync_word}\r\n", "utf-8")

        def start(self) -> bytes:
            return bytes(f"set_rx\r\n", "utf-8")

    class Packet:
        def __init__(
            self,
            packet_bytes: bytes,
            context={
                "frequency": 916,
                "bandwidth": 8,
                "spread_factor": 11,
                "coding_rate": 5,
            },
        ):
            self.packet_bytes = packet_bytes.replace(b"\r\n", b"")
            self.length = 0
            self.payload = None
            self.rssi = 0
            self.snr = None
            self.pcap = None
            self.context = context
            self.dissect()

        def dissect(self) -> None:
            (_, _, self.length) = struct.unpack_from("<HHH", self.packet_bytes)
            self.payload = self.packet_bytes[6:-10]
            self.rssi = struct.unpack_from("<f", self.packet_bytes[-10:])[0]
            self.snr = struct.unpack_from("<f", self.packet_bytes[-6:])[0]
            version = b"\x00"
            protocol = b"\x05"
            phy = bytes.fromhex("06")
            interfaceId = bytes.fromhex("0300")
            packet = (
                version
                + int(self.length).to_bytes(2, "little")
                + interfaceId
                + protocol
                + phy
                + int(self.context["frequency"]).to_bytes(4, "little")
                + int(self.context["bandwidth"]).to_bytes(1, "little")
                + int(self.context["spread_factor"]).to_bytes(1, "little")
                + int(self.context["coding_rate"]).to_bytes(1, "little")
                + struct.pack("<f", self.rssi)
                + struct.pack("<f", self.snr)
                + self.payload
            )
            pcap_file = Pcap(packet, time.time())
            self.pcap = pcap_file.get_pcap()

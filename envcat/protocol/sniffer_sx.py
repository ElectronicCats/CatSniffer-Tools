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
        def __init__(self, packet_bytes: bytes):
            self.packet_bytes = packet_bytes
            self.length = 0
            self.payload = None
            self.rssi = 0
            self.snr = None
            self.pcap = None

        def dissect(self) -> None:
            (_, self.length) = struct.unpack_from("<HH", self.packet_bytes)
            self.payload = self.packet_bytes[4:]
            self.rssi = self.packet_bytes[8:-4]
            self.snr = self.packet_bytes[-4:]
            print(self.payload)
            print(self.rssi)
            print(self.snr)
            version = b"\x00"
            packet = version + self.payload
            pcap_file = Pcap(packet, time.time())
            self.pcap = pcap_file.get_pcap()

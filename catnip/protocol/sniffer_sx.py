import re
import struct
import time
from .common import *


class LoRaShellCommands:
    """Shell commands for LoRa configuration via Cat-Shell port."""

    @staticmethod
    def set_freq(frequency_hz: int) -> str:
        return f"lora_freq {frequency_hz}"

    @staticmethod
    def set_sf(spreading_factor: int) -> str:
        return f"lora_sf {spreading_factor}"

    @staticmethod
    def set_bw(bandwidth: int) -> str:
        # El firmware espera el índice (7,8,9) o el valor en kHz
        if bandwidth in [7, 8, 9]:
            bw_map = {7: 125, 8: 250, 9: 500}
            return f"lora_bw {bw_map[bandwidth]}"
        return f"lora_bw {bandwidth}"

    @staticmethod
    def set_cr(coding_rate: int) -> str:
        return f"lora_cr {coding_rate}"

    @staticmethod
    def set_power(tx_power_dbm: int) -> str:
        return f"lora_power {tx_power_dbm}"

    @staticmethod
    def set_syncword(syncword: str) -> str:
        if syncword in ["private", "public"]:
            return f"lora_syncword {syncword}"
        return f"lora_syncword {syncword}"

    @staticmethod
    def set_mode(mode: str) -> str:
        return f"lora_mode {mode}"

    @staticmethod
    def get_config() -> str:
        return "lora_config"

    @staticmethod
    def apply_config() -> str:
        return "lora_apply"

    @staticmethod
    def get_status() -> str:
        return "status"

    @staticmethod
    def start_streaming() -> str:
        return "lora_mode stream"

    @staticmethod
    def start_command() -> str:
        return "lora_mode command"

    @staticmethod
    def get_help() -> str:
        return "help"


class FskShellCommands:
    """Shell commands for FSK/GFSK configuration via Cat-Shell port."""

    @staticmethod
    def set_freq(frequency_hz: int) -> str:
        return f"fsk_freq {frequency_hz}"

    @staticmethod
    def set_bitrate(bitrate_bps: int) -> str:
        return f"fsk_bitrate {bitrate_bps}"

    @staticmethod
    def set_fdev(fdev_hz: int) -> str:
        return f"fsk_fdev {fdev_hz}"

    @staticmethod
    def set_bw(bandwidth_khz: int) -> str:
        return f"fsk_bw {bandwidth_khz}"

    @staticmethod
    def set_power(tx_power_dbm: int) -> str:
        return f"fsk_power {tx_power_dbm}"

    @staticmethod
    def set_preamble(preamble_len: int) -> str:
        return f"fsk_preamble {preamble_len}"

    @staticmethod
    def set_syncword(hex_str: str) -> str:
        return f"fsk_syncword {hex_str}"

    @staticmethod
    def set_crc(enabled: bool) -> str:
        return f"fsk_crc {'on' if enabled else 'off'}"

    @staticmethod
    def set_whitening(enabled: bool) -> str:
        return f"fsk_whitening {'on' if enabled else 'off'}"

    @staticmethod
    def set_pktlen(fixed: bool) -> str:
        return f"fsk_pktlen {'fixed' if fixed else 'variable'}"

    @staticmethod
    def set_payload_len(length: int) -> str:
        return f"fsk_payload {length}"

    @staticmethod
    def set_bt(bt_value: str) -> str:
        return f"fsk_bt {bt_value}"

    @staticmethod
    def set_modulation(mode: str) -> str:
        return f"modulation {mode}"

    @staticmethod
    def get_config() -> str:
        return "fsk_config"

    @staticmethod
    def apply_config() -> str:
        return "fsk_apply"

    @staticmethod
    def start_streaming() -> str:
        return "lora_mode stream"

    @staticmethod
    def start_command() -> str:
        return "lora_mode command"


class SnifferSx:
    """SX1262 LoRa sniffer protocol handler - Updated for new FW output format."""

    # Regex patterns for different RX formats
    _RX_PATTERN = re.compile(
        r"(?:LORA\s+)?RX:\s*(.*?)\s*\|\s*RSSI:\s*(-?\d+)\s*\|\s*SNR:\s*(-?\d+)",
        re.ASCII | re.IGNORECASE,
    )

    _FSK_PATTERN = re.compile(
        r"FSK\s+RX:\s*(.*?)\s*\|\s*RSSI:\s*(-?\d+)\s*\|\s*Len:\s*(\d+)",
        re.ASCII | re.IGNORECASE,
    )

    class Commands(LoRaShellCommands):
        """Shell commands for LoRa configuration."""

        pass

    class Packet:
        """
        LoRa packet parsed from the ASCII line emitted by the RP2040 firmware.
        Supports both LORA RX and FSK RX formats.
        """

        def __init__(
            self,
            packet_input,
            context=None,
        ):
            if context is None:
                context = {
                    "frequency": 915000000,
                    "bandwidth": 125,
                    "spread_factor": 7,
                    "coding_rate": 5,
                }

            self.context = context
            self.payload = b""
            self.length = 0
            self.rssi = 0.0
            self.snr = 0.0
            self.pcap = None
            self.raw_line = None
            self.is_fsk = False

            # Accept bytes or str
            if isinstance(packet_input, (bytes, bytearray)):
                try:
                    as_str = packet_input.decode("ascii", errors="ignore")
                except Exception:
                    as_str = ""
                self._dissect_text(as_str)
            elif isinstance(packet_input, str):
                self._dissect_text(packet_input)
            else:
                raise ValueError(f"Unsupported packet_input type: {type(packet_input)}")

        def _dissect_text(self, line: str) -> None:
            """Parse the ASCII line emitted by the firmware."""
            self.raw_line = line.strip()

            # Try FSK pattern first
            m = SnifferSx._FSK_PATTERN.search(line)
            if m:
                self.is_fsk = True
                hex_str_raw = m.group(1).replace(" ", "")
                rssi_int = int(m.group(2))
                length = int(m.group(3))

                # Clean hex string
                if "..." in hex_str_raw:
                    hex_str_raw = hex_str_raw.split("...")[0]
                hex_clean = "".join(
                    c for c in hex_str_raw if c.lower() in "0123456789abcdef"
                )
                if len(hex_clean) % 2 != 0:
                    hex_clean = hex_clean[:-1]

                try:
                    self.payload = bytes.fromhex(hex_clean)
                except ValueError:
                    self.payload = b""

                self.length = len(self.payload)
                self.rssi = float(rssi_int)
                self.snr = 0.0  # FSK no tiene SNR en este formato

                self._build_pcap()
                return

            # Try LoRa pattern
            m = SnifferSx._RX_PATTERN.search(line)
            if m:
                hex_str_raw = m.group(1).replace(" ", "")
                rssi_int = int(m.group(2))
                snr_int = int(m.group(3))

                if "..." in hex_str_raw:
                    hex_str_raw = hex_str_raw.split("...")[0]
                hex_clean = "".join(
                    c for c in hex_str_raw if c.lower() in "0123456789abcdef"
                )
                if len(hex_clean) % 2 != 0:
                    hex_clean = hex_clean[:-1]

                try:
                    self.payload = bytes.fromhex(hex_clean)
                except ValueError:
                    self.payload = b""

                self.length = len(self.payload)
                self.rssi = float(rssi_int)
                self.snr = float(snr_int)

                self._build_pcap()
                return

            raise ValueError(f"Line does not match any RX pattern: {line!r}")

        def _build_pcap(self) -> None:
            """
            Build a PCAP record for Wireshark's LoRa dissector (link-type 148).
            """
            freq_mhz = self.context["frequency"] // 1_000_000

            header = (
                b"\x00"  # version
                + self.length.to_bytes(2, "little")  # payload length
                + b"\x03\x00"  # interface ID
                + b"\x05"  # protocol
                + b"\x06"  # PHY
                + freq_mhz.to_bytes(4, "little")  # frequency MHz
                + self.context["bandwidth"].to_bytes(1, "little")
                + self.context["spread_factor"].to_bytes(1, "little")
                + self.context["coding_rate"].to_bytes(1, "little")
                + struct.pack("<f", self.rssi)
                + struct.pack("<f", self.snr)
            )

            pcap_record = Pcap(header + self.payload, time.time())
            self.pcap = pcap_record.get_pcap()

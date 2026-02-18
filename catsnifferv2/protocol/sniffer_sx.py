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
    def set_bw(bandwidth_khz: int) -> str:
        return f"lora_bw {bandwidth_khz}"

    @staticmethod
    def set_cr(coding_rate: int) -> str:
        return f"lora_cr {coding_rate}"

    @staticmethod
    def set_power(tx_power_dbm: int) -> str:
        return f"lora_power {tx_power_dbm}"

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
    def get_help() -> str:
        return "help"


class SnifferSx:
    """SX1262 LoRa sniffer protocol handler."""

    # ── Regex for the text line the RP2040 firmware emits on Cat-LoRa ──────
    # Format produced by lora_rx_cb() in main.c:
    #   "RX: <HEX_PAYLOAD>[...] | RSSI: <int> | SNR: <int>\r\n"
    #
    # Notes:
    #  • Payload may be truncated with "..." if > 40 bytes
    #  • RSSI is int16 (dBm), SNR is int8 (dB) — both signed integers
    #  • The regex is intentionally lenient about whitespace
    _RX_PATTERN = re.compile(
        r"RX:\s*([0-9A-Fa-f.]+?)\s*\|\s*RSSI:\s*(-?\d+)\s*\|\s*SNR:\s*(-?\d+)",
        re.ASCII,
    )

    class Commands:
        """Shell commands for LoRa configuration."""

        def set_freq(self, frequency_hz: int) -> str:
            return LoRaShellCommands.set_freq(frequency_hz)

        def set_bw(self, bandwidth_khz: int) -> str:
            return LoRaShellCommands.set_bw(bandwidth_khz)

        def set_sf(self, spreading_factor: int) -> str:
            return LoRaShellCommands.set_sf(spreading_factor)

        def set_cr(self, coding_rate: int) -> str:
            return LoRaShellCommands.set_cr(coding_rate)

        def set_power(self, tx_power_dbm: int) -> str:
            return LoRaShellCommands.set_power(tx_power_dbm)

        def set_mode(self, mode: str) -> str:
            return LoRaShellCommands.set_mode(mode)

        def get_config(self) -> str:
            return LoRaShellCommands.get_config()

        def apply(self) -> str:
            return LoRaShellCommands.apply_config()

        def start_streaming(self) -> str:
            return LoRaShellCommands.set_mode("stream")

        def start_command(self) -> str:
            return LoRaShellCommands.set_mode("command")

    # ── Packet ───────────────────────────────────────────────────────────────

    class Packet:
        """
        LoRa packet parsed from the ASCII line emitted by the RP2040 firmware.

        The firmware's lora_rx_cb() writes to CDC1 (Cat-LoRa) as:
            RX: <HEX>[...] | RSSI: <int> | SNR: <int>\r\n

        This class accepts that raw line (bytes or str), extracts the fields,
        and builds a PCAP record compatible with Wireshark's LoRa dissector
        (link-type 148).

        For backward compatibility it also accepts the old binary frame format
        (starts with START_OF_FRAME bytes) — those are passed through to the
        legacy dissect path.
        """

        def __init__(
            self,
            packet_input,
            context=None,
        ):
            if context is None:
                context = {
                    "frequency":     915000000,
                    "bandwidth":     125,
                    "spread_factor": 7,
                    "coding_rate":   5,
                }

            self.context  = context
            self.payload  = b""
            self.length   = 0
            self.rssi     = 0.0
            self.snr      = 0.0
            self.pcap     = None
            self.raw_line = None   # the original ASCII line, if text format

            # Accept bytes or str
            if isinstance(packet_input, (bytes, bytearray)):
                # Check if it looks like the text format
                try:
                    as_str = packet_input.decode("ascii", errors="ignore")
                except Exception:
                    as_str = ""

                if "RX:" in as_str:
                    self._dissect_text(as_str)
                else:
                    # Legacy binary format
                    self._dissect_binary(packet_input)
            elif isinstance(packet_input, str):
                self._dissect_text(packet_input)
            else:
                raise ValueError(f"Unsupported packet_input type: {type(packet_input)}")

        # ── Text-format parser ────────────────────────────────────────────

        def _dissect_text(self, line: str) -> None:
            """
            Parse the ASCII line emitted by lora_rx_cb() in main.c.

            Example:
                "RX: 486F6C61 4D756E64 6F202330 | RSSI: -45 | SNR: 8\r\n"
            """
            self.raw_line = line.strip()

            m = SnifferSx._RX_PATTERN.search(line)
            if not m:
                raise ValueError(f"Line does not match RX pattern: {line!r}")

            hex_str  = m.group(1).replace(" ", "").replace(".", "")
            rssi_int = int(m.group(2))
            snr_int  = int(m.group(3))

            # If the firmware truncated the payload with "..." we only have
            # the first 40 bytes — that is still useful metadata for Wireshark.
            try:
                # Remove any trailing dots (truncation marker)
                hex_clean = hex_str.rstrip(".")
                if len(hex_clean) % 2 != 0:
                    hex_clean = hex_clean[:-1]  # drop incomplete nibble
                self.payload = bytes.fromhex(hex_clean)
            except ValueError:
                self.payload = b""

            self.length = len(self.payload)
            self.rssi   = float(rssi_int)
            self.snr    = float(snr_int)

            self._build_pcap()

        # ── Binary / legacy format parser ─────────────────────────────────

        def _dissect_binary(self, packet_bytes: bytes) -> None:
            """
            Parse the original binary frame format (START_OF_FRAME header).

            Frame layout (little-endian):
              Offset  Size  Field
                 0      2   SOF marker
                 2      2   (reserved / frame type)
                 4      2   payload length
                 6      N   payload
                -10     4   RSSI (float32)
                 -6     4   SNR  (float32)
            """
            clean = packet_bytes.replace(b"\r\n", b"")

            if len(clean) < 16:
                raise ValueError(
                    f"Binary frame too short: {len(clean)} bytes"
                )

            (_, _, self.length) = struct.unpack_from("<HHH", clean)
            self.payload        = clean[6:-10]
            self.rssi           = struct.unpack_from("<f", clean[-10:])[0]
            self.snr            = struct.unpack_from("<f", clean[-6:])[0]

            self._build_pcap()

        # ── PCAP record builder ───────────────────────────────────────────

        def _build_pcap(self) -> None:
            """
            Build a PCAP record for Wireshark's LoRa dissector (link-type 148).

            Record header layout (all little-endian):
              1 B  version
              2 B  payload length
              2 B  interface ID (0x0003)
              1 B  protocol  (0x05)
              1 B  PHY       (0x06)
              4 B  frequency in MHz
              1 B  bandwidth (kHz: 125/250/500)
              1 B  spreading factor
              1 B  coding rate
              4 B  RSSI (float32)
              4 B  SNR  (float32)
              N B  payload
            """
            freq_mhz = self.context["frequency"] // 1_000_000

            header = (
                b"\x00"                                             # version
                + self.length.to_bytes(2, "little")                 # payload length
                + b"\x03\x00"                                       # interface ID
                + b"\x05"                                           # protocol
                + b"\x06"                                           # PHY
                + freq_mhz.to_bytes(4, "little")                    # frequency MHz
                + self.context["bandwidth"].to_bytes(1, "little")
                + self.context["spread_factor"].to_bytes(1, "little")
                + self.context["coding_rate"].to_bytes(1, "little")
                + struct.pack("<f", self.rssi)
                + struct.pack("<f", self.snr)
            )

            pcap_record = Pcap(header + self.payload, time.time())
            self.pcap = pcap_record.get_pcap()
import struct
import time
from .common import *


class LoRaShellCommands:
    """Shell commands for LoRa configuration via Cat-Shell port."""

    @staticmethod
    def set_freq(frequency_hz: int) -> str:
        """Set frequency in Hz (e.g., 915000000)."""
        return f"lora_freq {frequency_hz}"

    @staticmethod
    def set_sf(spreading_factor: int) -> str:
        """Set spreading factor (7-12)."""
        return f"lora_sf {spreading_factor}"

    @staticmethod
    def set_bw(bandwidth_khz: int) -> str:
        """Set bandwidth in kHz (125, 250, 500)."""
        return f"lora_bw {bandwidth_khz}"

    @staticmethod
    def set_cr(coding_rate: int) -> str:
        """Set coding rate (5-8)."""
        return f"lora_cr {coding_rate}"

    @staticmethod
    def set_power(tx_power_dbm: int) -> str:
        """Set TX power in dBm."""
        return f"lora_power {tx_power_dbm}"

    @staticmethod
    def set_mode(mode: str) -> str:
        """Set mode: 'stream' or 'command'."""
        return f"lora_mode {mode}"

    @staticmethod
    def get_config() -> str:
        """Get current LoRa configuration."""
        return "lora_config"

    @staticmethod
    def apply_config() -> str:
        """Apply pending configuration changes."""
        return "lora_apply"

    @staticmethod
    def get_status() -> str:
        """Get device status."""
        return "status"

    @staticmethod
    def get_help() -> str:
        """Get available commands."""
        return "help"


class SnifferSx:
    """SX1262 LoRa sniffer protocol handler."""

    class Commands:
        """Shell commands for LoRa configuration."""

        def __init__(self):
            pass

        def set_freq(self, frequency_hz: int) -> str:
            """Set frequency in Hz."""
            return LoRaShellCommands.set_freq(frequency_hz)

        def set_bw(self, bandwidth_khz: int) -> str:
            """Set bandwidth in kHz."""
            return LoRaShellCommands.set_bw(bandwidth_khz)

        def set_sf(self, spreading_factor: int) -> str:
            """Set spreading factor."""
            return LoRaShellCommands.set_sf(spreading_factor)

        def set_cr(self, coding_rate: int) -> str:
            """Set coding rate."""
            return LoRaShellCommands.set_cr(coding_rate)

        def set_power(self, tx_power_dbm: int) -> str:
            """Set TX power."""
            return LoRaShellCommands.set_power(tx_power_dbm)

        def set_mode(self, mode: str) -> str:
            """Set stream or command mode."""
            return LoRaShellCommands.set_mode(mode)

        def get_config(self) -> str:
            """Get current configuration."""
            return LoRaShellCommands.get_config()

        def apply(self) -> str:
            """Apply pending configuration."""
            return LoRaShellCommands.apply_config()

        def start_streaming(self) -> str:
            """Start streaming mode."""
            return LoRaShellCommands.set_mode("stream")

        def start_command(self) -> str:
            """Start command mode."""
            return LoRaShellCommands.set_mode("command")

    class Packet:
        """LoRa packet parser."""

        def __init__(
            self,
            packet_bytes: bytes,
            context={
                "frequency": 915000000,
                "bandwidth": 125,
                "spread_factor": 7,
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

            # Convert frequency from Hz to MHz for PCAP
            freq_mhz = self.context["frequency"] // 1000000

            packet = (
                version
                + int(self.length).to_bytes(2, "little")
                + interfaceId
                + protocol
                + phy
                + int(freq_mhz).to_bytes(4, "little")
                + int(self.context["bandwidth"]).to_bytes(1, "little")
                + int(self.context["spread_factor"]).to_bytes(1, "little")
                + int(self.context["coding_rate"]).to_bytes(1, "little")
                + struct.pack("<f", self.rssi)
                + struct.pack("<f", self.snr)
                + self.payload
            )
            pcap_file = Pcap(packet, time.time())
            self.pcap = pcap_file.get_pcap()

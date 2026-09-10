import re
import struct
import time
from pathlib import Path

from .common import *


# pcap linktype 270 = LORATAP, a link type Wireshark can dissect natively
# (built-in packet-loratap.c), unlike the previous private/USER1 (148) format
# which Wireshark has no dissector for and just shows as raw "Packet" bytes.
LORATAP_DLT = 270

# loratap.channel.bandwidth is an enum, not the raw kHz value
_LORATAP_BANDWIDTH = {125: 1, 250: 2, 500: 4}

# loratap.syncword: 0x12 = private LoRa, 0x34 = LoRaWAN
_LORATAP_SYNCWORD = {"private": 0x12, "public": 0x34}

# Wireshark's LoRaTap dissector picks the payload dissector from the sync word
# in the header: `tshark -G decodes` shows a single default entry,
# "loratap.syncword 52 lorawan".  So anything captured on the LoRaWAN sync word
# (0x34, what --sync-word public sets) is handed to the LoRaWAN dissector, and
# a payload that is plain LoRa - Meshtastic, a RadioHead/LoRa.h sketch, a raw
# test frame - comes out as "LoRaWAN MAC Header malformed" rather than bytes.
# The sync word is a radio setting, not a protocol marker, so the fix is to
# override that mapping on the Wireshark command line instead of lying about
# the sync word in the header.
LORATAP_DECODE_AS_FIELD = "loratap.syncword"
LORAWAN_SYNCWORD = 0x34

# Wireshark's default columns assume an addressed link layer: Source and
# Destination stay empty for every LoRaTap frame, because a LoRa radio reports
# no addresses at all.  Info is empty too - the LoRaTap dissector never writes
# it, and neither does the payload dissector it hands the frame to - so a
# capture arrives with three blank columns and the payload only visible after
# clicking into a packet.  `loratap.payload` is a LoRaTap field, so it is
# populated whichever payload dissector `lora_decode_as_args` selects.
LORATAP_COLUMN_FORMAT = (
    '"No.","%m","Time","%t","Protocol","%p","Length","%L",'
    '"Info","%Cus:loratap.payload:0:R"'
)

# Wireshark renders a bytes field as hex, so the payload only reads as text
# through the postdissector shipped next to this module, which registers the
# same bytes as a string field.  Both halves have to agree on the field name.
LORATAP_ASCII_COLUMN = '"ASCII","%Cus:catnip_lora.ascii:0:R"'
LORATAP_ASCII_POSTDISSECTOR = Path(__file__).with_name("lora_ascii.lua")


def lora_wireshark_display_args() -> list:
    """Wireshark arguments that make the packet list readable at a glance.

    Replaces the default column set with one that fits LoRa: no Source and
    Destination columns, which a LoRa radio has nothing to put in, and the
    payload in an Info column as hex and an ASCII column as text.  The override
    lives on the command line, so the user's own saved column layout is
    untouched.  Accepted by both ``wireshark`` and ``tshark``.

    The ASCII column comes from a Lua postdissector, which a build that did not
    ship the script - or a Wireshark compiled without Lua - cannot load, so the
    column is only asked for when the script is actually there.
    """
    columns = LORATAP_COLUMN_FORMAT
    script_args = []

    if LORATAP_ASCII_POSTDISSECTOR.is_file():
        columns += f",{LORATAP_ASCII_COLUMN}"
        script_args = ["-X", f"lua_script:{LORATAP_ASCII_POSTDISSECTOR}"]

    return ["-o", f"gui.column.format:{columns}"] + script_args


def lora_decode_as_args(dissect_as: str = "auto", sync_word="private") -> list:
    """Wireshark ``-d`` arguments that decide how the LoRa payload is dissected.

    ``auto``    - the default: catnip picks, from the sync word the capture was
                  made on.  A sniffer that is handed arbitrary LoRa traffic
                  cannot know whether a 0x34 payload is LoRaWAN, so it picks the
                  reading whose failure mode is harmless: raw bytes.  Guessing
                  the other way stamps a red "LoRaWAN MAC Header malformed" over
                  every plain-LoRa frame, which looks like a broken capture
                  rather than a dissector mismatch.
    ``data``    - never dissect as LoRaWAN, whatever the sync word.
    ``lorawan`` - dissect as LoRaWAN whatever sync word this capture uses, for a
                  LoRaWAN network (0x34, or a non-standard sync word).

    Returns an empty list when Wireshark's own defaults already do the right
    thing - every sync word except 0x34 - so the caller can always splice the
    result into a command line.  Accepted by both ``wireshark`` and ``tshark``.
    """
    mode = str(dissect_as).strip().lower()

    if mode not in ("auto", "data", "lorawan"):
        raise ValueError(
            f"Invalid dissect-as {dissect_as!r}: use 'auto', 'data' or 'lorawan'"
        )

    _, byte = normalize_syncword(sync_word)

    if mode == "lorawan":
        if byte == LORAWAN_SYNCWORD:
            return []  # already Wireshark's default mapping
        return ["-d", f"{LORATAP_DECODE_AS_FIELD}=={byte},lorawan"]

    # auto and data agree today, because 0x34 is the only mapping Wireshark
    # ships; ``data`` stays explicit so a capture keeps dissecting the same way
    # if that ever changes, and so scripts can state what they meant.
    if mode == "data" or byte == LORAWAN_SYNCWORD:
        return ["-d", f"{LORATAP_DECODE_AS_FIELD}=={LORAWAN_SYNCWORD},data"]

    return []


def normalize_syncword(syncword) -> tuple:
    """
    Validate a sync word and return ``(firmware_arg, loratap_byte)``.

    Accepts the two aliases the firmware knows (``private`` → 0x12,
    ``public`` → 0x34) or an arbitrary byte written as ``0xNN``/``NN``
    (e.g. 0x2B for Meshtastic).  The firmware parser at
    ``cmd_lora_syncword`` only recognises the ``0x`` prefix, so bare hex is
    normalised before being sent.

    Raises ValueError on anything else, including ``0x00``: the firmware
    uses ``lora_sync_word == 0`` as the sentinel for "derive from
    public_network", so it cannot express a literal zero sync word.
    """
    value = str(syncword).strip().lower()

    if value in _LORATAP_SYNCWORD:
        return value, _LORATAP_SYNCWORD[value]

    try:
        byte = int(value, 16)
    except ValueError:
        raise ValueError(
            f"Invalid sync word {syncword!r}: use 'private', 'public' or a hex byte like 0x2B"
        )

    if not 0 <= byte <= 0xFF:
        raise ValueError(f"Sync word 0x{byte:X} out of range: must fit in one byte")
    if byte == 0:
        raise ValueError(
            "Sync word 0x00 is not selectable: the firmware reads 0 as "
            "'use private/public' — pass 'private' or 'public' instead"
        )

    return f"0x{byte:02X}", byte


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
        """``private``, ``public`` or an arbitrary byte (``0xNN``)."""
        arg, _ = normalize_syncword(syncword)
        return f"lora_syncword {arg}"

    @staticmethod
    def set_preamble(symbols: int) -> str:
        symbols = int(symbols)
        if not 6 <= symbols <= 65535:
            raise ValueError(f"Preamble length {symbols} out of range (6-65535)")
        return f"lora_preamble {symbols}"

    @staticmethod
    def set_iq(iq: str) -> str:
        """``normal`` or ``inverted`` (LoRaWAN downlinks use inverted IQ)."""
        value = str(iq).strip().lower()
        if value not in ("normal", "inverted"):
            raise ValueError(f"Invalid IQ {iq!r}: must be 'normal' or 'inverted'")
        return f"lora_iq {value}"

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
            Build a PCAP record using Wireshark's built-in LoRaTap header
            (link-type 270), so frequency/bandwidth/SF/RSSI/SNR/sync word show
            up in the packet details pane instead of raw undissected bytes.
            """
            bandwidth_enum = _LORATAP_BANDWIDTH.get(self.context["bandwidth"], 1)
            try:
                _, sync_word = normalize_syncword(
                    self.context.get("sync_word", "private")
                )
            except ValueError:
                sync_word = _LORATAP_SYNCWORD["private"]

            # loratap.rssi.* are stored as (dBm + 139), clamped to a byte
            rssi_byte = max(0, min(255, round(self.rssi) + 139))
            # loratap.rssi.snr is stored as (dB * 4) in a signed byte
            snr_byte = max(-128, min(127, round(self.snr * 4))) & 0xFF

            header = (
                struct.pack(">BBH", 0, 0, 15)  # version, padding, header_length
                + struct.pack(
                    ">IBB",
                    self.context["frequency"],
                    bandwidth_enum,
                    self.context["spread_factor"],
                )
                + struct.pack(">BBBB", rssi_byte, rssi_byte, rssi_byte, snr_byte)
                + struct.pack(">B", sync_word)
            )

            pcap_record = Pcap(header + self.payload, time.time())
            self.pcap = pcap_record.get_pcap()

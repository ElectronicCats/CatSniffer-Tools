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
# RSSI and SNR are already in the LoRaTap header this module writes, so
# Wireshark's own dissector resolves them: `:R` renders the raw bytes back as
# "-42 dBm" and "9.0 dB", the same strings the details pane shows.  Link
# quality is the first thing a sniffing session is judged on - whether a frame
# arrived at the noise floor or from the bench next door - and reading it one
# packet at a time in the details pane defeats the point of a packet list.
# The SNR column is split out because only LoRa measures one: the SX1262
# reports FSK frames with an RSSI and nothing else, so the column would read
# "0.0 dB" down a whole FSK capture - a measurement the radio never took.
LORATAP_SNR_COLUMN = '"SNR","%Cus:loratap.rssi.snr:0:R"'
LORATAP_COLUMN_FORMAT = (
    '"No.","%m","Time","%t","Protocol","%p","Length","%L",'
    '"RSSI","%Cus:loratap.rssi.packet:0:R",' + LORATAP_SNR_COLUMN + ","
    '"Info","%Cus:loratap.payload:0:R"'
)

# Wireshark renders a bytes field as hex, so the payload only reads as text
# through the postdissector shipped next to this module, which registers the
# same bytes as a string field.  Both halves have to agree on the field name.
LORATAP_ASCII_COLUMN = '"ASCII","%Cus:catnip_lora.ascii:0:R"'
LORATAP_ASCII_POSTDISSECTOR = Path(__file__).with_name("lora_ascii.lua")


def lora_wireshark_display_args(snr: bool = True) -> list:
    """Wireshark arguments that make the packet list readable at a glance.

    Replaces the default column set with one that fits LoRa: no Source and
    Destination columns, which a LoRa radio has nothing to put in; RSSI and SNR
    from the LoRaTap header, so link quality reads down the list instead of one
    packet at a time; and the payload in an Info column as hex and an ASCII
    column as text.  The override lives on the command line, so the user's own
    saved column layout is untouched.  Accepted by both ``wireshark`` and
    ``tshark``.

    The ASCII column comes from a Lua postdissector, which a build that did not
    ship the script - or a Wireshark compiled without Lua - cannot load, so the
    column is only asked for when the script is actually there.

    ``snr=False`` drops the SNR column, for an FSK capture where the radio
    reports no such measurement.
    """
    columns = LORATAP_COLUMN_FORMAT
    if not snr:
        columns = columns.replace(f"{LORATAP_SNR_COLUMN},", "")
    script_args = []

    if LORATAP_ASCII_POSTDISSECTOR.is_file():
        columns += f",{LORATAP_ASCII_COLUMN}"
        script_args = ["-X", f"lua_script:{LORATAP_ASCII_POSTDISSECTOR}"]

    return ["-o", f"gui.column.format:{columns}"] + script_args


def lora_decode_as_args(sync_word="private") -> list:
    """Wireshark ``-d`` arguments that keep the LoRa payload readable.

    A sniffer that is handed arbitrary LoRa traffic cannot know whether a 0x34
    payload is LoRaWAN, so it picks the reading whose failure mode is harmless:
    raw bytes.  Guessing the other way stamps a red "LoRaWAN MAC Header
    malformed" over every plain-LoRa frame, which looks like a broken capture
    rather than a dissector mismatch.  A capture that really is LoRaWAN is one
    Wireshark "Decode As..." away from the LoRaWAN dissector, and nothing about
    the capture itself is lost.

    The rule follows from the sync word alone, which is why it is not a CLI
    option: a user who could set the two independently could only ever break
    their own capture.  Returns an empty list for every sync word except 0x34 -
    the only mapping Wireshark ships - so the caller can always splice the
    result into a command line.  Accepted by both ``wireshark`` and ``tshark``.
    """
    _, byte = normalize_syncword(sync_word)

    if byte == LORAWAN_SYNCWORD:
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


# The 21 RX bandwidths the SX1262 offers in (G)FSK mode, in kHz, spelled the way
# ``cmd_fsk_bw`` echoes them back.  The firmware maps whatever value it is given
# to an enum entry with a threshold ladder, so each of these strings round-trips
# to the entry it names — anything in between silently lands on a neighbour.
FSK_BANDWIDTHS = (
    "4.8",
    "5.8",
    "7.3",
    "9.7",
    "11.7",
    "14.6",
    "19.5",
    "23.4",
    "29.3",
    "39.0",
    "46.9",
    "58.6",
    "78.2",
    "93.8",
    "117.3",
    "156.2",
    "187.2",
    "234.3",
    "312.0",
    "373.6",
    "467.0",
)

# ``apply_fsk_config`` refuses a bandwidth narrower than the signal it is meant
# to receive — Carson's rule, bitrate + 2*fdev — and falls back to 187.2 kHz on
# its own.  It compares against the *nominal* enum value in kHz (FSK_BW_117_KHZ
# is 117, not 117.3), so the prediction here truncates the same way to reach the
# same verdict.
FSK_FALLBACK_BANDWIDTH = "187.2"


def fsk_bandwidth_is_wide_enough(bandwidth_khz, bitrate: int, fdev: int) -> bool:
    """Would the firmware accept this bandwidth, or override it silently?"""
    return int(float(bandwidth_khz)) * 1000 >= int(bitrate) + 2 * int(fdev)


def normalize_fsk_syncword(syncword) -> str:
    """Validate an FSK sync word and return it as bare uppercase hex.

    Where LoRa matches a single byte, the SX1262 matches up to 8 in FSK, and
    ``cmd_fsk_syncword`` reads them as one plain hex string.  Accepts the shapes
    a datasheet or a capture tends to use — ``2DD4``, ``0x2DD4``, ``2D:D4``,
    ``2D D4`` — and rejects what the firmware would otherwise take a silent
    guess at: it stops at the first non-hex character and keeps only the first
    8 bytes, so a typo turns into a sync word that never matches anything.
    """
    value = re.sub(r"[\s:_-]", "", str(syncword).strip())
    if value[:2].lower() == "0x":
        value = value[2:]

    if not value:
        raise ValueError("Empty sync word: pass hex bytes such as 2DD4")
    if any(c not in "0123456789abcdefABCDEF" for c in value):
        raise ValueError(f"Invalid sync word {syncword!r}: not hexadecimal")
    if len(value) % 2:
        raise ValueError(
            f"Invalid sync word {syncword!r}: {len(value)} hex digits is not a "
            "whole number of bytes"
        )
    if len(value) > 16:
        raise ValueError(
            f"Sync word {syncword!r} is {len(value) // 2} bytes: the SX1262 "
            "matches at most 8"
        )

    return value.upper()


def modulation_command(modulation: str) -> str:
    """``modulation lora|fsk``: the firmware's one-step switch-and-apply.

    Both ``switch_to_lora`` and ``switch_to_fsk`` stop whatever reception is in
    flight, reconfigure the modem from the stored settings and re-arm RX, so
    this is the only command that reliably lands the radio in a known
    modulation — a plain ``lora_apply`` after an FSK session is refused by the
    firmware, which cleared ``lora_initialized`` when it switched away.
    """
    value = str(modulation).strip().lower()
    if value not in ("lora", "fsk"):
        raise ValueError(f"Invalid modulation {modulation!r}: use 'lora' or 'fsk'")
    return f"modulation {value}"


def sx1262_band_command() -> str:
    """``band3``: point the RF switch at the SX1262 antenna path.

    The board's antenna is shared through a switch (``ctf1``/``ctf2``/``ctf3``)
    and the firmware boots it on ``GIG`` — the CC1352's 2.4 GHz port — so an
    SX1262 capture that never sends this configures the modem perfectly and
    then listens through the wrong antenna path: poor sensitivity, or nothing
    at all.  ``band3`` selects ``SUBGIG_2``, the SX1262 leg, which is what the
    firmware's own ``lora_test.py`` sends as part of its setup sequence.
    """
    return "band3"


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


class FskShellCommands:
    """Shell commands for (G)FSK configuration via the Cat-Shell port.

    One method per ``fsk_*`` command in ``shell_commands.c``; the ranges
    enforced here are the firmware's own, so a value it would reject never
    reaches the wire as a silently ignored setting.
    """

    @staticmethod
    def set_freq(frequency_hz: int) -> str:
        frequency_hz = int(frequency_hz)
        if not 137_000_000 <= frequency_hz <= 1_020_000_000:
            raise ValueError(f"Frequency {frequency_hz} Hz out of range (137-1020 MHz)")
        return f"fsk_freq {frequency_hz}"

    @staticmethod
    def set_bitrate(bitrate_bps: int) -> str:
        bitrate_bps = int(bitrate_bps)
        if not 600 <= bitrate_bps <= 300_000:
            raise ValueError(f"Bitrate {bitrate_bps} out of range (600-300000 bps)")
        return f"fsk_bitrate {bitrate_bps}"

    @staticmethod
    def set_fdev(fdev_hz: int) -> str:
        fdev_hz = int(fdev_hz)
        if not 600 <= fdev_hz <= 200_000:
            raise ValueError(f"Deviation {fdev_hz} out of range (600-200000 Hz)")
        return f"fsk_fdev {fdev_hz}"

    @staticmethod
    def set_bw(bandwidth_khz) -> str:
        """RX bandwidth in kHz, one of :data:`FSK_BANDWIDTHS`."""
        value = str(bandwidth_khz).strip()
        if value not in FSK_BANDWIDTHS:
            raise ValueError(
                f"Invalid FSK bandwidth {bandwidth_khz!r}: use one of "
                f"{', '.join(FSK_BANDWIDTHS)} kHz"
            )
        return f"fsk_bw {value}"

    @staticmethod
    def set_power(tx_power_dbm: int) -> str:
        tx_power_dbm = int(tx_power_dbm)
        if not -9 <= tx_power_dbm <= 22:
            raise ValueError(f"TX power {tx_power_dbm} out of range (-9 to 22 dBm)")
        return f"fsk_power {tx_power_dbm}"

    @staticmethod
    def set_preamble(length_bytes: int) -> str:
        """Preamble length in *bytes* — FSK counts bytes where LoRa counts symbols."""
        length_bytes = int(length_bytes)
        if not 0 <= length_bytes <= 65535:
            raise ValueError(f"Preamble {length_bytes} out of range (0-65535 bytes)")
        return f"fsk_preamble {length_bytes}"

    @staticmethod
    def set_syncword(syncword: str) -> str:
        """Up to 8 sync-word bytes as hex (e.g. ``2DD4`` for Meshtastic's FSK)."""
        return f"fsk_syncword {normalize_fsk_syncword(syncword)}"

    @staticmethod
    def set_crc(enabled: bool) -> str:
        return f"fsk_crc {'on' if enabled else 'off'}"

    @staticmethod
    def set_whitening(enabled: bool) -> str:
        return f"fsk_whitening {'on' if enabled else 'off'}"

    @staticmethod
    def set_pktlen(mode: str) -> str:
        """``variable`` reads the length from the header, ``fixed`` from --payload."""
        value = str(mode).strip().lower()
        if value not in ("fixed", "variable"):
            raise ValueError(f"Invalid packet length mode {mode!r}")
        return f"fsk_pktlen {value}"

    @staticmethod
    def set_payload(length: int) -> str:
        length = int(length)
        if not 1 <= length <= 255:
            raise ValueError(f"Payload length {length} out of range (1-255)")
        return f"fsk_payload {length}"

    @staticmethod
    def set_bt(shaping: str) -> str:
        """Gaussian filter BT — ``off`` is plain FSK, anything else is GFSK."""
        value = str(shaping).strip().lower()
        if value not in ("off", "0.3", "0.5", "0.7", "1.0"):
            raise ValueError(f"Invalid BT shaping {shaping!r}")
        return f"fsk_bt {value}"

    @staticmethod
    def get_config() -> str:
        return "fsk_config"

    @staticmethod
    def apply_config() -> str:
        return "fsk_apply"


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

    class FskCommands(FskShellCommands):
        """Shell commands for (G)FSK configuration."""

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
            if self.is_fsk:
                # LoRaTap's bandwidth, spreading factor and sync word describe a
                # LoRa modem, and an FSK frame was received by none of it.  They
                # go out as 0 — which the dissector renders as "Unknown" —
                # rather than as a LoRa setting the radio never used; frequency,
                # RSSI and the payload are real either way, and those are what a
                # capture is opened for.
                bandwidth_enum = 0
                spread_factor = 0
                sync_word = 0
            else:
                bandwidth_enum = _LORATAP_BANDWIDTH.get(self.context["bandwidth"], 1)
                spread_factor = self.context["spread_factor"]
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
                    spread_factor,
                )
                + struct.pack(">BBBB", rssi_byte, rssi_byte, rssi_byte, snr_byte)
                + struct.pack(">B", sync_word)
            )

            pcap_record = Pcap(header + self.payload, time.time())
            self.pcap = pcap_record.get_pcap()

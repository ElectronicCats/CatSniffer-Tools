import base64
import re
import time
from typing import Dict, List, Optional, Tuple

from modules.utils.output import console, print_success, print_error, print_info

# Third-party
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from protocol.sniffer_sx import SnifferSx

# Meshtastic is an optional dependency
try:
    from meshtastic import mesh_pb2, admin_pb2, telemetry_pb2

    MESHTASTIC_AVAILABLE = True
except ImportError:
    MESHTASTIC_AVAILABLE = False
    mesh_pb2 = None
    admin_pb2 = None
    telemetry_pb2 = None

DEFAULT_KEYS = [
    "1PG7OiApB1nwvP+rz05pAQ==",
    "mH4hwdawhY2v6yC+yHwUvA==",
    "bWe55jD4Z7F8qGqC14V3lA==",
    "1Wz30FmXvj+kL/a9wRYqGQ==",
    "Rz+H90c9Z9i6wH+D9Z8ZlA==",
    "M7M2S11W6gJ1GvD8oU+Szw==",
    "wZ7B1W+D/v7R0W8X8YvO8A==",
    "TiIdi8MJG+IRnIkS8iUZXRU+MHuGtuzEasOWXp4QndU=",
]

# CORRECTED: Correct sync word for Meshtastic
SYNC_WORD_MESHTASTIC = 0x2B

CHANNELS_PRESET = {
    "defcon33": {"sf": 7, "bw": 500, "cr": 5, "pl": 16},
    "ShortTurbo": {"sf": 7, "bw": 500, "cr": 5, "pl": 8},
    "ShortSlow": {"sf": 9, "bw": 250, "cr": 5, "pl": 8},
    "ShortFast": {"sf": 8, "bw": 250, "cr": 5, "pl": 8},
    "MediumSlow": {"sf": 10, "bw": 250, "cr": 5, "pl": 8},
    "MediumFast": {"sf": 9, "bw": 250, "cr": 5, "pl": 8},
    "LongSlow": {"sf": 12, "bw": 250, "cr": 5, "pl": 8},
    "LongFast": {"sf": 11, "bw": 250, "cr": 5, "pl": 8},
    "LongMod": {"sf": 11, "bw": 250, "cr": 6, "pl": 8},
    "VLongSlow": {"sf": 12, "bw": 125, "cr": 5, "pl": 8},
}


def msb2lsb(hexstr: str) -> str:
    return hexstr[6:8] + hexstr[4:6] + hexstr[2:4] + hexstr[0:2]


def extract_frame(raw: bytes) -> bytes:
    """
    Extracts the frame from the updated firmware output format.
    Supports both LORA RX and FSK RX.
    """
    try:
        as_str = raw.decode("ascii", errors="ignore").strip()

        # Pattern for LORA RX
        if "LORA RX:" in as_str:
            hex_match = re.search(r"LORA RX:\s*([0-9A-Fa-f\s]+)", as_str)
            if hex_match:
                hex_str = hex_match.group(1).replace(" ", "").split("...")[0]
                hex_clean = "".join(c for c in hex_str if c in "0123456789ABCDEFabcdef")
                if hex_clean and len(hex_clean) % 2 == 0:
                    return bytes.fromhex(hex_clean)

        # Pattern for FSK RX
        elif "FSK RX:" in as_str:
            hex_match = re.search(r"FSK RX:\s*([0-9A-Fa-f\s]+)", as_str)
            if hex_match:
                hex_str = hex_match.group(1).replace(" ", "").split("...")[0]
                hex_clean = "".join(c for c in hex_str if c in "0123456789ABCDEFabcdef")
                if hex_clean and len(hex_clean) % 2 == 0:
                    return bytes.fromhex(hex_clean)

        # Simple "RX:" format (legacy)
        elif "RX:" in as_str and "LORA" not in as_str and "FSK" not in as_str:
            hex_match = re.search(r"RX:\s*([0-9A-Fa-f\s]+)", as_str)
            if hex_match:
                hex_str = hex_match.group(1).replace(" ", "").split("...")[0]
                hex_clean = "".join(c for c in hex_str if c in "0123456789ABCDEFabcdef")
                if hex_clean and len(hex_clean) % 2 == 0:
                    return bytes.fromhex(hex_clean)
    except Exception:
        pass

    # Legacy binary format
    if raw.startswith(b"@S") and raw.endswith(b"@E\r\n"):
        try:
            length = int.from_bytes(raw[2:4], byteorder="big")
            return raw[4 : 4 + length]
        except Exception:
            pass

    return b""


def extract_fields(data: bytes) -> Dict[str, bytes]:
    """Extracts the fields from the Meshtastic packet"""
    if len(data) < 16:
        return {}
    return {
        "dest": data[0:4],
        "sender": data[4:8],
        "packet_id": data[8:12],
        "flags": data[12:13],
        "channel": data[13:14] if len(data) > 13 else b"\x00",
        "reserved": data[14:16] if len(data) > 15 else b"\x00\x00",
        "payload": data[16:],
    }


def decrypt(payload: bytes, key: bytes, sender: bytes, packet_id: bytes) -> bytes:
    """Decrypt payload with given key"""
    nonce = packet_id + b"\x00\x00\x00\x00" + sender + b"\x00\x00\x00\x00"
    cipher = Cipher(algorithms.AES(key), modes.CTR(nonce), backend=default_backend())
    return cipher.decryptor().update(payload)


def decode_protobuf(data: bytes, src: str, dst: str) -> Optional[str]:
    """Decode protobuf message"""
    pb = mesh_pb2.Data()
    try:
        pb.ParseFromString(data)
        if pb.portnum == 1:  # TEXT
            text = pb.payload.decode(errors="ignore")
            return f"[TEXT] {src} -> {dst}: {text}"
        elif pb.portnum == 3:  # POSITION
            pos = mesh_pb2.Position()
            pos.ParseFromString(pb.payload)
            return f"[POSITION] {src} -> {dst}: {pos.latitude_i * 1e-7}, {pos.longitude_i * 1e-7}"
        elif pb.portnum == 4:  # NODEINFO
            return decode_nodeinfo(pb.payload)
        elif pb.portnum == 5:  # ROUTING
            r = mesh_pb2.Routing()
            r.ParseFromString(pb.payload)
            return f"[ROUTING]\n{r}"
        elif pb.portnum == 6:  # ADMIN
            a = admin_pb2.AdminMessage()
            a.ParseFromString(pb.payload)
            return f"[ADMIN]\n{a}"
        elif pb.portnum == 67:  # TELEMETRY
            t = telemetry_pb2.Telemetry()
            t.ParseFromString(pb.payload)
            return f"[TELEMETRY]\n{t}"
        else:
            return f"[PORT {pb.portnum}] Raw: {pb.payload.hex()}"
    except Exception:
        return None


def decode_nodeinfo(data: bytes) -> str:
    """Decode NODEINFO protobuf"""
    info = mesh_pb2.User()
    info.ParseFromString(data)
    output = "[NODEINFO]\n"
    output += f"  ID         : {info.id}\n"
    output += f"  Long Name  : {info.long_name}\n"
    output += f"  Short Name : {info.short_name}\n"
    if info.macaddr:
        mac = ":".join(f"{b:02x}" for b in info.macaddr)
        output += f"  MAC Addr   : {mac}\n"
    output += f"  HW Model   : {info.hw_model}\n"
    if info.public_key:
        output += f"  Public Key : {info.public_key.hex()}\n"
    output += f"  Messaging  : {'Disabled' if info.is_unmessagable else 'Enabled'}"
    return output


def configure_meshtastic_radio(
    shell_port: str, freq_hz: int, preset: str = "LongFast"
) -> bool:
    """Configure radio parameters using the shell port with proper values for Meshtastic"""
    from modules.core.catnip import ShellConnection

    preset_config = CHANNELS_PRESET.get(preset, CHANNELS_PRESET["LongFast"])

    print_info(f"Configuring radio via shell port {shell_port}")
    print_info(f"Preset: {preset}, Freq: {freq_hz} Hz")

    try:
        shell = ShellConnection(shell_port)
        shell.connect()

        commands = [
            f"lora_freq {freq_hz}",
            f"lora_sf {preset_config['sf']}",
            f"lora_bw {preset_config['bw']}",
            f"lora_cr {preset_config['cr']}",
            f"lora_preamble {preset_config['pl']}",
            f"lora_syncword 0x{SYNC_WORD_MESHTASTIC:02X}",
            "lora_apply",
            "lora_mode stream",
        ]

        for cmd in commands:
            console.print(f"  > {cmd}")
            shell.send_command(cmd)
            time.sleep(0.1)

        print_info("Current LoRa configuration:")
        shell.send_command("lora_config")
        time.sleep(0.5)

        shell.disconnect()
        print_success("Radio configured successfully")
        return True
    except Exception as e:
        print_error(f"Failed to configure radio: {e}")
        return False

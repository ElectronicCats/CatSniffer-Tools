#!/usr/bin/env python3
"""
Meshtastic Offline Decoder
Decrypt and decode a hex-encoded Meshtastic packet
"""

import argparse
import base64
import sys
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from meshtastic import mesh_pb2, admin_pb2, telemetry_pb2


def parse_aes_key(key_str):
    """Parse AES key from base64 string"""
    if key_str.lower() in ["0", "nokey", "none", "ham"]:
        key_str = "AAAAAAAAAAAAAAAAAAAAAA=="
    return base64.b64decode(key_str)


def extract_fields(data_hex):
    """Extract fields from hex-encoded packet"""
    return {
        "dest": bytes.fromhex(data_hex[0:8]),
        "sender": bytes.fromhex(data_hex[8:16]),
        "packet_id": bytes.fromhex(data_hex[16:24]),
        "flags": bytes.fromhex(data_hex[24:26]),
        "channel": bytes.fromhex(data_hex[26:28]),
        "reserved": bytes.fromhex(data_hex[28:32]),
        "payload": bytes.fromhex(data_hex[32:]),
    }


def decrypt_packet(packet, key):
    """Decrypt Meshtastic packet payload"""
    # Interleaved nonce: PacketID (4) + 0000 + SenderID (4) + 0000
    nonce = (
        packet["packet_id"]
        + b"\x00\x00\x00\x00"
        + packet["sender"]
        + b"\x00\x00\x00\x00"
    )
    cipher = Cipher(algorithms.AES(key), modes.CTR(nonce), backend=default_backend())
    decryptor = cipher.decryptor()
    return decryptor.update(packet["payload"]) + decryptor.finalize()


def format_mac(mac_bytes):
    """Format MAC address"""
    return ":".join(f"{b:02x}" for b in mac_bytes)


def decode_nodeinfo(data):
    """Decode NODEINFO protobuf"""
    info = mesh_pb2.User()
    info.ParseFromString(data)
    output = "[NODEINFO]\n"
    output += f"  ID         : {info.id}\n"
    output += f"  Long Name  : {info.long_name}\n"
    output += f"  Short Name : {info.short_name}\n"
    if info.macaddr:
        output += f"  MAC Addr   : {format_mac(info.macaddr)}\n"
    output += f"  HW Model   : {info.hw_model}\n"
    if info.public_key:
        output += f"  Public Key : {info.public_key.hex()}\n"
    output += f"  Messaging  : {'Disabled' if info.is_unmessagable else 'Enabled'}"
    return output


def _try_decode_as_plain_text(data):
    """Try to decode raw bytes as UTF-8 plain text (no protobuf wrapper)."""
    try:
        text = data.decode("utf-8")
        # Must be printable enough to be considered valid text
        if text.isprintable() or all(c.isprintable() or c in "\n\r\t" for c in text):
            return text
    except UnicodeDecodeError:
        pass
    return None


def decode_protobuf(decrypted, source_id, dest_id):
    """Decode protobuf message. Falls back to plain-text detection if protobuf parsing fails."""
    data = mesh_pb2.Data()
    parsed_ok = False
    try:
        data.ParseFromString(decrypted)
        # ParseFromString can succeed even on garbage — validate portnum is non-zero
        if data.portnum != 0:
            parsed_ok = True
    except Exception:
        pass

    if not parsed_ok:
        # Fallback 1: try the raw bytes as plain-text (unencrypted open-channel packets)
        plain = _try_decode_as_plain_text(decrypted)
        if plain:
            label = (
                f"{source_id} -> {dest_id}"
                if dest_id == "ffffffff"
                else f"{source_id} -> {dest_id} (private)"
            )
            return f"[TEXT - UNENCRYPTED] {label}: {plain}"
        return f"INVALID PROTOBUF\n  Hint: try --key ham for open/unencrypted channels"

    if data.portnum == 1:  # TEXT
        text = data.payload.decode("utf-8", errors="replace")
        return (
            f"[TEXT] {source_id} -> {dest_id}: {text}"
            if dest_id == "ffffffff"
            else f"[TEXT] {source_id} -> {dest_id} (private): {text}"
        )
    elif data.portnum == 3:  # POSITION
        pos = mesh_pb2.Position()
        pos.ParseFromString(data.payload)
        return f"[POSITION] {source_id} -> {dest_id}: {pos.latitude_i * 1e-7}, {pos.longitude_i * 1e-7}"
    elif data.portnum == 4:  # NODEINFO
        return decode_nodeinfo(data.payload)
    elif data.portnum == 5:  # ROUTING
        r = mesh_pb2.Routing()
        r.ParseFromString(data.payload)
        return f"[ROUTING]\n{r}"
    elif data.portnum == 6:  # ADMIN
        a = admin_pb2.AdminMessage()
        a.ParseFromString(data.payload)
        return f"[ADMIN]\n{a}"
    elif data.portnum == 67:  # TELEMETRY
        t = telemetry_pb2.Telemetry()
        t.ParseFromString(data.payload)
        return f"[TELEMETRY]\n{t}"
    else:
        return f"[PORT {data.portnum}] Raw: {data.payload.hex()}"


class MeshtasticDecoder:
    """Meshtastic packet decoder class"""

    def __init__(self, key=None):
        """
        Initialize decoder with optional AES key

        Args:
            key: Base64-encoded AES key (or 'ham' for no encryption)
        """
        if key is None:
            key = "1PG7OiApB1nwvP+rz05pAQ=="
        self.key = parse_aes_key(key)

    def decode(self, hex_data):
        """
        Decode a hex-encoded Meshtastic packet.

        Tries decryption with the provided key first. If the result is not a valid
        protobuf, also attempts to parse the raw (unencrypted) payload as a fallback,
        which handles open/ham channels where no encryption is applied.

        Args:
            hex_data: Hex string of the packet (dest + sender + packet_id + flags + channel + reserved + payload)

        Returns:
            tuple: (decrypted_hex, decoded_message)
        """
        packet = extract_fields(hex_data)
        src = packet["sender"].hex()
        dst = packet["dest"].hex()

        # Attempt 1: decrypt with the configured key
        decrypted = decrypt_packet(packet, self.key)
        result = decode_protobuf(decrypted, src, dst)

        # Attempt 2: if decryption didn't produce a valid message, try the raw payload
        # (covers unencrypted / plain-text packets on open channels)
        if result.startswith("INVALID PROTOBUF") or result.startswith(
            "[TEXT - UNENCRYPTED]"
        ):
            raw_payload = packet["payload"]
            raw_result = decode_protobuf(raw_payload, src, dst)
            if not raw_result.startswith("INVALID PROTOBUF"):
                return raw_payload.hex(), raw_result

        return decrypted.hex(), result


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Decrypt and decode a hex-encoded Meshtastic packet captured from SDR or LoRa sniffer.",
        epilog="""Examples:
  catsniffer meshtastic decode -i fffffffff449ca274402870263...
  catsniffer meshtastic decode -i <hex> -k 1PG7OiApB1nwvP+rz05pAQ==
  catsniffer meshtastic decode -i <hex> -k ham   # For open channels
""",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Hex-encoded payload (raw packet data starting with dest, sender, etc.)",
    )
    parser.add_argument(
        "-k",
        "--key",
        required=False,
        default="1PG7OiApB1nwvP+rz05pAQ==",
        help="Base64-encoded AES key. Use 'ham' or 'nokey' for open channels",
    )

    args = parser.parse_args()

    try:
        decoder = MeshtasticDecoder(key=args.key)
        decrypted_hex, result = decoder.decode(args.input)

        print(f"Decrypted raw (hex): {decrypted_hex}")
        print(result)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

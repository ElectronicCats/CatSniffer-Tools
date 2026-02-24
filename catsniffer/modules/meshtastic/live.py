#!/usr/bin/env python3
"""
Meshtastic Live Decoder
Live decoder for Meshtastic packets from CatSniffer LoRa port

Kevin Leon @ Electronic Cats
"""

import argparse
import base64
import queue
import sys
import threading
import time

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from meshtastic import mesh_pb2, admin_pb2, telemetry_pb2

from modules.catsniffer import LoRaConnection

DEFAULT_KEYS = [
    "OEu8wB3AItGBvza4YSHh+5a3LlW/dCJ+nWr7SNZMsaE=",
    "6IzsaoVhx1ETWeWuu0dUWMLqItvYJLbRzwgTAKCfvtY=",
    "TiIdi8MJG+IRnIkS8iUZXRU+MHuGtuzEasOWXp4QndU=",
]

SYNC_WORLD = 0x2B

CHANNELS_PRESET = {
    "defcon33": {"sf": 7, "bw": 9, "cr": 5, "pl": 16},
    "ShortTurbo": {"sf": 7, "bw": 9, "cr": 5, "pl": 8},
    "ShortSlow": {"sf": 8, "bw": 8, "cr": 5, "pl": 8},
    "ShortFast": {"sf": 7, "bw": 8, "cr": 5, "pl": 8},
    "MediumSlow": {"sf": 10, "bw": 8, "cr": 5, "pl": 8},
    "MediumFast": {"sf": 9, "bw": 8, "cr": 5, "pl": 8},
    "LongSlow": {"sf": 12, "bw": 7, "cr": 5, "pl": 8},
    "LongFast": {"sf": 11, "bw": 8, "cr": 5, "pl": 8},
    "LongFast125": {"sf": 11, "bw": 7, "cr": 5, "pl": 8},
    "LongMod": {"sf": 11, "bw": 7, "cr": 8, "pl": 8},
    "VLongSlow": {"sf": 11, "bw": 7, "cr": 8, "pl": 8},
}


def msb2lsb(hexstr):
    """Convert MSB to LSB hex string"""
    return hexstr[6:8] + hexstr[4:6] + hexstr[2:4] + hexstr[0:2]


def extract_frame(raw):
    """Extract frame from raw data"""
    if not raw.startswith(b"@S") or not raw.endswith(b"@E\r\n"):
        raise ValueError("Invalid frame")
    length = int.from_bytes(raw[2:4], byteorder="big")
    return raw[4 : 4 + length]


def extract_fields(data):
    """Extract fields from frame data"""
    return {
        "dest": data[0:4],
        "sender": data[4:8],
        "packet_id": data[8:12],
        "flags": data[12:13],
        "payload": data[16:],
    }


def decrypt(payload, key, sender, packet_id):
    """Decrypt payload with given key"""
    nonce = packet_id + b"\x00\x00\x00\x00" + sender + b"\x00\x00\x00\x00"
    cipher = Cipher(algorithms.AES(key), modes.CTR(nonce), backend=default_backend())
    return cipher.decryptor().update(payload)


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


def decode_protobuf(data, src, dst):
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
            if a.HasField("peerSessionInitiation"):
                pk = a.peerSessionInitiation.pub_key
                return f"[KEY EXCHANGE DETECTED] Ephemeral pubkey: {pk.hex()}"
            return f"[ADMIN]\n{a}"
        elif pb.portnum == 67:  # TELEMETRY
            t = telemetry_pb2.Telemetry()
            t.ParseFromString(pb.payload)
            return f"[TELEMETRY]\n{t}"
        else:
            return f"[PORT {pb.portnum}] Raw: {pb.payload.hex()}"
    except:
        return None


def print_packet_info(fields, decrypted):
    """Print packet information"""
    print("\n========================= Packet Info =========================")
    print(
        f"Sender: {msb2lsb(fields['sender'].hex())} -> Destination: {msb2lsb(fields['dest'].hex())} PacketID: {msb2lsb(fields['packet_id'].hex())}"
    )
    flags = fields["flags"][0]
    print(f"Flags:   {chr(flags)}")
    print(f"╰──▶ Hop limit: {(flags >> 5) & 0b111}")
    print(f"╰──▶ Want ACK:  {(flags >> 4) & 1}")
    print(f"╰──▶ Via MQTT:  {(flags >> 3) & 1}")
    print(f"╰──▶ Hop Start: {flags & 0b111}")
    print("\n--- Raw Payload (Encrypted) ---")
    print(" ".join(f"{b:02X}" for b in fields["payload"]))
    print("\n--- First Valid Decrypted Protobuf (Hex) ---")
    print(" ".join(f"{b:02X}" for b in decrypted))


class MeshtasticLiveDecoder:
    """Live Meshtastic decoder using CatSniffer"""

    def __init__(self, port, baudrate=115200, keys=None):
        """
        Initialize live decoder

        Args:
            port: Serial port for LoRa device
            baudrate: Baud rate (default: 115200)
            keys: List of base64-encoded AES keys to try
        """
        self.port = port
        self.baudrate = baudrate
        self.keys = [base64.b64decode(k) for k in (keys or DEFAULT_KEYS)]
        self.rx_queue = queue.Queue()
        self.running = False
        self.lora = None
        self.thread = None

    def configure_radio(self, frequency, preset="LongFast", shell_port=None):
        """Configure radio parameters"""
        if self.lora is None:
            self.lora = LoRaConnection(self.port)
            self.lora.connect()

        preset_config = CHANNELS_PRESET.get(preset, CHANNELS_PRESET["LongFast"])

        if shell_port:
            from ..catsniffer import ShellConnection

            shell = ShellConnection(shell_port)
            shell.connect()

            # Map old BW indices (7=125, 8=250, 9=500) to kHz required by shell
            bw_map = {7: 125, 8: 250, 9: 500}
            bw_khz = bw_map.get(preset_config["bw"], 250)

            shell.send_command(f"lora_bw {bw_khz}")
            shell.send_command(f"lora_sf {preset_config['sf']}")
            shell.send_command(f"lora_cr {preset_config['cr']}")
            shell.send_command(f"lora_preamble {preset_config['pl']}")
            shell.send_command("lora_syncword 43")
            shell.send_command(f"lora_freq {frequency}")
            shell.send_command("lora_apply")
            shell.disconnect()
        else:
            self.lora.write(f"set_bw {preset_config['bw']}\r\n".encode())
            self.lora.write(f"set_sf {preset_config['sf']}\r\n".encode())
            self.lora.write(f"set_cr {preset_config['cr']}\r\n".encode())
            self.lora.write(f"set_pl {preset_config['pl']}\r\n".encode())
            self.lora.write(f"set_sw {SYNC_WORLD}\r\n".encode())
            self.lora.write(f"set_freq {frequency}\r\n".encode())
            self.lora.write(b"set_rx\r\n")

    def start(self):
        """Start receiving packets"""
        if self.lora is None:
            self.lora = LoRaConnection(self.port)
            self.lora.connect()

        self.running = True
        self.thread = threading.Thread(target=self._recv_worker, daemon=True)
        self.thread.start()

    def _recv_worker(self):
        """Worker thread for receiving data"""
        while self.running:
            try:
                data = self.lora.read()
                if data:
                    self.rx_queue.put(data)
            except Exception as e:
                if self.running:
                    print(f"[ERROR] {e}")

    def stop(self):
        """Stop receiving packets"""
        self.running = False
        if self.lora:
            try:
                self.lora.disconnect()
            except:
                pass
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1)

    def process_packets(self):
        """Process received packets"""
        while self.running:
            try:
                if not self.rx_queue.empty():
                    frame = self.rx_queue.get_nowait()
                    try:
                        raw = extract_frame(frame)
                        fields = extract_fields(raw)
                        for key in self.keys:
                            try:
                                decrypted = decrypt(
                                    fields["payload"],
                                    key,
                                    fields["sender"],
                                    fields["packet_id"],
                                )
                                decoded = decode_protobuf(
                                    decrypted,
                                    fields["sender"].hex(),
                                    fields["dest"].hex(),
                                )
                                if decoded:
                                    print_packet_info(fields, decrypted)
                                    print(f"[INFO] Decryption successful")
                                    print(decoded)
                                    break
                            except Exception:
                                continue
                    except Exception as e:
                        pass  # Not a valid frame
                else:
                    time.sleep(0.1)
            except KeyboardInterrupt:
                break


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Live Meshtastic decoder - Capture and decode Meshtastic packets in real-time",
        epilog="""
Examples:
  catsniffer meshtastic live -p /dev/ttyUSB1
  catsniffer meshtastic live -p COM3 -f 902 -ps LongFast
        """,
    )
    parser.add_argument(
        "-p",
        "--port",
        required=True,
        help="Serial port for CatSniffer LoRa device",
    )
    parser.add_argument(
        "-baud",
        "--baudrate",
        type=int,
        default=115200,
        help="Baudrate (default: 115200)",
    )
    parser.add_argument(
        "-f",
        "--frequency",
        type=float,
        default=902.0,
        help="Frequency in MHz (default: 902.0)",
    )
    parser.add_argument(
        "-ps",
        "--preset",
        choices=list(CHANNELS_PRESET.keys()),
        default="LongFast",
        help="Channel preset (default: LongFast)",
    )

    args = parser.parse_args()

    decoder = MeshtasticLiveDecoder(args.port, args.baudrate)

    freq_hz = int(args.frequency * 1_000_000)
    print(
        f"[*] Configuring radio: {args.frequency} MHz ({freq_hz} Hz), preset: {args.preset}"
    )
    decoder.configure_radio(freq_hz, args.preset)

    print("[*] Starting capture... Press Ctrl+C to stop")
    decoder.start()

    try:
        decoder.process_packets()
    except KeyboardInterrupt:
        print("\n[*] Shutting down...")
    finally:
        decoder.stop()


if __name__ == "__main__":
    main()

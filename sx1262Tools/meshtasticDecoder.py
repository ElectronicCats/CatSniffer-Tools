import threading
import catsniffer
import argparse
import queue
import base64
import sys
import time
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from meshtastic import mesh_pb2, admin_pb2, telemetry_pb2

DEFAULT_KEYS = [
    "OEu8wB3AItGBvza4YSHh+5a3LlW/dCJ+nWr7SNZMsaE=",
    "6IzsaoVhx1ETWeWuu0dUWMLqItvYJLbRzwgTAKCfvtY=",
    "TiIdi8MJG+IRnIkS8iUZXRU+MHuGtuzEasOWXp4QndU="
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
    "LongMod": {"sf": 11, "bw": 7, "cr": 8, "pl": 8},
    "VLongSlow": {"sf": 11, "bw": 7, "cr": 8, "pl": 8},
}

def hexlify(b):
    return b.hex().upper()

def msb2lsb(hexstr):
    return hexstr[6:8] + hexstr[4:6] + hexstr[2:4] + hexstr[0:2]

def extract_frame(raw):
    if not raw.startswith(b"@S") or not raw.endswith(b"@E\r\n"):
        raise ValueError("Invalid frame")
    length = int.from_bytes(raw[2:4], byteorder="big")
    return raw[4:4+length]

def extract_fields(data):
    return {
        "dest": data[0:4],
        "sender": data[4:8],
        "packet_id": data[8:12],
        "flags": data[12:13],
        "payload": data[16:],
    }

def decrypt(payload, key, sender, packet_id):
    nonce = packet_id + b"\x00\x00\x00\x00" + sender + b"\x00\x00\x00\x00"
    cipher = Cipher(algorithms.AES(key), modes.CTR(nonce), backend=default_backend())
    return cipher.decryptor().update(payload)

def format_mac(mac_bytes):
    return ":".join(f"{b:02x}" for b in mac_bytes)

def decode_nodeinfo(data):
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
    pb = mesh_pb2.Data()
    try:
        pb.ParseFromString(data)
        if pb.portnum == 1:
            text = pb.payload.decode(errors='ignore')
            return f"[TEXT] {src} -> {dst}: {text}"
        elif pb.portnum == 3:
            pos = mesh_pb2.Position()
            pos.ParseFromString(pb.payload)
            return f"[POSITION] {src} -> {dst}: {pos.latitude_i * 1e-7}, {pos.longitude_i * 1e-7}"
        elif pb.portnum == 4:
            return decode_nodeinfo(pb.payload)
        elif pb.portnum == 5:
            r = mesh_pb2.Routing()
            r.ParseFromString(pb.payload)
            return f"[ROUTING]\n{r}"
        elif pb.portnum == 6:
            a = admin_pb2.AdminMessage()
            a.ParseFromString(pb.payload)
            return f"[ADMIN]\n{a}"
        elif pb.portnum == 67:
            t = telemetry_pb2.Telemetry()
            t.ParseFromString(pb.payload)
            return f"[TELEMETRY]\n{t}"
        else:
            return f"[PORT {pb.portnum}] Raw: {pb.payload.hex()}"
    except:
        return None

def print_packet_info(fields, decrypted):
    print("\n========================= Packet Info =========================")
    print(f"Sender: {msb2lsb(fields['sender'].hex())} -> Destination: {msb2lsb(fields['dest'].hex())} PacketID: {msb2lsb(fields['packet_id'].hex())}")
    flags = fields['flags'][0]
    print(f"Flags:   {chr(flags)}")
    print(f"╰──▶ Hop limit: {(flags >> 5) & 0b111}")
    print(f"╰──▶ Want ACK:  {(flags >> 4) & 1}")
    print(f"╰──▶ Via MQTT:  {(flags >> 3) & 1}")
    print(f"╰──▶ Hop Start: {flags & 0b111}")
    print("\n--- Raw Payload (Encrypted) ---")
    print(" ".join(f"{b:02X}" for b in fields['payload']))
    print("\n--- First Valid Decrypted Protobuf (Hex) ---")
    print(" ".join(f"{b:02X}" for b in decrypted))

class Monitor(catsniffer.Catsniffer):
    def __init__(self, port, baudrate, rx_queue=queue.Queue()) -> None:
        super().__init__(port, baudrate)
        self.rx_queue = rx_queue
        self.running = True
        self.thread = None

    def start(self):
        self.open()
        self.thread = threading.Thread(target=self.__recv_worker, daemon=True)
        self.thread.start()

    def __recv_worker(self):
        while self.running:
            try:
                data = self.recv()
                if data:
                    self.rx_queue.put(data)
            except Exception as e:
                if self.running:
                    print(f"[ERROR] {e}")

    def stop(self):
        self.running = False
        try:
            super().close()
        except:
            pass
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", default=catsniffer.find_catsniffer_serial_port())
    parser.add_argument("-baud", "--baudrate", default=catsniffer.DEFAULT_BAUDRATE)
    parser.add_argument("-f", "--frequency", default=902)
    parser.add_argument("-ps", "--preset", choices=CHANNELS_PRESET.keys(), default="LongFast")
    args = parser.parse_args()

    rx_queue = queue.Queue()
    mon = Monitor(args.port, args.baudrate, rx_queue)
    mon.start()

    mon.transmit(f"set_bw {CHANNELS_PRESET[args.preset]['bw']}")
    mon.transmit(f"set_sf {CHANNELS_PRESET[args.preset]['sf']}")
    mon.transmit(f"set_cr {CHANNELS_PRESET[args.preset]['cr']}")
    mon.transmit(f"set_pl {CHANNELS_PRESET[args.preset]['pl']}")
    mon.transmit(f"set_sw {SYNC_WORLD}")
    mon.transmit(f"set_freq {args.frequency}")
    mon.transmit("set_rx")

    try:
        while True:
            if not rx_queue.empty():
                frame = rx_queue.get()
                try:
                    raw = extract_frame(frame)
                    fields = extract_fields(raw)
                    for key_b64 in DEFAULT_KEYS:
                        key = base64.b64decode(key_b64)
                        try:
                            decrypted = decrypt(fields['payload'], key, fields['sender'], fields['packet_id'])
                            decoded = decode_protobuf(decrypted, fields['sender'].hex(), fields['dest'].hex())
                            if decoded:
                                print_packet_info(fields, decrypted)
                                print(f"[INFO] Successfully decrypted using key: {key_b64}")
                                print(decoded)
                                break
                        except Exception:
                            continue
                except Exception as e:
                    print(f"[MSG] raw: {frame}")
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down gracefully...")
        mon.stop()
        sys.exit(0)

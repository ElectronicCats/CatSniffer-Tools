import threading
import catsniffer
import argparse
import queue
import base64
import sys
import time
from pprint import pprint
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

DEFAULT_MESHTASTIC_KEY = "OEu8wB3AItGBvza4YSHh+5a3LlW/dCJ+nWr7SNZMsaE="

CANDIDATE_KEYS = [
    "OEu8wB3AItGBvza4YSHh+5a3LlW/dCJ+nWr7SNZMsaE=",  # Key 1
    "6IzsaoVhx1ETWeWuu0dUWMLqItvYJLbRzwgTAKCfvtY=",  # Key 2
    "TiIdi8MJG+IRnIkS8iUZXRU+MHuGtuzEasOWXp4QndU="                      # Key 3
]

SYNC_WORLD = 0x2B

CHANNELS_PRESET = {
    "defcon33": {
        "sf": 7, 
        "bw": 9, 
        "cr": 5, 
        "pl": 16
    },
    "ShortTurbo": {
        "sf": 7,
        "bw": 9,
        "cr": 5,
        "pl": 8,
    },
    "ShortSlow": {
        "sf": 8,
        "bw": 8,
        "cr": 5,
        "pl": 8,
    },
    "ShortFast": {
        "sf": 7,
        "bw": 8,
        "cr": 5,
        "pl": 8,
    },
    "MediumSlow": {
        "sf": 10,
        "bw": 8,
        "cr": 5,
        "pl": 8,
    },
    "MediumFast": {
        "sf": 9,
        "bw": 8,
        "cr": 5,
        "pl": 8,
    },
    "LongSlow": {
        "sf": 12,
        "bw": 7,
        "cr": 5,
        "pl": 8,
    },
    "LongFast": {
        "sf": 11,
        "bw": 8,
        "cr": 5,
        "pl": 8,
    },
    "LongMod": {
        "sf": 11,
        "bw": 7,  # 125 kHz
        "cr": 8,
        "pl": 8,
    },
    "VLongSlow": {
        "sf": 11,
        "bw": 7,
        "cr": 8,
        "pl": 8,
    },
}

def extract_frame(raw):
    if not raw.startswith(b"@S") or not raw.endswith(b"@E\r\n"):
        raise ValueError("Invalid frame")

    payload_len = int.from_bytes(raw[2:4], byteorder="big")
    payload = raw[4 : 4 + payload_len]  # LoRa encrypted payload

    meta_start = 4 + payload_len
    modem_settings = raw[meta_start : meta_start + 8]
    rssi_info = raw[meta_start + 8 : meta_start + 14]

    return {
        "payload": payload,
        "modem_settings": modem_settings,
        "rssi": rssi_info,
    }


class MeshtasticDecoder:
    def __init__(self) -> None:
        self.default_key = DEFAULT_MESHTASTIC_KEY

    def hexToBinary(self, hex_string):
        return bytes.fromhex(hex_string)

    def msb2lsb(self, data):
        try:
            return (
                data[6]
                + data[7]
                + data[4]
                + data[5]
                + data[2]
                + data[3]
                + data[0]
                + data[1]
            )
        except Exception:
            return data

    def hexdump(self, data, width=16):
        hex_lines = []
        ascii_lines = []

        for i in range(0, len(data), width):
            chunk = data[i : i + width]
            hex_part = " ".join(f"{byte:02X}" for byte in chunk)
            ascii_part = "".join(
                chr(byte) if 32 <= byte <= 126 else "." for byte in chunk
            )
            hex_lines.append(hex_part.ljust(width * 3))
            ascii_lines.append(ascii_part)
        return "\n".join(f"{h}  {a}" for h, a in zip(hex_lines, ascii_lines))

    def print_header(self, packet):
        print(f"\n\n{'='*25} Packet Info {'='*25}")
        print(
            f"Sender: {self.msb2lsb(packet['sender'].hex())} -> Destination: {self.msb2lsb(packet['dest'].hex())} PacketID: {self.msb2lsb(packet['packetid'].hex())}"
        )
        flags_bit = packet["flags"][0]
        hop_limit = (flags_bit >> 5) & 0b111
        want_ack = (flags_bit >> 4) & 0b1
        via_mqtt = (flags_bit >> 3) & 0b1
        hop_start = flags_bit & 0b111
        print(f"Flags:\t {packet['flags'].decode('latin1')}")
        print(f"╰──▶ Hop limit: {hop_limit}")
        print(f"╰──▶ Want ACK:  {want_ack}")
        print(f"╰──▶ Via MQTT:  {via_mqtt}")
        print(f"╰──▶ Hop Start: {hop_start}")
    
    def print_decryption(self, decrypted, key_index):
        if decrypted:
            print(f"\n=== Attempt for channel #{key_index + 1} with Key #{key_index + 1} ===")
            print(self.hexdump(decrypted))
        else:
            print(f"\n=== Attempt for channel #{key_index + 1} with Key #{key_index + 1} ===")
            print("[ERROR] Could not decrypt with this key.")
    
    def validate_key(self, key):
        try:
            key_decoded = base64.b64decode(key, validate=True)
            key_len = len(key_decoded.hex())
            if (key_len == 32) or (key_len == 64):
                return True
            raise Exception("Key len not valid.")
        except Exception as e:
            print(f"[ERROR] {e}")
            return False

    def get_candidate_keys(self):
        keys = []
        for key_b64 in CANDIDATE_KEYS:
            try:
                keys.append(base64.b64decode(key_b64.encode("ascii")))
            except Exception as e:
                print(f"[ERROR] Invalid key: {key_b64} - {e}")
        return keys

    def extract_data(self, packet):
        mesh_packet = {
            "dest": self.hexToBinary(packet[0:8]),
            "sender": self.hexToBinary(packet[8:16]),
            "packetid": self.hexToBinary(packet[16:24]),
            "flags": self.hexToBinary(packet[24:26]),
            "channel": self.hexToBinary(packet[26:28]),
            "reserv": self.hexToBinary(packet[28:32]),
            "raw_data": self.hexToBinary(packet[32 : len(packet)]),
            "decrypted": "",
        }
        return mesh_packet

    def __decrypt_packet(self, packet):
        nonce = (
            packet["packetid"]
            + b"\x00\x00\x00\x00"
            + packet["sender"]
            + b"\x00\x00\x00\x00"
        )
        key = self.get_aeskey()
        cipher = Cipher(
            algorithm=algorithms.AES(key=key),
            mode=modes.CTR(nonce),
            backend=default_backend(),
        )
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(packet["raw_data"]) + decryptor.finalize()
        return decrypted

    def decrypt_all(self, raw_packet):
        results = []
        packet = self.extract_data(raw_packet)
        for i, key in enumerate(self.get_candidate_keys()):
            try:
                nonce = (
                    packet["packetid"]
                    + b"\x00\x00\x00\x00"
                    + packet["sender"]
                    + b"\x00\x00\x00\x00"
                )
                cipher = Cipher(
                    algorithm=algorithms.AES(key=key),
                    mode=modes.CTR(nonce),
                    backend=default_backend(),
                )
                decryptor = cipher.decryptor()
                decrypted = decryptor.update(packet["raw_data"]) + decryptor.finalize()
                results.append({
                    "key_index": i,
                    "packet": packet,
                    "decrypted": decrypted
                })
            except Exception as e:
                results.append({
                    "key_index": i,
                    "packet": packet,
                    "decrypted": None,
                    "error": str(e)
                })
        return results

    def show_details(self, packet):
        print(f"\n\n{'='*25} Packet Info {'='*25}")
        print(
            f"Sender: {self.msb2lsb(packet['sender'].hex())} -> Destination: {self.msb2lsb(packet['dest'].hex())} PacketID: {self.msb2lsb(packet['packetid'].hex())}"
        )
        flags_bit = packet["flags"][0]
        hop_limit = (flags_bit >> 5) & 0b111
        want_ack = (flags_bit >> 4) & 0b1
        via_mqtt = (flags_bit >> 3) & 0b1
        hop_start = flags_bit & 0b111
        print(f"Flags:\t {packet['flags'].decode('latin1')}")
        print(f"╰──▶ Hop limit: {hop_limit}")
        print(f"╰──▶ Want ACK:  {want_ack}")
        print(f"╰──▶ Via MQTT:  {via_mqtt}")
        print(f"╰──▶ Hop Start: {hop_start}")
        print("\n".join(
            " ".join(f"{b:02X}" for b in packet["decrypted"][i:i+16])
            for i in range(0, len(packet["decrypted"]), 16)
        ))


class Monitor(catsniffer.Catsniffer):
    def __init__(
        self, port, baudrate, rx_queue=queue.Queue(), show_prompt=True
    ) -> None:
        super().__init__(port, baudrate)
        self.cmd_char = "> "
        self.running = False
        self.show_prompt = show_prompt
        self.rx_queue = rx_queue
        self.prompt_session = PromptSession()
        self.worker_prompt = threading.Thread()
        self.worker_recv = threading.Thread()

    def __worker_recv(self):
        while self.running:
            try:
                data = self.recv()
                if data:
                    #print("[RAW]", data)  # <-- This will show you what you're really getting
                    self.rx_queue.put(data)
            except Exception as e:
                print(str(e))

    def __worker_prompt(self):
        with patch_stdout():
            while self.running:
                try:
                    text = self.prompt_session.prompt(self.cmd_char)
                    self.transmit(text)
                except (KeyboardInterrupt, EOFError):
                    self.running = False
                    break

    def prompt(self):
        self.running = True
        self.open()
        if self.show_prompt:
            self.worker_prompt = threading.Thread(target=self.__worker_prompt)
            self.worker_prompt.start()

        self.worker_recv = threading.Thread(target=self.__worker_recv)
        self.worker_recv.start()

    def close_prompt(self):
        self.running = False
        if self.show_prompt:
            self.worker_prompt.join(timeout=1)
        self.worker_recv.join(timeout=1)
        self.close()


if __name__ == "__main__":
    print(
        """
To use this tool, you must first flash your CatSniffer with the LoRa Sniffer firmware.
If you encounter any issues, make sure you are uploading the correct firmware version from the official release page:
    https://github.com/ElectronicCats/CatSniffer-Firmware/releases\n"""
    )
    parser = argparse.ArgumentParser(prog="MeshtasticDecoder")
    parser.add_argument(
        "-p", "--port", default=catsniffer.find_catsniffer_serial_port()
    )
    parser.add_argument("-baud", "--baudrate", default=catsniffer.DEFAULT_BAUDRATE)
    parser.add_argument(
        "-key",
        "--key",
        type=str,
        default=DEFAULT_MESHTASTIC_KEY,
        help="AES decryption key in base64 format.",
    )
    parser.add_argument("-prompt", "--prompt", default=True)
    parser.add_argument("-f", "--frequency", help="Band Frequency", default=902)
    parser.add_argument(
        "-ps",
        "--preset",
        help="Modem Preset",
        choices=[pres for pres in CHANNELS_PRESET.keys()],
        default="LongFast",
    )
    args = parser.parse_args()

    m_decoder = MeshtasticDecoder()
    m_decoder.validate_key(args.key)
    rx_queue = queue.Queue()
    mon = Monitor(args.port, args.baudrate, rx_queue, args.prompt)
    try:
        mon.prompt()
        mon.transmit(f"set_bw {CHANNELS_PRESET[args.preset]['bw']}\n")
        mon.transmit(f"set_sf {CHANNELS_PRESET[args.preset]['sf']}\n")
        mon.transmit(f"set_cr {CHANNELS_PRESET[args.preset]['cr']}\n")
        mon.transmit(f"set_pl {CHANNELS_PRESET[args.preset]['pl']}\n")
        mon.transmit(f"set_sw {SYNC_WORLD}\n")
        mon.transmit(f"set_freq {args.frequency}\n")
        mon.transmit("set_rx\n")
        while True:
            if not rx_queue.empty():
                data = rx_queue.get(timeout=2)
                if data:
                    if b"@S" in data:
                        try:
                            frame = extract_frame(data)
                            results = m_decoder.decrypt_all(frame["payload"].hex())
                            # Print metadata only once (from first result)
                            if results:
                                m_decoder.print_header(results[0]["packet"])

                            # Print each key result
                            for result in results:
                                m_decoder.print_decryption(result.get("decrypted"), result["key_index"])
                        except Exception as e:
                            print(f"[ERROR] Failed to decode frame: {e}")
                    # if b"@S" in data:
                    #     data = data[4:-4]
                    #     decrypted_dict = m_decoder.decrypt(data.hex())
                    #     if decrypted_dict:
                    #         m_decoder.show_details(decrypted_dict)
                rx_queue.task_done()
            time.sleep(0.1)
    except KeyboardInterrupt:
        mon.close_prompt()
        sys.exit(0)

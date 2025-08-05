import argparse
import base64
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from meshtastic import mesh_pb2, admin_pb2, telemetry_pb2

def parse_aes_key(key_str):
    if key_str.lower() in ["0", "nokey", "none", "ham"]:
        key_str = "AAAAAAAAAAAAAAAAAAAAAA=="
    return base64.b64decode(key_str)

def extract_fields(data_hex):
    return {
        "dest": bytes.fromhex(data_hex[0:8]),
        "sender": bytes.fromhex(data_hex[8:16]),
        "packet_id": bytes.fromhex(data_hex[16:24]),
        "flags": bytes.fromhex(data_hex[24:26]),
        "channel": bytes.fromhex(data_hex[26:28]),
        "reserved": bytes.fromhex(data_hex[28:32]),
        "payload": bytes.fromhex(data_hex[32:])
    }

def decrypt_packet(packet, key):
    nonce = packet["packet_id"] + b'\x00\x00\x00\x00' + packet["sender"] + b'\x00\x00\x00\x00'
    cipher = Cipher(algorithms.AES(key), modes.CTR(nonce), backend=default_backend())
    decryptor = cipher.decryptor()
    return decryptor.update(packet["payload"]) + decryptor.finalize()

def decode_protobuf(decrypted, source_id, dest_id):
    data = mesh_pb2.Data()
    try:
        data.ParseFromString(decrypted)
    except Exception:
        return "INVALID PROTOBUF"

    if data.portnum == 1:
        text = data.payload.decode("utf-8", errors="replace")
        return f"[TEXT] {source_id} -> {dest_id}: {text}" if dest_id == "ffffffff" else "[TEXT] PRIVATE MESSAGE"
    elif data.portnum == 3:
        pos = mesh_pb2.Position()
        pos.ParseFromString(data.payload)
        return f"[POSITION] {source_id} -> {dest_id}: {pos.latitude_i * 1e-7}, {pos.longitude_i * 1e-7}"
    elif data.portnum == 4:
        info = mesh_pb2.User()
        info.ParseFromString(data.payload)
        return f"[NODEINFO] {info}"
    elif data.portnum == 5:
        r = mesh_pb2.Routing()
        r.ParseFromString(data.payload)
        return f"[ROUTING] {r}"
    elif data.portnum == 6:
        a = admin_pb2.AdminMessage()
        a.ParseFromString(data.payload)
        return f"[ADMIN] {a}"
    elif data.portnum == 67:
        t = telemetry_pb2.Telemetry()
        t.ParseFromString(data.payload)
        return f"[TELEMETRY] {t}"
    else:
        return f"[PORT {data.portnum}] Raw: {data.payload.hex()}"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", required=True, help="Hex-encoded payload from SDR")
    parser.add_argument("-k", "--key", required=False, default="1PG7OiApB1nwvP+rz05pAQ==", help="Base64 AES key")
    args = parser.parse_args()

    key = parse_aes_key(args.key)
    packet = extract_fields(args.input)
    decrypted = decrypt_packet(packet, key)
    src = packet["sender"].hex()
    dst = packet["dest"].hex()
    print(f"Decrypted raw (hex): {decrypted.hex()}")
    result = decode_protobuf(decrypted, src, dst)
    print(result)

if __name__ == "__main__":
    main()
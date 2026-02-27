#!/usr/bin/env python3
"""
Meshtastic Live Decoder - Updated for Catsniffer FW with FSK support
"""

import argparse
import base64
import queue
import sys
import threading
import time
import re

from .core import (
    DEFAULT_KEYS,
    SYNC_WORD_MESHTASTIC,
    CHANNELS_PRESET,
    msb2lsb,
    extract_frame,
    extract_fields,
    decrypt,
    decode_protobuf,
    decode_nodeinfo,
    configure_meshtastic_radio
)
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from meshtastic import mesh_pb2, admin_pb2, telemetry_pb2
from modules.catsniffer import LoRaConnection, ShellConnection
from protocol.sniffer_sx import SnifferSx

def print_packet_info(fields, decrypted, key_index=None):
    """Print packet information"""
    print("\n" + "="*60)
    print(f"   Packet from {msb2lsb(fields['sender'].hex())} to {msb2lsb(fields['dest'].hex())}")
    print(f"   Packet ID: {msb2lsb(fields['packet_id'].hex())}")
    print(f"   Channel: {fields['channel'][0] if 'channel' in fields else 0}")
    
    flags = fields['flags'][0]
    print(f"   Flags: 0x{flags:02X}")
    print(f"     ├─ Hop limit: {(flags >> 5) & 0b111}")
    print(f"     ├─ Want ACK:  {(flags >> 4) & 1}")
    print(f"     ├─ Via MQTT:  {(flags >> 3) & 1}")
    print(f"     └─ Hop Start: {flags & 0b111}")
    
    if key_index is not None:
        print(f"      Decrypted with key #{key_index}")
    
    print("\n   Decrypted payload (hex):")
    print("   " + " ".join(f"{b:02X}" for b in decrypted[:32]))
    if len(decrypted) > 32:
        print("   ...")


class MeshtasticLiveDecoder:
    """Live Meshtastic decoder using CatSniffer (updated for FW with FSK)"""

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
        self.shell = None
        self.stats = {"total": 0, "decrypted": 0, "errors": 0}

    def configure_radio(self, frequency, preset="LongFast", shell_port=None):
        """Configure radio parameters using the shell port"""
        if shell_port is None:
            print("[ERROR] Shell port required for configuration")
            return False

        preset_config = CHANNELS_PRESET.get(preset, CHANNELS_PRESET["LongFast"])

        print(f"[*] Configuring radio via shell port {shell_port}")
        print(f"[*] Preset: {preset}, Freq: {frequency} Hz")

        try:
            self.shell = ShellConnection(shell_port)
            self.shell.connect()

            # Send configuration commands for new firmware
            commands = [
                f"lora_freq {frequency}",
                f"lora_sf {preset_config['sf']}",
                f"lora_bw {preset_config['bw']}",
                f"lora_cr {preset_config['cr']}",
                f"lora_preamble {preset_config['pl']}",
                f"lora_syncword 0x{SYNC_WORD_MESHTASTIC:02X}",  # CORREGIDO
                "lora_apply",
                "lora_mode stream"
            ]

            for cmd in commands:
                print(f"  > {cmd}")
                self.shell.send_command(cmd)
                time.sleep(0.1)

            # Verify configuration
            print("[*] Current LoRa configuration:")
            response = self.shell.send_command("lora_config")
            if response:
                print(response)

            self.shell.disconnect()
            print("[✓] Radio configured successfully")
            return True

        except Exception as e:
            print(f"[ERROR] Failed to configure radio: {e}")
            if self.shell:
                try:
                    self.shell.disconnect()
                except:
                    pass
            return False

    def start(self):
        """Start receiving packets"""
        if self.lora is None:
            self.lora = LoRaConnection(self.port)
            self.lora.connect()

        self.running = True
        self.thread = threading.Thread(target=self._recv_worker, daemon=True)
        self.thread.start()
        print("[*] Capture started. Press Ctrl+C to stop.")

    def _recv_worker(self):
        """Worker thread for receiving data"""
        last_ka = 0.0
        while self.running:
            try:
                # Keepalive to maintain radio semaphore
                now = time.time()
                if now - last_ka > 2.0:
                    try:
                        self.lora.connection.write(b"\x00")
                        self.lora.connection.flush()
                        last_ka = now
                    except Exception:
                        pass

                data = self.lora.readline()
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
                    self.stats["total"] += 1
                    
                    try:
                        raw = extract_frame(frame)
                        if not raw or len(raw) < 16:
                            continue
                            
                        fields = extract_fields(raw)
                        if not fields or len(fields.get("payload", b"")) == 0:
                            continue
                            
                        decrypted_success = False
                        for idx, key in enumerate(self.keys):
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
                                    print_packet_info(fields, decrypted, idx)
                                    print(decoded)
                                    self.stats["decrypted"] += 1
                                    decrypted_success = True
                                    break
                            except Exception:
                                continue
                                
                        if not decrypted_success:
                            # Intentar interpretar como texto plano (canales abiertos)
                            try:
                                raw_payload = fields["payload"]
                                plain_text = raw_payload.decode('utf-8', errors='ignore')
                                if plain_text.isprintable() and len(plain_text) > 0:
                                    print(f"[PLAIN] {fields['sender'].hex()}: {plain_text}")
                                    self.stats["decrypted"] += 1
                            except:
                                pass
                                
                    except Exception as e:
                        self.stats["errors"] += 1
                        
                else:
                    time.sleep(0.01)
                    
                # Mostrar estadísticas cada 100 paquetes
                if self.stats["total"] % 100 == 0 and self.stats["total"] > 0:
                    print(f"\r[*] Stats: {self.stats['total']} packets, "
                          f"{self.stats['decrypted']} decrypted, "
                          f"{self.stats['errors']} errors", end="", flush=True)
                          
            except KeyboardInterrupt:
                break


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Live Meshtastic decoder - Updated for Catsniffer FW",
        epilog="""
Examples:
  python live.py -p /dev/ttyUSB1
  python live.py -p COM3 -f 902 -ps LongFast -s /dev/ttyUSB2
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
        default=906.875,
        help="Frequency in MHz (default: 906.875)",
    )
    parser.add_argument(
        "-ps",
        "--preset",
        choices=list(CHANNELS_PRESET.keys()),
        default="LongFast",
        help="Channel preset (default: LongFast)",
    )
    parser.add_argument(
        "-s",
        "--shell-port",
        help="Shell port for configuration (if different from LoRa port)",
    )

    args = parser.parse_args()

    decoder = MeshtasticLiveDecoder(args.port, args.baudrate)

    freq_hz = int(args.frequency * 1_000_000)
    print(f"[*] Frequency: {args.frequency} MHz ({freq_hz} Hz), preset: {args.preset}")

    # Configurar radio si se proporciona puerto shell
    if args.shell_port:
        decoder.configure_radio(freq_hz, args.preset, args.shell_port)
    else:
        print("[WARNING] No shell port provided. Radio may need manual configuration.")

    decoder.start()

    try:
        decoder.process_packets()
    except KeyboardInterrupt:
        print("\n[*] Shutting down...")
    finally:
        decoder.stop()
        print(f"\n[*] Final stats: {decoder.stats}")


if __name__ == "__main__":
    main()
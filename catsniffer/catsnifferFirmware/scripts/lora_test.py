#!/usr/bin/env python3
"""
CatSniffer LoRa TX/RX Test Script
Tests communication between two CatSniffers and measures throughput.

Usage:
    python3 lora_test.py                    # Auto-detect devices
    python3 lora_test.py --tx /dev/X --rx /dev/Y  # Specify ports
    python3 lora_test.py --packets 100      # Number of test packets
    python3 lora_test.py --payload 50       # Payload size in bytes

Requirements:
    pip install pyusb pyserial
"""

import sys
import time
import argparse
import threading
import queue
from dataclasses import dataclass
from typing import Optional, List, Tuple

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("Error: pyserial not installed. Run: pip install pyserial")
    sys.exit(1)

try:
    import usb.core
    import usb.util
except ImportError:
    print("Error: pyusb not installed. Run: pip install pyusb")
    sys.exit(1)

CATSNIFFER_VID = 0x1209
CATSNIFFER_PID = 0xBABB


@dataclass
class CatSnifferDevice:
    """Represents a CatSniffer device."""

    device_id: int
    bridge_port: Optional[str]
    lora_port: Optional[str]
    shell_port: Optional[str]

    def __str__(self):
        return f"CatSniffer #{self.device_id}"


class LoRaTester:
    """LoRa TX/RX tester for CatSniffer devices."""

    def __init__(self, tx_device: CatSnifferDevice, rx_device: CatSnifferDevice):
        self.tx_device = tx_device
        self.rx_device = rx_device
        self.tx_shell: Optional[serial.Serial] = None
        self.tx_lora: Optional[serial.Serial] = None
        self.rx_shell: Optional[serial.Serial] = None
        self.rx_lora: Optional[serial.Serial] = None
        self.rx_queue = queue.Queue()
        self.rx_thread: Optional[threading.Thread] = None
        self.running = False

    def connect(self):
        """Connect to both devices."""
        print(f"\nConnecting to devices...")
        print(f"  TX Device: {self.tx_device}")
        print(f"    Shell: {self.tx_device.shell_port}")
        print(f"    LoRa:  {self.tx_device.lora_port}")
        print(f"  RX Device: {self.rx_device}")
        print(f"    Shell: {self.rx_device.shell_port}")
        print(f"    LoRa:  {self.rx_device.lora_port}")

        # Connect to TX device
        self.tx_shell = serial.Serial(self.tx_device.shell_port, 115200, timeout=2)
        self.tx_lora = serial.Serial(self.tx_device.lora_port, 115200, timeout=1)

        # Connect to RX device
        self.rx_shell = serial.Serial(self.rx_device.shell_port, 115200, timeout=2)
        self.rx_lora = serial.Serial(self.rx_device.lora_port, 115200, timeout=1)

        # Clear buffers
        for port in [self.tx_shell, self.tx_lora, self.rx_shell, self.rx_lora]:
            port.reset_input_buffer()
            port.reset_output_buffer()

        print("  Connected!")

    def disconnect(self):
        """Disconnect from devices."""
        self.running = False
        if self.rx_thread:
            self.rx_thread.join(timeout=2)

        for port in [self.tx_shell, self.tx_lora, self.rx_shell, self.rx_lora]:
            if port and port.is_open:
                port.close()

    def send_shell_command(
        self, port: serial.Serial, cmd: str, timeout: float = 1.0
    ) -> str:
        """Send command to shell and return response."""
        port.reset_input_buffer()
        port.write((cmd + "\r\n").encode("ascii"))
        port.flush()
        time.sleep(0.3)

        response = b""
        start = time.time()
        while time.time() - start < timeout:
            if port.in_waiting:
                response += port.read(port.in_waiting)
                time.sleep(0.05)
            else:
                if response:
                    break
                time.sleep(0.05)

        return response.decode("ascii", errors="ignore").strip()

    def configure_lora(
        self,
        frequency: int = 915000000,
        sf: int = 7,
        bw: int = 125,
        cr: int = 5,
        power: int = 20,
    ):
        """Configure both devices with same LoRa parameters."""
        print(f"\nConfiguring LoRa parameters:")
        print(f"  Frequency: {frequency/1e6:.1f} MHz")
        print(f"  Spreading Factor: SF{sf}")
        print(f"  Bandwidth: {bw} kHz")
        print(f"  Coding Rate: 4/{cr}")
        print(f"  TX Power: {power} dBm")

        for name, shell in [("TX", self.tx_shell), ("RX", self.rx_shell)]:
            # Set parameters
            self.send_shell_command(shell, f"lora_freq {frequency}")
            self.send_shell_command(shell, f"lora_sf {sf}")
            self.send_shell_command(shell, f"lora_bw {bw}")
            self.send_shell_command(shell, f"lora_cr {cr}")
            self.send_shell_command(shell, f"lora_power {power}")
            self.send_shell_command(shell, f"band3")

            # Apply configuration
            response = self.send_shell_command(shell, "lora_apply", timeout=2)
            if "successfully" in response.lower():
                print(f"  {name} device configured successfully")
            else:
                print(f"  {name} device configuration: {response}")

        # Switch both to stream mode for binary communication
        self.send_shell_command(self.tx_shell, "lora_mode stream")
        self.send_shell_command(self.rx_shell, "lora_mode stream")
        print("  Both devices set to STREAM mode")

    def _rx_thread_func(self):
        """Background thread to receive LoRa packets."""
        while self.running:
            try:
                if self.rx_lora.in_waiting:
                    # Read length byte
                    length_byte = self.rx_lora.read(1)
                    if length_byte:
                        length = length_byte[0]
                        if 0 < length <= 255:
                            # Read payload + RSSI + SNR
                            data = self.rx_lora.read(length + 2)
                            if len(data) >= length + 2:
                                payload = data[:length]
                                rssi = data[length] - 128
                                snr = data[length + 1] - 128
                                rx_time = time.time()
                                self.rx_queue.put((rx_time, payload, rssi, snr))
                else:
                    time.sleep(0.001)
            except Exception as e:
                if self.running:
                    print(f"RX Error: {e}")
                break

    def start_rx_thread(self):
        """Start the RX background thread."""
        self.running = True
        self.rx_thread = threading.Thread(target=self._rx_thread_func, daemon=True)
        self.rx_thread.start()

    def stop_rx_thread(self):
        """Stop the RX background thread."""
        self.running = False
        if self.rx_thread:
            self.rx_thread.join(timeout=2)

    def send_packet(self, payload: bytes) -> float:
        """Send a packet via TX device. Returns time taken."""
        start = time.time()
        self.tx_lora.write(payload)
        self.tx_lora.flush()
        return time.time() - start

    def run_ping_test(self, count: int = 10) -> dict:
        """Run a simple ping test to verify communication."""
        print(f"\n{'='*60}")
        print("PING TEST")
        print(f"{'='*60}")
        print(f"Sending {count} ping packets...")

        # Clear RX queue
        while not self.rx_queue.empty():
            self.rx_queue.get()

        self.start_rx_thread()
        time.sleep(0.5)  # Let RX stabilize

        sent = 0
        received = 0
        rssi_values = []
        snr_values = []
        rtts = []

        for i in range(count):
            # Create ping packet with sequence number
            seq = i.to_bytes(2, "big")
            payload = b"PING" + seq + b"\x00" * 10  # 16 bytes total

            tx_time = time.time()
            self.send_packet(payload)
            sent += 1

            # Wait for response (with timeout)
            try:
                rx_time, rx_payload, rssi, snr = self.rx_queue.get(timeout=3.0)
                if rx_payload[:4] == b"PING" and rx_payload[4:6] == seq:
                    received += 1
                    rtt = (rx_time - tx_time) * 1000  # ms
                    rtts.append(rtt)
                    rssi_values.append(rssi)
                    snr_values.append(snr)
                    print(
                        f"  [{i+1:3d}/{count}] OK  RSSI: {rssi:4d} dBm  SNR: {snr:3d} dB  RTT: {rtt:6.1f} ms"
                    )
                else:
                    print(f"  [{i+1:3d}/{count}] MISMATCH - got {rx_payload[:6].hex()}")
            except queue.Empty:
                print(f"  [{i+1:3d}/{count}] TIMEOUT")

            time.sleep(0.1)  # Brief pause between packets

        self.stop_rx_thread()

        # Calculate statistics
        loss = ((sent - received) / sent) * 100 if sent > 0 else 100
        avg_rssi = sum(rssi_values) / len(rssi_values) if rssi_values else 0
        avg_snr = sum(snr_values) / len(snr_values) if snr_values else 0
        avg_rtt = sum(rtts) / len(rtts) if rtts else 0

        results = {
            "sent": sent,
            "received": received,
            "loss_percent": loss,
            "avg_rssi": avg_rssi,
            "avg_snr": avg_snr,
            "avg_rtt_ms": avg_rtt,
            "min_rtt_ms": min(rtts) if rtts else 0,
            "max_rtt_ms": max(rtts) if rtts else 0,
        }

        print(f"\nPing Results:")
        print(f"  Packets: {received}/{sent} received ({loss:.1f}% loss)")
        print(f"  RSSI: {avg_rssi:.1f} dBm (avg)")
        print(f"  SNR:  {avg_snr:.1f} dB (avg)")
        if rtts:
            print(
                f"  RTT:  {avg_rtt:.1f} ms avg, {min(rtts):.1f} ms min, {max(rtts):.1f} ms max"
            )

        return results

    def run_throughput_test(
        self, packet_count: int = 50, payload_size: int = 50
    ) -> dict:
        """Run throughput test to measure data rate."""
        print(f"\n{'='*60}")
        print("THROUGHPUT TEST")
        print(f"{'='*60}")
        print(f"Sending {packet_count} packets of {payload_size} bytes each...")

        # Clear RX queue
        while not self.rx_queue.empty():
            self.rx_queue.get()

        self.start_rx_thread()
        time.sleep(0.5)

        sent = 0
        received = 0
        total_bytes_sent = 0
        total_bytes_received = 0
        rssi_values = []
        snr_values = []

        start_time = time.time()

        for i in range(packet_count):
            # Create payload with sequence number and padding
            seq = i.to_bytes(2, "big")
            padding = bytes([i % 256] * (payload_size - 2))
            payload = seq + padding

            self.send_packet(payload)
            sent += 1
            total_bytes_sent += len(payload)

            # Brief wait to not overwhelm
            time.sleep(0.05)

            # Check for any received packets (non-blocking)
            while not self.rx_queue.empty():
                try:
                    _, rx_payload, rssi, snr = self.rx_queue.get_nowait()
                    received += 1
                    total_bytes_received += len(rx_payload)
                    rssi_values.append(rssi)
                    snr_values.append(snr)
                except queue.Empty:
                    break

            # Progress indicator
            if (i + 1) % 10 == 0:
                print(f"  Sent: {i+1}/{packet_count}  Received: {received}")

        # Wait for remaining packets
        print("  Waiting for remaining packets...")
        wait_start = time.time()
        while time.time() - wait_start < 5.0:  # 5 second timeout
            try:
                _, rx_payload, rssi, snr = self.rx_queue.get(timeout=0.5)
                received += 1
                total_bytes_received += len(rx_payload)
                rssi_values.append(rssi)
                snr_values.append(snr)
            except queue.Empty:
                if received >= sent:
                    break
                continue

        end_time = time.time()
        self.stop_rx_thread()

        # Calculate statistics
        duration = end_time - start_time
        loss = ((sent - received) / sent) * 100 if sent > 0 else 100
        tx_throughput = (total_bytes_sent * 8) / duration if duration > 0 else 0  # bps
        rx_throughput = (
            (total_bytes_received * 8) / duration if duration > 0 else 0
        )  # bps
        packet_rate = sent / duration if duration > 0 else 0
        avg_rssi = sum(rssi_values) / len(rssi_values) if rssi_values else 0
        avg_snr = sum(snr_values) / len(snr_values) if snr_values else 0

        results = {
            "packets_sent": sent,
            "packets_received": received,
            "loss_percent": loss,
            "bytes_sent": total_bytes_sent,
            "bytes_received": total_bytes_received,
            "duration_sec": duration,
            "tx_throughput_bps": tx_throughput,
            "rx_throughput_bps": rx_throughput,
            "packet_rate_pps": packet_rate,
            "avg_rssi": avg_rssi,
            "avg_snr": avg_snr,
        }

        print(f"\nThroughput Results:")
        print(f"  Packets: {received}/{sent} received ({loss:.1f}% loss)")
        print(f"  Duration: {duration:.2f} seconds")
        print(
            f"  TX Throughput: {tx_throughput:.1f} bps ({tx_throughput/1000:.2f} kbps)"
        )
        print(
            f"  RX Throughput: {rx_throughput:.1f} bps ({rx_throughput/1000:.2f} kbps)"
        )
        print(f"  Packet Rate: {packet_rate:.1f} packets/sec")
        print(f"  RSSI: {avg_rssi:.1f} dBm (avg)")
        print(f"  SNR:  {avg_snr:.1f} dB (avg)")

        return results

    def run_sf_comparison(
        self, payload_size: int = 20, packets_per_sf: int = 10
    ) -> dict:
        """Compare throughput across different spreading factors."""
        print(f"\n{'='*60}")
        print("SPREADING FACTOR COMPARISON")
        print(f"{'='*60}")
        print(
            f"Testing SF7-SF12 with {packets_per_sf} packets of {payload_size} bytes each\n"
        )

        results = {}

        for sf in range(7, 13):
            print(f"\n--- Testing SF{sf} ---")

            # Reconfigure both devices
            self.configure_lora(sf=sf)
            time.sleep(0.5)

            # Run quick throughput test
            test_results = self.run_throughput_test(
                packet_count=packets_per_sf, payload_size=payload_size
            )
            results[f"SF{sf}"] = test_results

        # Print comparison summary
        print(f"\n{'='*60}")
        print("SPREADING FACTOR COMPARISON SUMMARY")
        print(f"{'='*60}")
        print(f"{'SF':<6} {'Loss %':<10} {'Throughput':<15} {'RSSI':<12} {'SNR':<10}")
        print("-" * 60)

        for sf in range(7, 13):
            key = f"SF{sf}"
            r = results[key]
            print(
                f"{key:<6} {r['loss_percent']:<10.1f} "
                f"{r['rx_throughput_bps']/1000:<15.2f} kbps "
                f"{r['avg_rssi']:<12.1f} dBm "
                f"{r['avg_snr']:<10.1f} dB"
            )

        return results


def find_all_catsniffers() -> List[CatSnifferDevice]:
    """Find all connected CatSniffer devices."""
    devices = []

    # Find USB devices
    usb_devices = list(
        usb.core.find(find_all=True, idVendor=CATSNIFFER_VID, idProduct=CATSNIFFER_PID)
    )

    if not usb_devices:
        return devices

    # Get serial ports
    all_ports = list(serial.tools.list_ports.comports())
    cat_ports = sorted(
        [p for p in all_ports if p.vid == CATSNIFFER_VID and p.pid == CATSNIFFER_PID],
        key=lambda x: x.device,
    )

    # Get interface names
    all_interfaces = []
    for dev in usb_devices:
        for cfg in dev:
            for intf in cfg:
                if intf.bInterfaceClass == 0x02:  # CDC Control
                    try:
                        name = (
                            usb.util.get_string(dev, intf.iInterface)
                            if intf.iInterface
                            else None
                        )
                    except:
                        name = None
                    all_interfaces.append(
                        {
                            "number": intf.bInterfaceNumber,
                            "name": name,
                            "bus": dev.bus,
                            "address": dev.address,
                        }
                    )

    # Match ports to devices (3 ports per device)
    for device_idx in range(len(usb_devices)):
        port_offset = device_idx * 3
        if port_offset + 2 < len(cat_ports):
            ports = {}
            for i in range(3):
                intf_idx = port_offset + i
                port_idx = port_offset + i

                if intf_idx < len(all_interfaces) and port_idx < len(cat_ports):
                    intf_name = all_interfaces[intf_idx]["name"] or f"Interface-{i}"
                    ports[intf_name] = cat_ports[port_idx].device

            devices.append(
                CatSnifferDevice(
                    device_id=device_idx + 1,
                    bridge_port=ports.get("Cat-Bridge"),
                    lora_port=ports.get("Cat-LoRa"),
                    shell_port=ports.get("Cat-Shell"),
                )
            )

    return devices


def main():
    parser = argparse.ArgumentParser(description="CatSniffer LoRa TX/RX Test")
    parser.add_argument(
        "--tx", type=str, help="TX device shell port (e.g., /dev/cu.usbmodem2105)"
    )
    parser.add_argument(
        "--rx", type=str, help="RX device shell port (e.g., /dev/cu.usbmodem2205)"
    )
    parser.add_argument(
        "--packets", type=int, default=50, help="Number of packets for throughput test"
    )
    parser.add_argument("--payload", type=int, default=50, help="Payload size in bytes")
    parser.add_argument("--sf", type=int, default=7, help="Spreading factor (7-12)")
    parser.add_argument("--freq", type=int, default=915000000, help="Frequency in Hz")
    parser.add_argument(
        "--compare-sf", action="store_true", help="Run SF comparison test"
    )
    parser.add_argument("--ping-only", action="store_true", help="Run only ping test")
    args = parser.parse_args()

    print("=" * 60)
    print("CATSNIFFER LORA TX/RX TEST")
    print("=" * 60)

    # Find devices
    if args.tx and args.rx:
        # Manual port specification - need to map shell ports to full device
        print("\nUsing manually specified ports...")
        # This is simplified - in production you'd want to detect the lora port too
        tx_device = CatSnifferDevice(
            device_id=1,
            bridge_port=None,
            lora_port=args.tx.replace("2105", "2103").replace("2205", "2203"),
            shell_port=args.tx,
        )
        rx_device = CatSnifferDevice(
            device_id=2,
            bridge_port=None,
            lora_port=args.rx.replace("2105", "2103").replace("2205", "2203"),
            shell_port=args.rx,
        )
    else:
        print("\nSearching for CatSniffer devices...")
        devices = find_all_catsniffers()

        if len(devices) < 2:
            print(f"\nError: Found {len(devices)} device(s), need 2 for TX/RX test.")
            print("Connect two CatSniffers or specify ports with --tx and --rx")
            sys.exit(1)

        print(f"Found {len(devices)} CatSniffer devices:")
        for dev in devices:
            print(f"  {dev}")
            print(f"    Shell: {dev.shell_port}")
            print(f"    LoRa:  {dev.lora_port}")

        tx_device = devices[0]
        rx_device = devices[1]

    print(f"\nUsing:")
    print(f"  TX: {tx_device}")
    print(f"  RX: {rx_device}")

    # Create tester
    tester = LoRaTester(tx_device, rx_device)

    try:
        # Connect
        tester.connect()

        # Configure LoRa
        tester.configure_lora(frequency=args.freq, sf=args.sf, bw=125, cr=5, power=20)

        if args.compare_sf:
            # Run SF comparison
            tester.run_sf_comparison(
                payload_size=args.payload,
                packets_per_sf=args.packets // 6,  # Divide packets among SF values
            )
        else:
            # Run ping test
            ping_results = tester.run_ping_test(count=10)

            if not args.ping_only and ping_results["received"] > 0:
                # Run throughput test
                tester.run_throughput_test(
                    packet_count=args.packets, payload_size=args.payload
                )
            elif args.ping_only:
                pass
            else:
                print("\nSkipping throughput test - ping test failed")

    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
    finally:
        tester.disconnect()
        print("\nTest complete!")


if __name__ == "__main__":
    main()

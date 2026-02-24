#!/usr/bin/env python3
"""
CatSniffer Multi-Device Verification Tool
Detects all connected CatSniffers and tests shell commands.

Usage:
    python3 verify_endpoints.py
    python3 verify_endpoints.py --test-all    # Include LoRa commands

Remember to use the virtual environment:
source ~/zephyrproject/.venv/bin/activate && export ZEPHYR_BASE=$HOME/zephyrproject/zephyr
"""

import sys
import time
import argparse

try:
    import usb.core
    import usb.util
except ImportError:
    print("Error: pyusb not installed. Run: pip install pyusb")
    sys.exit(1)

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("Error: pyserial not installed. Run: pip install pyserial")
    sys.exit(1)

CATSNIFFER_VID = 0x1209
CATSNIFFER_PID = 0xBABB


class CatSnifferDevice:
    """Represents a single CatSniffer device with its 3 endpoints."""

    def __init__(self, device_id, ports):
        self.device_id = device_id
        self.bridge_port = ports.get("Cat-Bridge")
        self.lora_port = ports.get("Cat-LoRa")
        self.shell_port = ports.get("Cat-Shell")

    def __str__(self):
        return f"CatSniffer #{self.device_id}"

    def send_command(self, port, command, timeout=1.0):
        """Send command and return response."""
        if not port:
            return None

        try:
            with serial.Serial(port, 115200, timeout=timeout) as ser:
                # Flush any pending data
                ser.reset_input_buffer()
                ser.reset_output_buffer()

                # Send command
                cmd_bytes = (command + "\r\n").encode("ascii")
                ser.write(cmd_bytes)
                ser.flush()

                # Wait a bit for response
                time.sleep(0.2)

                # Read response
                response = b""
                start_time = time.time()
                while time.time() - start_time < timeout:
                    if ser.in_waiting:
                        chunk = ser.read(ser.in_waiting)
                        response += chunk
                        time.sleep(0.05)
                    else:
                        if response:
                            break
                        time.sleep(0.05)

                return response.decode("ascii", errors="ignore").strip()
        except Exception as e:
            return f"ERROR: {str(e)}"


def get_all_usb_devices():
    """Find all Catsniffer USB devices."""
    devices = []
    for dev in usb.core.find(
        find_all=True, idVendor=CATSNIFFER_VID, idProduct=CATSNIFFER_PID
    ):
        devices.append(dev)
    return devices


def get_usb_interfaces(dev):
    """Read interface strings from a specific USB device."""
    interfaces = []

    for cfg in dev:
        for intf in cfg:
            intf_num = intf.bInterfaceNumber
            try:
                if intf.iInterface:
                    name = usb.util.get_string(dev, intf.iInterface)
                else:
                    name = None
            except:
                name = None

            interfaces.append(
                {
                    "number": intf_num,
                    "name": name,
                    "class": intf.bInterfaceClass,
                    "bus": dev.bus,
                    "address": dev.address,
                }
            )

    return interfaces


def find_all_catsniffers():
    """Find all connected CatSniffer devices and their ports."""
    print(
        f"Searching for CatSniffers (VID:{CATSNIFFER_VID:04X} PID:{CATSNIFFER_PID:04X})..."
    )

    usb_devices = get_all_usb_devices()

    if not usb_devices:
        print("No CatSniffers found.")
        return []

    print(f"Found {len(usb_devices)} CatSniffer device(s)\n")

    # Get all serial ports
    all_ports = list(serial.tools.list_ports.comports())
    cat_ports = sorted(
        [p for p in all_ports if p.vid == CATSNIFFER_VID and p.pid == CATSNIFFER_PID],
        key=lambda x: x.device,
    )

    # Group ports by device (each CatSniffer has 3 consecutive ports)
    catsniffers = []

    # Collect all interfaces from all devices
    all_interfaces = []
    for dev in usb_devices:
        interfaces = get_usb_interfaces(dev)
        cdc_ctrl_intfs = sorted(
            [i for i in interfaces if i["class"] == 0x02], key=lambda x: x["number"]
        )
        all_interfaces.extend(cdc_ctrl_intfs)

    # Match ports to interfaces (3 ports per device)
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

            catsniffers.append(CatSnifferDevice(device_idx + 1, ports))

    return catsniffers


def print_device_info(devices):
    """Print information about all detected devices."""
    print("=" * 70)
    print("DETECTED CATSNIFFERS")
    print("=" * 70)

    for dev in devices:
        print(f"\n{dev}")
        print(f"  Cat-Bridge (CC1352): {dev.bridge_port or 'Not found'}")
        print(f"  Cat-LoRa (SX1262):   {dev.lora_port or 'Not found'}")
        print(f"  Cat-Shell (Config):  {dev.shell_port or 'Not found'}")


def test_basic_commands(device):
    """Test basic shell commands on a CatSniffer."""
    print(f"\n{'='*70}")
    print(f"TESTING {device} - BASIC COMMANDS")
    print(f"{'='*70}")

    if not device.shell_port:
        print("  ERROR: Shell port not available")
        return False

    tests_passed = 0
    tests_total = 0

    # Test 1: help command
    print("\n[1/4] Testing 'help' command...")
    tests_total += 1
    response = device.send_command(device.shell_port, "help", timeout=1.0)
    if response and "Commands:" in response:
        print("  ✓ PASS: Help command works")
        print(f"  Response preview: {response[:200]}...")
        tests_passed += 1
    else:
        print(f"  ✗ FAIL: {response}")

    # Test 2: status command
    print("\n[2/4] Testing 'status' command...")
    tests_total += 1
    response = device.send_command(device.shell_port, "status", timeout=1.0)
    if response and "Mode:" in response and "Band:" in response:
        print("  ✓ PASS: Status command works")
        print(f"  Response: {response}")
        tests_passed += 1
    else:
        print(f"  ✗ FAIL: {response}")

    # Test 3: lora_config command
    print("\n[3/4] Testing 'lora_config' command...")
    tests_total += 1
    response = device.send_command(device.shell_port, "lora_config", timeout=1.0)
    if response and "LoRa Configuration:" in response and "Frequency:" in response:
        print("  ✓ PASS: LoRa config command works")
        print(f"  Configuration:\n{response}")
        tests_passed += 1
    else:
        print(f"  ✗ FAIL: {response}")

    # Test 4: lora_mode command
    print("\n[4/4] Testing 'lora_mode' command...")
    tests_total += 1
    response = device.send_command(device.shell_port, "lora_mode stream", timeout=1.0)
    if response and "STREAM" in response:
        print("  ✓ PASS: LoRa mode switch to stream works")
        print(f"  Response: {response}")

        # Switch back to command mode for testing
        response2 = device.send_command(
            device.shell_port, "lora_mode command", timeout=1.0
        )
        if response2 and "COMMAND" in response2:
            print("  ✓ PASS: LoRa mode switch to command works")
            print(f"  Response: {response2}")
        tests_passed += 1
    else:
        print(f"  ✗ FAIL: {response}")

    print(f"\n  Summary: {tests_passed}/{tests_total} tests passed")
    return tests_passed == tests_total


def test_lora_config_commands(device):
    """Test LoRa configuration commands."""
    print(f"\n{'='*70}")
    print(f"TESTING {device} - LORA CONFIGURATION")
    print(f"{'='*70}")

    if not device.shell_port:
        print("  ERROR: Shell port not available")
        return False

    tests_passed = 0
    tests_total = 0

    # Test frequency
    print("\n[1/6] Testing 'lora_freq' command...")
    tests_total += 1
    response = device.send_command(
        device.shell_port, "lora_freq 868000000", timeout=1.0
    )
    if response and "Frequency set to" in response and "pending" in response:
        print("  ✓ PASS: Frequency setting works")
        print(f"  Response: {response}")
        tests_passed += 1
    else:
        print(f"  ✗ FAIL: {response}")

    # Test spreading factor
    print("\n[2/6] Testing 'lora_sf' command...")
    tests_total += 1
    response = device.send_command(device.shell_port, "lora_sf 10", timeout=1.0)
    if response and "Spreading Factor set to SF10" in response:
        print("  ✓ PASS: Spreading factor setting works")
        print(f"  Response: {response}")
        tests_passed += 1
    else:
        print(f"  ✗ FAIL: {response}")

    # Test bandwidth
    print("\n[3/6] Testing 'lora_bw' command...")
    tests_total += 1
    response = device.send_command(device.shell_port, "lora_bw 250", timeout=1.0)
    if response and "Bandwidth set to 250" in response:
        print("  ✓ PASS: Bandwidth setting works")
        print(f"  Response: {response}")
        tests_passed += 1
    else:
        print(f"  ✗ FAIL: {response}")

    # Test coding rate
    print("\n[4/6] Testing 'lora_cr' command...")
    tests_total += 1
    response = device.send_command(device.shell_port, "lora_cr 7", timeout=1.0)
    if response and "Coding Rate set to 4/7" in response:
        print("  ✓ PASS: Coding rate setting works")
        print(f"  Response: {response}")
        tests_passed += 1
    else:
        print(f"  ✗ FAIL: {response}")

    # Test TX power
    print("\n[5/6] Testing 'lora_power' command...")
    tests_total += 1
    response = device.send_command(device.shell_port, "lora_power 14", timeout=1.0)
    if response and "TX Power set to 14" in response:
        print("  ✓ PASS: TX power setting works")
        print(f"  Response: {response}")
        tests_passed += 1
    else:
        print(f"  ✗ FAIL: {response}")

    # Verify pending config
    print("\n[6/6] Verifying pending configuration...")
    tests_total += 1
    response = device.send_command(device.shell_port, "lora_config", timeout=1.0)
    if response and "pending apply" in response:
        print("  ✓ PASS: Configuration changes marked as pending")
        print(f"  Configuration:\n{response}")
        tests_passed += 1
    else:
        print(f"  ✗ FAIL: {response}")

    # Reset to defaults (don't apply the test config)
    print("\n  Resetting to defaults...")
    device.send_command(device.shell_port, "lora_freq 915000000", timeout=1.0)
    device.send_command(device.shell_port, "lora_sf 7", timeout=1.0)
    device.send_command(device.shell_port, "lora_bw 125", timeout=1.0)
    device.send_command(device.shell_port, "lora_cr 5", timeout=1.0)
    device.send_command(device.shell_port, "lora_power 20", timeout=1.0)
    device.send_command(device.shell_port, "lora_mode stream", timeout=1.0)

    print(f"\n  Summary: {tests_passed}/{tests_total} tests passed")
    return tests_passed == tests_total


def test_lora_communication(device):
    """Test LoRa command mode communication."""
    print(f"\n{'='*70}")
    print(f"TESTING {device} - LORA COMMUNICATION")
    print(f"{'='*70}")

    if not device.lora_port:
        print("  ERROR: LoRa port not available")
        return False

    # First, ensure we're in command mode
    device.send_command(device.shell_port, "lora_mode command", timeout=1.0)
    time.sleep(0.5)

    tests_passed = 0
    tests_total = 0

    # Test TEST command
    print("\n[1/2] Testing 'TEST' command on LoRa port...")
    tests_total += 1
    response = device.send_command(device.lora_port, "TEST", timeout=2.0)
    if response:
        print("  ✓ PASS: TEST command received response")
        print(f"  Response: {response}")
        tests_passed += 1
    else:
        print(f"  ✗ FAIL: No response")

    # Test TXTEST command
    print("\n[2/2] Testing 'TXTEST' command on LoRa port...")
    tests_total += 1
    response = device.send_command(device.lora_port, "TXTEST", timeout=2.0)
    if response:
        print("  ✓ PASS: TXTEST command received response")
        print(f"  Response: {response}")
        tests_passed += 1
    else:
        print(f"  ✗ FAIL: No response")

    # Switch back to stream mode
    device.send_command(device.shell_port, "lora_mode stream", timeout=1.0)

    print(f"\n  Summary: {tests_passed}/{tests_total} tests passed")
    return tests_passed == tests_total


def main():
    parser = argparse.ArgumentParser(
        description="CatSniffer Multi-Device Verification Tool"
    )
    parser.add_argument(
        "--test-all",
        action="store_true",
        help="Run all tests including LoRa configuration and communication",
    )
    parser.add_argument(
        "--device", type=int, metavar="N", help="Test only device number N (1-indexed)"
    )
    args = parser.parse_args()

    print("=" * 70)
    print("CATSNIFFER MULTI-DEVICE VERIFICATION TOOL")
    print("=" * 70)
    print()

    # Find all devices
    devices = find_all_catsniffers()

    if not devices:
        print("\n✗ No CatSniffers found. Check USB connections.")
        sys.exit(1)

    print_device_info(devices)

    # Filter devices if specific device requested
    if args.device:
        devices = [d for d in devices if d.device_id == args.device]
        if not devices:
            print(f"\n✗ Device #{args.device} not found.")
            sys.exit(1)

    # Run tests
    print("\n" + "=" * 70)
    print("RUNNING TESTS")
    print("=" * 70)

    results = {}
    for device in devices:
        results[device.device_id] = {"basic": test_basic_commands(device)}

        if args.test_all:
            results[device.device_id]["config"] = test_lora_config_commands(device)
            results[device.device_id]["lora"] = test_lora_communication(device)

    # Print summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    all_passed = True
    for device_id, tests in results.items():
        print(f"\nCatSniffer #{device_id}:")
        basic_status = "✓ PASS" if tests["basic"] else "✗ FAIL"
        print(f"  Basic Commands:        {basic_status}")

        if args.test_all:
            config_status = "✓ PASS" if tests.get("config") else "✗ FAIL"
            lora_status = "✓ PASS" if tests.get("lora") else "✗ FAIL"
            print(f"  LoRa Configuration:    {config_status}")
            print(f"  LoRa Communication:    {lora_status}")
            all_passed = (
                all_passed
                and tests["basic"]
                and tests.get("config")
                and tests.get("lora")
            )
        else:
            all_passed = all_passed and tests["basic"]

    print("\n" + "=" * 70)
    if all_passed:
        print("✓ ALL TESTS PASSED")
    else:
        print("✗ SOME TESTS FAILED")
    print("=" * 70)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())

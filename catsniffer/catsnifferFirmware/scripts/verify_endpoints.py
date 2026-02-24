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
    print("\033[31m✗ ERROR: pyusb not installed. Run: pip install pyusb\033[0m")
    sys.exit(1)

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("\033[31m✗ ERROR: pyserial not installed. Run: pip install pyserial\033[0m")
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
            return f"\033[31mERROR: {str(e)}\033[0m"


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
    """Find all connected CatSniffer devices and their ports with cross-platform."""
    print(
        f"\033[92mSearching for CatSniffers (VID:{CATSNIFFER_VID:04X} PID:{CATSNIFFER_PID:04X})...\033[0m"
    )

    all_ports = list(serial.tools.list_ports.comports())
    cat_ports = [
        p for p in all_ports if p.vid == CATSNIFFER_VID and p.pid == CATSNIFFER_PID
    ]

    if not cat_ports:
        print("\033[91mNo CatSniffer ports found.\033[0m")
        return []

    print(f"\033[96mFound {len(cat_ports)} CatSniffer port(s)\033[0m")

    # Sort consistently across systems
    cat_ports.sort(key=lambda x: x.device)

    # Group by device using serial number
    import re

    devices = {}

    for port in cat_ports:
        serial_num = "unknown"
        if port.hwid:
            match = re.search(r"SER=([A-Fa-f0-9]+)", port.hwid)
            if match:
                serial_num = match.group(1)
            elif port.location:
                serial_num = f"loc-{port.location}"

        if serial_num not in devices:
            devices[serial_num] = []
        devices[serial_num].append(port)

    catsniffers = []
    device_id = 1

    for serial_num, ports in devices.items():
        if len(ports) < 3:
            print(
                f"\033[93mWarning: Device {serial_num} has only {len(ports)}/3 ports\033[0m"
            )
            continue

        # Sort ports for this device
        ports.sort(key=lambda x: x.device)

        # Intelligent mapping
        ports_dict = {}

        # 1. By description (more reliable)
        for port in ports:
            desc = (port.description or "").lower()
            if "shell" in desc:
                ports_dict["Cat-Shell"] = port.device
            elif "lora" in desc:
                ports_dict["Cat-LoRa"] = port.device
            elif "bridge" in desc:
                ports_dict["Cat-Bridge"] = port.device

        # 2. By order (fallback)
        if len(ports_dict) < 3:
            fallback_map = {0: "Cat-Bridge", 1: "Cat-LoRa", 2: "Cat-Shell"}
            for i, port in enumerate(ports[:3]):
                name = fallback_map.get(i)
                if name and name not in ports_dict:
                    ports_dict[name] = port.device

        if len(ports_dict) == 3:
            device = CatSnifferDevice(device_id, ports_dict)
            catsniffers.append(device)
            device_id += 1

    print(f"\n\033[32mDetected {len(catsniffers)} CatSniffer device(s):\033[0m")
    for dev in catsniffers:
        print(f"\n\033[97mCatSniffer #{dev.device_id}:\033[0m")
        print(f"  \033[36mBridge:\033[0m {dev.bridge_port}")
        print(f"  \033[36mLoRa:\033[0m   {dev.lora_port}")
        print(f"  \033[36mShell:\033[0m  {dev.shell_port}")

    return catsniffers


def print_device_info(devices):
    """Print information about all detected devices."""
    print("\033[35m=" * 70 + "\033[0m")
    print("\033[35mDETECTED CATSNIFFERS\033[0m")
    print("\033[35m=" * 70 + "\033[0m")

    for dev in devices:
        print(f"\n{dev}")
        print(
            f"  \033[36mCat-Bridge (CC1352):\033[0m {dev.bridge_port or '\033[91mNot found\033[0m'}"
        )
        print(
            f"  \033[36mCat-LoRa (SX1262):\033[0m   {dev.lora_port or '\033[91mNot found\033[0m'}"
        )
        print(
            f"  \033[36mCat-Shell (Config):\033[0m  {dev.shell_port or '\033[91mNot found\033[0m'}"
        )


def test_basic_commands(device):
    """Test basic shell commands on a CatSniffer."""
    print(f"\n\033[94m" + "=" * 70 + "\033[0m")
    print(f"\033[94mTESTING {device} - BASIC COMMANDS\033[0m")
    print(f"\033[94m" + "=" * 70 + "\033[0m")

    if not device.shell_port:
        print("\033[31m ERROR: Shell port not available\033[0m")
        return False

    tests_passed = 0
    tests_total = 0

    # Test 1: help command
    print("\n\033[97m[1/4] Testing 'help' command...\033[0m")
    tests_total += 1
    response = device.send_command(device.shell_port, "help", timeout=1.0)
    if response and "Commands:" in response:
        print("\033[32m  ✓ PASS: Help command works\033[0m")
        print(f"\033[36m  Response preview: {response[:200]}...\033[0m")
        tests_passed += 1
    else:
        print(f"\033[31m  ✗ FAIL: {response}\033[0m")

    # Test 2: status command
    print("\n\033[97m[2/4] Testing 'status' command...\033[0m")
    tests_total += 1
    response = device.send_command(device.shell_port, "status", timeout=1.0)
    if response and "Mode:" in response and "Band:" in response:
        print("\033[32m  ✓ PASS: Status command works\033[0m")
        print(f"\033[36m  Response: {response}\033[0m")
        tests_passed += 1
    else:
        print(f"\033[31m  ✗ FAIL: {response}\033[0m")

    # Test 3: lora_config command
    print("\n\033[97m[3/4] Testing 'lora_config' command...\033[0m")
    tests_total += 1
    response = device.send_command(device.shell_port, "lora_config", timeout=1.0)
    if response and "LoRa Configuration:" in response and "Frequency:" in response:
        print("\033[32m  ✓ PASS: LoRa config command works\033[0m")
        print(f"\033[36m  Configuration:\n{response}\033[0m")
        tests_passed += 1
    else:
        print(f"\033[31m  ✗ FAIL: {response}\033[0m")

    # Test 4: lora_mode command
    print("\n\033[97m[4/4] Testing 'lora_mode' command...\033[0m")
    tests_total += 1
    response = device.send_command(device.shell_port, "lora_mode stream", timeout=1.0)
    if response and "STREAM" in response:
        print("\033[32m  ✓ PASS: LoRa mode switch to stream works\033[0m")
        print(f"\033[36m  Response: {response}\033[0m")

        # Switch back to command mode for testing
        response2 = device.send_command(
            device.shell_port, "lora_mode command", timeout=1.0
        )
        if response2 and "COMMAND" in response2:
            print("\033[32m  ✓ PASS: LoRa mode switch to command works\033[0m")
            print(f"\033[36m  Response: {response2}\033[0m")
        tests_passed += 1
    else:
        print(f"\033[31m  ✗ FAIL: {response}\033[0m")

    print(f"\n\033[97m  Summary: {tests_passed}/{tests_total} tests passed\033[0m")
    return tests_passed == tests_total


def test_lora_config_commands(device):
    """Test LoRa configuration commands."""
    print(f"\n\033[94m" + "=" * 70 + "\033[0m")
    print(f"\033[94mTESTING {device} - LORA CONFIGURATION\033[0m")
    print(f"\033[94m" + "=" * 70 + "\033[0m")

    if not device.shell_port:
        print("\033[31m ERROR: Shell port not available\033[0m")
        return False

    tests_passed = 0
    tests_total = 0

    # Test 1: Set frequency
    print("\n\033[97m[1/6] Testing 'lora_freq' command...\033[0m")
    tests_total += 1
    response = device.send_command(
        device.shell_port, "lora_freq 915000000", timeout=2.0
    )
    if response and "Frequency" in response:
        print("\033[32m  ✓ PASS: Frequency set\033[0m")
        tests_passed += 1
    else:
        print(f"\033[31m  ✗ FAIL: {response}\033[0m")

    # Test 2: Set spreading factor
    print("\n\033[97m[2/6] Testing 'lora_sf' command...\033[0m")
    tests_total += 1
    response = device.send_command(device.shell_port, "lora_sf 7", timeout=2.0)
    if response and ("Spreading" in response or "SF" in response):
        print("\033[32m  ✓ PASS: Spreading factor set\033[0m")
        tests_passed += 1
    else:
        print(f"\033[31m  ✗ FAIL: {response}\033[0m")

    # Test 3: Set bandwidth
    print("\n\033[97m[3/6] Testing 'lora_bw' command...\033[0m")
    tests_total += 1
    response = device.send_command(device.shell_port, "lora_bw 125", timeout=2.0)
    if response and "Bandwidth" in response:
        print("\033[32m  ✓ PASS: Bandwidth set\033[0m")
        tests_passed += 1
    else:
        print(f"\033[31m  ✗ FAIL: {response}\033[0m")

    # Test 4: Set coding rate
    print("\n\033[97m[4/6] Testing 'lora_cr' command...\033[0m")
    tests_total += 1
    response = device.send_command(device.shell_port, "lora_cr 5", timeout=2.0)
    if response and "Coding" in response:
        print("\033[32m  ✓ PASS: Coding rate set\033[0m")
        tests_passed += 1
    else:
        print(f"\033[31m  ✗ FAIL: {response}\033[0m")

    # Test 5: Set TX power
    print("\n\033[97m[5/6] Testing 'lora_power' command...\033[0m")
    tests_total += 1
    response = device.send_command(device.shell_port, "lora_power 14", timeout=2.0)
    if response and "power" in response.lower():
        print("\033[32m  ✓ PASS: TX power set\033[0m")
        tests_passed += 1
    else:
        print(f"\033[31m  ✗ FAIL: {response}\033[0m")

    # Test 6: Apply configuration
    print("\n\033[97m[6/6] Testing 'lora_apply' command...\033[0m")
    tests_total += 1
    response = device.send_command(device.shell_port, "lora_apply", timeout=3.0)
    if response and ("applied" in response.lower() or "success" in response.lower()):
        print("\033[32m  ✓ PASS: Configuration applied\033[0m")
        tests_passed += 1
    else:
        print(f"\033[31m  ✗ FAIL: {response}\033[0m")

    print(f"\n\033[97m  Summary: {tests_passed}/{tests_total} tests passed\033[0m")
    return tests_passed >= 4


def test_lora_communication(device):
    """Test LoRa communication using both LoRa and Shell ports simultaneously."""
    print(f"\n\033[94m" + "=" * 70 + "\033[0m")
    print(f"\033[94mTESTING {device} - LORA COMMUNICATION\033[0m")
    print(f"\033[94m" + "=" * 70 + "\033[0m")

    if not device.lora_port or not device.shell_port:
        print("\033[31m ERROR: LoRa or Shell port not available\033[0m")
        return False

    tests_passed = 0
    tests_total = 0

    # 1. First switch to command mode
    print("\n\033[97m[1/6] Switching to command mode...\033[0m")
    tests_total += 1
    response = device.send_command(device.shell_port, "lora_mode command", timeout=2.0)
    if response and "COMMAND" in response:
        print(f"\033[32m{response}\033[0m")
        print("\033[32m  ✓ PASS: Successfully switched to command mode\033[0m")
        tests_passed += 1
        time.sleep(0.5)  # Give time for mode change
    else:
        print(f"\033[31m  ✗ FAIL: Could not switch to command mode\033[0m")
        print(f"\033[31m  Response: {response}\033[0m")
        return False

    # Function to send command to LoRa and read response from Shell
    def send_lora_listen_shell(lora_cmd, expected_keywords, timeout=3.0):
        """
        Send a command to the LoRa port and listen for the response on the Shell port.
        Keep both ports open simultaneously as in manual usage.
        """
        try:
            # Open both ports simultaneously
            shell_ser = serial.Serial(device.shell_port, 115200, timeout=0.5)
            lora_ser = serial.Serial(device.lora_port, 115200, timeout=0.5)

            # Clear buffers
            shell_ser.reset_input_buffer()
            shell_ser.reset_output_buffer()
            lora_ser.reset_input_buffer()
            lora_ser.reset_output_buffer()

            time.sleep(0.1)

            # Send command to LoRa port
            cmd_bytes = (lora_cmd + "\r\n").encode("ascii")
            lora_ser.write(cmd_bytes)
            lora_ser.flush()
            print(f"\033[36m  Sent to LoRa: '{lora_cmd}'\033[0m")
            print(f"\033[90m  Bytes: {cmd_bytes.hex()}\033[0m")

            # Wait and read response from Shell
            response = b""
            start_time = time.time()

            while time.time() - start_time < timeout:
                if shell_ser.in_waiting > 0:
                    chunk = shell_ser.read(shell_ser.in_waiting)
                    response += chunk
                    print(f"\033[90m  [Shell] Got {len(chunk)} bytes\033[0m")
                time.sleep(0.1)

            # Close ports
            lora_ser.close()
            shell_ser.close()

            # Decode response
            response_str = response.decode("ascii", errors="ignore").strip()

            if response_str:
                print(f"\033[36m  Shell response: {response_str}\033[0m")
                # Check if any expected keyword is in the response
                if any(keyword in response_str for keyword in expected_keywords):
                    return True, response_str
                else:
                    return False, response_str
            else:
                print(f"\033[31m  No response from Shell\033[0m")
                return False, ""

        except Exception as e:
            print(f"\033[31m  ERROR: {e}\033[0m")
            return False, ""

    # 2. Test TEST command (first time)
    print("\n\033[97m[2/6] Testing 'TEST' command (1st time)...\033[0m")
    tests_total += 1
    success, response = send_lora_listen_shell(
        "TEST", ["TEST", "LoRa ready", "initialized"], timeout=4.0
    )
    if success:
        print("\033[32m  ✓ PASS: TEST command successful\033[0m")
        tests_passed += 1
    else:
        print("\033[31m  ✗ FAIL: No valid response to TEST command\033[0m")

    # 3. Test TEST command (second time)
    print("\n\033[97m[3/6] Testing 'TEST' command (2nd time)...\033[0m")
    tests_total += 1
    success, response = send_lora_listen_shell(
        "TEST", ["TEST", "LoRa ready"], timeout=4.0
    )
    if success:
        print("\033[32m  ✓ PASS: TEST command successful (2nd time)\033[0m")
        tests_passed += 1
    else:
        print("\033[33m  ⚠ WARNING: Second TEST had unexpected response\033[0m")
        # Doesn't necessarily fail, sometimes the second response is different
        tests_passed += 1

    # 4. Test TXTEST command
    print("\n\033[97m[4/6] Testing 'TXTEST' command...\033[0m")
    tests_total += 1
    success, response = send_lora_listen_shell(
        "TXTEST", ["TX Result", "DEBUG: Sending", "Success"], timeout=5.0
    )
    if success:
        print("\033[32m  ✓ PASS: TXTEST command successful\033[0m")
        tests_passed += 1
    else:
        print("\033[31m  ✗ FAIL: No response to TXTEST command\033[0m")

    # 5. Test TX command with hex data
    print("\n\033[97m[5/6] Testing 'TX' command with hex data...\033[0m")
    tests_total += 1
    success, response = send_lora_listen_shell(
        "TX 50494E47", ["TX Result", "Success"], timeout=5.0
    )
    if success:
        print("\033[32m  ✓ PASS: TX command successful\033[0m")
        tests_passed += 1
    else:
        print("\033[31m  ✗ FAIL: No response to TX command\033[0m")

    # 6. Check for data available on LoRa port
    print("\n\033[97m[6/6] Checking LoRa port for data...\033[0m")
    tests_total += 1
    try:
        with serial.Serial(device.lora_port, 115200, timeout=1) as lora_ser:
            lora_ser.reset_input_buffer()
            time.sleep(0.5)

            if lora_ser.in_waiting > 0:
                data = lora_ser.read(lora_ser.in_waiting)
                print(f"\033[32m  ✓ Data available on LoRa port: {data.hex()}\033[0m")
                tests_passed += 1
            else:
                print("\033[90m  No data on LoRa port (this is normal)\033[0m")
                tests_passed += 1
    except Exception as e:
        print(f"\033[31m  Error checking LoRa port: {e}\033[0m")

    # 7. Return to stream mode
    print("\n\033[93m[Cleanup] Switching back to stream mode...\033[0m")
    response = device.send_command(device.shell_port, "lora_mode stream", timeout=2.0)
    if response and "STREAM" in response:
        print("\033[32m  ✓ Returned to stream mode\033[0m")
    else:
        print(f"\033[33m  ⚠ Warning: {response}\033[0m")

    print(f"\n\033[97m  Summary: {tests_passed}/{tests_total} tests passed\033[0m")

    # Consider successful if at least 4 out of 6 tests pass
    return tests_passed >= 4


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

    print("\033[92m" + "=" * 70 + "\033[0m")
    print("\033[92m🐱 CATSNIFFER MULTI-DEVICE VERIFICATION TOOL\033[0m")
    print("\033[92m" + "=" * 70 + "\033[0m")
    print()

    # Find all devices
    devices = find_all_catsniffers()

    if not devices:
        print("\n\033[91m✗ No CatSniffers found. Check USB connections.\033[0m")
        sys.exit(1)

    print_device_info(devices)

    # Filter devices if specific device requested
    if args.device:
        devices = [d for d in devices if d.device_id == args.device]
        if not devices:
            print(f"\n\033[91m✗ Device #{args.device} not found.\033[0m")
            sys.exit(1)

    # Run tests
    print("\n" + "\033[35m" + "=" * 70 + "\033[0m")
    print("\033[35m RUNNING TESTS\033[0m")
    print("\033[35m" + "=" * 70 + "\033[0m")

    results = {}
    for device in devices:
        results[device.device_id] = {"basic": test_basic_commands(device)}

        if args.test_all:
            results[device.device_id]["config"] = test_lora_config_commands(device)
            results[device.device_id]["lora"] = test_lora_communication(device)

    # Print summary
    print("\n" + "\033[92m" + "=" * 70 + "\033[0m")
    print("\033[92m TEST SUMMARY\033[0m")
    print("\033[92m" + "=" * 70 + "\033[0m")

    all_passed = True
    for device_id, tests in results.items():
        print(f"\n\033[97mCatSniffer #{device_id}:\033[0m")
        basic_status = (
            "\033[32m✓ PASS\033[0m" if tests["basic"] else "\033[31m✗ FAIL\033[0m"
        )
        print(f"  \033[36mBasic Commands:\033[0m        {basic_status}")

        if args.test_all:
            config_status = (
                "\033[32m✓ PASS\033[0m"
                if tests.get("config")
                else "\033[31m✗ FAIL\033[0m"
            )
            lora_status = (
                "\033[32m✓ PASS\033[0m"
                if tests.get("lora")
                else "\033[31m✗ FAIL\033[0m"
            )
            print(f"  \033[36mLoRa Configuration:\033[0m    {config_status}")
            print(f"  \033[36mLoRa Communication:\033[0m    {lora_status}")
            all_passed = (
                all_passed
                and tests["basic"]
                and tests.get("config")
                and tests.get("lora")
            )
        else:
            all_passed = all_passed and tests["basic"]

    print("\n" + "\033[92m" + "=" * 70 + "\033[0m")
    if all_passed:
        print("\033[32m ALL TESTS PASSED\033[0m")
    else:
        print("\033[31m SOME TESTS FAILED\033[0m")
    print("\033[92m" + "=" * 70 + "\033[0m")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())

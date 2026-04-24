#!/usr/bin/env python3
"""
CatSniffer Verification Module
Provides device verification and testing functionality.
"""

import time
from typing import Dict, List, Optional, Tuple

from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box

from ..core.usb_connection import (
    CatSnifferDevice,
    ShellConnection,
    LoRaConnection,
    open_serial_port,
    find_devices,
    DEFAULT_BAUDRATE,
    CATSNIFFER_VID,
    CATSNIFFER_PID,
)
from ..utils.output import (
    console,
    set_quiet_mode,
    print_test_header,
    print_test_step,
    print_test_pass,
    print_test_fail,
    print_test_summary,
    print_error,
    print_warning,
)


# ── Device table ──────────────────────────────────────────────────────────────


def print_device_table(
    devices: List[CatSnifferDevice], title: str = "Detected Devices"
):
    table = Table(title=title, box=box.ROUNDED)
    table.add_column("Device", style="cyan")
    table.add_column("Bridge Port", style="blue")
    table.add_column("LoRa Port", style="yellow")
    table.add_column("Shell Port", style="green")
    table.add_column("Status", style="bold")

    for dev in devices:
        bridge = dev.bridge_port or "[red]Not found[/red]"
        lora = dev.lora_port or "[red]Not found[/red]"
        shell = dev.shell_port or "[red]Not found[/red]"
        status = (
            "[green]✓ Complete[/green]"
            if dev.is_valid()
            else "[yellow]⚠ Incomplete[/yellow]"
        )
        table.add_row(str(dev), bridge, lora, shell, status)

    console.print(table)


# ── Individual test suites ────────────────────────────────────────────────────


def test_basic_commands(device: CatSnifferDevice) -> bool:
    """Test basic shell commands via the Cat-Shell port."""
    print_test_header(f"Testing {device} - Basic Commands")

    if not device.shell_port:
        print_error("Shell port not available")
        return False

    tests = [
        ("help", "help", "Commands:", "Help command"),
        ("status", "status", "Mode:", "Status command"),
        ("lora_config", "lora_config", "LoRa Configuration:", "LoRa config command"),
        ("lora_mode", "lora_mode stream", "STREAM", "LoRa mode switch"),
        ("identify", "identify", "identify", "Identify command"),
    ]

    results = []
    shell = ShellConnection(port=device.shell_port)

    with shell:
        for test_name, cmd, expected, description in tests:
            print_test_step(test_name, description)
            response = shell.send_command(cmd, timeout=2.0)
            if response and expected in response:
                print_test_pass(response)
                results.append(True)
            else:
                print_test_fail(response or "No response")
                results.append(False)

        # Restore command mode if we switched to stream
        shell.send_command("lora_mode command", timeout=1.0)

    passed = sum(results)
    print_test_summary(passed, len(results))
    return passed == len(results)


def test_lora_configuration(device: CatSnifferDevice) -> bool:
    """Test LoRa configuration commands."""
    print_test_header(f"Testing {device} - LoRa Configuration")

    if not device.shell_port:
        print_error("Shell port not available")
        return False

    tests = [
        ("freq", "lora_freq 915000000", ["Frequency"], "Set frequency to 915 MHz"),
        ("sf", "lora_sf 7", ["Spreading", "SF"], "Set spreading factor to 7"),
        ("bw", "lora_bw 125", ["Bandwidth"], "Set bandwidth to 125 kHz"),
        ("cr", "lora_cr 5", ["Coding"], "Set coding rate to 4/5"),
        ("power", "lora_power 14", ["power"], "Set TX power to 14 dBm"),
        ("apply", "lora_apply", ["applied", "success"], "Apply configuration"),
    ]

    results = []
    shell = ShellConnection(port=device.shell_port)

    with shell:
        for test_name, cmd, expected_list, description in tests:
            print_test_step(test_name, description)
            response = shell.send_command(cmd, timeout=3.0)
            if response and any(e.lower() in response.lower() for e in expected_list):
                print_test_pass(response)
                results.append(True)
            else:
                print_test_fail(response or "No response")
                results.append(False)
            time.sleep(0.5)

    passed = sum(results)
    print_test_summary(passed, len(results), "configuration")
    return passed >= 4  # Require at least 4 out of 6


def test_lora_communication(device: CatSnifferDevice) -> bool:
    """Test LoRa communication between the LoRa and Shell ports."""
    print_test_header(f"Testing {device} - LoRa Communication")

    if not device.lora_port or not device.shell_port:
        print_error("LoRa or Shell port not available")
        return False

    results = []
    shell = ShellConnection(port=device.shell_port, timeout=0.5)

    with shell:
        # Switch to command mode
        print_test_step("SETUP", "Switching to command mode")
        response = shell.send_command("lora_mode command", timeout=2.0)
        if not (response and "COMMAND" in response):
            print_test_fail("Failed to switch to command mode")
            return False
        print_test_pass(response)
        time.sleep(0.5)

        def send_lora_listen_shell(
            lora_cmd: str,
            expected_keywords: List[str],
            test_name: str,
            timeout: float = 3.0,
        ) -> bool:
            """Send *lora_cmd* to the LoRa port; capture the Shell port response."""
            print_test_step(test_name, f"Sending '{lora_cmd}' to LoRa port")

            lora_ser = open_serial_port(device.lora_port, timeout=0.5)  # type: ignore[arg-type]
            if lora_ser is None:
                print_error(f"Cannot open LoRa port {device.lora_port}")
                return False

            try:
                shell.connection.reset_input_buffer()  # type: ignore[union-attr]
                lora_ser.write((lora_cmd + "\r\n").encode("ascii"))
                lora_ser.flush()

                response = b""
                deadline = time.monotonic() + timeout
                last_rx: Optional[float] = None

                while time.monotonic() < deadline:
                    conn = shell.connection
                    if conn is None:
                        break
                    waiting = conn.in_waiting
                    if waiting:
                        response += conn.read(waiting)
                        last_rx = time.monotonic()
                        time.sleep(0.02)
                    else:
                        if last_rx is not None and (time.monotonic() - last_rx) >= 0.15:
                            break
                        time.sleep(0.02)

            finally:
                lora_ser.close()

            response_str = response.decode("ascii", errors="ignore").strip()
            if response_str and any(kw in response_str for kw in expected_keywords):
                print_test_pass(response_str)
                return True
            print_test_fail(response_str or "No response from Shell")
            return False

        communication_tests = [
            ("TEST", ["TEST", "LoRa ready", "initialized"], "TEST", 4.0),
            ("TEST", ["TEST", "LoRa ready"], "TEST2", 4.0),
            ("TXTEST", ["TX Result", "DEBUG: Sending", "Success"], "TXTEST", 4.0),
            ("TX 50494E47", ["TX Result", "Success"], "TX", 4.0),
        ]

        for cmd, expected, test_id, tout in communication_tests:
            results.append(send_lora_listen_shell(cmd, expected, test_id, tout))
            time.sleep(1)

        # Check LoRa port for data
        print_test_step("CHECK", "Checking for data on LoRa port")
        lora_check = open_serial_port(device.lora_port, timeout=1.0)
        if lora_check is not None:
            time.sleep(0.5)
            if lora_check.in_waiting > 0:
                data = lora_check.read(lora_check.in_waiting)
                print_test_pass(f"Data available: {data.hex()[:50]}")
            else:
                print_test_pass("No data on LoRa port (normal)")
            lora_check.close()
            results.append(True)
        else:
            print_error(f"Cannot open LoRa port {device.lora_port}")
            results.append(False)

        # Restore stream mode
        print_test_step("CLEANUP", "Switching back to stream mode")
        response = shell.send_command("lora_mode stream", timeout=2.0)
        if response and "STREAM" in response:
            print_test_pass(response)
        else:
            print_warning("Could not restore stream mode")

    passed = sum(results)
    print_test_summary(passed, len(results), "communication")
    return passed >= 4  # Require at least 4 out of 6


# ── Entry point ───────────────────────────────────────────────────────────────


def run_verification(
    test_all: bool = False,
    device_id: Optional[int] = None,
    quiet: bool = False,
) -> Tuple[bool, Dict]:
    """
    Run complete verification of CatSniffer devices.

    Args:
        test_all:  If True, also run LoRa configuration and communication tests.
        device_id: Limit testing to this device ID.
        quiet:     Reduce output verbosity.

    Returns:
        Tuple of (overall_success, results_dict)
    """
    set_quiet_mode(quiet)

    if not quiet:
        console.print("[cyan]Starting device verification...[/cyan]")

    if not quiet:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            progress.add_task("Searching for CatSniffers...", total=None)
            devices = find_devices()
    else:
        devices = find_devices()

    if not devices:
        if not quiet:
            console.print("[red]✗ No CatSniffer device(s) found![/red]")
        return False, {}

    if not quiet:
        console.print(f"[green]✓ Found {len(devices)} CatSniffer device(s)[/green]")
        print_device_table(devices)

    if device_id:
        devices = [d for d in devices if d.device_id == device_id]
        if not devices:
            if not quiet:
                console.print(f"[red]✗ Device #{device_id} not found![/red]")
            return False, {}
        if not quiet:
            console.print(f"[yellow]Testing only device #{device_id}[/yellow]")

    results: Dict = {}
    for dev in devices:
        if not quiet:
            console.print("\n" + "=" * 60)
            console.print(f"[bold]Testing {dev}[/bold]")
            console.print("=" * 60)

        results[dev.device_id] = {"basic": test_basic_commands(dev)}

        if test_all:
            results[dev.device_id]["config"] = (
                test_lora_configuration(dev) if dev.shell_port else False
            )
            results[dev.device_id]["lora"] = (
                test_lora_communication(dev)
                if (dev.lora_port and dev.shell_port)
                else False
            )

    # Summary table
    if not quiet:
        print_test_header("Verification Summary")

    summary = Table(box=box.SIMPLE)
    summary.add_column("Device", style="cyan")
    summary.add_column("Basic", justify="center")
    if test_all:
        summary.add_column("Config", justify="center")
        summary.add_column("Comm", justify="center")
        summary.add_column("Overall", justify="center")

    all_passed = True
    for dev_id, res in results.items():
        b_ok = res["basic"]
        b_col = "green" if b_ok else "red"

        if test_all:
            c_ok = res.get("config", False)
            l_ok = res.get("lora", False)
            ok = b_ok and c_ok and l_ok
            all_passed = all_passed and ok
            summary.add_row(
                f"Device #{dev_id}",
                f"[{b_col}]{'✅' if b_ok else '❌'}[/{b_col}]",
                f"[{'green' if c_ok else 'red'}]{'✅' if c_ok else '❌'}[/{'green' if c_ok else 'red'}]",
                f"[{'green' if l_ok else 'red'}]{'✅' if l_ok else '❌'}[/{'green' if l_ok else 'red'}]",
                f"[{'green' if ok else 'red'}]{'✅' if ok else '❌'}[/{'green' if ok else 'red'}]",
            )
        else:
            all_passed = all_passed and b_ok
            summary.add_row(
                f"Device #{dev_id}",
                f"[{b_col}]{'✅' if b_ok else '❌'}[/{b_col}]",
            )

    if not quiet:
        console.print(summary)
    else:
        for dev_id, res in results.items():
            if test_all:
                ok = (
                    res["basic"] and res.get("config", False) and res.get("lora", False)
                )
            else:
                ok = res["basic"]
            print(f"Device #{dev_id}: {'PASS' if ok else 'FAIL'}")

    return all_passed, results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CatSniffer Verification Tool")
    parser.add_argument("--test-all", action="store_true")
    parser.add_argument("--device", type=int, metavar="N")
    parser.add_argument("--quiet", "-q", action="store_true")
    args = parser.parse_args()

    success, _ = run_verification(
        test_all=args.test_all, device_id=args.device, quiet=args.quiet
    )
    exit(0 if success else 1)

#!/usr/bin/env python3
"""
CatSniffer Verification Module
Provides device verification and testing functionality.
"""

import time
import re
import serial
import serial.tools.list_ports
from typing import Dict, List, Optional, Tuple

try:
    import usb.core
    import usb.util
    HAS_USB = True
except ImportError:
    HAS_USB = False

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from .catsniffer import CatSnifferDevice

console = Console()

# Constants for CatSniffer USB identification
CATSNIFFER_VID = 0x1209
CATSNIFFER_PID = 0xBABB


class VerificationDevice:
    """Device wrapper for verification testing."""
    
    def __init__(self, device_id: int, ports: Dict[str, str]):
        self.device_id = device_id
        self.bridge_port = ports.get("Cat-Bridge")
        self.lora_port = ports.get("Cat-LoRa")
        self.shell_port = ports.get("Cat-Shell")
    
    def __str__(self) -> str:
        return f"CatSniffer #{self.device_id}"
    
    def send_command(self, port: str, command: str, timeout: float = 1.0) -> Optional[str]:
        """Send command to serial port and return response."""
        if not port:
            return None
        
        try:
            with serial.Serial(port, 115200, timeout=timeout) as ser:
                ser.reset_input_buffer()
                ser.reset_output_buffer()
                
                cmd_bytes = (command + "\r\n").encode('ascii')
                ser.write(cmd_bytes)
                ser.flush()
                
                time.sleep(0.2)
                
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
                
                return response.decode('ascii', errors='ignore').strip()
        except Exception as e:
            return f"ERROR: {str(e)}"
    
    def is_complete(self) -> bool:
        """Check if device has all 3 ports."""
        return all([self.bridge_port, self.lora_port, self.shell_port])


def find_verification_devices() -> List[VerificationDevice]:
    """
    Find all connected CatSniffer devices for verification.
    
    Returns:
        List of VerificationDevice objects
    """
    all_ports = list(serial.tools.list_ports.comports())
    cat_ports = [p for p in all_ports if p.vid == CATSNIFFER_VID and p.pid == CATSNIFFER_PID]
    
    if not cat_ports:
        return []
    
    # Group by device using serial number
    devices = {}
    
    for port in cat_ports:
        serial_num = "unknown"
        if port.hwid:
            match = re.search(r'SER=([A-Fa-f0-9]+)', port.hwid)
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
            continue  # Skip incomplete devices
        
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
            device = VerificationDevice(device_id, ports_dict)
            catsniffers.append(device)
            device_id += 1
    
    return catsniffers


def print_device_table(devices: List[VerificationDevice], title: str = "Detected Devices"):
    """Print a table of devices."""
    from rich import box
    
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
        
        if dev.is_complete():
            status = "[green]✓ Complete[/green]"
        else:
            status = "[yellow]⚠ Incomplete[/yellow]"
        
        table.add_row(str(dev), bridge, lora, shell, status)
    
    console.print(table)


def test_basic_commands(device: VerificationDevice) -> bool:
    """Test basic shell commands."""
    console.print(Panel(
        f"[bold cyan]Testing {device} - Basic Commands[/bold cyan]",
        border_style="cyan"
    ))
    
    if not device.shell_port:
        console.print("[red]✗ Shell port not available[/red]")
        return False
    
    tests = [
        ("help", "help", "Commands:", "Help command"),
        ("status", "status", "Mode:", "Status command"),
        ("lora_config", "lora_config", "LoRa Configuration:", "LoRa config command"),
        ("lora_mode", "lora_mode stream", "STREAM", "LoRa mode switch")
    ]
    
    results = []
    
    for test_name, cmd, expected, description in tests:
        console.print(f"\n[blue][{test_name.upper()}][/blue] {description}...")
        
        response = device.send_command(device.shell_port, cmd, timeout=2.0)
        
        if response and expected in response:
            console.print("[green]  ✓ PASS[/green]")
            if len(response) > 100:
                console.print(f"[dim]  Response: {response[:100]}...[/dim]")
            else:
                console.print(f"[dim]  Response: {response}[/dim]")
            results.append(True)
        else:
            console.print(f"[red]  ✗ FAIL[/red]")
            if response:
                console.print(f"[red]  Got: {response[:100]}[/red]")
            else:
                console.print("[red]  No response[/red]")
            results.append(False)
    
    # Return to command mode if we switched to stream
    if device.shell_port and "lora_mode stream" in [t[1] for t in tests]:
        device.send_command(device.shell_port, "lora_mode command", timeout=1.0)
    
    passed = sum(results)
    total = len(results)
    
    console.print(f"\n[bold]Summary:[/bold] [green]{passed}/{total}[/green] tests passed")
    return passed == total


def test_lora_configuration(device: VerificationDevice) -> bool:
    """Test LoRa configuration commands."""
    console.print(Panel(
        f"[bold cyan]Testing {device} - LoRa Configuration[/bold cyan]",
        border_style="cyan"
    ))
    
    if not device.shell_port:
        console.print("[red]✗ Shell port not available[/red]")
        return False
    
    tests = [
        ("freq", "lora_freq 915000000", ["Frequency"], "Set frequency to 915MHz"),
        ("sf", "lora_sf 7", ["Spreading", "SF"], "Set spreading factor to 7"),
        ("bw", "lora_bw 125", ["Bandwidth"], "Set bandwidth to 125kHz"),
        ("cr", "lora_cr 5", ["Coding"], "Set coding rate to 4/5"),
        ("power", "lora_power 14", ["power"], "Set TX power to 14dBm"),
        ("apply", "lora_apply", ["applied", "success"], "Apply configuration")
    ]
    
    results = []
    
    for test_name, cmd, expected_list, description in tests:
        console.print(f"\n[blue][{test_name.upper()}][/blue] {description}...")
        
        response = device.send_command(device.shell_port, cmd, timeout=3.0)
        
        if response:
            found = any(expected.lower() in response.lower() for expected in expected_list)
            
            if found:
                console.print("[green]  ✓ PASS[/green]")
                results.append(True)
            else:
                console.print(f"[red]  ✗ FAIL - Unexpected response[/red]")
                console.print(f"[dim]  Response: {response[:100]}...[/dim]")
                results.append(False)
        else:
            console.print("[red]  ✗ FAIL - No response[/red]")
            results.append(False)
        
        time.sleep(0.5)
    
    passed = sum(results)
    total = len(results)
    
    console.print(f"\n[bold]Summary:[/bold] [green]{passed}/{total}[/green] configuration tests passed")
    return passed >= 4  # Require at least 4 out of 6


def test_lora_communication(device: VerificationDevice) -> bool:
    """Test LoRa communication."""
    console.print(Panel(
        f"[bold cyan]Testing {device} - LoRa Communication[/bold cyan]",
        border_style="cyan"
    ))
    
    if not device.lora_port or not device.shell_port:
        console.print("[red]✗ LoRa or Shell port not available[/red]")
        return False
    
    results = []
    
    # Switch to command mode
    console.print("\n[blue][SETUP][/blue] Switching to command mode...")
    response = device.send_command(device.shell_port, "lora_mode command", timeout=2.0)
    
    if response and "COMMAND" in response:
        console.print("[green]  ✓ Command mode enabled[/green]")
        time.sleep(0.5)
    else:
        console.print("[red]  ✗ Failed to switch to command mode[/red]")
        return False
    
    def send_lora_listen_shell(lora_cmd: str, expected_keywords: List[str], 
                               test_name: str, timeout: float = 3.0) -> bool:
        """Send command to LoRa port and listen for response on Shell port."""
        console.print(f"\n[blue][{test_name}][/blue] Sending '{lora_cmd}' to LoRa port...")
        
        try:
            shell_ser = serial.Serial(device.shell_port, 115200, timeout=0.5)
            lora_ser = serial.Serial(device.lora_port, 115200, timeout=0.5)
            
            shell_ser.reset_input_buffer()
            shell_ser.reset_output_buffer()
            lora_ser.reset_input_buffer()
            lora_ser.reset_output_buffer()
            
            time.sleep(0.1)
            
            cmd_bytes = (lora_cmd + "\r\n").encode('ascii')
            lora_ser.write(cmd_bytes)
            lora_ser.flush()
            console.print(f"[dim]  Sent {len(cmd_bytes)} bytes to LoRa port[/dim]")
            
            response = b""
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                if shell_ser.in_waiting > 0:
                    chunk = shell_ser.read(shell_ser.in_waiting)
                    response += chunk
                time.sleep(0.1)
            
            lora_ser.close()
            shell_ser.close()
            
            response_str = response.decode('ascii', errors='ignore').strip()
            
            if response_str:
                if len(response_str) > 100:
                    console.print(f"[dim]  Shell response: {response_str[:100]}...[/dim]")
                else:
                    console.print(f"[dim]  Shell response: {response_str}[/dim]")
                
                found = any(keyword in response_str for keyword in expected_keywords)
                
                if found:
                    console.print("[green]  ✓ Response received and validated[/green]")
                    return True
                else:
                    console.print("[yellow]  ⚠ Response received but didn't match expected pattern[/yellow]")
                    return False
            else:
                console.print("[red]  ✗ No response from Shell[/red]")
                return False
                
        except Exception as e:
            console.print(f"[red]  ✗ Error: {e}[/red]")
            return False
    
    # Communication tests
    communication_tests = [
        ("TEST", ["TEST", "LoRa ready", "initialized"], "TEST"),
        ("TEST", ["TEST", "LoRa ready"], "TEST2"),
        ("TXTEST", ["TX Result", "DEBUG: Sending", "Success"], "TXTEST"),
        ("TX 50494E47", ["TX Result", "Success"], "TX")
    ]
    
    for cmd, expected, test_id in communication_tests:
        success = send_lora_listen_shell(cmd, expected, test_id, timeout=4.0)
        results.append(success)
        time.sleep(1)
    
    # Check LoRa port for data
    console.print("\n[blue][CHECK][/blue] Checking for data on LoRa port...")
    
    try:
        with serial.Serial(device.lora_port, 115200, timeout=1) as lora_ser:
            lora_ser.reset_input_buffer()
            time.sleep(0.5)
            
            if lora_ser.in_waiting > 0:
                data = lora_ser.read(lora_ser.in_waiting)
                console.print(f"[green]  ✓ Data available on LoRa port: {data.hex()[:50]}...[/green]")
                results.append(True)
            else:
                console.print("[dim]  No data on LoRa port (normal)[/dim]")
                results.append(True)
    except Exception as e:
        console.print(f"[red]  ✗ Error checking LoRa port: {e}[/red]")
        results.append(False)
    
    # Return to stream mode
    console.print("\n[blue][CLEANUP][/blue] Switching back to stream mode...")
    response = device.send_command(device.shell_port, "lora_mode stream", timeout=2.0)
    
    if response and "STREAM" in response:
        console.print("[green]  ✓ Stream mode restored[/green]")
    else:
        console.print("[yellow]  ⚠ Could not restore stream mode[/yellow]")
    
    passed = sum(results)
    total = len(results)
    
    console.print(f"\n[bold]Summary:[/bold] [green]{passed}/{total}[/green] communication tests passed")
    return passed >= 4  # Require at least 4 out of 6


def run_verification(test_all: bool = False, device_id: Optional[int] = None, 
                     quiet: bool = False) -> Tuple[bool, Dict]:
    """
    Run complete verification of CatSniffer devices.
    
    Args:
        test_all: If True, run all tests including LoRa
        device_id: Test only this device ID
        quiet: Reduce output verbosity
    
    Returns:
        Tuple of (success, results_dict)
    """
    if quiet:
        # Could implement quiet mode here
        pass
    
    console.print("[cyan]Starting device verification...[/cyan]")
    
    # Find devices
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        task = progress.add_task("Searching for CatSniffers...", total=None)
        devices = find_verification_devices()
    
    if not devices:
        console.print("[red]✗ No CatSniffer devices found![/red]")
        return False, {}
    
    console.print(f"[green]✓ Found {len(devices)} CatSniffer device(s)[/green]")
    
    # Print device table
    print_device_table(devices)
    
    # Filter by device ID if specified
    if device_id:
        devices = [d for d in devices if d.device_id == device_id]
        if not devices:
            console.print(f"[red]✗ Device #{device_id} not found![/red]")
            return False, {}
        console.print(f"[yellow]Testing only device #{device_id}[/yellow]")
    
    # Run tests
    results = {}
    for dev in devices:
        console.print("\n" + "="*60)
        console.print(f"[bold]Testing {dev}[/bold]")
        console.print("="*60)
        
        # Basic tests
        results[dev.device_id] = {
            'basic': test_basic_commands(dev)
        }
        
        # Extended tests if requested
        if test_all:
            if dev.shell_port:
                results[dev.device_id]['config'] = test_lora_configuration(dev)
            else:
                console.print("[yellow]Skipping LoRa config tests - no shell port[/yellow]")
                results[dev.device_id]['config'] = False
            
            if dev.lora_port and dev.shell_port:
                results[dev.device_id]['lora'] = test_lora_communication(dev)
            else:
                console.print("[yellow]Skipping LoRa communication tests - missing ports[/yellow]")
                results[dev.device_id]['lora'] = False
    
    # Print summary
    console.print(Panel(
        "[bold cyan]Verification Summary[/bold cyan]",
        border_style="cyan",
        padding=(1, 2)
    ))
    
    from rich import box
    summary_table = Table(box=box.SIMPLE)
    summary_table.add_column("Device", style="cyan")
    summary_table.add_column("Basic", justify="center")
    
    if test_all:
        summary_table.add_column("Config", justify="center")
        summary_table.add_column("Comm", justify="center")
        summary_table.add_column("Overall", justify="center")
    
    all_passed = True
    for dev_id, test_results in results.items():
        basic_status = "✅" if test_results['basic'] else "❌"
        basic_color = "green" if test_results['basic'] else "red"
        
        if test_all:
            config_status = "✅" if test_results.get('config', False) else "❌"
            config_color = "green" if test_results.get('config', False) else "red"
            comm_status = "✅" if test_results.get('lora', False) else "❌"
            comm_color = "green" if test_results.get('lora', False) else "red"
            
            all_tests_passed = test_results['basic'] and test_results.get('config', False) and test_results.get('lora', False)
            overall_status = "✅" if all_tests_passed else "❌"
            overall_color = "green" if all_tests_passed else "red"
            
            summary_table.add_row(
                f"Device #{dev_id}",
                f"[{basic_color}]{basic_status}[/{basic_color}]",
                f"[{config_color}]{config_status}[/{config_color}]",
                f"[{comm_color}]{comm_status}[/{comm_color}]",
                f"[{overall_color}]{overall_status}[/{overall_color}]"
            )
            
            all_passed = all_passed and all_tests_passed
        else:
            summary_table.add_row(
                f"Device #{dev_id}",
                f"[{basic_color}]{basic_status}[/{basic_color}]"
            )
            all_passed = all_passed and test_results['basic']
    
    console.print(summary_table)
    
    return all_passed, results


# Standalone execution support
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='CatSniffer Verification Tool')
    parser.add_argument('--test-all', action='store_true',
                       help='Run all tests including LoRa configuration and communication')
    parser.add_argument('--device', type=int, metavar='N',
                       help='Test only device number N (1-indexed)')
    parser.add_argument('--quiet', '-q', action='store_true',
                       help='Show only summary results')
    
    args = parser.parse_args()
    
    success, _ = run_verification(
        test_all=args.test_all,
        device_id=args.device,
        quiet=args.quiet
    )
    
    exit(0 if success else 1)
"""
CatSniffer TUI Testbench Discovery

USB/serial port discovery and device grouping logic.
Adapted from verify_endpoints.py
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import serial.tools.list_ports

from .constants import (
    CATSNIFFER_VID,
    CATSNIFFER_PID,
    ENDPOINT_BRIDGE,
    ENDPOINT_LORA,
    ENDPOINT_SHELL,
    DeviceHealth,
)


@dataclass(frozen=True)
class DeviceIdentity:
    """Stable identity for a physical device."""
    serial_number: str
    usb_bus: Optional[int] = None
    usb_address: Optional[int] = None

    def __hash__(self):
        # Only hash by serial_number for stable identity
        return hash(self.serial_number)

    def __eq__(self, other):
        if not isinstance(other, DeviceIdentity):
            return False
        # Only compare serial_number for equality
        return self.serial_number == other.serial_number

    def __str__(self):
        return f"Serial:{self.serial_number[:8]}"


@dataclass
class DiscoveredPort:
    """Information about a discovered serial port."""
    device: str
    description: str
    hwid: str
    serial_number: Optional[str] = None
    location: Optional[str] = None
    vid: Optional[int] = None
    pid: Optional[int] = None


@dataclass
class DiscoveredDevice:
    """A discovered CatSniffer with its endpoints."""
    identity: DeviceIdentity
    ports: Dict[str, str] = field(default_factory=dict)  # endpoint_name -> port_path

    @property
    def bridge_port(self) -> Optional[str]:
        return self.ports.get(ENDPOINT_BRIDGE)

    @property
    def lora_port(self) -> Optional[str]:
        return self.ports.get(ENDPOINT_LORA)

    @property
    def shell_port(self) -> Optional[str]:
        return self.ports.get(ENDPOINT_SHELL)

    @property
    def health(self) -> DeviceHealth:
        has_shell = self.shell_port is not None
        has_lora = self.lora_port is not None
        has_bridge = self.bridge_port is not None

        if has_shell and has_lora and has_bridge:
            return DeviceHealth.HEALTHY
        elif has_shell:
            return DeviceHealth.PARTIAL
        else:
            return DeviceHealth.CRITICAL

    @property
    def is_complete(self) -> bool:
        return all([self.bridge_port, self.lora_port, self.shell_port])

    def missing_endpoints(self) -> List[str]:
        """Return list of missing endpoint names."""
        missing = []
        if not self.bridge_port:
            missing.append(ENDPOINT_BRIDGE)
        if not self.lora_port:
            missing.append(ENDPOINT_LORA)
        if not self.shell_port:
            missing.append(ENDPOINT_SHELL)
        return missing


def _extract_serial_number(hwid: str) -> Optional[str]:
    """Extract serial number from hwid string."""
    if not hwid:
        return None

    # Try to find SER=XXXX pattern
    match = re.search(r'SER=([A-Fa-f0-9]+)', hwid)
    if match:
        return match.group(1)

    return None


def _extract_usb_info(port) -> Tuple[Optional[int], Optional[int]]:
    """Extract USB bus and address from port info."""
    bus = None
    address = None

    # Try location string (e.g., "1-2.3" means bus 1, address path 2.3)
    if hasattr(port, 'location') and port.location:
        parts = port.location.split('-')
        if parts:
            try:
                bus = int(parts[0])
            except ValueError:
                pass

    # Try hwid for USB bus/address
    if hasattr(port, 'hwid') and port.hwid:
        # Pattern: USB VID:PID=1209:BABB SER=... LOCATION=1-2
        loc_match = re.search(r'LOCATION=(\d+)-(\d+)', port.hwid)
        if loc_match:
            try:
                bus = int(loc_match.group(1))
            except ValueError:
                pass

    return bus, address


def _group_ports_by_device(ports: List) -> Dict[str, List]:
    """Group ports by device serial number or location."""
    groups: Dict[str, List] = {}

    for port in ports:
        serial_num = None

        # Try serial number from hwid
        if port.hwid:
            serial_num = _extract_serial_number(port.hwid)

        # Fallback to location
        if not serial_num and hasattr(port, 'location') and port.location:
            serial_num = f"loc-{port.location}"

        # Last resort: use port device as identifier
        if not serial_num:
            serial_num = f"unknown-{port.device}"

        if serial_num not in groups:
            groups[serial_num] = []
        groups[serial_num].append(port)

    return groups


def _map_endpoints_intelligent(ports: List) -> Dict[str, str]:
    """
    Map ports to endpoint names using multiple strategies.

    Priority:
    1. Description string matching (shell/lora/bridge)
    2. Positional fallback (0=Bridge, 1=LoRa, 2=Shell)
    """
    ports_dict: Dict[str, str] = {}

    # Sort ports for consistent ordering
    sorted_ports = sorted(ports, key=lambda p: p.device)

    # Strategy 1: Map by description
    for port in sorted_ports:
        desc = (port.description or "").lower()

        if "shell" in desc:
            ports_dict[ENDPOINT_SHELL] = port.device
        elif "lora" in desc:
            ports_dict[ENDPOINT_LORA] = port.device
        elif "bridge" in desc:
            ports_dict[ENDPOINT_BRIDGE] = port.device

    # Strategy 2: Positional fallback
    if len(ports_dict) < 3:
        fallback_map = {0: ENDPOINT_BRIDGE, 1: ENDPOINT_LORA, 2: ENDPOINT_SHELL}

        for i, port in enumerate(sorted_ports[:3]):
            endpoint_name = fallback_map.get(i)
            if endpoint_name and endpoint_name not in ports_dict:
                ports_dict[endpoint_name] = port.device

    return ports_dict


def discover_devices() -> List[DiscoveredDevice]:
    """
    Discover all connected CatSniffer devices.

    Returns:
        List of DiscoveredDevice objects with mapped endpoints.
    """
    # Get all serial ports
    all_ports = list(serial.tools.list_ports.comports())

    # Filter by CatSniffer VID/PID
    cat_ports = [
        p for p in all_ports
        if p.vid == CATSNIFFER_VID and p.pid == CATSNIFFER_PID
    ]

    if not cat_ports:
        return []

    # Sort for consistency
    cat_ports.sort(key=lambda p: p.device)

    # Group ports by device
    port_groups = _group_ports_by_device(cat_ports)

    devices = []

    for serial_num, ports in port_groups.items():
        # Sort ports within group
        ports.sort(key=lambda p: p.device)

        # Get USB bus/address from first port
        bus, address = _extract_usb_info(ports[0]) if ports else (None, None)

        # Create identity
        identity = DeviceIdentity(
            serial_number=serial_num,
            usb_bus=bus,
            usb_address=address
        )

        # Map endpoints
        endpoint_map = _map_endpoints_intelligent(ports)

        # Create discovered device (even if incomplete)
        device = DiscoveredDevice(
            identity=identity,
            ports=endpoint_map
        )
        devices.append(device)

    return devices


def get_port_description(port_path: str) -> str:
    """Get description for a specific port path."""
    for port in serial.tools.list_ports.comports():
        if port.device == port_path:
            return port.description or port_path
    return port_path


def check_port_available(port_path: str) -> bool:
    """Check if a port is available (not already open)."""
    try:
        ser = serial.Serial(port_path, timeout=0.1)
        ser.close()
        return True
    except (serial.SerialException, OSError):
        return False

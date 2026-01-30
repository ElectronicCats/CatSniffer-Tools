import enum
import time
from base64 import b64encode, b64decode
from binascii import Error as BAError

# Internal
from protocol.sniffer_ti import SnifferTI

# External
import serial
from serial.tools import list_ports

try:
    import usb.core
    import usb.util
except ImportError:
    usb = None

# New CatSniffer VID/PID
CATSNIFFER_VID = 0x1209
CATSNIFFER_PID = 0xBABB
DEFAULT_BAUDRATE = 115200
DEFAULT_COMPORT = "/dev/ttyUSB0"

# Shell commands for bootloader control
SHELL_CMD_BOOT = "boot"
SHELL_CMD_EXIT = "exit"


# Supported Sniffer protocols
class SniffingFirmware(enum.Enum):
    BLE = enum.auto()  # Sniffle Firmware
    ZIGBEE = enum.auto()  # TI Sniffer Firmware
    THREAD = enum.auto()  # TI Sniffer Firmware
    JWORKS = enum.auto()  # Just works
    LORA = enum.auto()


class SniffingBaseFirmware(enum.Enum):
    BLE = "sniffle"
    ZIGBEE = "sniffer"
    THREAD = "sniffer"
    JWORKS = "justworks"
    LORA = "lora"


class CatSnifferDevice:
    """Represents a CatSniffer device with its 3 endpoints."""

    def __init__(self, device_id=1, bridge_port=None, lora_port=None, shell_port=None):
        self.device_id = device_id
        self.bridge_port = bridge_port  # Cat-Bridge (CC1352)
        self.lora_port = lora_port  # Cat-LoRa (SX1262)
        self.shell_port = shell_port  # Cat-Shell (Config)

    def __str__(self):
        return f"CatSniffer #{self.device_id}"

    def __repr__(self):
        return (
            f"CatSnifferDevice(id={self.device_id}, "
            f"bridge={self.bridge_port}, lora={self.lora_port}, shell={self.shell_port})"
        )

    def is_valid(self):
        """Check if all ports are detected."""
        return all([self.bridge_port, self.lora_port, self.shell_port])


def _get_usb_interfaces(dev):
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
            except Exception:
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


def catsniffer_get_devices():
    """Find all connected CatSniffer devices with their 3 ports."""
    if usb is None:
        # Fallback if pyusb not available
        return _get_devices_fallback()

    usb_devices = list(
        usb.core.find(find_all=True, idVendor=CATSNIFFER_VID, idProduct=CATSNIFFER_PID)
    )

    if not usb_devices:
        return []

    # Get all serial ports matching our VID/PID
    all_ports = list(list_ports.comports())
    cat_ports = sorted(
        [p for p in all_ports if p.vid == CATSNIFFER_VID and p.pid == CATSNIFFER_PID],
        key=lambda x: x.device,
    )

    # Collect all CDC control interfaces from all devices
    all_interfaces = []
    for dev in usb_devices:
        interfaces = _get_usb_interfaces(dev)
        # CDC control interfaces have class 0x02
        cdc_ctrl_intfs = sorted(
            [i for i in interfaces if i["class"] == 0x02], key=lambda x: x["number"]
        )
        all_interfaces.extend(cdc_ctrl_intfs)

    # Match ports to interfaces (3 ports per device)
    catsniffers = []
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

            catsniffers.append(
                CatSnifferDevice(
                    device_id=device_idx + 1,
                    bridge_port=ports.get("Cat-Bridge"),
                    lora_port=ports.get("Cat-LoRa"),
                    shell_port=ports.get("Cat-Shell"),
                )
            )

    return catsniffers


def _get_devices_fallback():
    """Fallback device detection using only pyserial (no interface names)."""
    ports = list(list_ports.comports())
    cat_ports = sorted(
        [p for p in ports if p.vid == CATSNIFFER_VID and p.pid == CATSNIFFER_PID],
        key=lambda x: x.device,
    )

    catsniffers = []
    # Group ports in sets of 3
    for i in range(0, len(cat_ports), 3):
        if i + 2 < len(cat_ports):
            catsniffers.append(
                CatSnifferDevice(
                    device_id=(i // 3) + 1,
                    bridge_port=cat_ports[i].device,
                    lora_port=cat_ports[i + 1].device,
                    shell_port=cat_ports[i + 2].device,
                )
            )

    return catsniffers


def catsniffer_get_device(device_id=None):
    """Get a single CatSniffer device, optionally by ID."""
    devices = catsniffer_get_devices()
    if not devices:
        return None

    if device_id is not None:
        for dev in devices:
            if dev.device_id == device_id:
                return dev
        return None

    return devices[0]


def catsniffer_get_port():
    """Legacy function - returns the bridge port of the first device."""
    device = catsniffer_get_device()
    if device and device.bridge_port:
        return device.bridge_port
    return DEFAULT_COMPORT


class CatsnifferException(Exception):
    pass


class SerialConnection:
    """Base serial connection for raw data streams."""

    def __init__(self, port="", baudrate=DEFAULT_BAUDRATE):
        self.port = port
        self.baudrate = baudrate
        self.connection = serial.Serial()

    def connect(self) -> bool:
        try:
            self.connection = serial.Serial(self.port, self.baudrate, timeout=2)
            return True
        except Exception:
            return False

    def read(self, size=1024) -> bytes:
        return self.connection.read(size)

    def read_until(self, frame: bytes) -> bytes:
        try:
            bytestream = self.connection.read_until(frame)
            sof_index = 0

            eof_index = bytestream.find(frame, sof_index)
            if eof_index == -1:
                return None

            bytestream = bytestream[sof_index : eof_index + 2]
            return bytestream
        except serial.SerialException:
            return None

    def readline(self) -> bytes:
        return self.connection.readline()

    def flush(self) -> None:
        self.connection.flush()

    def write(self, data):
        self.connection.write(data)

    def disconnect(self) -> None:
        self.flush()
        self.connection.close()

    def set_port(self, port) -> None:
        self.port = port


class ShellConnection:
    """Connection for shell commands with response parsing."""

    def __init__(self, port="", baudrate=DEFAULT_BAUDRATE, timeout=1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.connection = None

    def connect(self) -> bool:
        try:
            self.connection = serial.Serial(
                self.port, self.baudrate, timeout=self.timeout
            )
            return True
        except Exception:
            return False

    def disconnect(self) -> None:
        if self.connection:
            self.connection.close()
            self.connection = None

    def send_command(self, command: str, timeout: float = None) -> str:
        """Send a shell command and return the response."""
        if not self.connection:
            if not self.connect():
                return None

        if timeout is None:
            timeout = self.timeout

        try:
            # Flush any pending data
            self.connection.reset_input_buffer()
            self.connection.reset_output_buffer()

            # Send command
            cmd_bytes = (command + "\r\n").encode("ascii")
            self.connection.write(cmd_bytes)
            self.connection.flush()

            # Wait a bit for response
            time.sleep(0.2)

            # Read response
            response = b""
            start_time = time.time()
            while time.time() - start_time < timeout:
                if self.connection.in_waiting:
                    chunk = self.connection.read(self.connection.in_waiting)
                    response += chunk
                    time.sleep(0.05)
                else:
                    if response:
                        break
                    time.sleep(0.05)

            return response.decode("ascii", errors="ignore").strip()
        except Exception:
            return None

    def enter_bootloader(self) -> bool:
        """Send boot command to enter CC1352 bootloader mode."""
        response = self.send_command(SHELL_CMD_BOOT, timeout=2.0)
        return response is not None

    def exit_bootloader(self) -> bool:
        """Send exit command to exit CC1352 bootloader mode."""
        response = self.send_command(SHELL_CMD_EXIT, timeout=2.0)
        return response is not None


class Catsniffer(SerialConnection):
    """Main CatSniffer class for bridge port communication."""

    def __init__(self, port=None):
        super(Catsniffer, self).__init__()
        if port is None:
            port = catsniffer_get_port()
        self.set_port(port)

    def check_flag(self, flag, timeout=2) -> bool:
        stop = time.time() + timeout
        got = b""
        if not self.connect():
            return False
        self.write(SnifferTI().Commands().stop())
        self.write(SnifferTI().Commands().ping())
        got += self.read(16)
        if got[7:8].hex() == "40" or flag in got:
            self.disconnect()
            return True
        self.disconnect()
        return False

    def check_ti_firmware(self, timeout=2) -> bool:
        flag = b"TI Packet"
        return self.check_flag(flag=flag, timeout=timeout)

    def check_sniffle_firmware(self) -> bool:
        flag = [0x24]
        b0 = (len(flag) + 3) // 3
        cmd = bytes([b0, *flag])
        msg = b64encode(cmd) + b"\r\n"
        if not self.connect():
            return False
        self.write(msg)
        pkt = self.readline()
        try:
            _ = b64decode(pkt.rstrip())
            return True
        except BAError:
            return False
        finally:
            self.disconnect()


class LoRaConnection(SerialConnection):
    """Connection for LoRa data stream port."""

    def __init__(self, port=""):
        super(LoRaConnection, self).__init__(port=port)

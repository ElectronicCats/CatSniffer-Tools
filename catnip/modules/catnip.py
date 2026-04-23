import enum
import time
import re

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

# Shell commands for firmware update
SHELL_CMD_FW_VERSION = "fw_version"
SHELL_CMD_REBOOT = "reboot"


# Supported Sniffer protocols
class SniffingFirmware(enum.Enum):
    BLE = enum.auto()  # Sniffle Firmware
    ZIGBEE = enum.auto()  # TI Sniffer Firmware
    THREAD = enum.auto()  # TI Sniffer Firmware
    JWORKS = enum.auto()  # Just works
    LORA = enum.auto()
    AIRTAG_SCANNER = enum.auto()


class SniffingBaseFirmware(enum.Enum):
    BLE = "sniffle"
    ZIGBEE = "sniffer"
    THREAD = "sniffer"
    JWORKS = "justworks"
    LORA = "lora"
    AIRTAG_SCANNER = "airtag_scanner"


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


def _identify_ports_by_serial(cat_ports):
    """
    Group ports by device using serial number or USB location prefix.
    Returns a dict mapping device_key -> list of ports for that device.

    Serial number is tried first because it is present and unique for all
    three interfaces of the same device.  USB location (stripped of its
    ":config.interface" suffix) is used as a fallback when the serial number
    is absent — but ONLY when the location string contains a colon, confirming
    the "bus-hub.port:config.interface" format.  Using the full location
    (including interface number) would create one group per port instead of
    one group per device.
    """
    devices = {}

    for port in cat_ports:
        device_key = "unknown"

        # Priority 1: serial number (shared by all interfaces of one device)
        if port.hwid:
            match = re.search(r"SER[=:]([A-Fa-f0-9]+)", port.hwid)
            if match:
                device_key = match.group(1)
            elif port.serial_number:
                device_key = port.serial_number
        elif port.serial_number:
            device_key = port.serial_number

        # Priority 2: USB location prefix — only when the value contains a
        # colon, confirming it is in "path:config.interface" format.
        # Splitting on ":" discards the interface designator so all ports of
        # the same physical device share the same prefix key.
        # On Windows, pyserial may not populate location for every interface;
        # mixing present/absent location values across the same device would
        # create split groups, so we only fall back here if serial is absent.
        if device_key == "unknown" and port.location and ":" in port.location:
            device_key = port.location.split(":")[0]

        if device_key not in devices:
            devices[device_key] = []
        devices[device_key].append(port)

    return devices


def _map_ports_intelligent(ports):
    """
    Intelligently map ports to their functions (Bridge, LoRa, Shell).
    Uses description strings and falls back to positional ordering.
    Returns dict with keys: "Cat-Bridge", "Cat-LoRa", "Cat-Shell"
    """
    ports_dict = {}

    # Strategy 1: Map by description (most reliable)
    for port in ports:
        desc = (port.description or "").lower()

        if "shell" in desc:
            ports_dict["Cat-Shell"] = port.device
        elif "lora" in desc:
            ports_dict["Cat-LoRa"] = port.device
        elif "bridge" in desc:
            ports_dict["Cat-Bridge"] = port.device

    # Strategy 2: Map by interface name if available (requires pyusb)
    if len(ports_dict) < 3 and usb is not None:
        try:
            # Try to get interface names from USB
            for port in ports:
                if hasattr(port, "interface") and port.interface:
                    intf_name = port.interface
                    if "Shell" in intf_name and "Cat-Shell" not in ports_dict:
                        ports_dict["Cat-Shell"] = port.device
                    elif "LoRa" in intf_name and "Cat-LoRa" not in ports_dict:
                        ports_dict["Cat-LoRa"] = port.device
                    elif "Bridge" in intf_name and "Cat-Bridge" not in ports_dict:
                        ports_dict["Cat-Bridge"] = port.device
        except Exception:
            pass

    # Strategy 3: USB interface number from location field.
    # Location format: "bus-port:config.interface" (e.g. "1-2.1:1.0").
    # Interface 0 = Bridge, 1 = LoRa, 2 = Shell.
    # This is reliable on Linux and Windows because the interface number in the
    # location string always matches the USB interface descriptor index, regardless
    # of the COM/ttyACM number assigned by the OS.
    if len(ports_dict) < 3:
        intf_role = {0: "Cat-Bridge", 1: "Cat-LoRa", 2: "Cat-Shell"}
        for port in ports:
            if port.location and ":" in port.location:
                try:
                    intf_part = port.location.split(":")[1]  # e.g. "1.0"
                    intf_num = int(intf_part.split(".")[-1])
                    role = intf_role.get(intf_num)
                    if role and role not in ports_dict:
                        ports_dict[role] = port.device
                except (ValueError, IndexError):
                    pass

    # Strategy 4: Fallback to positional ordering (sorted by device name).
    # Used only when location is unavailable for some ports.
    # On Windows, interface 0 may lack a location string; since Windows enumerates
    # interfaces in order (0→1→2), the missing interface gets the lowest COM number
    # after sorting, so positional assignment is still correct in practice.
    # Guard: skip any port already assigned to a different role to prevent
    # one COM port appearing under two role keys (which would cause len == 3
    # but with a duplicate value).
    if len(ports_dict) < 3:
        fallback_map = {0: "Cat-Bridge", 1: "Cat-LoRa", 2: "Cat-Shell"}
        already_assigned = set(ports_dict.values())
        for i, port in enumerate(ports[:3]):
            name = fallback_map.get(i)
            if name and name not in ports_dict and port.device not in already_assigned:
                ports_dict[name] = port.device
                already_assigned.add(port.device)

    return ports_dict


def catnip_get_devices():
    """
    Find all connected CatSniffer devices with their 3 ports.

    Uses intelligent detection based on:
    1. Serial number grouping (to handle multiple devices)
    2. Port description matching
    3. Positional fallback

    Returns:
        list: List of CatSnifferDevice objects
    """
    # Get all serial ports matching our VID/PID
    all_ports = list(list_ports.comports())
    cat_ports = [
        p for p in all_ports if p.vid == CATSNIFFER_VID and p.pid == CATSNIFFER_PID
    ]

    if not cat_ports:
        return []

    # Sort consistently across systems
    cat_ports.sort(key=lambda x: x.device)

    # Group ports by device using serial number
    devices_by_serial = _identify_ports_by_serial(cat_ports)

    catnips = []
    device_id = 1

    for serial_num, ports in sorted(devices_by_serial.items()):
        # Each CatSniffer should have exactly 3 ports
        if len(ports) < 3:
            # Incomplete device, skip it
            continue

        # Sort ports for this specific device
        ports.sort(key=lambda x: x.device)

        # Intelligently map the ports
        ports_dict = _map_ports_intelligent(ports)

        # Only create device if we successfully mapped all 3 ports
        if len(ports_dict) == 3:
            device = CatSnifferDevice(
                device_id=device_id,
                bridge_port=ports_dict.get("Cat-Bridge"),
                lora_port=ports_dict.get("Cat-LoRa"),
                shell_port=ports_dict.get("Cat-Shell"),
            )
            catnips.append(device)
            device_id += 1

    return catnips


def catnip_get_device(device_id=None):
    """Get a single CatSniffer device, optionally by ID."""
    devices = catnip_get_devices()
    if not devices:
        return None

    if device_id is not None:
        for dev in devices:
            if dev.device_id == device_id:
                return dev
        return None

    return devices[0]


def catnip_get_port():
    """Legacy function - returns the bridge port of the first device."""
    device = catnip_get_device()
    if device and device.bridge_port:
        return device.bridge_port
    return DEFAULT_COMPORT


class SerialConnection:
    """Base serial connection for raw data streams."""

    def __init__(self, port="", baudrate=DEFAULT_BAUDRATE):
        self.port = port
        self.baudrate = baudrate
        self.connection = serial.Serial()

    def connect(self) -> bool:
        try:
            self.connection = serial.Serial(
                self.port, self.baudrate, timeout=2, dsrdtr=False, rtscts=False
            )
            self.connection.setDTR(False)
            self.connection.setRTS(False)
            return True
        except Exception:
            return False

    def read(self, size=1024) -> bytes:
        return self.connection.read(size)

    def readline(self) -> bytes:
        return self.connection.readline()

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
                self.port,
                self.baudrate,
                timeout=self.timeout,
                dsrdtr=False,
                rtscts=False,
            )
            self.connection.setDTR(False)
            self.connection.setRTS(False)
            time.sleep(0.05)
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
            self.connection.reset_input_buffer()
            self.connection.reset_output_buffer()

            cmd_bytes = (command + "\r\n").encode("ascii")
            self.connection.write(cmd_bytes)
            self.connection.flush()

            # Read until 150 ms of silence after the last byte.  The old
            # approach (fixed 200 ms pre-sleep + break-on-empty) caused early
            # exits on Windows where USB CDC delivers data in bursts with gaps
            # between them, causing partial responses to be returned.
            response = b""
            deadline = time.time() + timeout
            last_rx = None

            while time.time() < deadline:
                waiting = self.connection.in_waiting
                if waiting:
                    chunk = self.connection.read(waiting)
                    response += chunk
                    last_rx = time.time()
                    time.sleep(0.02)
                else:
                    if last_rx and (time.time() - last_rx) >= 0.15:
                        break
                    time.sleep(0.02)

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


class Catnip(SerialConnection):
    """Main CatSniffer class for bridge port communication."""

    def __init__(self, port=None):
        super(Catnip, self).__init__()
        if port is None:
            port = catnip_get_port()
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

    def check_firmware_by_metadata(
        self, expected_fw_id: str, shell_port: str = None
    ) -> bool:
        """
        Verify the firmware using the RP2040 metadata system.

        This method is much more reliable than check_sniffle_firmware() because
        it queries the ID stored in the RP2040 flash instead of trying
        to communicate with the CC1352 firmware.

        Args:
            expected_fw_id: Expected ID ("sniffle", "ti_sniffer", etc.)
            shell_port: Shell port (optional, inferred from bridge_port if not provided)

        Returns:
            bool: True if the firmware matches, False otherwise
        """
        from .fw_metadata import FirmwareMetadata

        # shell_port must be provided; inferring it from bridge_port is unreliable
        # cross-platform (COM numbers on Windows are not contiguous by interface).
        if shell_port is None:
            return False

        try:
            # Create shell connection
            shell = ShellConnection(port=shell_port)
            if not shell.connect():
                return False

            # Query metadata
            metadata = FirmwareMetadata(shell)
            current_id = metadata.get_firmware_id()

            shell.disconnect()

            if not current_id:
                return False

            return current_id == expected_fw_id

        except Exception:
            return False

    def check_sniffle_firmware_smart(
        self, shell_port: str = None, timeout=3, max_retries=2
    ) -> bool:
        """
        Intelligent version that first tries metadata, then falls back to direct communication.

        ATTEMPT ORDER:
        1. Query RP2040 metadata (faster and more reliable)
        2. If it fails, try direct communication with Sniffle (old method)

        Args:
            shell_port: Shell port for metadata
            timeout: Timeout for direct communication
            max_retries: Retries for direct communication

        Returns:
            bool: True if Sniffle is detected
        """
        # METHOD 1: Query metadata (preferred)
        if shell_port:
            if self.check_firmware_by_metadata("sniffle", shell_port):
                return True
        elif self.port:
            # Try to infer shell port if possible
            if self.check_firmware_by_metadata("sniffle"):
                return True

        # METHOD 2: Fallback to direct communication (old method)
        # IMPORTANT: Ensure the connection is closed before trying direct communication
        try:
            if (
                hasattr(self, "connection")
                and self.connection
                and self.connection.is_open
            ):
                self.disconnect()
            time.sleep(0.2)
        except:
            pass

        return self.check_sniffle_firmware(timeout, max_retries)

    def check_sniffle_firmware(self, timeout=3, max_retries=2) -> bool:
        """
        Check if Sniffle firmware is loaded by sending a command marker request.

        Args:
            timeout: Timeout in seconds for each attempt
            max_retries: Number of retry attempts if port is busy

        Returns:
            bool: True if Sniffle firmware responds correctly, False otherwise
        """
        import time
        from base64 import b64encode, b64decode
        from binascii import Error as BAError

        # Sniffle command: 0x24 (CMD_MARKER)
        flag = [0x24]
        b0 = (len(flag) + 3) // 3
        cmd = bytes([b0, *flag])
        msg = b64encode(cmd) + b"\r\n"

        for attempt in range(max_retries + 1):
            try:
                # If it's not the first attempt, wait before retrying
                if attempt > 0:
                    time.sleep(1)  # Wait 1 second between retries

                # Try to connect
                if not self.connect():
                    if attempt < max_retries:
                        continue  # Retry
                    return False

                # Configure timeout
                self.connection.timeout = timeout

                # Clear buffers with error handling
                try:
                    self.connection.reset_input_buffer()
                    self.connection.reset_output_buffer()
                except Exception:
                    # If cleanup fails, close and retry
                    self.disconnect()
                    if attempt < max_retries:
                        continue
                    return False

                # Send command
                self.write(msg)
                time.sleep(0.2)  # Give more time to respond

                # Try to read response
                start_time = time.time()
                pkt = b""

                while time.time() - start_time < timeout:
                    try:
                        line = self.readline()
                        if line and len(line) > 0:
                            pkt = line
                            break
                    except Exception:
                        # Error reading, continue waiting
                        pass
                    time.sleep(0.05)

                # Verify if we received a response
                if not pkt or len(pkt) == 0:
                    self.disconnect()
                    if attempt < max_retries:
                        continue  # Retry
                    return False

                # Decode response
                try:
                    decoded = b64decode(pkt.rstrip())
                    # Sniffle must respond with at least 3 bytes
                    if len(decoded) >= 3:
                        self.disconnect()
                        return True
                    else:
                        self.disconnect()
                        if attempt < max_retries:
                            continue
                        return False
                except (BAError, ValueError):
                    self.disconnect()
                    if attempt < max_retries:
                        continue
                    return False

            except serial.SerialException as e:
                # Port busy or access error
                try:
                    self.disconnect()
                except:
                    pass

                if attempt < max_retries:
                    continue  # Retry
                return False

            except Exception as e:
                # Another error
                try:
                    self.disconnect()
                except:
                    pass

                if attempt < max_retries:
                    continue
                return False
            finally:
                # Ensure disconnection
                try:
                    if (
                        hasattr(self, "connection")
                        and self.connection
                        and self.connection.is_open
                    ):
                        self.disconnect()
                except:
                    pass

        return False


class LoRaConnection(SerialConnection):
    """
    Connection for LoRa data stream port (Cat-LoRa / SX1262).

    Uses a short read timeout so the streaming loop stays responsive
    to KeyboardInterrupt and can detect gaps between frames without
    blocking the entire thread.
    """

    # Timeout used while waiting for the next byte of a frame.
    # Short enough to feel responsive, long enough not to spin-burn CPU.
    STREAM_TIMEOUT = 0.5

    def __init__(self, port=""):
        super(LoRaConnection, self).__init__(port=port)

    def connect(self) -> bool:
        """Open the serial port with the streaming timeout."""
        try:
            self.connection = serial.Serial(
                self.port,
                self.baudrate,
                timeout=self.STREAM_TIMEOUT,
                dsrdtr=False,
                rtscts=False,
            )
            self.connection.setDTR(False)
            self.connection.setRTS(False)
            return True
        except Exception:
            return False

    def read_frame(self, start_of_frame: bytes, max_frame_bytes: int = 512) -> bytes:
        """
        Read one complete LoRa frame from the stream.

        Blocks until a frame starting with *start_of_frame* is found, then
        accumulates bytes until no more data arrives within STREAM_TIMEOUT.
        Returns the raw bytes of the frame (including the SOF prefix), or
        ``None`` if nothing was received before the timeout expired.

        This replaces the bare ``readline()`` call in the bridge loop and
        makes the framing logic explicit and resilient to partial reads.

        Args:
            start_of_frame: Magic bytes that mark the beginning of a frame.
            max_frame_bytes: Safety cap — frames larger than this are discarded.

        Returns:
            Raw frame bytes starting with *start_of_frame*, or None.
        """
        buf = b""

        try:
            # Phase 1: wait for the SOF marker.
            # read_until is fine here because the underlying timeout will
            # unblock us if no data arrives.
            raw = self.connection.read_until(start_of_frame)
            if not raw or start_of_frame not in raw:
                return None  # Timeout — nothing on the wire

            # Trim everything before the SOF so we always start clean.
            sof_idx = raw.rfind(start_of_frame)
            buf = raw[sof_idx:]  # starts with SOF

            # Phase 2: accumulate the rest of the frame.
            # Keep reading small chunks as long as bytes keep arriving.
            deadline = time.time() + self.STREAM_TIMEOUT
            while time.time() < deadline:
                waiting = self.connection.in_waiting
                if waiting:
                    chunk = self.connection.read(waiting)
                    buf += chunk
                    deadline = time.time() + self.STREAM_TIMEOUT  # reset on new data
                    if len(buf) >= max_frame_bytes:
                        break
                else:
                    time.sleep(0.005)  # brief yield — avoids spinning

            return buf if buf else None

        except serial.SerialException:
            return None

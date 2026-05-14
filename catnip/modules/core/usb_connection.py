"""
usb_connection.py — Standardized CatSniffer USB serial port management.

The CatSniffer RP2040 firmware exposes three USB CDC-ACM interfaces:

    Interface 0  →  Cat-Bridge  (CC1352 binary sniffer data, CDC0)
    Interface 1  →  Cat-LoRa   (SX1262 LoRa/FSK stream, CDC1)
    Interface 2  →  Cat-Shell  (RP2040 text config shell, CDC2)

The host OS assigns COM/ttyACM numbers non-deterministically.  This
module uses a three-stage strategy to resolve interface roles:

    1. Description / interface name substring match ("bridge", "lora", "shell")
    2. USB location field interface index ("bus-port:config.N" → N)
    3. Positional fallback on sorted device path

Multiple simultaneous devices are supported: ports are first grouped by
USB serial number (shared by all three interfaces of one device), with
USB location prefix used as a fallback when the serial number is absent.

Cross-platform notes:
    Linux   — location field always present; description may contain role name.
    macOS   — location field present; description may be generic.
    Windows — location may be absent for some interfaces; COM numbers are not
              ordered by interface index, making positional fallback unreliable
              without location data.  Strategies 1 and 2 are preferred.
"""

import re
import time
import serial
from serial.tools import list_ports
from typing import Dict, List, Optional

try:
    import usb.core  # noqa: F401
    import usb.util  # noqa: F401

    _HAS_PYUSB = True
except ImportError:
    _HAS_PYUSB = False


# ── USB identifiers ──────────────────────────────────────────────────────────

CATSNIFFER_VID = 0x1209
CATSNIFFER_PID = 0xBABB

# ── Serial defaults ───────────────────────────────────────────────────────────

DEFAULT_BAUDRATE = 115200
DEFAULT_COMPORT = "/dev/ttyUSB0"

# ── Interface role labels (match RP2040 firmware CDC node labels) ─────────────

ROLE_BRIDGE = "Cat-Bridge"  # CDC0 — CC1352 raw binary bridge
ROLE_LORA = "Cat-LoRa"  # CDC1 — SX1262 LoRa/FSK data stream
ROLE_SHELL = "Cat-Shell"  # CDC2 — RP2040 text configuration shell

# USB interface index → role  (from firmware: cdc_acm_uart0 / 1 / 2)
# Each CDC-ACM instance occupies 2 USB interfaces (communication + data), so
# the communication interface numbers are 0, 2, 4 — not 0, 1, 2.
# Both Linux (LOCATION=bus:cfg.N) and Windows (LOCATION=bus:x.N) expose
# these same USB interface numbers in the location field.
_INTF_TO_ROLE: Dict[int, str] = {0: ROLE_BRIDGE, 2: ROLE_LORA, 4: ROLE_SHELL}

# Description keyword → role  (case-insensitive sub-string match)
_DESC_TO_ROLE: Dict[str, str] = {
    "bridge": ROLE_BRIDGE,
    "lora": ROLE_LORA,
    "shell": ROLE_SHELL,
}

# pyserial interface attribute keyword → role
_INTF_NAME_TO_ROLE: Dict[str, str] = {
    "Bridge": ROLE_BRIDGE,
    "LoRa": ROLE_LORA,
    "Shell": ROLE_SHELL,
}


# ════════════════════════════════════════════════════════════════════════════ #
# Device model                                                                 #
# ════════════════════════════════════════════════════════════════════════════ #


class CatSnifferDevice:
    """Physical CatSniffer unit with its three serial port paths."""

    def __init__(
        self,
        device_id: int = 1,
        bridge_port: Optional[str] = None,
        lora_port: Optional[str] = None,
        shell_port: Optional[str] = None,
    ) -> None:
        self.device_id = device_id
        self.bridge_port = bridge_port
        self.lora_port = lora_port
        self.shell_port = shell_port

    def is_valid(self) -> bool:
        """True when all three ports are detected."""
        return all([self.bridge_port, self.lora_port, self.shell_port])

    def __str__(self) -> str:
        return f"CatSniffer #{self.device_id}"

    def __repr__(self) -> str:
        return (
            f"CatSnifferDevice(id={self.device_id}, "
            f"bridge={self.bridge_port!r}, "
            f"lora={self.lora_port!r}, "
            f"shell={self.shell_port!r})"
        )


# ════════════════════════════════════════════════════════════════════════════ #
# Port discovery                                                               #
# ════════════════════════════════════════════════════════════════════════════ #


def _group_ports_by_device(cat_ports: list) -> Dict[str, list]:
    """
    Group pyserial ListPortInfo entries by physical device.

    Grouping key priority:
        1. Serial number from HWID string ("SER=XXXX" or "SER:XXXX").
        2. port.serial_number attribute.
        3. USB location prefix (the "bus-hub.port" part before the first ':').

    Using only the location prefix (not the full location string) is critical:
    the interface index appended after the colon differs per port, so grouping
    on the full string would create a separate group for every interface.
    On Windows, location may be absent for some interfaces — in that case
    the serial number (if present) keeps all interfaces in the same group.
    """
    groups: Dict[str, list] = {}

    for port in cat_ports:
        key = "unknown"

        if port.hwid:
            m = re.search(r"SER[=:]([A-Fa-f0-9]+)", port.hwid)
            if m:
                key = m.group(1)
            elif port.serial_number:
                key = port.serial_number
        elif port.serial_number:
            key = port.serial_number

        # Location fallback — only when it contains ':', confirming the
        # "bus-port:config.interface" format; the prefix is sufficient.
        if key == "unknown" and port.location and ":" in port.location:
            key = port.location.split(":")[0]

        groups.setdefault(key, []).append(port)

    return groups


def _map_roles(ports: list) -> Dict[str, str]:
    """
    Map a group of same-device ports to {role: device_path}.

    Three strategies are applied in order; mapping stops once all three
    roles are resolved.

    Strategy 1 — description/interface name substring match:
        Reliable when the OS driver exposes the USB interface descriptor
        string in the port description or interface fields.  Works on
        recent Linux kernels and some Windows CDC drivers.

    Strategy 2 — USB location interface index:
        The location field has the form "bus-hub.port:config.interface"
        (e.g. "1-2.1:1.0").  The last numeric segment after the colon is
        the USB interface index, which maps 1:1 to the firmware's CDC node
        order (0→Bridge, 1→LoRa, 2→Shell).  Reliable on Linux and Windows
        when location is present for all interfaces.

    Strategy 3 — positional fallback (sorted device path):
        Used when location data is missing.  On Windows the OS typically
        assigns COM numbers in ascending order of USB interface index, so
        sorted port names correspond to interfaces 0, 1, 2 respectively.
        Only unassigned roles and unassigned ports are considered.
    """
    result: Dict[str, str] = {}

    # Strategy 1a — description substring (case-insensitive)
    for port in ports:
        desc = (port.description or "").lower()
        for keyword, role in _DESC_TO_ROLE.items():
            if keyword in desc and role not in result:
                result[role] = port.device
                break

    # Strategy 1b — pyserial 'interface' attribute (populated on some platforms)
    if len(result) < 3:
        for port in ports:
            intf_name = getattr(port, "interface", None) or ""
            for keyword, role in _INTF_NAME_TO_ROLE.items():
                if keyword in intf_name and role not in result:
                    result[role] = port.device

    # Strategy 1c — LOCATION embedded in the HWID string
    # pyserial on Windows normalises the HWID to:
    #   "USB VID:PID=XXXX:YYYY SER=... LOCATION=bus-hub:x.N"
    # where N is the USB interface number (0, 2, 4 for 3 CDC-ACM instances).
    # This catches devices where port.location is absent but hwid is not.
    if len(result) < 3:
        for port in ports:
            if not port.hwid:
                continue
            m = re.search(r"LOCATION=\S+:(?:\w+)\.(\d+)", port.hwid, re.IGNORECASE)
            if m:
                role = _INTF_TO_ROLE.get(int(m.group(1)))
                if role and role not in result:
                    result[role] = port.device

    # Strategy 2 — USB location interface index
    if len(result) < 3:
        for port in ports:
            if not (port.location and ":" in port.location):
                continue
            try:
                intf_idx = int(port.location.split(":")[-1].split(".")[-1])
                role = _INTF_TO_ROLE.get(intf_idx)
                if role and role not in result:
                    result[role] = port.device
            except (ValueError, IndexError):
                pass

    # Strategy 3 — positional fallback on sorted device path
    if len(result) < 3:
        role_order = [ROLE_BRIDGE, ROLE_LORA, ROLE_SHELL]
        already_used = set(result.values())
        role_idx = 0

        for port in sorted(ports, key=lambda p: p.device):
            if port.device in already_used:
                continue
            while role_idx < len(role_order) and role_order[role_idx] in result:
                role_idx += 1
            if role_idx >= len(role_order):
                break
            result[role_order[role_idx]] = port.device
            already_used.add(port.device)
            role_idx += 1

    return result


def find_devices() -> List[CatSnifferDevice]:
    """
    Return all connected CatSniffer devices with their three ports mapped.

    Devices with fewer than three detectable interfaces are skipped.
    """
    all_ports = list(list_ports.comports())
    cat_ports = [
        p for p in all_ports if p.vid == CATSNIFFER_VID and p.pid == CATSNIFFER_PID
    ]

    if not cat_ports:
        return []

    cat_ports.sort(key=lambda p: p.device)
    groups = _group_ports_by_device(cat_ports)
    devices: List[CatSnifferDevice] = []
    dev_id = 1

    for _key, ports in sorted(groups.items()):
        if len(ports) < 3:
            continue

        ports.sort(key=lambda p: p.device)
        role_map = _map_roles(ports)

        if len(role_map) == 3:
            devices.append(
                CatSnifferDevice(
                    device_id=dev_id,
                    bridge_port=role_map.get(ROLE_BRIDGE),
                    lora_port=role_map.get(ROLE_LORA),
                    shell_port=role_map.get(ROLE_SHELL),
                )
            )
            dev_id += 1

    return devices


def find_device(device_id: Optional[int] = None) -> Optional[CatSnifferDevice]:
    """Return one CatSniffer device, optionally filtered by numeric ID."""
    devices = find_devices()
    if not devices:
        return None
    if device_id is not None:
        return next((d for d in devices if d.device_id == device_id), None)
    return devices[0]


def get_bridge_port() -> str:
    """Return the bridge port path of the first detected device."""
    dev = find_device()
    return dev.bridge_port if dev and dev.bridge_port else DEFAULT_COMPORT


# ════════════════════════════════════════════════════════════════════════════ #
# Low-level utility                                                             #
# ════════════════════════════════════════════════════════════════════════════ #


def open_serial_port(
    port: str,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = 2.0,
    **kwargs,
) -> Optional[serial.Serial]:
    """
    Open *port* with the settings required for CatSniffer Shell/LoRa CDC interfaces.

    dsrdtr and rtscts are always False to disable hardware flow control.
    DTR is asserted (True) so that Zephyr's USB CDC ACM stack recognises the
    host as connected and processes incoming data — required on Windows where
    the OS does not auto-assert DTR on port open (unlike Linux/macOS).

    Returns the open Serial instance, or None on failure.
    """
    try:
        sp = serial.Serial(
            port,
            baudrate,
            timeout=timeout,
            dsrdtr=False,
            rtscts=False,
            **kwargs,
        )
        sp.dtr = True
        return sp
    except serial.SerialException:
        return None


# ════════════════════════════════════════════════════════════════════════════ #
# Connection base                                                               #
# ════════════════════════════════════════════════════════════════════════════ #


class _SerialBase:
    """
    Common serial port wrapper.

    Hardware flow control (dsrdtr / rtscts) is always disabled.  DTR is NOT
    touched here so that each subclass can apply the correct polarity:
      - BridgeConnection keeps DTR=False (prevents inadvertent CC1352 reset).
      - ShellConnection / LoRaConnection assert DTR=True so Zephyr's CDC ACM
        stack recognises the host as connected on Windows.
    """

    def __init__(
        self,
        port: str = "",
        baudrate: int = DEFAULT_BAUDRATE,
        timeout: float = 2.0,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.connection: Optional[serial.Serial] = None

    # ── lifecycle ─────────────────────────────────────────────────────────

    def _open(self, **kwargs) -> serial.Serial:
        """Open self.port with hardware flow control disabled."""
        sp = serial.Serial(
            self.port,
            self.baudrate,
            timeout=self.timeout,
            dsrdtr=False,
            rtscts=False,
            **kwargs,
        )
        return sp

    def connect(self) -> bool:
        """Open the serial port. Returns True on success."""
        try:
            self.connection = self._open()
            return True
        except Exception:
            return False

    def disconnect(self) -> None:
        """Flush and close the serial port."""
        if self.connection:
            try:
                if self.connection.is_open:
                    self.connection.flush()
                    self.connection.close()
            except Exception:
                pass
            self.connection = None

    def is_connected(self) -> bool:
        return self.connection is not None and self.connection.is_open

    def set_port(self, port: str) -> None:
        self.port = port

    # ── I/O ──────────────────────────────────────────────────────────────

    def flush(self) -> None:
        if self.connection:
            self.connection.flush()

    def write(self, data: bytes) -> None:
        if self.connection:
            self.connection.write(data)

    def read(self, size: int = 1024) -> bytes:
        return self.connection.read(size) if self.connection else b""

    def readline(self) -> bytes:
        return self.connection.readline() if self.connection else b""

    # ── context manager ───────────────────────────────────────────────────

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()


# ════════════════════════════════════════════════════════════════════════════ #
# Specialised connection classes                                                #
# ════════════════════════════════════════════════════════════════════════════ #


class BridgeConnection(_SerialBase):
    """
    Raw binary bridge to the CC1352 (Cat-Bridge / CDC0 / Interface 0).

    Transparent byte-stream; framing and protocol interpretation are handled
    by the layer above (e.g. SnifferTI, Sniffle).

    DTR and RTS are held low so the CC1352 is not inadvertently reset when
    the port is opened.  cc2538.py toggles them deliberately for bootloader
    entry / exit.
    """

    def _open(self, **kwargs) -> serial.Serial:
        sp = super()._open(**kwargs)
        sp.dtr = False
        sp.rts = False
        return sp

    def read_until(self, terminator: bytes) -> Optional[bytes]:
        """
        Read bytes until *terminator* appears (inclusive).

        Returns the slice from the start up to and including *terminator*,
        or None if it never appeared before the read timeout.
        """
        if not self.connection:
            return None
        try:
            raw = self.connection.read_until(terminator)
            idx = raw.find(terminator)
            return raw[: idx + len(terminator)] if idx != -1 else None
        except serial.SerialException:
            return None


class LoRaConnection(_SerialBase):
    """
    Streaming connection for the SX1262 LoRa/FSK port (Cat-LoRa / CDC1 / Interface 1).

    The short STREAM_TIMEOUT keeps the receive loop responsive to
    KeyboardInterrupt and lets it detect natural inter-frame gaps without
    blocking the thread for an excessive duration.
    """

    STREAM_TIMEOUT: float = 0.5

    def __init__(
        self,
        port: str = "",
        baudrate: int = DEFAULT_BAUDRATE,
        timeout: Optional[float] = None,
    ) -> None:
        super().__init__(
            port=port,
            baudrate=baudrate,
            timeout=timeout if timeout is not None else self.STREAM_TIMEOUT,
        )

    def connect(self) -> bool:
        try:
            self.connection = self._open()
            self.connection.dtr = True  # signal "host connected" to Zephyr CDC ACM
            return True
        except Exception:
            return False

    def read_frame(
        self,
        start_of_frame: bytes,
        max_frame_bytes: int = 512,
    ) -> Optional[bytes]:
        """
        Block until a frame starting with *start_of_frame* arrives, then
        accumulate bytes until STREAM_TIMEOUT seconds of silence.

        Returns the raw frame (SOF prefix included), or None on timeout.
        Resets the deadline on every new chunk received so that a slow but
        continuous burst is not cut short.
        """
        if not self.connection:
            return None

        try:
            raw = self.connection.read_until(start_of_frame)
            if not raw or start_of_frame not in raw:
                return None

            buf = raw[raw.rfind(start_of_frame) :]
            deadline = time.monotonic() + self.STREAM_TIMEOUT

            while time.monotonic() < deadline:
                waiting = self.connection.in_waiting
                if waiting:
                    buf += self.connection.read(waiting)
                    deadline = time.monotonic() + self.STREAM_TIMEOUT
                    if len(buf) >= max_frame_bytes:
                        break
                else:
                    time.sleep(0.005)

            return buf or None

        except serial.SerialException:
            return None


class ShellConnection(_SerialBase):
    """
    Text command/response shell for the RP2040 config port
    (Cat-Shell / CDC2 / Interface 2).

    Response collection uses a 150 ms inactivity window instead of a fixed
    sleep.  On Windows the USB CDC driver delivers shell output in multiple
    bursts separated by short gaps; a fixed sleep would either truncate the
    response or waste time waiting for data that has already arrived.
    """

    _SILENCE_S: float = 0.15  # seconds of silence that ends a response

    def __init__(
        self,
        port: str = "",
        baudrate: int = DEFAULT_BAUDRATE,
        timeout: float = 1.0,
    ) -> None:
        super().__init__(port=port, baudrate=baudrate, timeout=timeout)

    def connect(self) -> bool:
        try:
            self.connection = self._open()
            self.connection.dtr = True  # signal "host connected" to Zephyr CDC ACM
            time.sleep(0.05)  # brief settle before the first command
            return True
        except Exception:
            return False

    def send_command(
        self,
        command: str,
        timeout: Optional[float] = None,
    ) -> Optional[str]:
        """
        Send *command* (ASCII text) and return the decoded response string.

        Automatically connects if not already connected.  Returns None on
        any error or connection failure — never raises.
        """
        if not self.connection:
            if not self.connect():
                return None

        conn = self.connection
        if conn is None:
            return None

        effective_timeout = timeout if timeout is not None else self.timeout

        try:
            conn.reset_input_buffer()
            conn.reset_output_buffer()

            conn.write((command + "\r\n").encode("ascii"))
            conn.flush()

            response: bytes = b""
            deadline: float = time.monotonic() + effective_timeout
            last_rx: Optional[float] = None

            while time.monotonic() < deadline:
                waiting = conn.in_waiting
                if waiting:
                    response += conn.read(waiting)
                    last_rx = time.monotonic()
                    time.sleep(0.02)
                else:
                    if (
                        last_rx is not None
                        and (time.monotonic() - last_rx) >= self._SILENCE_S
                    ):
                        break
                    time.sleep(0.02)

            return response.decode("ascii", errors="ignore").strip()

        except Exception:
            return None

    def enter_bootloader(self) -> bool:
        """Send 'boot' to put the CC1352 into BSL mode via the RP2040."""
        return self.send_command("boot", timeout=2.0) is not None

    def exit_bootloader(self) -> bool:
        """Send 'exit' to leave BSL mode."""
        return self.send_command("exit", timeout=2.0) is not None

# External
import enum
import time
from base64 import b64encode, b64decode
from binascii import Error as BAError

# External
import serial
from serial.tools import list_ports

CATSNIFFER_VID = 11914
CATSNIFFER_PID = 192
DEFAULT_COMPORT = "/dev/ttyUSB0"
COMMAND_ENTER_BOOTLOADER = "ñÿ<boot>ÿñ"
COMMAND_EXIT_BOOTLOADER = "ñÿ<exit>ÿñ"


# Supported Sniffer protocols
class SniffingFirmware(enum.Enum):
    BLE = enum.auto()  # Sniffle Firmware
    ZIGBEE = enum.auto()  # TI Sniffer Firmware
    THREAD = enum.auto()  # TI Sniffer Firmware


def catsniffer_get_port():
    ports = list_ports.comports()
    for port in ports:
        if port.vid == CATSNIFFER_VID and port.pid == CATSNIFFER_PID:
            return port.device
    return DEFAULT_COMPORT


def cmd_bootloader_enter() -> bytes:
    return COMMAND_ENTER_BOOTLOADER.encode()


def cmd_bootloader_exit() -> bytes:
    return COMMAND_EXIT_BOOTLOADER.encode()


class CatsnifferException(Exception):
    pass


class SerialConnection:
    def __init__(self, port="", baudrate=921600):
        self.port = port
        self.baudrate = baudrate
        self.connection = serial.Serial()

    def connect(self) -> bool:
        try:
            self.connection = serial.Serial(self.port, self.baudrate)
            return True
        except Exception as e:
            return False

    def read(self, size=1024) -> bytes:
        return self.connection.read(size)

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


class Catsniffer(SerialConnection):
    def __init__(self):
        super(Catsniffer, self).__init__()
        self.set_port(catsniffer_get_port())

    def check_flag(self, flag, timeout=1) -> bool:
        stop = time.time() + timeout
        got = b""
        if not self.connect():
            return False
        while flag not in got:
            got += self.read(1)
            if time.time() > stop:
                self.disconnect()
                return False
        self.disconnect()
        return True

    def check_ti_firmware(self, timeout=1) -> bool:
        flag = b"TI Packet"
        return self.check_flag(flag=flag, timeout=timeout)

    def check_sniffle_firmware(self, timeout=1) -> bool:
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

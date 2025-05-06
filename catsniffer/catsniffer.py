import serial
from serial.tools import list_ports

CATSNIFFER_VID = 11914
CATSNIFFER_PID = 192
DEFAULT_BAUDRATE = 115200
DEFAULT_CRLF = "\r\n"
DEFAULT_COMPORT = "/dev/ttyUSB0"


def find_catsniffer_serial_port():
    ports = list_ports.comports()
    for port in ports:
        if port.vid == CATSNIFFER_VID and port.pid == CATSNIFFER_PID:
            return port.device
    return DEFAULT_COMPORT


class SerialError(Exception):
    pass


class Catsniffer:
    def __init__(self, port=find_catsniffer_serial_port(), baudrate=DEFAULT_BAUDRATE):
        if port is None:
            raise SerialError("Serial port is None")
        if baudrate is None:
            baudrate = DEFAULT_BAUDRATE
        self.serial_device = serial.Serial(port=port, baudrate=baudrate)
        self.serial_line_control = DEFAULT_CRLF
        self.serial_alive = False

    def set_serial_port(self, port):
        self.serial_device.port = port

    def set_baudrate(self, baudrate):
        if baudrate not in serial.Serial.BAUDRATES:
            raise ValueError("Invalid baudrate")
        self.serial_device.baudrate = baudrate

    def get_port(self):
        return self.serial_device.port

    def is_connected(self):
        return self.serial_device.is_open

    def resetBuffer(self):
        self.serial_device.reset_input_buffer()
        self.serial_device.reset_output_buffer()

    def validate_connection(self):
        try:
            self.serial_device.open()
            self.close()
            return True
        except (serial.SerialException, FileNotFoundError):
            return False

    def open(self):
        try:
            if self.is_connected():
                self.close()

            self.serial_device.open()

            self.resetBuffer()
            self.serial_alive = True
        except serial.SerialException as e:
            raise SerialError(e)

    def close(self):
        if self.is_connected():
            try:
                self.serial_device.close()
                self.serial_alive = False
            except serial.SerialException as e:
                raise SerialError(e)

    def recv(self):
        try:
            if self.serial_device.in_waiting > 0:
                bytestream = self.serial_device.readline()
                return bytestream
        except (serial.SerialException, UnicodeDecodeError):
            self.serial_alive = False
            return None

    def transmit(self, data):
        try:
            message = f"{data}{self.serial_line_control}"
            self.serial_device.write(message.encode())
        except serial.SerialException as e:
            print(f"Error: {e}")

    def reconnect(self, max_attempts=5):
        attempts = 0
        while not self.serial_alive and attempts < max_attempts:
            time.sleep(3)
            try:
                print("Reconnecting")
                self.open()
                return
            except SerialError:
                attempts += 1
        if not self.serial_alive:
            print("No connected")
        else:
            print("Connected")

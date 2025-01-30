import serial
import logging
import platform
import serial.tools.list_ports

BOARD_BAUDRATE = 921600
CATSNIFFER_VID = 11914
CATSNIFFER_PID = 192

if platform.system() == "Windows":
    DEFAULT_COMPORT = "COM1"
elif platform.system() == "Darwin":
    DEFAULT_COMPORT = "/dev/tty.usbmodem0001"
else:
    DEFAULT_COMPORT = "/dev/ttyACM0"

class SerialError(Exception):
    pass

class Board:
    def __init__(self):
        self.serial_worker = serial.Serial()
        self.serial_path = None
        self.serial_worker.baudrate = BOARD_BAUDRATE
        self.serial_worker.timeout = 2

    def __del__(self):
        self.serial_worker.close()

    def __str__(self):
        return "Board(serial_path={}, baudrate={})".format(
            self.serial_path, self.serial_worker.baudrate
        )

    def set_serial_path(self, serial_path):
        self.serial_path = serial_path
        self.serial_worker.port = self.serial_path

    def set_serial_baudrate(self, baudrate):
        self.serial_worker.baudrate = baudrate

    def reset_buffer(self):
        self.serial_worker.reset_input_buffer()
        self.serial_worker.reset_output_buffer()

    def write(self, data):
        if self.serial_worker.is_open:
            self.serial_worker.write(data)

    def is_connected(self):
        return self.serial_worker.is_open

    def open(self) -> bool:
        if not self.is_connected():
            try:
                self.serial_worker.open()
                self.reset_buffer()
            except serial.SerialException as e:
                print("Error opening serial port: %s", e)
                raise SerialError("Error opening serial port")

    def close(self):
        if self.is_connected():
            try:
                self.reset_buffer()
                self.serial_worker.close()
            except serial.SerialException as e:
                print("Error closing serial port: %s", e)
                raise e

    def recv(self):
        if not self.is_connected():
            self.open()

        try:
            bytestream = self.serial_worker.readline()
            return bytestream
        except serial.SerialTimeoutException:
            return "TIMEOUT"
        except serial.SerialException as e:
            print("Error reading from serial port: %s", e)
            raise e
    
    @staticmethod
    def find_catsniffer_serial_port():
        ports = serial.tools.list_ports.comports()
        for port in ports:
            if port.vid == CATSNIFFER_VID and port.pid == CATSNIFFER_PID:
                return port.device
        return DEFAULT_COMPORT
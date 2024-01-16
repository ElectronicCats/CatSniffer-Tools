import platform
import serial
import time
import serial.tools.list_ports
import threading

from .Definitions import START_OF_FRAME, END_OF_FRAME

if platform.system() == "Windows":
    DEFAULT_COMPORT = "COM1"
else:
    DEFAULT_COMPORT = "/dev/ttyACM0"

DEFAULT_SERIAL_BAUDRATE = 2000000


class UART(threading.Thread):
    def __init__(self, serial_port: str = DEFAULT_COMPORT):
        self.serial_worker = serial.Serial()
        self.serial_worker.port = serial_port
        self.serial_worker.baudrate = DEFAULT_SERIAL_BAUDRATE
        self.recv_cancel = False

    def __del__(self):
        self.serial_worker.close()

    def __str__(self):
        return f"Serial port: {self.serial_worker.port}"

    def set_serial_port(self, serial_port: str):
        self.serial_worker.port = serial_port

    def is_valid_connection(self) -> bool:
        try:
            self.open()
            self.close()
            return True
        except serial.SerialException as e:
            print(e)
            return False

    def open(self):
        self.serial_worker.open()
    
    def close(self):
        self.serial_worker.close()

    def is_connected(self):
        return self.serial_worker.is_open

    def send(self, data):
        self.serial_worker.write(data)

    def recv2(self):
        if not self.is_connected():
            self.open()
        try:
            if self.serial_worker.in_waiting == 0:
                return None

            time.sleep(0.01)
            bytestream = self.serial_worker.read(self.serial_worker.in_waiting)
            sof_index = 0
            
            while True:
                sof_index = bytestream.find(START_OF_FRAME, sof_index)
                if sof_index == -1:
                    #print(f"[UART] SOF - {sof_index} not found in {bytestream}")
                    bytestream += self.serial_worker.read(self.serial_worker.in_waiting)
                    continue
                
                eof_index = bytestream.find(END_OF_FRAME, sof_index)
                if eof_index == -1:
                    print(f"[UART] EOF - {eof_index} not found in {bytestream}")
                    break
                
                bytestream = bytestream[sof_index:eof_index+2]
                return bytestream
        except serial.SerialException as e:
            print("Serial recv2: ", e)
            return None
    
    def recv(self):
        if not self.is_connected():
            self.open()
        try:
            time.sleep(0.01)
            bytestream = self.serial_worker.read_until(END_OF_FRAME)
            sof_index = 0
            sof_index = bytestream.find(START_OF_FRAME, sof_index)
            if sof_index == -1:
                #print(f"[UART] SOF - {sof_index} not found in {bytestream}")
                bytestream += self.serial_worker.read(self.serial_worker.in_waiting)
            
            eof_index = bytestream.find(END_OF_FRAME, sof_index)
            if eof_index == -1:
                print(f"[UART] EOF - {eof_index} not found in {bytestream}")
                return None
            
            bytestream = bytestream[sof_index:eof_index+2]
            return bytestream
        except serial.SerialException as e:
            print(e)
            return None
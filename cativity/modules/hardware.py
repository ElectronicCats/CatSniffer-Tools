import serial
import logging
import serial.tools.list_ports
from .utils import TrivialLogger, SerialError

BOARD_BAUDRATE = 921600

class Board:
  def __init__(self, logger=None):
    self.serial_worker = serial.Serial()
    self.serial_path = None
    self.serial_worker.baudrate = BOARD_BAUDRATE
    self.logger = logger if logger else TrivialLogger()

  def __del__(self):
    self.serial_worker.close()
  
  def __str__(self):
    return "Board(serial_path={}, baudrate={})".format(self.serial_path, self.serial_worker.baudrate)
  
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
        logging.error("Error opening serial port: %s", e)
        raise SerialError("Error opening serial port")
  
  def close(self):
    if self.is_connected():
      try:
        self.reset_buffer()
        self.serial_worker.close()
      except serial.SerialException as e:
        logging.error("Error closing serial port: %s", e)
        raise e
  
  def recv(self):
    if not self.is_connected():
      self.open()
    
    try:
      bytestream = self.serial_worker.readline()
      if bytestream == b"":
        return None
      return bytestream
    except serial.SerialException as e:
      logging.error("Error reading from serial port: %s", e)
      raise e
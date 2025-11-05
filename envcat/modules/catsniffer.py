# External
import serial
from serial.tools import list_ports

class Catsniffer:
  CATSNIFFER_VID = 11914
  CATSNIFFER_PID = 192
  DEFAULT_COMPORT = "/dev/ttyUSB0"
  
  def __init__(self):
    pass
  
  @classmethod
  def get_port(clc):
    ports = list_ports.comports()
    for port in ports:
      if port.vid == clc.CATSNIFFER_VID and port.pid == clc.CATSNIFFER_PID:
          return port.device
    return clc.DEFAULT_COMPORT
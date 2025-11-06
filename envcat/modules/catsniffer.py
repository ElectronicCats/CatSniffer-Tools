# External
import serial
from serial.tools import list_ports

COMMAND_ENTER_BOOTLOADER = "ñÿ<boot>ÿñ"
COMMAND_EXIT_BOOTLOADER = "ñÿ<exit>ÿñ"

class Catsniffer:
  CATSNIFFER_VID = 11914
  CATSNIFFER_PID = 192
  DEFAULT_COMPORT = "/dev/ttyUSB0"
  
  def __init__(self):
    pass
  
  @classmethod
  def cmd_bootloader_enter(clc) -> bytes:
    return COMMAND_ENTER_BOOTLOADER.encode()
  
  @classmethod
  def cmd_bootloader_exit(clc) -> bytes:
    return COMMAND_EXIT_BOOTLOADER.encode()
  
  @classmethod
  def get_port(clc):
    ports = list_ports.comports()
    for port in ports:
      if port.vid == clc.CATSNIFFER_VID and port.pid == clc.CATSNIFFER_PID:
          return port.device
    return clc.DEFAULT_COMPORT
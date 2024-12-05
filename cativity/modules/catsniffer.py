import serial
import struct
import platform
from enum import Enum
from .utils import TrivialLogger
from .hardware import Board

CATSNIFFER_VID      = 11914
CATSNIFFER_PID      = 192
SNIFFER_CHANNELS    = range(11, 27)
SNIFFER_DEF_CHANNEL = 11
START_OF_FRAME      = b"\x40\x53"
END_OF_FRAME        = b"\x40\x45"

if platform.system() == "Windows":
    DEFAULT_COMPORT = "COM1"
elif platform.system() == "Darwin":
    DEFAULT_COMPORT = "/dev/tty.usbmodem0001"
else:
    DEFAULT_COMPORT = "/dev/ttyACM0"

class TISnifferPacket:
  class Commands(Enum):
    CMD_PING                      = 0x40
    CMD_START                     = 0x41
    CMD_STOP                      = 0x42
    CMD_PAUSE                     = 0x43
    CMD_RESUME                    = 0x44
    CMD_CFG_FREQUENCY             = 0x45
    CMD_CFG_PHY                   = 0x47
    CMD_CFG_WBMS_CHANNEL_TABLE    = 0x50
    CMD_CFG_BLE_INITIATOR_ADDRESS = 0x70

    def __str__(self):
      return str(self.value)
  
  class PacketCommand:
    def __init__(self, cmd, data=b''):
      self.cmd    = cmd
      self.data   = data
      self.packet = self.__pack()
    
    def calculate_fcs(self):
      if type(self.cmd) == int:
        self.cmd = self.cmd.to_bytes(1, byteorder="little")
      core_bytes = sum(self.cmd + len(self.data).to_bytes(2, byteorder="little"))
      if self.data != b'':
        core_bytes += sum(self.data)
      
      checksum = core_bytes & 0xFF
      return checksum.to_bytes(1, byteorder="little")

    def __pack(self):
      if type(self.cmd) == int:
        self.cmd = self.cmd.to_bytes(1, byteorder="little")
      return b''.join([START_OF_FRAME, self.cmd, len(self.data).to_bytes(2, byteorder="little"), self.data, self.calculate_fcs(), END_OF_FRAME])
  
    def __str__(self):
      return f"TISnifferPacket.PacketCommand(cmd={self.cmd}, data={self.data}, packet={self.packet})"

  def __init__(self, packet_bytes, logger=None):
    self.packet_bytes = packet_bytes
    # Packet struct
    self.sof     = None
    self.info    = None
    self.p_len   = None
    self.payload = None
    self.eof     = None
    self.logger          = logger if logger else TrivialLogger()

    self.__unpack()
  
  def __str__(self):
    return "TISnifferPacket(packet_bytes={})".format(self.packet_bytes)

  def __unpack_packet_info(self) -> tuple:
    """Unpack the packet info.
    Parameters:
      packet_info (bytes): The packet info to unpack.
      Returns: (packet_category, packet_type)
    Category: 2 bits -> Index: 6-7
    Type:     6 bits -> Index: 0-5"""
    packet_category = (self.info >> 6) & 0b11
    packet_type = self.info & 0b00111111
    return (packet_category, packet_type)
  
  def is_command_response(self) -> bool:
    return (
      self.__unpack_packet_info()[0] == 0x1 or
      self.__unpack_packet_info()[0] == 0x2
    )
  
  def __unpack(self):
    try:
      (self.sof, self.info, self.p_len) = struct.unpack_from("<HBH", self.packet_bytes)
      self.payload = self.packet_bytes[5:-2]
      if len(self.payload) > 7:
        # tmp_payload = self.packet_bytes[11:-4]
        # print("="*20)
        # timestamp = self.payload[:7]
        # print("Timestamp: ", int.from_bytes(timestamp, byteorder="little"))
        # print("RSSI: ", self.payload[-2])
        # print("Status: ", self.payload[-1])
        # print(self.packet_bytes.hex())
        # print("="*20)
        self.payload = self.payload[7:-2]
      self.eof = struct.unpack_from("<H", self.packet_bytes[-2:])
    except struct.error as e:
      self.logger.error("Error unpacking packet: %s", e)
      raise e
  
  @property
  def hex_payload(self):
    return self.payload.hex()
  


class Sniffer(Board):
  CONST_FRECUENCY = 65536  # 2^16 -> 16 bits -> MHz
  def __init__(self, channel=SNIFFER_DEF_CHANNEL, logger=None):
    super().__init__()
    self.catsniffer      = self.serial_worker
    self.channel         = channel
    self.channel_range   = SNIFFER_CHANNELS
    self.frequency       = 2405
    self.logger          = logger if logger else TrivialLogger()
  
  def __str__(self):
    return "Sniffer(catsniffer={}, channel={}, frequency={})".format(self.catsniffer, self.channel, self.frequency)

  def recv(self) -> bytes:
      if not self.is_connected():
        self.open()
      
      try:
        bytestream = self.serial_worker.read_until((END_OF_FRAME+START_OF_FRAME))
        sof_idx = 0
        eof_idx = bytestream.find((END_OF_FRAME+START_OF_FRAME), sof_idx)
        if eof_idx == -1:
          self.logger.error(f"Invalid frame received: {bytestream}")
          return None
        bytestream = START_OF_FRAME + bytestream[sof_idx:eof_idx+2]
        return bytestream
      except serial.SerialException as e:
        self.logger.error("Error reading from serial port: %s", e)
        raise e

  def set_channel(self, channel):
    if channel in self.channel_range:
      self.channel = channel
      self.frequency = 2405 + (self.channel - 11) * 5
    else:
      self.logger.error("Invalid channel: %d", channel)
      raise ValueError("Invalid channel")
  
  def __calculate_frational_frequency(self, frequency):
    integer_value = int(frequency)
    fractional_value = int((integer_value - integer_value) * self.CONST_FRECUENCY)
    return integer_value, fractional_value

  def __calculate_frequency(self, frequency):
    integer_value, fractional_value = self.__calculate_frational_frequency(frequency)
    frequency_int_bytes = integer_value.to_bytes(2, byteorder="little")
    frequency_frac_bytes = fractional_value.to_bytes(2, byteorder="little")
    return frequency_int_bytes + frequency_frac_bytes

  def get_frequency(self):
    return self.__calculate_frequency(self.frequency)

  @staticmethod
  def find_catsniffer_serial_port():
    ports = serial.tools.list_ports.comports()
    for port in ports:
      if port.vid == CATSNIFFER_VID and port.pid == CATSNIFFER_PID:
        return port.device
    return DEFAULT_COMPORT
  
  def __str__(self):
    return "Sniffer(catsniffer={}, channel={}, frequency={})".format(self.catsniffer, self.channel, self.frequency)
  
  def change_channel(self, channel):
    self.set_channel(channel)
    self.catsniffer.write(TISnifferPacket.PacketCommand(TISnifferPacket.Commands.CMD_STOP.value).packet)
    self.catsniffer.write(TISnifferPacket.PacketCommand(TISnifferPacket.Commands.CMD_CFG_PHY.value, b'\x12').packet)
    self.catsniffer.write(TISnifferPacket.PacketCommand(TISnifferPacket.Commands.CMD_CFG_FREQUENCY.value, self.get_frequency()).packet)
    self.catsniffer.write(TISnifferPacket.PacketCommand(TISnifferPacket.Commands.CMD_START.value).packet)

  def start_sniffer(self):
    self.catsniffer.open()
    self.catsniffer.write(TISnifferPacket.PacketCommand(TISnifferPacket.Commands.CMD_PING.value).packet)
    self.catsniffer.write(TISnifferPacket.PacketCommand(TISnifferPacket.Commands.CMD_STOP.value).packet)
    self.catsniffer.write(TISnifferPacket.PacketCommand(TISnifferPacket.Commands.CMD_CFG_PHY.value, b'\x12').packet)
    self.catsniffer.write(TISnifferPacket.PacketCommand(TISnifferPacket.Commands.CMD_CFG_FREQUENCY.value, self.get_frequency()).packet)
    self.catsniffer.write(TISnifferPacket.PacketCommand(TISnifferPacket.Commands.CMD_START.value).packet)
    self.logger.info("Sniffer started")
  
  def stop_sniffer(self):
    self.catsniffer.write(TISnifferPacket.PacketCommand(TISnifferPacket.Commands.CMD_STOP.value).packet)
    self.logger.info("Sniffer stopped")

  

  

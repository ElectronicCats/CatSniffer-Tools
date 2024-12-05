from scapy.layers.dot15d4 import *
from scapy.layers.zigbee import *

BEACON_CMD_ID = 7

def is_beacon_response(frame):
  if Dot15d4Beacon in frame and ZigBeeBeacon in frame:
    return True
  return False
def is_beacon_request(frame):
  if Dot15d4Cmd in frame and frame[Dot15d4Cmd].cmd_id == BEACON_CMD_ID:
    return True
  return False
def is_association_request(frame):
  if Dot15d4Cmd in frame and frame[Dot15d4Cmd].cmd_id == 0x01:
    return True
  return False
def is_association_response(frame):
  if Dot15d4Cmd in frame and frame[Dot15d4Cmd].cmd_id == 0x02:
    return True
  return False
def is_disassociation_request(frame):
  if Dot15d4Cmd in frame and frame[Dot15d4Cmd].cmd_id == 0x03:
    return True
  return False


  
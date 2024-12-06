import time
from scapy.layers.dot15d4 import *
from scapy.layers.zigbee import *
from scapy.config import conf
from .packets import is_beacon_request, is_beacon_response
from .graphs import Graphs

conf.dot15d4_protocol = "zigbee"

CORDINATOR_ADDR_SHORT = 0x0000

class NetworkStats:
  def __init__(self):
    self.start_time = time.time()
    self.end_time = 0
    self.beacons_requests = 0
    self.beacons_responses = 0
  
  def update_network_stats(self, packet):
    if is_beacon_request(packet):
      self.beacons_requests += 1
    if is_beacon_response(packet):
      self.beacons_responses += 1

class Network:
  def __init__(self):
    self.children = []
    self.parent_addr_src = None
    self.parent_addr_ext = None
    self.nStats = NetworkStats()
    self.grapher = Graphs()
  
  def dissect_packet(self, packet):
    pkt = Dot15d4(packet)
    new_pkt = {}
    self.nStats.update_network_stats(pkt)
    
    if pkt.haslayer(ZigbeeNWK):
      nwk_src = pkt[ZigbeeNWK].fields.get("source", None)
      ext_src = pkt[ZigbeeNWK].fields.get("ext_src", None)
      if nwk_src == CORDINATOR_ADDR_SHORT:
        if self.parent_addr_src == None:
          self.parent_addr_src = nwk_src
          if ext_src != None:
            self.parent_addr_ext = ext_src
        return None
      
      if nwk_src != None:
        if nwk_src not in self.children:
          if self.parent_addr_src != None:
            self.children.append(nwk_src)
            if nwk_src != None:
              new_pkt[str(nwk_src)] = nwk_src
            if ext_src != None:
              ext_src_mac = ':'.join(f"{(ext_src >> (8 * i)) & 0xFF:02x}" for i in range(7, -1, -1))
              new_pkt[str(nwk_src)] = ext_src
          return new_pkt
    
    return None

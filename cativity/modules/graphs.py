import time
from rich.live import Live
from rich.table import Table

HOPP_INTERVAL        = 3.1
REFRESH_INTERVAL     = 1.1
MAX_CHANNEL_ACTIVITY = 50

class Graphs:
  def __init__(self):
    self.running = True
    self.channel_activity = {}
    self.topology_activity = {}
    self.current_channel = 11
    self.channel_packets = 0
  
  def draw_bar(self, data,  char="❚"):
    if data == 0:
      return ""
    if data > MAX_CHANNEL_ACTIVITY:
      return f"{char*8} ({data}) {char*8}"
    return char * data
  
  def update_graph_value(self, channel_activity):
    self.channel_activity = channel_activity
  
  def update_topology_packets(self, packets):
    self.topology_activity = packets
  
  def update_channel_packets(self, packets):
    self.channel_packets = packets
  
  def update_channel(self, channel):
    self.current_channel = channel
  
  def __convert_to_mac(self, data):
    return ':'.join(f"{(data >> (8 * i)) & 0xFF:02x}" for i in range(7, -1, -1))
  
  def generate_topology_graph(self):
    self.table = Table(title=f"Network Topology - {0x0000}", title_justify="center", caption="Zigbee Network Topology", caption_justify="center")
    self.table.add_column("Children", style="cyan", no_wrap=True)
    self.table.add_column("Ext. Source", style="green", no_wrap=True)

    for parent, children in self.topology_activity.items():
      parent = int(parent)
      self.table.add_row(f"0x{parent:04x}", self.__convert_to_mac(children))

    return self.table
  
  def generate_channel_graph(self):
    self.table = Table(title="Channel Activity", title_justify="center", caption="Channel Hopping Activity", caption_justify="center")
    self.table.add_column("Current", style="red", no_wrap=True)
    self.table.add_column("Channel", style="cyan", no_wrap=True)
    self.table.add_column("Activity", style="green", no_wrap=True)
    self.table.add_column("Packets", style="magenta", no_wrap=True)
    
    for channel, data in self.channel_activity.items():
      channel_marker = ""
      if channel == self.current_channel:
        channel_marker = "---->"
      self.table.add_row(channel_marker, str(channel), str(self.draw_bar(data=data)), str(self.channel_activity[channel]))
    return self.table

  def stop(self):
    self.running = False
  
  def create_channel_graph(self):
    with Live(self.generate_channel_graph(), refresh_per_second=REFRESH_INTERVAL) as live:
      while self.running:
        time.sleep(0.4)
        live.update(self.generate_channel_graph(), refresh=True)

  def create_topology_graph(self):
    with Live(self.generate_topology_graph(), refresh_per_second=REFRESH_INTERVAL) as live:
      while self.running:
        time.sleep(0.4)
        live.update(self.generate_topology_graph(), refresh=True)


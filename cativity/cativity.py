"""
 CativityDetector - A tool to analyze the channel activity for Zigbee Networks
 Developed by astrobyte

 Thanks to @kevlem97 for the catbee repository, which was used as a reference for this project.
 GNU General Public License v3.0
 
  Usage: cativity.py catsniffer [options]
"""
import os
import sys
import logging
import threading
import queue
import time
import typer
from modules.utils import UsageError
from modules.catsniffer import Sniffer, TISnifferPacket
from modules.graphs import Graphs
from modules.network import Network

CHANNEL_HOPPING_INTERVAL    = 3.5
SCRIPT_NAME = os.path.basename(sys.argv[0])

logging.basicConfig(
    handlers=[logging.FileHandler("cativity.log"), logging.StreamHandler()],
    level="WARNING",
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

class Cativity:
  def __init__(self):
    self.app = typer.Typer(name="CativityDetector", help="A tool to analyze the channel activity for Zigbee Networks", add_completion=False, no_args_is_help=True, epilog="Hack the Bee!")
    self.app.command()(self.main)
    self.logger = logging.getLogger(SCRIPT_NAME)

    self.catsniffer = Sniffer(logger=logging.getLogger("CatSniffer"))
    self.grapher = Graphs()
    self.network = Network()
    self.capture_started = True
    self.packet_received = queue.Queue()
    self.channel_activity = {}
    self.fixed_channel = False
    self.__init_channel_map()
  
  def __init_channel_map(self):
    for channel in range(11, 27):
      self.channel_activity[channel] = 0
  
  def __print_banner(self):
    typer.secho("""
  ____      _   _       _ _         ____       _            _             
 / ___|__ _| |_(_)_   _(_) |_ _   _|  _ \  ___| |_ ___  ___| |_ ___  _ __ 
| |   / _` | __| \ \ / / | __| | | | | | |/ _ \ __/ _ \/ __| __/ _ \| '__|
| |__| (_| | |_| |\ V /| | |_| |_| | |_| |  __/ ||  __/ (__| || (_) | |   
 \____\__,_|\__|_| \_/ |_|\__|\__, |____/ \___|\__\___|\___|\__\___/|_|   
                              |___/                                       
""", fg=typer.colors.BRIGHT_YELLOW)
    typer.secho("A tool to analyze the channel activity fro Zigbee Networks", fg=typer.colors.BRIGHT_CYAN)
    typer.secho("Author: astrobyte", fg=typer.colors.BRIGHT_CYAN)
    typer.secho("Version: 1.0", fg=typer.colors.BRIGHT_CYAN)
    typer.secho("\n")


  def channel_handler(self):
    while self.capture_started:
      if self.fixed_channel:
        if len(self.packet_received.queue) > 0:
          self.channel_activity[self.catsniffer.channel] = len(self.packet_received.queue)
          self.grapher.update_graph_value(self.channel_activity)
      else:
        for channel in range(11, 27):
          self.catsniffer.change_channel(channel)
          self.grapher.update_channel(channel)
          time.sleep(CHANNEL_HOPPING_INTERVAL)
          if self.channel_activity[channel] == 0:
            self.channel_activity[channel] = len(self.packet_received.queue)
          else:
            self.channel_activity[channel] += len(self.packet_received.queue)
          
          self.grapher.update_graph_value(self.channel_activity)
          self.packet_received.queue.clear()
        

  def main(self,
      catsniffer: str = typer.Argument(help="Serial path to the CatSniffer", default=Sniffer.find_catsniffer_serial_port()),
      channel: int = typer.Option(None, help="Channel to start the sniffer", show_default=True),
      topology: bool = typer.Option(False, help="Show the network topology", show_default=True),
    ):
    if catsniffer is None:
        raise UsageError("Please provide the serial path to the CatSniffer")
    self.catsniffer.set_serial_path(catsniffer)
    

    if channel is not None:
      if channel < 11 or channel > 26:
        raise UsageError("Invalid channel. Please provide a channel between 11 and 26")
      self.catsniffer.set_channel(channel)
      if not topology:
        self.grapher.update_channel(channel)
        self.fixed_channel = True
        self.channel_activity = {}
        self.channel_activity[channel] = 0
    
    self.__print_banner()
    self.catsniffer.start_sniffer()
    
    if topology:
      typer.secho("Starting network topology analysis...", fg=typer.colors.BRIGHT_YELLOW)
      typer.secho(f"Channel sniffing: {self.catsniffer.channel}\n", fg=typer.colors.BRIGHT_YELLOW)
      topology_threat = threading.Thread(target=self.grapher.create_topology_graph, daemon=True)
      topology_threat.start()
    else:
      channel_threat = threading.Thread(target=self.channel_handler, daemon=True)
      channel_threat.start()
      grapher_threat = threading.Thread(target=self.grapher.create_channel_graph, daemon=True)
      grapher_threat.start()
    
      self.grapher.update_graph_value(self.channel_activity)
    
    while self.capture_started:
      packet = self.catsniffer.recv()
      if packet is not None:
        tisniffer_packet = TISnifferPacket(packet)
        if tisniffer_packet.is_command_response():
          continue
        self.packet_received.put(tisniffer_packet.payload)
        if topology:
          dissected_packet = self.network.dissect_packet(tisniffer_packet.payload)
          if dissected_packet is not None:
            self.grapher.update_topology_packets(dissected_packet)
    
    if topology:
      topology_threat.join()
    else:
      channel_threat.join()
      self.grapher.stop()
      grapher_threat.join()
    
  def stop(self):
    self.capture_started = False
    self.catsniffer.stop_sniffer()
    typer.secho("\nExiting...", fg=typer.colors.BRIGHT_RED)
    typer.secho("Happy Hacking!", fg=typer.colors.BRIGHT_YELLOW)

if __name__ == "__main__":
  catbee = Cativity()
  try:
    catbee.app()
  except UsageError as e:
    os._exit(1)
  except KeyboardInterrupt:
    catbee.stop()
    os._exit(0)
  except Exception as e:
    typer.echo(f"Error: {e}")
    os._exit(1)
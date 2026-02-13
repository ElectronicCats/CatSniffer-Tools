import time
import threading
import queue
import os
import sys
from ..catsniffer import Catsniffer, CatSnifferDevice
from protocol.sniffer_ti import SnifferTI, PacketCategory
from protocol.common import START_OF_FRAME, END_OF_FRAME
from .graphs import Graphs
from .network import Network

CHANNEL_HOPPING_INTERVAL = 3.5

class CativityRunner:
    def __init__(self, device: CatSnifferDevice, console=None):
        self.device = device
        self.console = console
        self.catsniffer = Catsniffer(port=device.bridge_port)
        self.grapher = Graphs()
        self.network = Network()
        self.protocol_filters = ["all", "zigbee", "thread"]
        self.protocol = "all"
        self.capture_started = False
        self.packet_received = queue.Queue()
        self.channel_activity = {}
        self.fixed_channel = False
        self.current_channel = 11
        self.ti_cmd = SnifferTI().Commands()
        self.__init_channel_map()

    def __init_channel_map(self):
        for channel in range(11, 27):
            self.channel_activity[channel] = 0

    def channel_handler(self):
        while self.capture_started:
            if self.fixed_channel:
                if not self.packet_received.empty():
                    # Instead of just counting what's in the queue, we accumulate
                    # but cativity original logic cleared it.
                    # Let's follow original logic approximately
                    count = 0
                    while not self.packet_received.empty():
                        self.packet_received.get()
                        count += 1
                    self.channel_activity[self.current_channel] += count
                    self.grapher.update_graph_value(self.channel_activity)
            else:
                for channel in range(11, 27):
                    if not self.capture_started:
                        break
                    self.current_channel = channel
                    # Change channel using TI commands
                    self.catsniffer.write(self.ti_cmd.stop())
                    time.sleep(0.05)
                    self.catsniffer.write(self.ti_cmd.config_freq(channel))
                    time.sleep(0.05)
                    self.catsniffer.write(self.ti_cmd.start())
                    
                    self.grapher.update_channel(channel)
                    time.sleep(CHANNEL_HOPPING_INTERVAL)
                    
                    count = 0
                    while not self.packet_received.empty():
                        self.packet_received.get()
                        count += 1
                    
                    self.channel_activity[channel] += count
                    self.grapher.update_graph_value(self.channel_activity)

    def run(self, channel=None, topology=False, protocol="all"):
        self.protocol = protocol
        self.capture_started = True
        
        if not self.catsniffer.connect():
            if self.console:
                self.console.print(f"[red]✗[/red] Failed to connect to {self.device.bridge_port}")
            return

        # Prepare device
        self.catsniffer.write(self.ti_cmd.ping())
        self.catsniffer.write(self.ti_cmd.stop())
        self.catsniffer.write(self.ti_cmd.config_phy())
        
        if channel is not None:
            self.fixed_channel = True
            self.current_channel = channel
            self.catsniffer.write(self.ti_cmd.config_freq(channel))
            self.grapher.update_channel(channel)
            # Reset activity for fixed channel to show live
            self.channel_activity = {channel: 0}
        
        self.catsniffer.write(self.ti_cmd.start())

        if topology:
            graph_thread = threading.Thread(
                target=self.grapher.create_topology_graph, 
                args=(self.console,),
                daemon=True
            )
        else:
            handler_thread = threading.Thread(target=self.channel_handler, daemon=True)
            handler_thread.start()
            graph_thread = threading.Thread(
                target=self.grapher.create_channel_graph, 
                args=(self.console,),
                daemon=True
            )
        
        graph_thread.start()

        try:
            while self.capture_started:
                data = self.catsniffer.read_until((END_OF_FRAME + START_OF_FRAME))
                if data:
                    full_packet = START_OF_FRAME + data
                    
                    # Extract packet category from the TI Sniffer protocol header
                    # Header: SOF(2) + Info(1) + Length(2)
                    if len(full_packet) > 2:
                        pkt_info = full_packet[2]
                        category = (pkt_info >> 6) & 0b11
                        
                        if category == PacketCategory.DATA_STREAMING_AND_ERROR.value:
                            # Payload extraction logic matching cativity's original structure
                            if len(full_packet) > 12:
                                payload = full_packet[12:-4]
                            else:
                                payload = full_packet[5:-2]
                            
                            packet_filtered = self.network.get_packet_filtered(payload, self.protocol)
                            if packet_filtered:
                                self.packet_received.put(packet_filtered)
                            
                            if topology:
                                dissected = self.network.dissect_packet(payload)
                                if dissected:
                                    self.grapher.update_topology_packets(dissected)
                time.sleep(0.01)
        except KeyboardInterrupt:
            self.stop()
        finally:
            self.stop()

    def stop(self):
        self.capture_started = False
        self.grapher.stop()
        if self.catsniffer:
            try:
                self.catsniffer.write(self.ti_cmd.stop())
                self.catsniffer.disconnect()
            except:
                pass

import time
from rich.live import Live
from rich.table import Table

HOPP_INTERVAL = 3.1
REFRESH_INTERVAL = 1.1
MAX_CHANNEL_ACTIVITY = 50

class Graphs:
    def __init__(self):
        self.running = True
        self.channel_activity = {}
        self.topology_activity = {}
        self.current_channel = 11
        self.channel_packets = 0

    def draw_bar(self, data, char="❚"):
        if data == 0:
            return ""
        if data > MAX_CHANNEL_ACTIVITY:
            return f"{char*8} ({data}) {char*8}"
        return char * data

    def update_graph_value(self, channel_activity):
        self.channel_activity = channel_activity

    def update_topology_packets(self, packets):
        if not packets:
            return
        key = list(packets.keys())[0]
        if key not in self.topology_activity:
            self.topology_activity[key] = packets[key]

    def update_channel_packets(self, packets):
        self.channel_packets = packets

    def update_channel(self, channel):
        self.current_channel = channel

    def __convert_to_mac(self, data):
        return ":".join(f"{(data >> (8 * i)) & 0xFF:02x}" for i in range(7, -1, -1))

    def generate_topology_graph(self):
        table = Table(
            title="Network Topology",
            title_justify="center",
            caption="Zigbee Network Topology",
            caption_justify="center",
        )
        table.add_column("Children", style="cyan", no_wrap=True)
        table.add_column("Ext. Source", style="green", no_wrap=True)

        for parent, children in self.topology_activity.items():
            try:
                parent_val = int(parent)
                table.add_row(f"0x{parent_val:04x}", self.__convert_to_mac(children))
            except Exception:
                table.add_row(parent, str(children))

        return table

    def generate_channel_graph(self):
        table = Table(
            title="Channel Activity",
            title_justify="center",
            caption="Channel Hopping Activity",
            caption_justify="center",
        )
        table.add_column("Current", style="red", no_wrap=True)
        table.add_column("Channel", style="cyan", no_wrap=True)
        table.add_column("Activity", style="green", no_wrap=True)
        table.add_column("Packets", style="magenta", no_wrap=True)

        for channel, data in sorted(self.channel_activity.items()):
            channel_marker = ""
            if channel == self.current_channel:
                channel_marker = "---->"
            table.add_row(
                channel_marker,
                str(channel),
                str(self.draw_bar(data=data)),
                str(data),
            )
        return table

    def stop(self):
        self.running = False

    def create_channel_graph(self, console=None):
        with Live(
            self.generate_channel_graph(), 
            refresh_per_second=REFRESH_INTERVAL,
            console=console
        ) as live:
            while self.running:
                time.sleep(0.4)
                live.update(self.generate_channel_graph(), refresh=True)

    def create_topology_graph(self, console=None):
        with Live(
            self.generate_topology_graph(), 
            refresh_per_second=REFRESH_INTERVAL,
            console=console
        ) as live:
            while self.running:
                time.sleep(0.4)
                live.update(self.generate_topology_graph(), refresh=True)

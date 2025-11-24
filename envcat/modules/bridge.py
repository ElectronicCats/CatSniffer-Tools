import time
import struct
import threading

# Internal
from .catsniffer import catsniffer_get_port, Catsniffer
from .pipes import UnixPipe, Wireshark
from protocol.sniffer_ti import SnifferTI, PacketCategory, START_OF_FRAME, END_OF_FRAME

# External

from rich.console import Console

PCAP_GLOBAL_HEADER_FORMAT = "<LHHIILL"
PCAP_PACKET_HEADER_FORMAT = "<llll"
PCAP_MAGIC_NUMBER = 0xA1B2C3D4
PCAP_VERSION_MAJOR = 2
PCAP_VERSION_MINOR = 4
PCAP_MAX_PACKET_SIZE = 0x0000FFFF

console = Console()
sniffer = SnifferTI()
snifferTICmd = sniffer.Commands()


def get_global_header(interface=147):
    global_header = struct.pack(
        PCAP_GLOBAL_HEADER_FORMAT,
        PCAP_MAGIC_NUMBER,
        PCAP_VERSION_MAJOR,
        PCAP_VERSION_MINOR,
        0,  # Reserved
        0,  # Reserved
        PCAP_MAX_PACKET_SIZE,
        interface,
    )
    return global_header


def run_bridge(serial_worker: Catsniffer, channel: int = 11, wireshark: bool = False):
    pipe = UnixPipe()
    opening_worker = threading.Thread(target=pipe.open, daemon=True)
    ws = Wireshark()
    if wireshark:
        ws.run()
    opening_worker.start()

    serial_worker.connect()

    startup = snifferTICmd.get_startup_cmd(channel)
    for cmd in startup:
        serial_worker.write(cmd)
        time.sleep(0.1)

    header_flag = False

    while True:
        try:
            data = serial_worker.read_until((END_OF_FRAME + START_OF_FRAME))
            if data:
                ti_packet = sniffer.Packet((START_OF_FRAME + data))
                if ti_packet.category == PacketCategory.DATA_STREAMING_AND_ERROR.value:
                    console.log(f"Recv -> {ti_packet}")
                    if not header_flag:
                        header_flag = True
                        pipe.write_packet(get_global_header())
                    pipe.write_packet(ti_packet.pcap)

            time.sleep(0.5)
        except KeyboardInterrupt:
            pipe.remove()
            opening_worker.join()
            serial_worker.write(snifferTICmd.stop())
            serial_worker.disconnect()
            break

import time
import struct
import threading

# Internal
from .catsniffer import Catsniffer
from .pipes import UnixPipe, Wireshark
from protocol.sniffer_sx import SnifferSx
from protocol.sniffer_ti import SnifferTI, PacketCategory
from protocol.common import START_OF_FRAME, END_OF_FRAME, get_global_header

# External

from rich.console import Console

console = Console()
sniffer = SnifferTI()
snifferSx = SnifferSx()
snifferTICmd = sniffer.Commands()
snifferSxCmd = snifferSx.Commands()


def run_sx_bridge(
    serial_worker: Catsniffer,
    frequency,
    bandwidth,
    spread_factor,
    coding_rate,
    sync_word,
    preamble_length,
    wireshark: bool = False,
):

    serial_worker.connect()

    serial_worker.write(snifferSxCmd.set_freq(frequency))
    serial_worker.write(snifferSxCmd.set_bw(bandwidth))
    serial_worker.write(snifferSxCmd.set_sf(spread_factor))
    serial_worker.write(snifferSxCmd.set_cr(coding_rate))
    serial_worker.write(snifferSxCmd.set_pl(preamble_length))
    serial_worker.write(snifferSxCmd.set_sw(sync_word))
    serial_worker.write(snifferSxCmd.start())

    while True:
        try:
            data = serial_worker.readline()
            if data:
                console.log(f"Recv -> {data}")
                if data.startswith(START_OF_FRAME):
                    packet = snifferSx.Packet((START_OF_FRAME + data))
                    console.log(f"Packet -> {packet}")

            time.sleep(0.5)
        except KeyboardInterrupt:
            serial_worker.disconnect()
            break


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
                ti_packet = sniffer.Packet((START_OF_FRAME + data), channel)
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

import time

# Internal
from .catsniffer import catsniffer_get_port, Catsniffer
from .pipes import UnixPipe, Wireshark
from protocol.sniffer_ti import SnifferTI

# External
import serial
from rich.console import Console

console = Console()


def wun(serial_worker: Catsniffer):
    pipe = UnixPipe()
    print("Running while")
    while True:
        try:
            print("Hello")
            time.sleep(0.5)
        except KeyboardInterrupt:
            pipe.remove()
            break

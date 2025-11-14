import asyncio
import signal

# Internal
from .catsniffer import catsniffer_get_port
from .pipes import UnixPipe, Wireshark
from protocol.sniffer_ti import SnifferTI

# External
import serial_asyncio
from rich.console import Console

console = Console()


class SerialReader(asyncio.Protocol):
    def __init__(self, pipe: UnixPipe, startup_commands=None):
        self.pipe = pipe
        self.transport = None
        self.startup_commands = startup_commands or []

    def connection_made(self, transport):
        self.transport = transport
        console.log("[*] Serial connection established")
        asyncio.create_task(self._send_startup_commands())

    def data_received(self, data):
        asyncio.create_task(self.pipe.write_packet(data))
        console.log(f"[>] Serial data: {data}")

    def connection_lost(self, exc):
        console.log("[X] Serial connection lost")

    async def write(self, data: bytes):
        if self.transport is None:
            console.log("[X] No serial connection established", style="red")
            return
        self.transport.write(data)
        console.log(f"[*] Sent serial data: {data}", style="white")

    async def _send_startup_commands(self):
        if not self.startup_commands:
            return
        await asyncio.sleep(0.5)

        for cmd in self.startup_commands:
            self.transport.write(cmd)
            console.log(f"[*] Sent startup command: {cmd}")
            await asyncio.sleep(0.1)


async def main_serial_pipeline(
    port: str = catsniffer_get_port(),
    baudrate: int = 115200,
    channel: int = 11,
    open_wireshark: bool | None = None,
):
    startup_cmds = SnifferTI.Commands().get_startup_cmd(channel=channel)
    pipe = UnixPipe()
    await pipe.create()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, loop.stop)
    transport, protocol = await serial_asyncio.create_serial_connection(
        loop, lambda: SerialReader(pipe, startup_commands=startup_cmds), port, baudrate
    )

    console.log("[*] Running serial + pipe bridge")
    print(open_wireshark)
    if open_wireshark:
        console.log("[*] Opening Wireshark")
        Wireshark().start()
        await pipe.open()
    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        console.log("[X] Shutting down bridge...")
    finally:
        transport.close()
        await pipe.remove()

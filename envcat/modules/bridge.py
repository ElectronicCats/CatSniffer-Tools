import asyncio
import signal
# Internal
from .catsniffer import Catsniffer
from .pipes import UnixPipe, DEFAULT_UNIX_PATH
# External
import serial_asyncio
from rich.console import Console

console = Console()

class SerialReader(asyncio.Protocol):
  def __init__(self, pipe: UnixPipe):
    self.pipe = pipe
    self.transport = None

  def connection_made(self, transport):
    self.transport = transport
    console.log("[*] Serial connection established")

  def data_received(self, data):
    asyncio.create_task(self.pipe.write_packet(data))
    console.log(f"[>] Serial data: {data}")

  def connection_lost(self, exc):
    console.log("[X] Serial connection lost")

async def main_serial_pipeline(port: str = Catsniffer().get_port(), baudrate: int = 115200):
  pipe = UnixPipe()
  await pipe.open()

  loop = asyncio.get_running_loop()
  for sig in (signal.SIGINT, signal.SIGTERM):
    loop.add_signal_handler(sig, loop.stop)
  transport, protocol = await serial_asyncio.create_serial_connection(
    loop, lambda: SerialReader(pipe), port, baudrate
  )

  console.log("[*] Running serial + pipe bridge")
  try:
    await asyncio.Future()
  except asyncio.CancelledError:
    console.log("[X] Shutting down bridge...")
  finally:
    transport.close()
    await pipe.remove()
import asyncio
import os
from . import Pcap
from .Definitions import LINKTYPE_IEEE802_15_4_NOFCS
import typer

DEFAULT_FILENAME = "fcatsniffer"

class AsyncFifoLinux:
    def __init__(self, fifo_filename: str = DEFAULT_FILENAME):
        self.fifo_filename = fifo_filename
        self.fifo_path = os.path.join("/tmp", fifo_filename)
        self.linktype = LINKTYPE_IEEE802_15_4_NOFCS
        self.fifo_need_header = True
        self.fifo_writer = None

    async def create(self):
        try:
            os.mkfifo(self.fifo_path)
        except FileExistsError:
            pass
        except OSError as e:
            typer.secho(f"[FIFO] Error creando FIFO: {e}", fg=typer.colors.RED)

    async def open(self):
        if not os.path.exists(self.fifo_path):
            await self.create()
        # abrir el archivo en hilo aparte (no bloqueante)
        self.fifo_writer = await asyncio.to_thread(open, self.fifo_path, "ab")

    async def write_packet(self, data: bytes):
        if self.fifo_writer is None:
            await self.open()

        try:
            if self.fifo_need_header:
                self.fifo_writer.write(Pcap.get_global_header(self.linktype))
                await asyncio.to_thread(self.fifo_writer.flush)
                self.fifo_need_header = False

            self.fifo_writer.write(data)
            await asyncio.to_thread(self.fifo_writer.flush)
        except BrokenPipeError:
            typer.secho("[FIFO] Broken pipe, reiniciando encabezado", fg=typer.colors.YELLOW)
            self.fifo_need_header = True
        except Exception as e:
            typer.secho(f"[FIFO] Error: {e}", fg=typer.colors.RED)

    async def close(self):
        if self.fifo_writer:
            await asyncio.to_thread(self.fifo_writer.close)
            self.fifo_writer = None
        try:
            os.remove(self.fifo_path)
        except FileNotFoundError:
            pass

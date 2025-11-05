import os
import asyncio
import platform

# External
from rich.console import Console

DEFAULT_UNIX_PATH = "/tmp/fcatsniffer"

console = Console()

# Blocking method, this is required to run all the script
if platform.system().lower() == "windows":
  try:
    import win32pipe, win32file, pywintypes
    console.log("[*] Windows library import done!", style="bold green")
  except:
    console.log("[bold red][X] Error[/bold red]: win32pipe, win32file, pywintypes modules not found. [yellow]Please install [bold]pywin32[/bold] package.[/yellow]")
    exit(1)
    

def show_generic_error(title="", e="") -> None:
  console.log(f"[bold red][X] Error {title}[/bold red]: {e}")
    
class UnixPipe:
  def __init__(self, path=DEFAULT_UNIX_PATH) -> None:
    self.pipe_path = path
    self.pipe_writer = None
  
  async def create(self):
    try:
      os.mkfifo(self.pipe_path)
      console.log(f"[*] Pipeline created: {self.pipe_path}", style="green")
    except FileExistsError:
      console.log(f"[-] Pipeline already exists.", style="yellow")
      pass
    except OSError as e:
      show_generic_error("Creating Pipeline", e)
      exit(1)
  
  async def open(self) -> None:
    if not os.path.exists(self.pipe_path):
      await self.create()
    try:
      self.pipe_writer = await asyncio.to_thread(open, self.pipe_path, "ab")
      console.log(f"[*] Pipeline Open: {self.pipe_path}", style="green")
    except Exception as e:
      show_generic_error("Opening Pipeline", e)
      exit(1)
  
  async def close(self) -> None:
    try:
      await asyncio.to_thread(self.pipe_writer.close)
      self.pipe_writer = None
      console.log(f"[*] Pipeline Closed: {self.pipe_path}", style="green")
    except Exception as e:
      show_generic_error("Closing Pipeline", e)
      pass
  
  def remove(self) -> None:
    try:
      if self.pipe_writer:
        self.pipe_writer.close()
      if os.path.exists(self.pipe_path):
        os.remove(self.pipe_path)
      console.log(f"[*] Pipeline removed: {self.pipe_path}", style="green")
    except Exception as e:
      show_generic_error("Removing Pipeline", e)
      pass
  
  async def write_packet(self, data: bytes) -> None:
    try:
      self.pipe_writer.write(data)
      await asyncio.to_thread(self.pipe_writer.flush)
      console.log(f"[*] Writing to Pipeline ({self.pipe_path}): {data}")
    except Exception as e:
      show_generic_error("Writing Pipeline", e)
      self.remove()
      exit(1)
import os
import asyncio
import platform
import threading
import platform
import subprocess
from pathlib import Path

# External
from rich.console import Console

DEFAULT_PIPELINE_NAME = "fcatsniffer"
DEFAULT_UNIX_PATH = f"/tmp/{DEFAULT_PIPELINE_NAME}"

console = Console()

# Blocking method, this is required to run all the script
if platform.system().lower() == "windows":
    try:
        import win32pipe, win32file, pywintypes

        console.log("[*] Windows library import done!", style="bold green")
    except:
        console.log(
            "[bold red][X] Error[/bold red]: win32pipe, win32file, pywintypes modules not found. [yellow]Please install [bold]pywin32[/bold] package.[/yellow]"
        )
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


class Wireshark(threading.Thread):
    def __init__(self, pipe_name=DEFAULT_UNIX_PATH, profile=None):
        super().__init__(daemon=True)
        self.pipe_name = pipe_name
        self.profile = profile
        self.running = True
        self.wireshark_process: subprocess.Popen | None = None
        self.system = platform.system()

    def get_wireshark_path(self):
        if self.system == "Windows":
            exe_path = Path("C:\\Program Files\\Wireshark\\Wireshark.exe")
            if not exe_path.exists():
                exe_path = Path("C:\\Program Files (x86)\\Wireshark\\Wireshark.exe")
        elif self.system == "Linux":
            exe_path = Path("/usr/bin/wireshark")
        elif self.system == "Darwin":
            exe_path = Path("/Applications/Wireshark.app/Contents/MacOS/Wireshark")
        else:
            console.log("[X] Error. Unsupported OS", style="red")
            return None
        return exe_path

    def get_wireshark_pipepath(self):
        fifo_path = (
            DEFAULT_UNIX_PATH
            if self.system != "Windows"
            else f"\\\\.\\pipe\\{DEFAULT_PIPELINE_NAME}"
        )
        return fifo_path

    def get_wireshark_cmd(self):
        exe_path = self.get_wireshark_path()
        fifo_path = self.get_wireshark_pipepath()
        cmd = [str(exe_path), "-k", "-i", fifo_path]
        if self.profile:
            cmd = [str(exe_path), "-k", "-i", fifo_path, "-C", self.profile]
        return cmd

    def run(self):
        cmd = self.get_wireshark_cmd()
        if not cmd:
            self.running = False
            return

        try:
            self.wireshark_process = subprocess.Popen(cmd, start_new_session=True)
        except Exception as e:
            console.log("[X] Error. Can't start Wireshark", style="red")
        finally:
            self.running = False

    def stop_thread(self):
        self.running = False
        if self.wireshark_process and self.wireshark_process.poll() is None:
            try:
                self.wireshark_process.terminate()
                self.wireshark_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.wireshark_process.kill()
            self.join(2)
            self.wireshark_process = None

import os
import platform
import threading
import platform
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger("rich")

DEFAULT_PIPELINE_NAME = "fcatsniffer"
DEFAULT_UNIX_PATH = f"/tmp/{DEFAULT_PIPELINE_NAME}"
DEFAULT_WINDOWS_PATH = f"\\\\.\\pipe\\{DEFAULT_PIPELINE_NAME}"

# Blocking method, this is required to run all the script
if platform.system().lower() == "windows":
    try:
        import win32pipe, win32file, pywintypes

        logger.info("[*] Windows library import done!")
    except:
        logger.error(
            "[bold red][X] Error[/bold red]: win32pipe, win32file, pywintypes modules not found. [yellow]Please install [bold]pywin32[/bold] package.[/yellow]"
        )
        exit(1)


def show_generic_error(title="", e="") -> None:
    logger.error(f"[bold red][X] Error {title}[/bold red]: {e}")


class UnixPipe:
    def __init__(self, path=DEFAULT_UNIX_PATH) -> None:
        self.pipe_path = path
        self.pipe_writer = None
        # Initial configuration
        self.create()

    def create(self):
        try:
            os.mkfifo(self.pipe_path)
            logger.info(f"[*] Pipeline created: {self.pipe_path}")
        except FileExistsError:
            logger.info(f"[-] Pipeline already exists.")
        except OSError as e:
            show_generic_error("Creating Pipeline", e)
            exit(1)

    def open(self) -> None:
        logger.info(f"[*] Check if exist: {self.pipe_path}")
        if not os.path.exists(self.pipe_path):
            self.create()
        try:
            self.pipe_writer = open(self.pipe_path, "ab")
            logger.info(f"[*] Pipeline Open: {self.pipe_path}")
        except Exception as e:
            show_generic_error("Opening Pipeline", e)
            exit(1)

    def close(self) -> None:
        try:
            self.pipe_writer.close()
            self.pipe_writer = None
            logger.info(f"[*] Pipeline Closed: {self.pipe_path}")
        except Exception as e:
            show_generic_error("Closing Pipeline", e)
            pass

    def remove(self) -> None:
        try:
            if self.pipe_writer:
                self.pipe_writer.close()
            if os.path.exists(self.pipe_path):
                os.remove(self.pipe_path)
            logger.info(f"[*] Pipeline removed: {self.pipe_path}")
        except Exception as e:
            show_generic_error("Removing Pipeline", e)
            pass

    def write_packet(self, data: bytes) -> None:
        try:
            if self.pipe_writer:
                self.pipe_writer.write(data)
                self.pipe_writer.flush()
                logger.info(f"[*] Writing to Pipeline ({self.pipe_path}): {data}")
        except BrokenPipeError:
            show_generic_error("BrokenPipe", "")
            self.remove()
            exit(1)
        except Exception as e:
            show_generic_error("Writing Pipeline", e)
            pass


class WindowsPipe:
    def __init__(self, path=DEFAULT_WINDOWS_PATH) -> None:
        self.pipe_path = path
        self.pipe_writer = None
        # Initial configuration
        self.create()

    def create(self):
        try:
            self.pipe_writer = win32pipe.CreateNamedPipe(
                self.pipe_path,
                win32pipe.PIPE_ACCESS_DUPLEX,
                win32pipe.PIPE_TYPE_MESSAGE
                | win32pipe.PIPE_READMODE_MESSAGE
                | win32pipe.PIPE_WAIT,
                1,
                65536,
                65536,
                0,
                None,
            )
        except FileExistsError:
            logger.info(f"[-] Pipeline already exists.")
        except pywintypes.error as e:
            logger.error(f"[X] {e}")
            exit(1)

    def open(self) -> None:
        logger.info(f"[*] Waiting for a client on {self.pipe_path}.")
        try:
            win32pipe.ConnectNamedPipe(self.pipe_writer, None)
            logger.info(f"[*] Pipeline Open: {self.pipe_path}")
        except pywintypes.error as e:
            if e.winerror == 535:  # ERROR_PIPE_CONNECTED
                logger.info("[*] Client already connected")
            elif e.winerror == 232:  # ERROR_NO_DATA
                logger.warning("[!] Client connected and disconnected immediately")
                return
            else:
                show_generic_error("Opening Pipeline", e)
                raise

    def close(self) -> None:
        try:
            if self.pipe_writer:
                win32pipe.DisconnectNamedPipe(self.pipe_writer)
                win32file.CloseHandle(self.pipe_writer)
                self.pipe_writer = None
                logger.info(f"[*] Pipeline Closed: {self.pipe_path}")
        except Exception as e:
            show_generic_error("Closing Pipeline", e)

    def remove(self) -> None:
        try:
            if self.pipe_writer:
                self.pipe_writer.close()
            if os.path.exists(self.pipe_path):
                os.remove(self.pipe_path)
            logger.info(f"[*] Pipeline removed: {self.pipe_path}")
        except Exception as e:
            show_generic_error("Removing Pipeline", e)
            pass

    def write_packet(self, data: bytes) -> None:
        try:
            win32file.WriteFile(self.pipe_writer, data)
            win32file.FlushFileBuffers(self.pipe_writer)
            logger.info(f"[*] Writing to Pipeline ({self.pipe_path}): {data}")
        except pywintypes.error as e:
            if e.winerror in (109, 232):
                logger.warning("[!] Client disconnected")
                self.close()
            else:
                show_generic_error("Writing Pipeline", e)


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
            show_generic_error("Unsupported OS", "We don't support this OS yet.")
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
        try:
            self.wireshark_process = subprocess.Popen(cmd)
        except Exception as e:
            show_generic_error("Can't start Wireshark", e)

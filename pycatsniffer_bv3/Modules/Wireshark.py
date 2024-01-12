import threading
import platform
import subprocess

from .Fifo import DEFAULT_FILENAME
from .Logger import SnifferLogger
class Wireshark(threading.Thread):
    def __init__(self, fifo_name: str = DEFAULT_FILENAME):
        super().__init__()
        self.logger = SnifferLogger().get_logger()
        self.fifo_name = fifo_name
        self.running = True
        self.type_worker = "wireshark"
        self.wireshark_process = None

    def run(self):
        if platform.system() == "Windows":
            self.wireshark_process = subprocess.Popen(
                [
                    "C:\\Program Files\\Wireshark\\Wireshark.exe",
                    "-k",
                    "-i",
                    f"\\\\.\\pipe\\{self.fifo_name}",
                ]
            )
            
        elif platform.system() == "Linux":
            self.wireshark_process = subprocess.Popen(
                [
                    "sudo",
                    "/usr/bin/wireshark",
                    "-k",
                    "-i",
                    f"/tmp/{self.fifo_name}",
                ]
            )
        elif platform.system() == "Darwin":
            self.wireshark_process = subprocess.Popen(
                [
                    "/Applications/Wireshark.app/Contents/MacOS/Wireshark",
                    "-k",
                    "-i",
                    f"/tmp/{self.fifo_name}",
                ]
            )
        else:
            print("Not supported OS")
            return
        self.running = False

    def stop(self):
        self.running = False
        self.join()
        if self.wireshark_process:
            self.wireshark_process = None
    
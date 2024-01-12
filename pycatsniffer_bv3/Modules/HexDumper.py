import os
import time
import threading

from .Utils import generate_filename
from .Definitions import DEFAUTL_DUMP_PATH, DEFAULT_HEX_PATH

class HexDumper(threading.Thread):
    DEFAULT_FILENAME = "hexdump.hexdump"
    
    def __init__(self, filename: str = DEFAULT_FILENAME):
        super().__init__()
        self.filename = filename
        self.data_queue = []
        self.data_queue_lock = threading.Lock()
        self.running = True
        self.type_worker = "raw"
    
    def get_filename(self):
        return os.path.join(os.getcwd(), DEFAUTL_DUMP_PATH, DEFAULT_HEX_PATH, f"{generate_filename()}_{self.filename}")
    
    def set_filename(self, filename):
        self.filename = filename
    
    def run(self):
        while self.running:
            if self.data_queue:
                with self.data_queue_lock:
                    data = self.data_queue.pop(0)
                
                with open(self.get_filename(), "ab") as dumper_file:
                    dumper_file.write(data)
                    dumper_file.write(b"\n")
                    dumper_file.flush()
                    os.fsync(dumper_file.fileno())
            else:
                time.sleep(0.1)
    
    def stop(self):
        self.running = False
        self.data_queue = []
        self.join()
        
    def add_data(self, data):
        with self.data_queue_lock:
            self.data_queue.append(data)
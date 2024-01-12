import os
import time
import threading

from .Utils import generate_filename
from .Definitions import DEFAUTL_DUMP_PATH, DEFAULT_PCAP_PATH
from .Pcap import get_global_header

class PcapDumper(threading.Thread):
    DEFAULT_FILENAME = "pcapdump.pcap"
    
    def __init__(self, filename: str = DEFAULT_FILENAME):
        super().__init__()
        self.filename = filename
        self.data_queue = []
        self.data_queue_lock = threading.Lock()
        self.running = True
        self.needs_header = True
        self.type_worker = "pcap"
    
    def get_filename(self):
        return os.path.join(os.getcwd(),DEFAUTL_DUMP_PATH, DEFAULT_PCAP_PATH, f"{generate_filename()}_{self.filename}")    
    def set_filename(self, filename):
        self.filename = filename
    
    def run(self):
        while self.running:
            if self.data_queue:
                with self.data_queue_lock:
                    data = self.data_queue.pop(0)
                
                with open(self.get_filename(), "ab") as dumper_file:
                    if self.needs_header:
                        dumper_file.write(get_global_header())
                        dumper_file.flush()
                        self.needs_header = False
                    
                    dumper_file.write(data)
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
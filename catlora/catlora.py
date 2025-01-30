"""
This code is still in development and is not yet ready for production use.
Kevin Leon @ Electronic Cats
  Original Creation Date: Jan 30, 2025
  This code is beerware; if you see me (or any other Electronic Cats
  member) at the local, and you've found our code helpful,
  please buy us a round!
  Distributed as-is; no warranty is given.
"""
import sys
import time
import threading
import argparse
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from modules.hardware import Board as Catsniffer

START_OF_FRAME        = "@S"
END_OF_FRAME          = "@E"
DEFAULT_COLOR_MAP     = "BuGn"
DEFAULT_RSSI_OFFSET   = -11
SCAN_WIDTH            = 33
DEFAULT_START_FREQ    = 860
DEFAULT_STEP_PER_FREQ = 0.2
DEFAULT_END_FREQ      = 928


class SpectrumScan:
    def __init__(self):
        self.catsniffer = Catsniffer()
        self.recv_running = False
        self.no_bytes_count = 0
        self.fig, self.ax = plt.subplots(figsize=(12, 6))
        self.im = None
        self.start_freq = DEFAULT_START_FREQ
        self.end_freq = DEFAULT_END_FREQ
        self.delta_freq = int((self.end_freq - self.start_freq) / DEFAULT_STEP_PER_FREQ)
        self.data_matrix = np.zeros((SCAN_WIDTH, self.delta_freq))
        self.fig.canvas.mpl_connect("close_event", self.on_close)
        self.parser = argparse.ArgumentParser(description="CatSniffer LoRa Spectrum Scan")
        self.__load_parser()

    def __data_dissector(self, plot_data):
        raw_data = plot_data[len(START_OF_FRAME):-len(END_OF_FRAME)]
        freq, data = raw_data.split(";")
        freq = float(freq)
        data = list(map(int, data.split(",")[:-1]))
        index = int((freq - self.start_freq) / DEFAULT_STEP_PER_FREQ)
        if freq == self.start_freq:
            self.data_matrix = np.zeros((SCAN_WIDTH, self.delta_freq))
        self.data_matrix[:, index] = data

    def __load_parser(self):
        self.parser.add_argument("--port", type=str, help="COM port to connect to the device", default=self.catsniffer.serial_path)
        self.parser.add_argument("--freqStart", type=float, help="Starting frequency in MHz", default=DEFAULT_START_FREQ)
        self.parser.add_argument("--freqEnd", type=float, help="End frequency in MHz", default=DEFAULT_END_FREQ)

    def on_close(self, event):
        self.recv_running = False

    def stop_task(self):
        self.recv_running = False
    
    def close(self):
        self.catsniffer.close()

    def recv_task(self):
        while self.recv_running:
            bytestream = self.catsniffer.recv()
            if bytestream == b"":
                self.no_bytes_count += 1
                if self.no_bytes_count > 5:
                    self.no_bytes_count = 0
                    print("No com")
                    self.stop_task()
                continue

            bytestream = bytestream.decode().strip()
            if bytestream.startswith(START_OF_FRAME):
                self.__data_dissector(bytestream)

    def create_plot(self):
        self.ax.set_ylabel("RSSI [dBm]")
        self.ax.set_xlabel("Frequency (MHz)")
        self.ax.set_aspect("auto")
        self.fig.suptitle("Catsniffer LoRa Spectral Scan")
        self.fig.canvas.manager.set_window_title("PWNLabs - ElectroniCats")
        self.im = self.ax.imshow(
            self.data_matrix[:,:self.delta_freq],
            cmap=DEFAULT_COLOR_MAP,
            aspect="auto",
            extent=[self.start_freq, self.end_freq, -4 *(SCAN_WIDTH+1), DEFAULT_RSSI_OFFSET],
        )
        self.fig.colorbar(self.im)

    def show_plot(self, i):
        self.im.set_data(self.data_matrix)
        self.ax.relim()
        self.ax.autoscale_view()
    
    def catsniffer_setup_freq(self, freq_start, freq_end):
        self.catsniffer.write(f"set_start_freq {freq_start}\n".encode())
        self.catsniffer.write(f"set_end_freq {freq_end}\n".encode())

    def main(self):
        self.recv_running = True
        serial_path = self.catsniffer.find_catsniffer_serial_port()
        self.catsniffer.set_serial_path(serial_path)
        self.catsniffer.open()

        args = self.parser.parse_args()
        if args.freqStart < DEFAULT_START_FREQ or args.freqStart > DEFAULT_END_FREQ:
            print("Frequency start out of range")
            sys.exit(1)
        
        if args.freqEnd < DEFAULT_START_FREQ or args.freqEnd > DEFAULT_END_FREQ:
            print("Frequency start out of range")
            sys.exit(1)
        
        if args.freqStart > args.freqEnd:
            print("Frequency start is greater than frequency end")
            sys.exit(1)

        self.start_freq = args.freqStart
        self.end_freq = args.freqEnd
        self.catsniffer_setup_freq(args.freqStart, args.freqEnd)
        self.delta_freq = int((self.end_freq - self.start_freq) / DEFAULT_STEP_PER_FREQ)
        self.data_matrix = np.zeros((SCAN_WIDTH, self.delta_freq))
        recv_worker = threading.Thread(target=self.recv_task, daemon=True)
        recv_worker.start()
        self.create_plot()

        ani = animation.FuncAnimation(self.fig, self.show_plot, interval=100)
        plt.show()

        while self.recv_running:
            time.sleep(0.1)

        recv_worker.join()
        self.catsniffer.close()
        print("Exited")


if __name__ == "__main__":
    print("This code is still in development and is not yet ready for production use.")
    sc = SpectrumScan()
    try:
        sc.main()
    except KeyboardInterrupt:
        sc.stop_task()
        sc.close()
        sys.exit(0)

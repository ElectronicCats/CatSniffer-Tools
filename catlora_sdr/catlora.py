import sys
import time
import threading
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from modules.hardware import Board as Catsniffer

DEFAULT_COLOR_MAP = "viridis"
DEFAULT_RSSI_OFFSET = -11
SCAN_WIDTH = 33  # Asumiendo que hay 33 muestras por escaneo

DEFAULT_START_FERQ = 868
DEFAULT_END_FREQ = 928


class SpectrumScan:
    def __init__(self):
        self.catsniffer = Catsniffer()
        self.recv_running = False
        self.no_bytes_count = 0
        self.fig, self.ax = plt.subplots(figsize=(12, 6))
        self.frequency_list = []
        self.data_matrix = np.zeros((33, 600))  # Ajusta el tamaño según tu necesidad
        self.im = None
        self.start_freq = DEFAULT_START_FERQ
        self.end_freq = DEFAULT_END_FREQ
        self.num_ticks = 50
        self.fig.canvas.mpl_connect("close_event", self.on_close)

    def __data_dissector(self, plot_data):
        raw_data = plot_data[len("@S") : -len("@E")]
        freq, data = raw_data.split(";")
        freq = float(freq)
        if freq not in self.frequency_list:
            self.frequency_list.append(freq)

        data = list(map(int, data.split(",")[:-1]))
        index = int(
            round(
                (freq - self.start_freq)
                / (self.end_freq - self.start_freq)
                * (self.num_ticks * 12 - 1)
            )
        )
        self.data_matrix[:, index] = data

    def on_close(self, event):
        self.recv_running = False

    def stop_task(self):
        self.recv_running = False

    def recv_task(self):
        print("Collecting")
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
            if bytestream.startswith("@S"):
                print(f"> {bytestream}")
                self.__data_dissector(bytestream)

    def create_plot(self):
        self.ax.set_ylabel("RSSI [dBm]")
        self.ax.set_xlabel("Frequency (Hz)")
        self.ax.set_xlim(self.start_freq - 5, self.end_freq)
        precise_ticks = np.linspace(self.start_freq, self.end_freq, self.num_ticks)
        self.ax.set_xticks(precise_ticks)
        self.ax.set_xticklabels([f"{tick:.1f}" for tick in precise_ticks], rotation=45)
        self.ax.set_aspect("auto")
        self.fig.suptitle("Catsniffer LoRa Spectral Scan")
        self.fig.canvas.manager.set_window_title("PWNLabs - ElectroniCats")
        self.im = self.ax.imshow(
            self.data_matrix,
            cmap=DEFAULT_COLOR_MAP,
            aspect="auto",
            extent=[self.start_freq, self.end_freq, -4 * 34, DEFAULT_RSSI_OFFSET],
        )
        self.fig.colorbar(self.im)

    def show_plot(self, i):
        self.im.set_data(self.data_matrix)
        self.ax.relim()
        self.ax.autoscale_view()

    def main(self):
        self.recv_running = True
        serial_path = self.catsniffer.find_catsniffer_serial_port()
        print(serial_path)
        self.catsniffer.set_serial_path(serial_path)
        self.catsniffer.open()
        recv_worker = threading.Thread(target=self.recv_task, daemon=True)
        recv_worker.start()
        self.create_plot()
        animation.FuncAnimation(self.fig, self.show_plot, interval=100)
        plt.show()
        while self.recv_running:
            time.sleep(0.1)

        recv_worker.join()
        self.catsniffer.close()
        print("Exited")


if __name__ == "__main__":
    sc = SpectrumScan()
    try:
        sc.main()
    except KeyboardInterrupt:
        sc.stop_task()
        sys.exit(0)

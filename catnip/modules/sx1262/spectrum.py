#!/usr/bin/env python3
"""
Live Spectrum Scanner for SX1262
Real-time spectrum analyzer with matplotlib visualization

Electronic Cats
"""

import sys
import serial
import threading
import argparse
import time
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation

# Internal
from modules.catnip import LoRaConnection

START_OF_FRAME = "SCAN"
END_OF_FRAME = "END"
FREQ_FRAME_MARK = "FREQ"
DEFAULT_COLOR_MAP = "BuGn"
DEFAULT_RSSI_OFFSET = -15
SCAN_WIDTH = 33
DEFAULT_START_FREQ = 150
DEFAULT_STEP_PER_FREQ = 0.2
DEFAULT_END_FREQ = 960
DEFAULT_BAUDRATE = 115200
LIMIT_COUNT = 2


def LOG_INFO(message):
    """Function to log information."""
    print(f"[INFO] {message}")


def LOG_ERROR(message):
    """Function to log error."""
    print(f"\x1b[31;1m[ERROR] {message}\x1b[0m")


def LOG_WARNING(message):
    """Function to log warning."""
    print(f"\x1b[33;1m[WARNING] {message}\x1b[0m")


class SpectrumScan:
    def __init__(self, port=None, baudrate=DEFAULT_BAUDRATE):
        self.port = port
        self.baudrate = baudrate
        self.device_uart = None
        self.recv_running = False
        self.no_bytes_count = 0
        self.fig, self.ax = plt.subplots(figsize=(12, 6))
        self.im = None
        self.recv_worker = None
        self.current_freq = DEFAULT_START_FREQ
        self.start_freq = DEFAULT_START_FREQ
        self.end_freq = DEFAULT_END_FREQ
        self.rssi_offset = DEFAULT_RSSI_OFFSET
        self.delta_freq = 0
        self.data_matrix = np.zeros((SCAN_WIDTH, self.delta_freq))

    def __data_dissector(self, plot_data):
        print(plot_data)
        if FREQ_FRAME_MARK in plot_data:
            self.current_freq = float(plot_data.split(" ")[1])
            if (
                self.current_freq >= self.start_freq
                and self.current_freq <= self.end_freq
            ):
                if self.current_freq == self.start_freq:
                    self.data_matrix = np.zeros((SCAN_WIDTH, self.delta_freq))
                return
        if (START_OF_FRAME in plot_data) and (END_OF_FRAME in plot_data):
            if (
                self.current_freq >= self.start_freq
                and self.current_freq <= self.end_freq
            ):
                scan_line = plot_data[len(START_OF_FRAME) : -len(END_OF_FRAME)].split(
                    ","
                )[:-1]
                data = list(map(int, scan_line))
                index = int(
                    (self.current_freq - self.start_freq) / DEFAULT_STEP_PER_FREQ
                )
                self.data_matrix[:, index] = data

    def on_close(self, event):
        self.recv_running = False

    def stop_task(self):
        self.recv_running = False
        if self.device_uart and self.device_uart.is_open:
            self.device_uart.close()
        if threading.current_thread() is not self.recv_worker:
            if self.recv_worker and self.recv_worker.is_alive():
                self.recv_worker.join(timeout=2)

    def recv_task(self):
        while self.recv_running:
            if self.recv_worker.is_alive():
                try:
                    bytestream = self.device_uart.readline().decode("utf-8").strip()
                    if not self.recv_running:
                        break
                    if bytestream == "":
                        self.no_bytes_count += 1
                        if self.no_bytes_count > LIMIT_COUNT:
                            self.no_bytes_count = 0
                            LOG_WARNING("No data received.")
                        continue
                    self.__data_dissector(bytestream)
                    if self.delta_freq < 1:
                        time.sleep(0.3)
                except serial.SerialException as e:
                    LOG_WARNING(e)
                    continue
                except UnicodeDecodeError as e:
                    LOG_WARNING(
                        "Please check the baud rate, as using a different value than the one set on the device may cause errors."
                    )
                    LOG_ERROR(e)
                    continue

        self.device_uart.reset_input_buffer()
        self.device_uart.reset_output_buffer()
        self.device_uart.close()
        self.stop_task()

    def create_plot(self):
        self.ax.set_ylabel("RSSI [dBm]")
        self.ax.set_xlabel("Frequency (MHz)")
        self.ax.set_aspect("auto")

        freq_range = self.end_freq - self.start_freq
        if freq_range < 5:
            tick_step = DEFAULT_STEP_PER_FREQ
        else:
            tick_step = freq_range / 10

        self.ax.set_xticks(
            np.arange(self.start_freq, self.end_freq + tick_step, tick_step)
        )
        self.ax.grid(True, linestyle="--", alpha=1)
        self.fig.suptitle(
            f"SX126x Spectral Scan (Frequency range: {self.start_freq}/{self.end_freq} MHz)"
        )
        self.fig.canvas.manager.set_window_title("Electronic Cats - Spectral Scan")
        print("Create plot: ", -8 * (SCAN_WIDTH + 1))
        self.im = self.ax.imshow(
            self.data_matrix[:, : self.delta_freq],
            cmap=DEFAULT_COLOR_MAP,
            aspect="auto",
            extent=[
                self.start_freq,
                self.start_freq + self.delta_freq * DEFAULT_STEP_PER_FREQ,
                -8 * (SCAN_WIDTH + 1),
                self.rssi_offset,
            ],
            interpolation="bilinear",
        )
        self.fig.colorbar(self.im)
        manager = plt.get_current_fig_manager()
        try:
            manager.window.attributes("-topmost", 1)
            manager.window.attributes("-topmost", 0)
        except AttributeError:
            pass

    def show_plot(self, i):
        self.im.set_data(self.data_matrix)
        self.ax.relim()
        self.ax.autoscale_view()

    def run(self, start_freq=None, end_freq=None, rssi_offset=None):
        """Run the spectrum scanner"""
        self.recv_running = True

        if start_freq is not None:
            self.start_freq = start_freq
            self.current_freq = start_freq
        if end_freq is not None:
            self.end_freq = end_freq
        if rssi_offset is not None:
            self.rssi_offset = rssi_offset

        if self.start_freq < DEFAULT_START_FREQ or self.start_freq > DEFAULT_END_FREQ:
            LOG_WARNING("Frequency start out of range")
            return False

        if self.end_freq < DEFAULT_START_FREQ or self.end_freq > DEFAULT_END_FREQ:
            LOG_WARNING("Frequency end out of range")
            return False

        if self.start_freq > self.end_freq:
            LOG_WARNING("Frequency start is greater than frequency end")
            return False

        if self.port is None:
            LOG_ERROR("No port specified!")
            return False

        try:
            self.device_uart = serial.Serial(self.port, self.baudrate, timeout=2)
            self.device_uart.flush()
            self.device_uart.reset_input_buffer()
            self.device_uart.reset_output_buffer()
        except serial.SerialException as e:
            LOG_ERROR(f"Failed to open port: {e}")
            return False

        time.sleep(0.2)

        self.device_uart.write(f"stop\r\n".encode())
        self.device_uart.write(f"set_start_freq {self.start_freq}\r\n".encode())
        self.device_uart.write(f"set_end_freq {self.end_freq}\r\n".encode())
        self.device_uart.write(f"start\r\n".encode())

        self.delta_freq = (
            int((self.end_freq - self.start_freq) / DEFAULT_STEP_PER_FREQ) + 1
        )
        self.data_matrix = np.zeros((SCAN_WIDTH, self.delta_freq))

        self.recv_worker = threading.Thread(target=self.recv_task, daemon=True)
        self.recv_worker.start()
        self.create_plot()

        # Connect close event to stop receiving thread when window is closed
        self.fig.canvas.mpl_connect("close_event", self.on_close)

        ani = animation.FuncAnimation(
            self.fig, self.show_plot, interval=100, cache_frame_data=False
        )
        plt.show()

        return True


def main():
    """Standalone entry point for spectrum scanner"""
    parser = argparse.ArgumentParser(
        description="SX1262 Live Spectrum Scanner - Real-time frequency spectrum analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  catnip lora spectrum -p /dev/ttyUSB1
  catnip lora spectrum -p COM3 --start-freq 400 --end-freq 500
        """,
    )
    parser.add_argument(
        "-p",
        "--port",
        required=True,
        help="Serial port for SX1262 device",
    )
    parser.add_argument(
        "-b",
        "--baudrate",
        type=int,
        default=DEFAULT_BAUDRATE,
        help=f"Baudrate (default: {DEFAULT_BAUDRATE})",
    )
    parser.add_argument(
        "--start-freq",
        type=float,
        default=DEFAULT_START_FREQ,
        help=f"Starting frequency in MHz (default: {DEFAULT_START_FREQ})",
    )
    parser.add_argument(
        "--end-freq",
        type=float,
        default=DEFAULT_END_FREQ,
        help=f"End frequency in MHz (default: {DEFAULT_END_FREQ})",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=DEFAULT_RSSI_OFFSET,
        help=f"RSSI offset in dBm (default: {DEFAULT_RSSI_OFFSET})",
    )

    args = parser.parse_args()

    scanner = SpectrumScan(port=args.port, baudrate=args.baudrate)

    try:
        scanner.run(
            start_freq=args.start_freq, end_freq=args.end_freq, rssi_offset=args.offset
        )
    except KeyboardInterrupt:
        scanner.stop_task()
        sys.exit(0)


if __name__ == "__main__":
    main()

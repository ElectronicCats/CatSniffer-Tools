"""
test_sx1262.py
==============
Tests for the SX1262 spectrum analyzer module.

Covers:
  - modules/sx1262/spectrum.py

Run with:
    pytest tests/test_sx1262.py -v
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch

# Get the absolute path to the project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

# Mocks for heavy or system libraries to avoid environment failures.
# NOTE: Use setdefault so that conftest.py's hierarchical serial mock is NOT
# overwritten when pytest collects all test files simultaneously.
sys.modules.setdefault("serial", MagicMock())
sys.modules.setdefault("numpy", MagicMock())
sys.modules.setdefault("matplotlib", MagicMock())
sys.modules.setdefault("matplotlib.pyplot", MagicMock())
sys.modules.setdefault("matplotlib.animation", MagicMock())


# Now we can import
from modules.sx1262.spectrum import SpectrumScan, DEFAULT_BAUDRATE, DEFAULT_START_FREQ


# ═════════════════════════════════════════════════════════════════════════════
#  1.  TESTS FOR SpectrumScan
# ═════════════════════════════════════════════════════════════════════════════


class TestSpectrumScan:
    """Tests for the SpectrumScan class."""

    def test_init(self):
        with patch(
            "modules.sx1262.spectrum.plt.subplots",
            return_value=(MagicMock(), MagicMock()),
        ):
            scanner = SpectrumScan(port="/dev/ttyUSB0")
            assert scanner.port == "/dev/ttyUSB0"
            assert scanner.baudrate == DEFAULT_BAUDRATE
            assert scanner.recv_running is False

    def test_data_dissector_freq_mark(self):
        with patch(
            "modules.sx1262.spectrum.plt.subplots",
            return_value=(MagicMock(), MagicMock()),
        ):
            scanner = SpectrumScan()
            scanner.start_freq = 150
            scanner.end_freq = 960

            # Channel/frequency mark format: "FREQ 433.0"
            scanner._SpectrumScan__data_dissector("FREQ 433.0")
            assert scanner.current_freq == 433.0

    @patch("modules.sx1262.spectrum.np")
    def test_data_dissector_scan_data(self, mock_np):
        with patch(
            "modules.sx1262.spectrum.plt.subplots",
            return_value=(MagicMock(), MagicMock()),
        ):
            scanner = SpectrumScan()
            scanner.start_freq = 150
            scanner.end_freq = 960
            scanner.current_freq = 150.0
            scanner.delta_freq = 100

            # Simulate predefined numpy array
            scanner.data_matrix = MagicMock()

            # Data line format: "SCAN -100,-95,-90,END"
            scanner._SpectrumScan__data_dissector("SCAN -100,-95,-90,END")

            # matrix slicing operation check
            # The code tries to fill a column. MagicMock captures the manipulation
            assert scanner.data_matrix.__setitem__.called

    @patch("modules.sx1262.spectrum.serial.Serial")
    def test_run_success(self, mock_serial):
        with patch(
            "modules.sx1262.spectrum.plt.subplots",
            return_value=(MagicMock(), MagicMock()),
        ):
            scanner = SpectrumScan(port="/dev/ttyUSB0")

            # Patch all plot and UI methods to run silently
            with patch.object(scanner, "create_plot"), patch(
                "modules.sx1262.spectrum.plt.show"
            ), patch("modules.sx1262.spectrum.animation.FuncAnimation"), patch(
                "modules.sx1262.spectrum.threading.Thread"
            ):

                res = scanner.run(start_freq=400, end_freq=500, rssi_offset=-20)

                assert res is True
                assert scanner.start_freq == 400
                assert scanner.end_freq == 500
                assert scanner.rssi_offset == -20
                mock_serial.assert_called_once_with(
                    "/dev/ttyUSB0", DEFAULT_BAUDRATE, timeout=2
                )

                # Correct commands should have been sent over serial
                device_uart = scanner.device_uart
                assert device_uart.write.call_count == 4
                device_uart.write.assert_any_call(b"stop\r\n")
                device_uart.write.assert_any_call(b"set_start_freq 400\r\n")
                device_uart.write.assert_any_call(b"set_end_freq 500\r\n")
                device_uart.write.assert_any_call(b"start\r\n")

    def test_run_invalid_frequencies(self):
        with patch(
            "modules.sx1262.spectrum.plt.subplots",
            return_value=(MagicMock(), MagicMock()),
        ):
            scanner = SpectrumScan(port="/dev/ttyUSB0")

            # frequency start is greater than frequency end
            res1 = scanner.run(start_freq=900, end_freq=400)
            assert res1 is False

            # out of bounds (> 960)
            res2 = scanner.run(start_freq=1000, end_freq=1100)
            assert res2 is False

    @patch("modules.sx1262.spectrum.serial.Serial")
    def test_run_serial_exception(self, mock_serial):
        import serial

        class FakeSerialException(Exception):
            pass

        serial.SerialException = FakeSerialException
        mock_serial.side_effect = serial.SerialException("Port Busy")

        with patch(
            "modules.sx1262.spectrum.plt.subplots",
            return_value=(MagicMock(), MagicMock()),
        ):
            scanner = SpectrumScan(port="/dev/ttyUSB0")

            res = scanner.run()
            assert res is False

    def test_stop_task(self):
        with patch(
            "modules.sx1262.spectrum.plt.subplots",
            return_value=(MagicMock(), MagicMock()),
        ):
            scanner = SpectrumScan(port="/dev/ttyUSB0")
            scanner.device_uart = MagicMock()
            scanner.device_uart.is_open = True

            mock_thread = MagicMock()
            mock_thread.is_alive.return_value = True
            scanner.recv_worker = mock_thread

            scanner.stop_task()
            assert scanner.recv_running is False
            scanner.device_uart.close.assert_called_once()
            mock_thread.join.assert_called_once()

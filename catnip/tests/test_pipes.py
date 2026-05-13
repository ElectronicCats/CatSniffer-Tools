"""
test_pipes.py
=============
Tests for CatSniffer pipes module.

Covers:
  - modules/pipes.py: UnixPipe, WindowsPipe, Wireshark

Run with:
    pytest tests/test_pipes.py -v
"""

import os
import sys
import threading
import subprocess
from unittest.mock import MagicMock, patch
import pytest

# Get the absolute path to the project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

# ─────────────────────────────────────────────────────────────────────────────
# Initial mocks to avoid import errors on Linux/Mac
# ─────────────────────────────────────────────────────────────────────────────

# Create a mock module so global import doesn't fail
mock_pywintypes = MagicMock()
mock_pywintypes.error = Exception  # Base exception type for mock
sys.modules["pywintypes"] = mock_pywintypes
sys.modules["win32pipe"] = MagicMock()
sys.modules["win32file"] = MagicMock()

# Now we can import safely
from modules.core.pipes import (
    UnixPipe,
    WindowsPipe,
    Wireshark,
    DEFAULT_UNIX_PATH,
    DEFAULT_WINDOWS_PATH,
)


# ═════════════════════════════════════════════════════════════════════════════
#  1.  TESTS FOR UnixPipe
# ═════════════════════════════════════════════════════════════════════════════


class TestUnixPipe:
    """Tests for the UnixPipe class."""

    @patch("os.mkfifo")
    def test_create_success(self, mock_mkfifo):
        pipe = UnixPipe(path="/tmp/test_pipe")
        mock_mkfifo.assert_called_once_with("/tmp/test_pipe")

    @patch("os.mkfifo", side_effect=FileExistsError("Already exists"))
    def test_create_exists(self, mock_mkfifo):
        pipe = UnixPipe(path="/tmp/test_pipe")
        # Should not raise exception
        mock_mkfifo.assert_called_once()

    @patch("os.mkfifo", return_value=None)
    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", new_callable=MagicMock)
    def test_open_success(self, mock_open, mock_exists, mock_mkfifo):
        pipe = UnixPipe(path="/tmp/test_pipe")
        pipe.open()
        mock_exists.assert_called()
        mock_open.assert_called_once_with("/tmp/test_pipe", "ab")
        assert pipe.ready_event.is_set()

    @patch("os.mkfifo", return_value=None)
    def test_close(self, mock_mkfifo):
        pipe = UnixPipe(path="/tmp/test_pipe")
        mock_writer = MagicMock()
        pipe.pipe_writer = mock_writer
        pipe.ready_event.set()
        pipe.close()
        mock_writer.close.assert_called_once()
        assert pipe.pipe_writer is None
        assert not pipe.ready_event.is_set()

    @patch("os.mkfifo", return_value=None)
    @patch("os.path.exists", return_value=True)
    @patch("os.remove")
    def test_remove(self, mock_remove, mock_exists, mock_mkfifo):
        pipe = UnixPipe(path="/tmp/test_pipe")
        pipe.pipe_writer = MagicMock()
        pipe.remove()
        pipe.pipe_writer.close.assert_called_once()
        mock_remove.assert_called_once_with("/tmp/test_pipe")

    @patch("os.mkfifo", return_value=None)
    def test_write_packet_success(self, mock_mkfifo):
        pipe = UnixPipe(path="/tmp/test_pipe")
        pipe.pipe_writer = MagicMock()
        test_data = b"test_data"
        pipe.write_packet(test_data)
        pipe.pipe_writer.write.assert_called_once_with(test_data)
        pipe.pipe_writer.flush.assert_called_once()

    @patch("os.mkfifo", return_value=None)
    @patch("os.path.exists", return_value=True)
    @patch("os.remove")
    def test_write_packet_broken_pipe(self, mock_remove, mock_exists, mock_mkfifo):
        pipe = UnixPipe(path="/tmp/test_pipe")
        pipe.pipe_writer = MagicMock()
        pipe.pipe_writer.write.side_effect = BrokenPipeError("Broken")
        with pytest.raises(SystemExit):
            pipe.write_packet(b"data")
        # Should have called remove()
        mock_remove.assert_called_once_with("/tmp/test_pipe")


# ═════════════════════════════════════════════════════════════════════════════
#  2.  TESTS FOR WindowsPipe
# ═════════════════════════════════════════════════════════════════════════════


class TestWindowsPipe:
    """Tests for the WindowsPipe class."""

    @patch("modules.core.pipes.win32pipe", create=True)
    def test_create_success(self, mock_win32pipe):
        mock_win32pipe.CreateNamedPipe.return_value = "fake_handle"
        pipe = WindowsPipe(path=r"\\.\pipe\test")
        mock_win32pipe.CreateNamedPipe.assert_called_once()
        assert pipe.pipe_writer == "fake_handle"

    @patch("modules.core.pipes.win32pipe", create=True)
    def test_open_success(self, mock_win32pipe):
        pipe = WindowsPipe(path=r"\\.\pipe\test")
        pipe.pipe_writer = "fake_handle"
        pipe.open()
        mock_win32pipe.ConnectNamedPipe.assert_called_once_with("fake_handle", None)
        assert pipe.ready_event.is_set()

    @patch("modules.core.pipes.win32pipe", create=True)
    @patch("modules.core.pipes.win32file", create=True)
    def test_close(self, mock_win32file, mock_win32pipe):
        pipe = WindowsPipe(path=r"\\.\pipe\test")
        pipe.pipe_writer = "fake_handle"
        pipe.ready_event.set()
        pipe.close()
        mock_win32pipe.DisconnectNamedPipe.assert_called_once_with("fake_handle")
        mock_win32file.CloseHandle.assert_called_once_with("fake_handle")
        assert pipe.pipe_writer is None
        assert not pipe.ready_event.is_set()

    @patch("modules.core.pipes.os.path.exists", return_value=True)
    @patch("modules.core.pipes.os.remove")
    @patch("modules.core.pipes.win32pipe", create=True)
    def test_remove(self, mock_win32pipe, mock_remove, mock_exists):
        pipe = WindowsPipe(path=r"\\.\pipe\test")
        mock_writer = MagicMock()
        pipe.pipe_writer = mock_writer
        pipe.remove()
        mock_writer.close.assert_called_once()
        mock_remove.assert_called_once_with(r"\\.\pipe\test")

    @patch("modules.core.pipes.win32file", create=True)
    @patch("modules.core.pipes.win32pipe", create=True)
    def test_write_packet_success(self, mock_win32pipe, mock_win32file):
        pipe = WindowsPipe(path=r"\\.\pipe\test")
        pipe.pipe_writer = "fake_handle"
        test_data = b"test_data"
        pipe.write_packet(test_data)
        mock_win32file.WriteFile.assert_called_once_with("fake_handle", test_data)
        mock_win32file.FlushFileBuffers.assert_called_once_with("fake_handle")


# ═════════════════════════════════════════════════════════════════════════════
#  3.  TESTS FOR Wireshark
# ═════════════════════════════════════════════════════════════════════════════


class TestWireshark:
    """Tests for the Wireshark class."""

    def test_get_wireshark_path_windows(self):
        with patch("platform.system", return_value="Windows"):
            ws = Wireshark()
            with patch("pathlib.Path.exists", return_value=True):
                path = ws.get_wireshark_path()
                assert "Wireshark.exe" in str(path)

    def test_get_wireshark_path_linux(self):
        with patch("platform.system", return_value="Linux"):
            ws = Wireshark()
            with patch("pathlib.Path.exists", return_value=True):
                path = ws.get_wireshark_path()
                assert "wireshark" in str(path).lower()

    def test_get_wireshark_path_darwin(self):
        with patch("platform.system", return_value="Darwin"):
            ws = Wireshark()
            path = ws.get_wireshark_path()
            assert "MacOS/Wireshark" in str(path)

    def test_get_wireshark_path_unsupported(self):
        with patch("platform.system", return_value="FreeBSD"):
            ws = Wireshark()
            path = ws.get_wireshark_path()
            assert path is None

    def test_get_wireshark_pipepath_unix(self):
        with patch("platform.system", return_value="Linux"):
            ws = Wireshark()
            assert ws.get_wireshark_pipepath() == DEFAULT_UNIX_PATH

    def test_get_wireshark_pipepath_windows(self):
        with patch("platform.system", return_value="Windows"):
            ws = Wireshark()
            assert "pipe" in ws.get_wireshark_pipepath()

    def test_get_wireshark_cmd(self):
        ws = Wireshark(pipe_name="/tmp/custom_pipe")
        ws.system = "Linux"
        with patch.object(
            ws, "get_wireshark_path", return_value="/bin/wireshark"
        ), patch.object(ws, "get_wireshark_pipepath", return_value="/tmp/custom_pipe"):
            cmd = ws.get_wireshark_cmd()
            assert cmd == ["/bin/wireshark", "-k", "-i", "/tmp/custom_pipe"]

    def test_get_wireshark_cmd_with_profile(self):
        ws = Wireshark(pipe_name="/tmp/custom_pipe", profile="zigbee")
        ws.system = "Linux"
        with patch.object(
            ws, "get_wireshark_path", return_value="/bin/wireshark"
        ), patch.object(ws, "get_wireshark_pipepath", return_value="/tmp/custom_pipe"):
            cmd = ws.get_wireshark_cmd()
            assert "-C" in cmd
            assert "zigbee" in cmd

    @patch("subprocess.Popen")
    def test_run_success(self, mock_popen):
        ws = Wireshark()
        with patch.object(ws, "get_wireshark_cmd", return_value=["wireshark", "-k"]):
            ws.run()
            mock_popen.assert_called_once_with(["wireshark", "-k"])
            assert ws.wireshark_process is not None

"""
conftest.py
===========
Global pytest configuration and shared fixtures for all test modules.

pytest automatically loads this before running any tests.
"""

import sys
from unittest.mock import MagicMock
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Mocks of system dependencies / heavy libraries
# These are injected ONLY ONCE here to avoid repeating them in each test file.
# ─────────────────────────────────────────────────────────────────────────────

# Scapy (package analysis IEEE 802.15.4 / Zigbee)
sys.modules.setdefault("scapy", MagicMock())
sys.modules.setdefault("scapy.layers", MagicMock())
sys.modules.setdefault("scapy.layers.dot15d4", MagicMock())
sys.modules.setdefault("scapy.layers.zigbee", MagicMock())
sys.modules.setdefault("scapy.config", MagicMock())

# Rich (UI terminal)
sys.modules.setdefault("rich.live", MagicMock())
sys.modules.setdefault("rich.table", MagicMock())

# Windows dependencies (no disponibles en Linux/macOS/CI)
mock_pywintypes = MagicMock()
mock_pywintypes.error = Exception
sys.modules.setdefault("pywintypes", mock_pywintypes)
sys.modules.setdefault("win32pipe", MagicMock())
sys.modules.setdefault("win32file", MagicMock())

# Hardware dependencies (serial coms, graphs)
# NOTE: We must explicitly build the serial mock hierarchy so that all access
# paths (`sys.modules`, attribute access on parent mock) resolve to the SAME
# objects.  Without this, `patch("serial.tools.list_ports.comports")` would
# patch a different object than what `verify.py` uses at runtime.
_mock_serial_tools_list_ports = MagicMock(name="serial.tools.list_ports")
_mock_serial_tools = MagicMock(name="serial.tools")
_mock_serial_tools.list_ports = _mock_serial_tools_list_ports
_mock_serial = MagicMock(name="serial")
_mock_serial.tools = _mock_serial_tools


# `except serial.SerialException` requires a real exception class, not a
# MagicMock attribute — give the mocked module a genuine one to catch.
class _SerialException(Exception):
    pass


_mock_serial.SerialException = _SerialException
for _mod_name, _mod_obj in [
    ("serial", _mock_serial),
    ("serial.tools", _mock_serial_tools),
    ("serial.tools.list_ports", _mock_serial_tools_list_ports),
]:
    sys.modules.setdefault(_mod_name, _mod_obj)
sys.modules.setdefault("numpy", MagicMock())
sys.modules.setdefault("matplotlib", MagicMock())
sys.modules.setdefault("matplotlib.pyplot", MagicMock())
sys.modules.setdefault("matplotlib.animation", MagicMock())


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures reusable across multiple test modules
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def run_catnip():
    """Run ``catnip.py`` as a real subprocess and return the ``CompletedProcess``.

    The only way to observe the CLI the way a user does: real exit codes, real
    stdout/stderr, and none of the ``sys.modules`` stubbing above.  No hardware
    is required by the commands that use it.
    """
    import os
    import subprocess

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def run(*args, timeout=10):
        return subprocess.run(
            [sys.executable, os.path.join(project_root, "catnip.py"), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=project_root,
        )

    return run


@pytest.fixture
def mock_device():
    """CatSniffer device mock for runner and similar tests."""
    dev = MagicMock()
    dev.bridge_port = "/dev/ttyACM0"
    return dev


@pytest.fixture
def mock_console():
    """Consola Rich."""
    return MagicMock()

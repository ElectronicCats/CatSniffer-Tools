"""
test_meshtastic_dashboard.py
============================
Tests for ``modules/protocols/meshtastic/dashboard.py`` — specifically the
standalone ``python dashboard.py`` entry point, which configured the radio
through the wrong serial port.

Kept out of ``test_catsniffer.py`` on purpose: that module replaces ``rich``
wholesale with a ``MagicMock`` in ``sys.modules``, and ``dashboard.py``
subclasses real textual widgets, which cannot be stubbed the same way and which
pull in the real ``rich`` themselves.  The fixture below lifts those stubs just
long enough to import the module under test.
"""

import asyncio
import sys
from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def dashboard():
    """Import ``dashboard.py`` against the real ``rich``.

    ``test_catsniffer.py`` registers ``rich`` and its submodules as MagicMocks
    at collection time and every later test module inherits them, so the
    ``rich.markup`` / ``rich.text`` imports at the top of ``dashboard.py`` fail
    with "'rich' is not a package".  Stubbing textual instead is not an option:
    ``MeshtasticChatApp`` subclasses ``App``, and a class cannot inherit from a
    MagicMock instance.

    The stubs are put back afterwards so the rest of the suite sees what it
    expects.  Modules already imported under the mock keep their references —
    only the imports performed inside this window get the real package.
    """
    stubbed = {
        name: mod
        for name, mod in sys.modules.items()
        if name == "rich" or name.startswith("rich.")
    }
    for name in stubbed:
        del sys.modules[name]

    try:
        import modules.protocols.meshtastic.dashboard as module

        yield module
    finally:
        for name, mod in stubbed.items():
            sys.modules.setdefault(name, mod)


def _args(**overrides):
    base = dict(
        port="/dev/ttyACM1",
        shell_port="/dev/ttyACM2",
        baudrate=115200,
        frequency=906.875,
        preset="LongFast",
    )
    base.update(overrides)
    return Namespace(**base)


class TestRunApp:
    """``python dashboard.py`` used to configure the radio over the LoRa port.

    Nothing on that port parses ``lora_freq``: ``process_lora_command`` knows
    only TEST/FSKTEST/FSKTX/FSKRX and only in COMMAND mode, while the firmware
    boots in STREAM mode, where every byte written there is handed to
    ``lora_send``.  So the whole configuration sequence went out over the air
    as LoRa payloads and the radio kept the settings it already had — no error
    anywhere, just a session on the wrong frequency and preset.
    """

    def test_the_radio_is_configured_through_the_shell_not_the_lora_stream(
        self, dashboard
    ):
        mock_monitor = MagicMock()
        mock_app = MagicMock()

        async def _run_async():
            return None

        mock_app.run_async = _run_async

        with patch.object(
            dashboard, "Monitor", return_value=mock_monitor
        ), patch.object(
            dashboard, "MeshtasticChatApp", return_value=mock_app
        ), patch.object(
            dashboard, "configure_meshtastic_radio", return_value=True
        ) as configure:
            asyncio.run(dashboard.run_app(_args()))

        configure.assert_called_once_with("/dev/ttyACM2", 906875000, "LongFast")
        # The monitor reads the LoRa stream; a command written into it is a
        # transmitted packet, not a setting.
        mock_monitor.write.assert_not_called()
        mock_monitor.stop.assert_called_once()

    def test_a_failed_configuration_does_not_open_the_lora_port(self, dashboard):
        """A radio left on the wrong preset has nothing to listen to."""
        with patch.object(dashboard, "Monitor") as monitor_cls, patch.object(
            dashboard, "configure_meshtastic_radio", return_value=False
        ):
            asyncio.run(dashboard.run_app(_args()))

        monitor_cls.assert_not_called()

    def test_no_config_port_is_reported_rather_than_worked_around(self, dashboard):
        with patch.object(
            dashboard, "resolve_shell_port", return_value=None
        ), patch.object(dashboard, "Monitor") as monitor_cls, patch.object(
            dashboard, "configure_meshtastic_radio"
        ) as configure:
            asyncio.run(dashboard.run_app(_args(shell_port=None)))

        configure.assert_not_called()
        monitor_cls.assert_not_called()


class TestResolveShellPort:
    """The script takes one ``--port``; the config port is detected."""

    def test_an_explicit_port_wins(self, dashboard):
        assert dashboard.resolve_shell_port("/dev/ttyACM9") == "/dev/ttyACM9"

    def test_it_falls_back_to_device_detection(self, dashboard):
        device = MagicMock(shell_port="/dev/ttyACM2")
        with patch("modules.core.usb_connection.find_device", return_value=device):
            assert dashboard.resolve_shell_port(None) == "/dev/ttyACM2"

    def test_no_device_resolves_to_nothing(self, dashboard):
        with patch("modules.core.usb_connection.find_device", return_value=None):
            assert dashboard.resolve_shell_port(None) is None

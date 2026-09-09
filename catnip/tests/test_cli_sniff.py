"""
test_cli_sniff.py
=================
Behaviour of ``modules/sniff/cli.py`` -- ``sniff ble|zigbee|thread|lora|
airtag_scanner``.

Part of ``BOMBERCAT_PARITY.md`` section 4: one test file per CLI module.  Only
the group-level test below was moved here from ``TestCLISubprocess`` in
``tests/test_catsniffer.py``; the sniffers themselves need a bridge and are
covered indirectly by ``TestRunBridge``/``TestRunSxBridge``.

Note on ``test_sniff_missing_required_args``: it is moved unchanged, and it
FAILS with Click 8.1, where a group invoked with no subcommand prints its help
and exits 0.  Click 8.2 made that case exit 2, which is what the assertion
expects.  ``setup.py`` asks for ``click>=8.0.0``, so the outcome follows
whichever Click is installed.  This predates the CLI refactor and is left as a
visible signal rather than relaxed away.
"""

import importlib
import sys
from unittest.mock import MagicMock

import pytest


# ``tests/test_catsniffer.py`` stubs ``protocol.*`` in ``sys.modules`` at import
# time, and it is collected first, so the stub is in place by the time this file
# runs.  These tests assert on the exact command strings the firmware parses, so
# they need the real module: swap the stub out and back around each test.
_PROTOCOL_MODULES = ("protocol", "protocol.common", "protocol.sniffer_sx")


@pytest.fixture
def sniffer_sx():
    saved = {
        name: sys.modules.pop(name)
        for name in _PROTOCOL_MODULES
        if isinstance(sys.modules.get(name), MagicMock)
    }
    try:
        yield importlib.import_module("protocol.sniffer_sx")
    finally:
        for name in _PROTOCOL_MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


@pytest.mark.slow
class TestSniffGroup:
    def test_sniff_missing_required_args(self, run_catnip):
        result = run_catnip("sniff")
        # Should ask for arguments or show error
        assert result.returncode != 0 or "Error" in result.stdout + result.stderr


class TestLoRaShellCommands:
    """``lora_syncword``/``lora_preamble``/``lora_iq`` command formatting.

    The firmware parser (``cmd_lora_syncword``/``cmd_lora_iq`` in
    ``shell_commands.c``) matches on exact lowercase keywords and a ``0x``
    prefix, so these strings are a contract, not cosmetics.
    """

    def test_syncword_aliases(self, sniffer_sx):
        cmd = sniffer_sx.LoRaShellCommands
        assert cmd.set_syncword("private") == "lora_syncword private"
        assert cmd.set_syncword("public") == "lora_syncword public"

    def test_syncword_custom_byte_is_normalised(self, sniffer_sx):
        # Meshtastic; bare and lowercase hex both reach the firmware prefixed
        cmd = sniffer_sx.LoRaShellCommands
        assert cmd.set_syncword("0x2b") == "lora_syncword 0x2B"
        assert cmd.set_syncword("2B") == "lora_syncword 0x2B"

    @pytest.mark.parametrize("bad", ["zz", "0x1234", "0x00", ""])
    def test_syncword_rejects_invalid(self, sniffer_sx, bad):
        with pytest.raises(ValueError):
            sniffer_sx.LoRaShellCommands.set_syncword(bad)

    def test_preamble_and_iq(self, sniffer_sx):
        cmd = sniffer_sx.LoRaShellCommands
        assert cmd.set_preamble(16) == "lora_preamble 16"
        assert cmd.set_iq("inverted") == "lora_iq inverted"
        with pytest.raises(ValueError):
            cmd.set_preamble(5)
        with pytest.raises(ValueError):
            cmd.set_iq("reversed")

    def test_loratap_header_carries_custom_syncword(self, sniffer_sx):
        context = {
            "frequency": 915000000,
            "bandwidth": 125,
            "spread_factor": 7,
            "coding_rate": 5,
            "sync_word": "0x2B",
        }
        packet = sniffer_sx.SnifferSx.Packet(
            "RX: DEADBEEF | RSSI: -50 | SNR: 9", context
        )
        # LoRaTap v0: the sync word is the last byte of the 15-byte header,
        # which sits right after the 16-byte pcap record header.
        assert packet.pcap[16 + 14] == 0x2B


@pytest.mark.slow
class TestSniffLoRaOptions:
    def test_rejects_invalid_sync_word(self, run_catnip):
        result = run_catnip("sniff", "lora", "-sw", "zzz")
        assert result.returncode != 0
        assert "sync word" in (result.stdout + result.stderr).lower()

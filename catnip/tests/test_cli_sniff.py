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


@pytest.mark.slow
class TestSniffLoRaDefaults:
    """``sniff lora`` has to work with no flags at all.

    Companion to ``test_choice_defaults_are_one_of_the_choices``: that one pins
    the declaration, this one pins the value the bridge actually receives.
    ``--bandwidth`` is declared as a ``Choice`` of strings but the radio wants
    an int, so the conversion is easy to lose.
    """

    def _invoke(self, sniffer_sx, *args):
        """Run ``sniff lora`` with the device and the bridge stubbed out.

        ``normalize_syncword`` is re-patched from the ``sniffer_sx`` fixture:
        ``modules.sniff.cli`` may have bound the ``protocol`` stub that
        ``test_catsniffer.py`` installs (see the module docstring), and the
        ``--sync-word`` callback unpacks that function's result.
        """
        from unittest.mock import patch

        from click.testing import CliRunner

        from modules.core.cli import build_cli

        with patch(
            "modules.sniff.cli.normalize_syncword", sniffer_sx.normalize_syncword
        ), patch("modules.sniff.cli.run_sx_bridge") as bridge, patch(
            "modules.sniff.cli.get_device_or_exit", return_value=MagicMock()
        ):
            result = CliRunner().invoke(build_cli(), ["sniff", "lora", *args])
        return result, bridge

    def test_runs_with_no_arguments(self, sniffer_sx):
        result, bridge = self._invoke(sniffer_sx)
        assert result.exit_code == 0, result.output
        bridge.assert_called_once()

    @pytest.mark.parametrize(
        "args,expected", [((), 125), (("-bw", "250"), 250), (("-bw", "500"), 500)]
    )
    def test_bandwidth_reaches_the_bridge_as_an_int(self, sniffer_sx, args, expected):
        _, bridge = self._invoke(sniffer_sx, *args)
        # run_sx_bridge(dev, frequency, bandwidth, ...) -- positional.
        bandwidth = bridge.call_args.args[2]
        assert bandwidth == expected
        assert isinstance(bandwidth, int)


@pytest.mark.slow
class TestCaptureFileGuard:
    """``-w`` refuses an existing file *before* the device is touched.

    The bridge refuses too, but by then the sniffer has been flashed and the
    port opened.  These run the real CLI with no hardware attached: reaching
    the device-selection stage at all would show up as a different error.
    """

    @pytest.mark.parametrize(
        "args",
        [
            ("sniff", "lora"),
            ("sniff", "zigbee", "-c", "15"),
            ("sniff", "thread", "-c", "15"),
        ],
    )
    def test_existing_capture_file_aborts(self, run_catnip, tmp_path, args):
        target = tmp_path / "capture.pcap"
        target.write_bytes(b"previous capture")

        result = run_catnip(*args, "-w", str(target))
        output = result.stdout + result.stderr

        assert result.returncode != 0
        assert "already exists" in output
        assert "--force" in output
        # Nothing was written over the top of the earlier capture.
        assert target.read_bytes() == b"previous capture"


@pytest.mark.slow
class TestSniffLoRaWireshark:
    """``sniff lora`` Wireshark integration: ``-ws``, ``-oc`` and the prompt.

    ``-ws`` streams into Wireshark live over a pipe (handled by the bridge);
    ``-oc`` and the post-capture prompt open the *saved file* once the sniffer
    stops, which is the path that works over SSH and on a machine where the
    LoRaTap pipe never had a reader.

    Everything below the CLI is stubbed: no device, no bridge, no Wireshark
    process.  ``sys`` is patched as a whole because ``CliRunner`` swaps
    ``sys.stdin`` for the duration of ``invoke()``, so patching the attribute
    would not survive into the command.  Messages are collected from the
    ``print_*`` helpers rather than from ``result.output``: they go out through
    the shared Rich console, which does not always land in Click's capture when
    the whole suite runs.
    """

    def _invoke(
        self,
        sniffer_sx,
        *args,
        packets=5,
        wireshark="/usr/bin/wireshark",
        isatty=True,
        confirm=True,
    ):
        from unittest.mock import patch

        from click.testing import CliRunner

        from modules.core.cli import build_cli

        messages = []

        def fake_bridge(*call_args, **kwargs):
            # The real bridge creates the capture file before streaming.
            pcap_file = call_args[13]
            if pcap_file:
                with open(pcap_file, "wb") as fh:
                    fh.write(b"header")
            return packets

        with patch(
            "modules.sniff.cli.normalize_syncword", sniffer_sx.normalize_syncword
        ), patch(
            "modules.sniff.cli.run_sx_bridge", side_effect=fake_bridge
        ) as bridge, patch(
            "modules.sniff.cli.get_device_or_exit", return_value=MagicMock()
        ), patch(
            "modules.sniff.cli.find_wireshark_path", return_value=wireshark
        ), patch(
            "modules.sniff.cli.open_capture_in_wireshark"
        ) as opener, patch(
            "modules.sniff.cli.click.confirm", return_value=confirm
        ), patch(
            "modules.sniff.cli.sys"
        ) as fake_sys, patch(
            "modules.sniff.cli.print_error", side_effect=messages.append
        ), patch(
            "modules.sniff.cli.print_dim", side_effect=messages.append
        ):
            fake_sys.stdin.isatty.return_value = isatty
            result = CliRunner().invoke(build_cli(), ["sniff", "lora", *args])
        return result, bridge, opener, "\n".join(messages)

    @pytest.mark.parametrize("flag", ["-ws", "-oc"])
    def test_missing_wireshark_aborts_before_touching_the_radio(self, sniffer_sx, flag):
        """The device is worth more than the flag: fail before configuring it."""
        result, bridge, opener, messages = self._invoke(
            sniffer_sx, flag, wireshark=None
        )

        assert result.exit_code == 1
        assert "Wireshark not found" in messages
        assert not bridge.called
        assert not opener.called

    def test_open_capture_without_write_saves_to_a_temp_file(self, sniffer_sx):
        """``-oc`` alone still has something to open when the capture ends."""
        result, bridge, opener, _ = self._invoke(sniffer_sx, "-oc")

        pcap_file = bridge.call_args.args[13]
        assert result.exit_code == 0
        assert pcap_file and pcap_file.endswith(".pcapng")
        opener.assert_called_once_with(pcap_file)

    def test_write_only_offers_the_capture_and_opens_it_on_yes(
        self, sniffer_sx, tmp_path
    ):
        target = tmp_path / "capture.pcapng"
        _, _, opener, _ = self._invoke(sniffer_sx, "-w", str(target), confirm=True)
        opener.assert_called_once_with(str(target))

    def test_declined_prompt_leaves_wireshark_closed(self, sniffer_sx, tmp_path):
        target = tmp_path / "capture.pcapng"
        _, _, opener, messages = self._invoke(
            sniffer_sx, "-w", str(target), confirm=False
        )
        assert not opener.called
        assert "wireshark -r" in messages

    def test_no_prompt_without_a_terminal(self, sniffer_sx, tmp_path):
        """Scripts and CI must not block on a confirmation nobody can answer."""
        target = tmp_path / "capture.pcapng"
        result, _, opener, _ = self._invoke(sniffer_sx, "-w", str(target), isatty=False)
        assert result.exit_code == 0
        assert not opener.called

    def test_empty_capture_is_not_offered(self, sniffer_sx, tmp_path):
        target = tmp_path / "capture.pcapng"
        _, _, opener, _ = self._invoke(sniffer_sx, "-w", str(target), packets=0)
        assert not opener.called

    def test_live_wireshark_does_not_prompt_afterwards(self, sniffer_sx, tmp_path):
        """``-ws`` already showed the packets; do not ask to show them again."""
        target = tmp_path / "capture.pcapng"
        _, bridge, opener, _ = self._invoke(sniffer_sx, "-ws", "-w", str(target))
        assert bridge.call_args.args[6] is True  # wireshark flag reaches the bridge
        assert not opener.called

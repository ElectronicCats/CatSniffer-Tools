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
        if saved:
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


class TestFskShellCommands:
    """``fsk_*`` command formatting.

    The firmware parsers (``cmd_fsk_syncword``/``cmd_fsk_bw``/``cmd_fsk_bt`` in
    ``shell_commands.c``) take no arguments they can report an error for: a
    sync word stops at the first non-hex character, a bandwidth falls through a
    threshold ladder to a neighbour, and a bad BT is simply rejected on the
    shell the user is not reading.  So the formatting is pinned here.
    """

    def test_sync_word_accepts_what_a_datasheet_looks_like(self, sniffer_sx):
        cmd = sniffer_sx.FskShellCommands
        assert cmd.set_syncword("2dd4") == "fsk_syncword 2DD4"
        assert cmd.set_syncword("0x2DD4") == "fsk_syncword 2DD4"
        assert cmd.set_syncword("2D:D4") == "fsk_syncword 2DD4"
        assert cmd.set_syncword("2D D4") == "fsk_syncword 2DD4"

    @pytest.mark.parametrize(
        "bad",
        [
            "",  # nothing to match on
            "2D4",  # half a byte
            "2DZ4",  # not hex — the firmware would stop at the Z
            "00112233445566778899",  # 10 bytes, the SX1262 matches 8
        ],
    )
    def test_sync_word_rejects_what_the_firmware_would_truncate(self, sniffer_sx, bad):
        with pytest.raises(ValueError):
            sniffer_sx.normalize_fsk_syncword(bad)

    def test_every_offered_bandwidth_is_accepted(self, sniffer_sx):
        for bandwidth in sniffer_sx.FSK_BANDWIDTHS:
            assert (
                sniffer_sx.FskShellCommands.set_bw(bandwidth) == f"fsk_bw {bandwidth}"
            )

    def test_a_bandwidth_between_two_entries_is_refused(self, sniffer_sx):
        # 100 kHz would land on 117.3 without a word about it.
        with pytest.raises(ValueError):
            sniffer_sx.FskShellCommands.set_bw("100")

    def test_booleans_are_spelled_the_way_the_firmware_reads_them(self, sniffer_sx):
        cmd = sniffer_sx.FskShellCommands
        assert cmd.set_crc(True) == "fsk_crc on"
        assert cmd.set_crc(False) == "fsk_crc off"
        assert cmd.set_whitening(True) == "fsk_whitening on"
        assert cmd.set_whitening(False) == "fsk_whitening off"

    def test_out_of_range_values_never_reach_the_wire(self, sniffer_sx):
        cmd = sniffer_sx.FskShellCommands
        with pytest.raises(ValueError):
            cmd.set_bitrate(500)  # firmware floor is 600 bps
        with pytest.raises(ValueError):
            cmd.set_fdev(250_000)  # firmware ceiling is 200 kHz
        with pytest.raises(ValueError):
            cmd.set_payload(0)

    def test_the_bandwidth_guard_predicts_the_firmware(self, sniffer_sx):
        """``apply_fsk_config`` compares against the nominal kHz, truncated."""
        wide_enough = sniffer_sx.fsk_bandwidth_is_wide_enough
        # 50 kbps at 25 kHz deviation needs 100 kHz by Carson's rule.
        assert wide_enough("187.2", 50000, 25000) is True
        assert wide_enough("117.3", 50000, 25000) is True
        assert wide_enough("93.8", 50000, 25000) is False


class TestFskLoRaTapHeader:
    """An FSK frame carries no LoRa modem settings, and must not claim any.

    The capture still goes out as LoRaTap — it is the only link type Wireshark
    dissects for this radio — so the fields that describe a LoRa modem have to
    read as "unknown" rather than as whatever the last LoRa session used.
    """

    def _fsk_packet(self, sniffer_sx):
        return sniffer_sx.SnifferSx.Packet(
            b"FSK RX: 11223344 | RSSI: -42 | Len: 4\r\n",
            context={"frequency": 868_000_000},
        )

    def test_the_frame_is_parsed_with_no_snr(self, sniffer_sx):
        packet = self._fsk_packet(sniffer_sx)
        assert packet.is_fsk is True
        assert packet.payload == b"\x11\x22\x33\x44"
        assert packet.rssi == -42.0

    def test_bandwidth_spreading_factor_and_sync_word_are_unknown(self, sniffer_sx):
        packet = self._fsk_packet(sniffer_sx)
        # LoRaTap v0 header starts after the 16-byte pcap record header:
        # bandwidth and SF are bytes 8 and 9, the sync word is byte 14.
        assert packet.pcap[16 + 8] == 0
        assert packet.pcap[16 + 9] == 0
        assert packet.pcap[16 + 14] == 0

    def test_the_frequency_is_real_and_reported(self, sniffer_sx):
        packet = self._fsk_packet(sniffer_sx)
        assert packet.pcap[16 + 4 : 16 + 8] == (868_000_000).to_bytes(4, "big")

    def test_a_lora_frame_still_reports_its_modem(self, sniffer_sx):
        """The FSK branch must not have taken the LoRa path with it."""
        packet = sniffer_sx.SnifferSx.Packet(
            b"LORA RX: aabb | RSSI: -30 | SNR: 9\r\n",
            context={
                "frequency": 915_000_000,
                "bandwidth": 250,
                "spread_factor": 9,
                "sync_word": "public",
            },
        )
        assert packet.is_fsk is False
        assert packet.pcap[16 + 8] == 2  # loratap bandwidth enum for 250 kHz
        assert packet.pcap[16 + 9] == 9  # SF9
        assert packet.pcap[16 + 14] == 0x34


@pytest.mark.slow
class TestSniffFskOptions:
    def test_rejects_invalid_sync_word(self, run_catnip):
        result = run_catnip("sniff", "fsk", "-sw", "zzz")
        assert result.returncode != 0
        assert "sync word" in (result.stdout + result.stderr).lower()

    def test_rejects_a_bandwidth_the_radio_does_not_have(self, run_catnip):
        result = run_catnip("sniff", "fsk", "-bw", "100")
        assert result.returncode != 0

    def test_existing_capture_file_aborts(self, run_catnip, tmp_path):
        target = tmp_path / "capture.pcap"
        target.write_bytes(b"previous capture")

        result = run_catnip("sniff", "fsk", "-w", str(target))
        output = result.stdout + result.stderr

        assert result.returncode != 0
        assert "already exists" in output
        assert target.read_bytes() == b"previous capture"


@pytest.mark.slow
class TestSniffFskDefaults:
    """``sniff fsk`` has to work with no flags at all, like ``sniff lora``."""

    def _invoke(self, sniffer_sx, *args):
        """Run ``sniff fsk`` with the device and the bridge stubbed out.

        ``print_warning`` is captured rather than read back off
        ``result.output``: ``rich`` itself is stubbed in ``sys.modules`` by
        whichever test module got there first, so what the console prints is
        not reliably visible to the CliRunner.
        """
        from unittest.mock import patch

        from click.testing import CliRunner

        from modules.core.cli import build_cli

        with patch(
            "modules.sniff.cli.normalize_fsk_syncword",
            sniffer_sx.normalize_fsk_syncword,
        ), patch("modules.sniff.cli.run_fsk_bridge") as bridge, patch(
            "modules.sniff.cli.get_device_or_exit", return_value=MagicMock()
        ), patch(
            "modules.sniff.cli.print_warning"
        ) as warning:
            result = CliRunner().invoke(build_cli(), ["sniff", "fsk", *args])
        result.warnings = " ".join(str(c.args[0]) for c in warning.call_args_list)
        return result, bridge

    def test_runs_with_no_arguments(self, sniffer_sx):
        result, bridge = self._invoke(sniffer_sx)
        assert result.exit_code == 0, result.output
        bridge.assert_called_once()

    def test_the_defaults_reach_the_bridge(self, sniffer_sx):
        _, bridge = self._invoke(sniffer_sx)
        # run_fsk_bridge(dev, frequency, bitrate, fdev, bandwidth, ...)
        args = bridge.call_args.args
        assert args[1:5] == (915000000, 50000, 25000, "187.2")

    def test_the_sync_word_is_normalised_before_it_is_sent(self, sniffer_sx):
        _, bridge = self._invoke(sniffer_sx, "-sw", "2d:d4")
        assert bridge.call_args.args[7] == "2DD4"

    def test_a_narrow_bandwidth_is_flagged_rather_than_silently_widened(
        self, sniffer_sx
    ):
        """The firmware overrides the -bw on a port the user is not watching."""
        result, bridge = self._invoke(sniffer_sx, "-bw", "39.0", "-br", "100000")
        assert result.exit_code == 0, result.output
        assert "too narrow" in result.warnings
        assert "187.2" in result.warnings
        # The override is the firmware's to make: the value asked for is still
        # what gets sent, so the shell reply says which one it settled on.
        assert bridge.call_args.args[4] == "39.0"

    def test_a_wide_enough_bandwidth_says_nothing(self, sniffer_sx):
        result, _ = self._invoke(sniffer_sx, "-bw", "187.2")
        assert "too narrow" not in result.warnings


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
            "modules.sniff.cli.lora_decode_as_args", sniffer_sx.lora_decode_as_args
        ), patch(
            "modules.sniff.cli.lora_wireshark_display_args",
            sniffer_sx.lora_wireshark_display_args,
        ), patch(
            "modules.sniff.cli.LORAWAN_SYNCWORD", sniffer_sx.LORAWAN_SYNCWORD
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
        opener.assert_called_once_with(
            pcap_file, extra_args=sniffer_sx.lora_wireshark_display_args()
        )

    def test_write_only_offers_the_capture_and_opens_it_on_yes(
        self, sniffer_sx, tmp_path
    ):
        target = tmp_path / "capture.pcapng"
        _, _, opener, _ = self._invoke(sniffer_sx, "-w", str(target), confirm=True)
        opener.assert_called_once_with(
            str(target), extra_args=sniffer_sx.lora_wireshark_display_args()
        )

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


class TestLoRaDecodeAsArgs:
    """``lora_decode_as_args``: which dissector Wireshark uses for the payload.

    Wireshark's LoRaTap dissector chooses by sync word — ``tshark -G decodes``
    lists exactly one default entry, ``loratap.syncword 52 lorawan`` — so a
    plain-LoRa capture made on the LoRaWAN sync word (0x34, what ``--sync-word
    public`` sets) is fed to the LoRaWAN dissector and comes out as "LoRaWAN MAC
    Header malformed".  The sync word has to match the transmitter, so the
    override belongs on the Wireshark command line.
    """

    def test_the_lorawan_mapping_is_overridden_without_being_asked(self, sniffer_sx):
        """``--sync-word public`` alone has to produce a readable capture.

        A sniffer cannot know whether a 0x34 payload is LoRaWAN, so it picks the
        harmless reading — raw bytes — rather than stamping a red "malformed"
        over every plain-LoRa frame.
        """
        assert sniffer_sx.lora_decode_as_args("public") == [
            "-d",
            "loratap.syncword==52,data",
        ]

    @pytest.mark.parametrize("sync_word", ["private", "0x2B"])
    def test_nothing_is_added_where_wireshark_is_already_right(
        self, sniffer_sx, sync_word
    ):
        """0x34 is the only sync word Wireshark maps; nothing else needs a rule."""
        assert sniffer_sx.lora_decode_as_args(sync_word) == []

    def test_the_rule_follows_the_sync_word_alone(self, sniffer_sx):
        """No second knob to disagree with the radio: one argument, one answer."""
        import inspect

        params = inspect.signature(sniffer_sx.lora_decode_as_args).parameters
        assert list(params) == ["sync_word"]


class TestLoRaWiresharkDisplayArgs:
    """``lora_wireshark_display_args``: the packet list a LoRa capture deserves.

    A LoRa radio reports no addresses, and neither the LoRaTap dissector nor the
    payload dissector it calls writes the Info column, so Wireshark's default
    columns leave Source, Destination and Info blank on every single packet.
    """

    def test_the_payload_is_what_the_info_column_shows(self, sniffer_sx):
        option = sniffer_sx.lora_wireshark_display_args()[1]
        assert '"Info","%Cus:loratap.payload:0:R"' in option

    def test_link_quality_gets_its_own_columns(self, sniffer_sx):
        """RSSI and SNR are the reason to look at a LoRa capture at all."""
        option = sniffer_sx.lora_wireshark_display_args()[1]
        assert '"RSSI","%Cus:loratap.rssi.packet:0:R"' in option
        assert '"SNR","%Cus:loratap.rssi.snr:0:R"' in option

    def test_link_quality_columns_are_resolved_not_raw(self, sniffer_sx):
        """LoRaTap stores RSSI as (dBm + 139) and SNR as (dB * 4).

        Only the resolved form (``:R``) renders those back as "-42 dBm" and
        "9.0 dB"; ``:U`` would put the stored bytes -- 97 and 36 -- in the
        packet list, which is worse than no column at all.
        """
        option = sniffer_sx.lora_wireshark_display_args()[1]
        assert "loratap.rssi.packet:0:U" not in option
        assert "loratap.rssi.snr:0:U" not in option

    def test_source_and_destination_are_left_out(self, sniffer_sx):
        option = sniffer_sx.lora_wireshark_display_args()[1]
        assert "%s" not in option and "%d" not in option

    def test_it_is_a_wireshark_preference_override(self, sniffer_sx):
        args = sniffer_sx.lora_wireshark_display_args()
        # -o overrides the preference for this run only: the user's own saved
        # column layout has to survive a catnip capture.
        assert args[0] == "-o"
        assert args[1].startswith("gui.column.format:")

    def test_the_ascii_column_is_loaded_with_its_postdissector(self, sniffer_sx):
        """The column and the Lua that fills it are useless one without the other."""
        args = sniffer_sx.lora_wireshark_display_args()
        script = sniffer_sx.LORATAP_ASCII_POSTDISSECTOR

        assert script.is_file(), f"postdissector not shipped: {script}"
        assert sniffer_sx.LORATAP_ASCII_COLUMN in args[1]
        assert args[-2:] == ["-X", f"lua_script:{script}"]

    def test_the_column_names_the_field_the_postdissector_registers(self, sniffer_sx):
        """A custom column is silently empty when the field name drifts."""
        lua = sniffer_sx.LORATAP_ASCII_POSTDISSECTOR.read_text()

        assert 'ProtoField.string("catnip_lora.ascii"' in lua
        assert "catnip_lora.ascii" in sniffer_sx.LORATAP_ASCII_COLUMN

    def test_the_ascii_column_is_dropped_without_the_script(
        self, sniffer_sx, tmp_path, monkeypatch
    ):
        """A frozen build that shipped no Lua must not ask for a column Wireshark
        cannot fill, nor for a script it cannot load."""
        monkeypatch.setattr(
            sniffer_sx, "LORATAP_ASCII_POSTDISSECTOR", tmp_path / "absent.lua"
        )
        args = sniffer_sx.lora_wireshark_display_args()

        assert "-X" not in args
        assert "catnip_lora.ascii" not in args[1]


@pytest.mark.slow
class TestSniffLoRaDecodeRule:
    """The decode-as rule has to reach *both* Wireshark paths.

    The live pipe and the capture file are opened by different code (the bridge
    and ``open_capture_in_wireshark``), and a rule that only reaches one of them
    means the same packets dissect differently depending on how they are viewed.
    """

    def _invoke(self, sniffer_sx, *args):
        from unittest.mock import patch

        from click.testing import CliRunner

        from modules.core.cli import build_cli

        def fake_bridge(*call_args, **kwargs):
            pcap_file = call_args[13]
            if pcap_file:
                with open(pcap_file, "wb") as fh:
                    fh.write(b"header")
            return 3

        with patch(
            "modules.sniff.cli.normalize_syncword", sniffer_sx.normalize_syncword
        ), patch(
            "modules.sniff.cli.lora_decode_as_args", sniffer_sx.lora_decode_as_args
        ), patch(
            "modules.sniff.cli.lora_wireshark_display_args",
            sniffer_sx.lora_wireshark_display_args,
        ), patch(
            "modules.sniff.cli.LORAWAN_SYNCWORD", sniffer_sx.LORAWAN_SYNCWORD
        ), patch(
            "modules.sniff.cli.run_sx_bridge", side_effect=fake_bridge
        ) as bridge, patch(
            "modules.sniff.cli.get_device_or_exit", return_value=MagicMock()
        ), patch(
            "modules.sniff.cli.find_wireshark_path", return_value="/usr/bin/wireshark"
        ), patch(
            "modules.sniff.cli.open_capture_in_wireshark"
        ) as opener, patch(
            "modules.sniff.cli.sys"
        ) as fake_sys:
            fake_sys.stdin.isatty.return_value = True
            result = CliRunner().invoke(build_cli(), ["sniff", "lora", *args])
        return result, bridge, opener

    def _decode_rule(self, args):
        """The ``-d`` pair, dropping the column layout every capture also gets."""
        return args[: args.index("-o")] if "-o" in args else args

    def test_rule_reaches_the_live_wireshark(self, sniffer_sx):
        result, bridge, _ = self._invoke(sniffer_sx, "-ws", "-sw", "public")
        assert result.exit_code == 0
        assert self._decode_rule(bridge.call_args.kwargs["wireshark_args"]) == [
            "-d",
            "loratap.syncword==52,data",
        ]

    def test_rule_reaches_the_capture_file(self, sniffer_sx, tmp_path):
        target = tmp_path / "capture.pcapng"
        _, _, opener = self._invoke(
            sniffer_sx, "-oc", "-w", str(target), "-sw", "public"
        )
        opener.assert_called_once_with(
            str(target),
            extra_args=["-d", "loratap.syncword==52,data"]
            + sniffer_sx.lora_wireshark_display_args(),
        )

    def test_nothing_is_passed_for_a_private_sync_word(self, sniffer_sx):
        _, bridge, _ = self._invoke(sniffer_sx, "-ws", "-sw", "private")
        assert self._decode_rule(bridge.call_args.kwargs["wireshark_args"]) == []

    def test_the_dissector_is_not_selectable_from_the_command_line(self, sniffer_sx):
        """The rule follows from ``--sync-word``; a second flag could only
        contradict it, so the removed one must not quietly come back.

        Both spellings have to be refused: ``-da`` would otherwise be read as
        ``-d a`` — Click splits a short option from its value — and quietly
        become a device argument rather than a dissector one.
        """
        for flag in ("--dissect-as", "-da"):
            result, bridge, _ = self._invoke(
                sniffer_sx, "-ws", "-sw", "public", flag, "lorawan"
            )
            assert result.exit_code != 0, flag
            assert not bridge.called, flag

    @pytest.mark.parametrize("args", [("-ws",), ("-ws", "-sw", "public")])
    def test_the_column_layout_reaches_wireshark_whatever_the_sync_word(
        self, sniffer_sx, args
    ):
        """Empty Source/Destination/Info columns are not a per-sync-word problem."""
        _, bridge, _ = self._invoke(sniffer_sx, *args)
        passed = bridge.call_args.kwargs["wireshark_args"]
        display = sniffer_sx.lora_wireshark_display_args()
        assert passed[-len(display) :] == display


class TestLoRaWANDissectionNotice:
    """catnip chooses the dissector for the user, so it has to say what it chose.

    The helper is exercised directly: the command prints plenty of other lines
    through the same ``print_*`` helpers, and this asserts on *this* notice.
    """

    def _notice(self, sniffer_sx, opening_wireshark, sync_word):
        from unittest.mock import patch

        from modules.sniff import cli

        lines = []
        with patch(
            "modules.sniff.cli.normalize_syncword", sniffer_sx.normalize_syncword
        ), patch(
            "modules.sniff.cli.LORAWAN_SYNCWORD", sniffer_sx.LORAWAN_SYNCWORD
        ), patch(
            "modules.sniff.cli.print_info", side_effect=lines.append
        ), patch(
            "modules.sniff.cli.print_dim", side_effect=lines.append
        ):
            cli._explain_lorawan_dissection(opening_wireshark, sync_word)
        return "\n".join(lines)

    def test_the_automatic_choice_is_announced_with_its_escape_hatch(self, sniffer_sx):
        """Silence is wrong here: a LoRaWAN user must learn why it says Data,
        and the escape hatch is now Wireshark's own, not a catnip flag."""
        notice = self._notice(sniffer_sx, True, "public")
        assert "0x34" in notice
        assert "Decode As" in notice
        assert "--dissect-as" not in notice

    @pytest.mark.parametrize("sync_word", ["private", "0x2B"])
    def test_silent_when_wireshark_would_have_been_right_anyway(
        self, sniffer_sx, sync_word
    ):
        assert self._notice(sniffer_sx, True, sync_word) == ""

    def test_silent_when_wireshark_is_not_being_opened(self, sniffer_sx):
        """Nothing to explain when nobody is looking at a dissector."""
        assert self._notice(sniffer_sx, False, "public") == ""

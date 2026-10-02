"""
test_lora_scan.py
=================
Tests for ``catnip lora scan`` — the host-driven LoRa parameter sweep.

Covers:
  - modules/protocols/sx1262/scan.py (parsing, table state, sweep attribution)
  - the ``catnip lora scan`` Click command's option validation

The serial and rich layers are the global mocks from ``conftest.py``, so
nothing here opens a port or paints a terminal.

Run with:
    pytest tests/test_lora_scan.py -v
"""

import queue
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from modules.protocols.cli.sx1262 import lora
from modules.protocols.sx1262.scan import (
    LoraScanner,
    ScanGraph,
    build_combos,
    format_combo,
    parse_bandwidths,
    parse_frequencies,
    parse_spread_factors,
    sniff_command,
    sweep_duration,
)


# ═════════════════════════════════════════════════════════════════════════════
#  1.  Parsing the search space
# ═════════════════════════════════════════════════════════════════════════════


class TestParseFrequencies:
    def test_megahertz(self):
        assert parse_frequencies("915") == [915_000_000]

    def test_fractional_megahertz(self):
        """868.1 MHz has to survive the float→int conversion exactly."""
        assert parse_frequencies("868.1") == [868_100_000]

    def test_hertz_passes_through(self):
        """Above 1000 the number can only be Hz — the radio stops at 960 MHz."""
        assert parse_frequencies("915000000") == [915_000_000]

    def test_list_keeps_order_and_drops_duplicates(self):
        assert parse_frequencies("915, 868.1 , 915") == [915_000_000, 868_100_000]

    @pytest.mark.parametrize("value", ["100", "1000000000", "0"])
    def test_out_of_range(self, value):
        with pytest.raises(ValueError, match="out of range"):
            parse_frequencies(value)

    def test_not_a_number(self):
        with pytest.raises(ValueError, match="not a valid frequency"):
            parse_frequencies("915,abc")

    def test_empty(self):
        with pytest.raises(ValueError, match="No frequency given"):
            parse_frequencies(" , ")


class TestParseSpreadFactorsAndBandwidths:
    def test_spread_factors(self):
        assert parse_spread_factors("7,9,12") == [7, 9, 12]

    @pytest.mark.parametrize("value", ["6", "13"])
    def test_spread_factor_out_of_range(self, value):
        with pytest.raises(ValueError, match="out of range"):
            parse_spread_factors(value)

    def test_bandwidths(self):
        assert parse_bandwidths("125,500") == [125, 500]

    def test_bandwidth_not_offered_by_the_firmware(self):
        """``lora_bw`` takes 125/250/500 and nothing else."""
        with pytest.raises(ValueError, match="not one of"):
            parse_bandwidths("62")


class TestCombos:
    def test_order_is_frequency_major_spreading_factor_minor(self):
        combos = build_combos([915_000_000, 868_000_000], [125, 250], [7, 8])

        assert combos == [
            (915_000_000, 125, 7),
            (915_000_000, 125, 8),
            (915_000_000, 250, 7),
            (915_000_000, 250, 8),
            (868_000_000, 125, 7),
            (868_000_000, 125, 8),
            (868_000_000, 250, 7),
            (868_000_000, 250, 8),
        ]

    def test_default_search_space_is_eighteen_combinations(self):
        combos = build_combos([915_000_000], [125, 250, 500], [7, 8, 9, 10, 11, 12])
        assert len(combos) == 18

    def test_duration_counts_dwell_and_retune_overhead(self):
        combos = build_combos([915_000_000], [125], [7, 8])
        # 2 combos x (1 s dwell + 4 shell commands of settling time)
        # ``pytest.approx`` is unusable here: conftest mocks numpy, which it probes.
        assert round(sweep_duration(combos, dwell=1.0, passes=1), 6) == round(
            2 * 1.6, 6
        )

    def test_unbounded_run_has_no_estimate(self):
        combos = build_combos([915_000_000], [125], [7])
        assert sweep_duration(combos, dwell=3.0, passes=0) == 0.0

    def test_format_and_suggested_command(self):
        combo = (868_100_000, 250, 9)
        assert format_combo(combo) == "868.100 MHz  BW250  SF9"
        assert sniff_command(combo, "0x2B") == (
            "catnip sniff lora -freq 868100000 -bw 250 -sf 9 -sw 0x2B"
        )


# ═════════════════════════════════════════════════════════════════════════════
#  2.  ScanGraph — the live table's state
# ═════════════════════════════════════════════════════════════════════════════


COMBOS = [(915_000_000, 125, 7), (915_000_000, 125, 8), (915_000_000, 250, 7)]


class TestScanGraph:
    def test_record_accumulates_packets(self):
        graph = ScanGraph(COMBOS)
        graph.record(COMBOS[0], [(-50.0, 9.0), (-60.0, 5.0)])
        graph.record(COMBOS[0], [(-70.0, 2.0)])

        assert graph.stats[COMBOS[0]]["packets"] == 3

    def test_link_quality_is_the_strongest_frame_not_the_average(self):
        graph = ScanGraph(COMBOS)
        graph.record(COMBOS[0], [(-90.0, -5.0), (-40.0, 10.0), (-70.0, 1.0)])

        stat = graph.stats[COMBOS[0]]
        assert stat["rssi"] == -40.0
        # The SNR reported is the one measured on that same frame.
        assert stat["snr"] == 10.0

    def test_record_of_nothing_leaves_the_row_untouched(self):
        graph = ScanGraph(COMBOS)
        graph.record(COMBOS[0], [])

        assert graph.stats[COMBOS[0]]["packets"] == 0
        assert graph.stats[COMBOS[0]]["rssi"] is None

    def test_ranked_is_busiest_first_and_only_what_was_heard(self):
        graph = ScanGraph(COMBOS)
        graph.record(COMBOS[0], [(-50.0, 9.0)])
        graph.record(COMBOS[2], [(-80.0, 1.0), (-80.0, 1.0)])

        ranked = graph.ranked()
        assert [combo for combo, _ in ranked] == [COMBOS[2], COMBOS[0]]

    def test_ranked_breaks_ties_on_signal_strength(self):
        graph = ScanGraph(COMBOS)
        graph.record(COMBOS[0], [(-90.0, 0.0)])
        graph.record(COMBOS[1], [(-30.0, 0.0)])

        assert graph.ranked()[0][0] == COMBOS[1]

    def test_ranked_is_empty_when_nothing_was_received(self):
        assert ScanGraph(COMBOS).ranked() == []

    def test_bar_is_empty_for_silence_and_capped_for_a_flood(self):
        graph = ScanGraph(COMBOS)
        assert graph.draw_bar(0) == ""
        assert len(graph.draw_bar(5)) == 5
        assert "(999)" in graph.draw_bar(999)

    def test_every_row_is_visible_while_the_sweep_fits(self):
        graph = ScanGraph(COMBOS)
        rows, hidden = graph.visible_rows()

        assert rows == COMBOS
        assert hidden == 0

    def test_a_long_sweep_hides_the_silent_rows(self):
        combos = build_combos(
            [915_000_000, 868_000_000], [125, 250, 500], [7, 8, 9, 10, 11, 12]
        )
        graph = ScanGraph(combos)
        graph.set_current(combos[20])
        graph.record(combos[3], [(-50.0, 9.0)])
        graph.mark_error(combos[5], "Error: bad frequency")

        rows, hidden = graph.visible_rows()

        # What was heard, what failed, and what is being listened to now.
        assert set(rows) == {combos[3], combos[5], combos[20]}
        assert hidden == len(combos) - 3

    def test_caption_reports_progress_and_an_unbounded_run(self):
        graph = ScanGraph(COMBOS, dwell=2.5, passes=0)
        graph.set_pass(4)
        graph.record(COMBOS[0], [(-50.0, 9.0)])

        caption = graph._caption(hidden=0)
        assert "pass 4/∞" in caption
        assert "2.5s dwell" in caption
        assert "1 with traffic" in caption

    def test_generate_table_runs_over_every_visible_row(self):
        graph = ScanGraph(COMBOS)
        graph.set_current(COMBOS[1])
        graph.record(COMBOS[0], [(-50.0, 9.0)])

        # conftest's rich.Table mock is shared by the whole session, so the
        # call count only means anything against a fresh one.  The point is
        # that rendering a half-filled sweep — None RSSIs included — emits one
        # row per combination and does not raise.
        with patch("modules.protocols.sx1262.scan.Table") as table_cls:
            graph.generate_table()

        assert table_cls.return_value.add_row.call_count == len(COMBOS)

    def test_stop_clears_the_render_loop_flag(self):
        graph = ScanGraph(COMBOS)
        assert graph.running is True
        graph.stop()
        assert graph.running is False


# ═════════════════════════════════════════════════════════════════════════════
#  3.  LoraScanner — retuning and attribution
# ═════════════════════════════════════════════════════════════════════════════


def _scanner(combos=None, dwell=0.05, passes=1, reply="OK"):
    """A scanner wired to mock ports, with the inter-command settling removed."""
    device = MagicMock()
    device.shell_port = "/dev/ttyACM2"
    device.lora_port = "/dev/ttyACM1"

    scanner = LoraScanner(
        device, combos or COMBOS, dwell=dwell, passes=passes, console=MagicMock()
    )
    scanner.shell = MagicMock()
    scanner.shell.send_command.return_value = reply
    scanner.lora = MagicMock()
    return scanner


class TestRetune:
    def test_sends_frequency_bandwidth_spreading_factor_then_apply(self):
        scanner = _scanner()

        with patch("modules.protocols.sx1262.scan._SHELL_CMD_DELAY", 0):
            scanner._retune((868_100_000, 250, 9))

        sent = [call.args[0] for call in scanner.shell.send_command.call_args_list]
        assert sent == [
            "lora_freq 868100000",
            "lora_bw 250",
            "lora_sf 9",
            "lora_apply",
        ]

    def test_a_refused_setting_is_marked_on_the_row(self):
        """A silent row and a row the radio never reached must not look alike."""
        scanner = _scanner(reply="Error: Invalid spreading factor")

        with patch("modules.protocols.sx1262.scan._SHELL_CMD_DELAY", 0):
            scanner._retune(COMBOS[0])

        assert "Invalid spreading factor" in scanner.graph.stats[COMBOS[0]]["error"]

    def test_an_unanswered_command_is_marked_too(self):
        scanner = _scanner(reply="")

        with patch("modules.protocols.sx1262.scan._SHELL_CMD_DELAY", 0):
            scanner._retune(COMBOS[0])

        assert scanner.graph.stats[COMBOS[0]]["error"] == "no reply"


class TestSweep:
    def test_visits_every_combination_once_per_pass(self):
        scanner = _scanner(passes=2)
        visited = []
        scanner._retune = lambda combo: visited.append(combo)
        scanner.running = True

        scanner._sweep()

        assert visited == COMBOS * 2

    def test_packets_are_attributed_to_the_combination_that_received_them(self):
        scanner = _scanner()
        scanner._retune = lambda combo: None
        scanner.running = True

        # One frame arrives while the second combination is being listened to.
        original = scanner.graph.set_current

        def feed(combo):
            original(combo)
            if combo == COMBOS[1]:
                scanner.packets.put((-42.0, 8.0))

        scanner.graph.set_current = feed
        scanner._sweep()

        assert scanner.graph.stats[COMBOS[0]]["packets"] == 0
        assert scanner.graph.stats[COMBOS[1]]["packets"] == 1
        assert scanner.graph.stats[COMBOS[1]]["rssi"] == -42.0
        assert scanner.graph.stats[COMBOS[2]]["packets"] == 0

    def test_frames_still_in_flight_are_not_credited_to_the_next_combination(self):
        """A frame demodulated with the old settings arrives after the retune."""
        scanner = _scanner()
        scanner._retune = lambda combo: None
        scanner.running = True
        scanner.packets.put((-42.0, 8.0))

        scanner._sweep()

        assert all(stat["packets"] == 0 for stat in scanner.graph.stats.values())

    def test_a_stopped_sweep_returns_without_finishing_the_pass(self):
        scanner = _scanner()
        visited = []

        def retune(combo):
            visited.append(combo)
            scanner.running = False

        scanner._retune = retune
        scanner.running = True
        scanner._sweep()

        assert visited == [COMBOS[0]]


class TestReader:
    def test_parses_a_firmware_rx_line_into_rssi_and_snr(self):
        scanner = _scanner()
        lines = [b"LORA RX: 48656c6c6f | RSSI: -42 | SNR: 9\r\n", b""]

        connection = scanner.lora.connection
        connection.is_open = True
        connection.readline.side_effect = lambda *a, **kw: (
            lines.pop(0) if lines else scanner.__setattr__("running", False) or b""
        )
        scanner.running = True
        scanner._reader()

        assert scanner._drain() == [(-42.0, 9.0)]

    def test_chatter_that_is_not_a_packet_is_ignored(self):
        scanner = _scanner()
        lines = [b"LoRa Control Port ready\r\n", b"RX: not hex at all\r\n"]

        connection = scanner.lora.connection
        connection.is_open = True
        connection.readline.side_effect = lambda *a, **kw: (
            lines.pop(0) if lines else scanner.__setattr__("running", False) or b""
        )
        scanner.running = True
        scanner._reader()

        assert scanner._drain() == []


class TestRunGuards:
    def test_refuses_without_a_shell_port(self):
        device = MagicMock()
        device.shell_port = None
        device.lora_port = "/dev/ttyACM1"

        assert LoraScanner(device, COMBOS).run() is False

    def test_refuses_without_a_lora_port(self):
        device = MagicMock()
        device.shell_port = "/dev/ttyACM2"
        device.lora_port = None

        assert LoraScanner(device, COMBOS).run() is False


def _reported(scanner) -> str:
    """Everything ``print_results`` says, as one string.

    Captured at the print helpers rather than through ``capsys``: the Rich
    console is a module-level singleton shared with the rest of the suite, and
    what it is bound to depends on which tests ran first.
    """
    lines = []
    with patch.multiple(
        "modules.protocols.sx1262.scan",
        print_dim=lambda msg: lines.append(msg),
        print_empty_line=lambda: None,
        print_info=lambda msg: lines.append(msg),
        print_success=lambda msg: lines.append(msg),
        print_warning=lambda msg: lines.append(msg),
    ):
        scanner.print_results()
    return "\n".join(lines)


class TestResults:
    def test_reports_the_busiest_combination_and_how_to_capture_it(self):
        scanner = _scanner()
        scanner.graph.record(COMBOS[2], [(-42.0, 9.0), (-50.0, 7.0)])
        scanner.graph.record(COMBOS[0], [(-80.0, 1.0)])

        out = _reported(scanner)

        assert "915.000 MHz  BW250  SF7" in out
        assert "catnip sniff lora -freq 915000000 -bw 250 -sf 7" in out

    def test_a_silent_sweep_says_what_to_try_next(self):
        out = _reported(_scanner())

        assert "No LoRa frames" in out
        # The three things that make a sweep come up empty.
        assert "sync word" in out.lower()
        assert "--dwell" in out
        assert "--freq" in out


# ═════════════════════════════════════════════════════════════════════════════
#  4.  The Click command
# ═════════════════════════════════════════════════════════════════════════════


class TestScanCommand:
    def test_rejects_a_bandwidth_the_firmware_cannot_take(self):
        result = CliRunner().invoke(lora, ["scan", "--bw", "62"])

        assert result.exit_code != 0
        assert "not one of" in result.output

    def test_rejects_a_frequency_outside_the_radio(self):
        result = CliRunner().invoke(lora, ["scan", "--freq", "2400"])

        assert result.exit_code != 0
        assert "out of range" in result.output

    def test_rejects_an_impossible_sync_word(self):
        result = CliRunner().invoke(lora, ["scan", "-sw", "nonsense"])

        assert result.exit_code != 0

    @patch("modules.protocols.cli.sx1262.get_device_or_exit")
    def test_builds_the_sweep_from_the_options_and_runs_it(self, get_device):
        device = MagicMock()
        get_device.return_value = device

        with patch("modules.protocols.sx1262.scan.LoraScanner") as scanner_cls:
            result = CliRunner().invoke(
                lora,
                [
                    "scan",
                    "--freq",
                    "868.1",
                    "--sf",
                    "7,9",
                    "--bw",
                    "125",
                    "--dwell",
                    "1",
                ],
            )

        assert result.exit_code == 0, result.output
        scanner_cls.assert_called_once()
        combos = scanner_cls.call_args.args[1]
        assert combos == [(868_100_000, 125, 7), (868_100_000, 125, 9)]
        assert scanner_cls.call_args.kwargs["dwell"] == 1.0
        scanner_cls.return_value.run.assert_called_once()

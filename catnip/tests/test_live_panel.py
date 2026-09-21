"""
test_live_panel.py
==================
Tests for ``catnip sniff lora|fsk --live`` — the live capture panel.

Covers:
  - modules/core/live_panel.py (rate window, RSSI histogram, recent frames)
  - the wiring in ``modules/core/bridge.py``: with ``--live`` the packets feed
    the panel and nothing is printed over it

``rich.table`` and ``rich.live`` are the global mocks from ``conftest.py``, so
the assertions here are about what the panel is *asked* to draw, never about
pixels on a terminal.  ``conftest.py`` mocks numpy too, which is why the rate
comparisons below are written by hand: ``pytest.approx`` reads ``np.bool_``.

Run with:
    pytest tests/test_live_panel.py -v
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from modules.core.live_panel import (
    HEX_PREVIEW_BYTES,
    RATE_WINDOW,
    RECENT_FRAMES,
    RSSI_BUCKET_DB,
    RSSI_CEILING,
    RSSI_FLOOR,
    CaptureGraph,
)


SUMMARY = [("Frequency:", "915.000 MHz"), ("Spreading Factor:", "SF7")]


# ═════════════════════════════════════════════════════════════════════════════
#  1.  Counters
# ═════════════════════════════════════════════════════════════════════════════


class TestRecord:
    def test_first_frame_fills_every_headline_figure(self):
        graph = CaptureGraph("LoRa", SUMMARY)
        graph.record(-42.0, 9.0, b"\xaa\xbb\xcc")

        assert graph.packets == 1
        assert graph.last_rssi == -42.0
        assert graph.last_snr == 9.0
        assert graph.best_rssi == -42.0

    def test_best_rssi_keeps_the_strongest_frame_not_the_last(self):
        """'Last' answers "is it still there?", 'best' "how close did it get?"."""
        graph = CaptureGraph()
        graph.record(-42.0, 9.0)
        graph.record(-95.0, 2.0)

        assert graph.last_rssi == -95.0
        assert graph.best_rssi == -42.0

    def test_errors_and_noise_are_counted_apart(self):
        """A frame that would not parse is a different problem from a line
        that was never a frame — the panel has to keep them apart, since it
        is the only place they are reported while the capture runs."""
        graph = CaptureGraph()
        graph.note_error()
        graph.note_noise()
        graph.note_noise()

        assert (graph.errors, graph.noise) == (1, 2)

    def test_stop_clears_the_render_loop_flag(self):
        graph = CaptureGraph()
        assert graph.running is True
        graph.stop()
        assert graph.running is False


# ═════════════════════════════════════════════════════════════════════════════
#  2.  Packets per second
# ═════════════════════════════════════════════════════════════════════════════


class TestRate:
    def test_no_traffic_is_zero_not_a_division_by_zero(self):
        assert CaptureGraph().rate() == 0.0

    def test_a_burst_in_the_first_second_is_not_scaled_to_infinity(self):
        """Three frames in the first millisecond of a capture divided by the
        elapsed time would read as thousands per second."""
        graph = CaptureGraph()
        for _ in range(3):
            graph.record(-50.0, 5.0)

        assert abs(graph.rate() - 3.0) < 1e-6

    def test_the_window_averages_over_its_own_length(self):
        graph = CaptureGraph()
        graph.started = time.monotonic() - 60
        for _ in range(20):
            graph.record(-50.0, 5.0)

        assert abs(graph.rate() - 20 / RATE_WINDOW) < 1e-6

    def test_arrivals_older_than_the_window_stop_counting(self):
        """The figure has to fall back to zero while the panel is still being
        looked at, or a capture that died minutes ago still reads as busy."""
        graph = CaptureGraph()
        graph.started = time.monotonic() - 60
        graph.record(-50.0, 5.0)
        graph.arrivals[0] -= RATE_WINDOW + 1

        assert graph.rate() == 0.0
        assert not graph.arrivals

    def test_peak_survives_the_silence_that_follows_it(self):
        graph = CaptureGraph()
        graph.started = time.monotonic() - 60
        for _ in range(20):
            graph.record(-50.0, 5.0)
        graph.rate()

        graph.arrivals.clear()
        assert graph.rate() == 0.0
        assert abs(graph.peak_rate - 20 / RATE_WINDOW) < 1e-6


# ═════════════════════════════════════════════════════════════════════════════
#  3.  RSSI histogram
# ═════════════════════════════════════════════════════════════════════════════


class TestHistogram:
    @pytest.mark.parametrize(
        "rssi, floor",
        [
            (-90.0, -90),  # exactly on a boundary belongs to the row above it
            (-85.4, -90),
            (-42.0, -50),
        ],
    )
    def test_bucketing(self, rssi, floor):
        assert CaptureGraph._bucket(rssi) == floor

    @pytest.mark.parametrize(
        "rssi, floor",
        [
            (-200.0, RSSI_FLOOR),
            (0.0, RSSI_CEILING - RSSI_BUCKET_DB),
        ],
    )
    def test_out_of_range_readings_are_clamped_into_the_end_rows(self, rssi, floor):
        """A reading outside the radio's range must not invent a bucket: the
        render thread iterates the ones built at startup, and a key appearing
        mid-iteration is exactly the race the fixed dict avoids."""
        graph = CaptureGraph()
        graph.record(rssi, 0.0)

        assert graph.buckets[floor] == 1
        assert sum(graph.buckets.values()) == 1

    def test_the_bar_scales_against_the_busiest_row(self):
        graph = CaptureGraph()
        assert graph.draw_bar(10, 10) == graph.draw_bar(5, 5)
        assert len(graph.draw_bar(5, 10)) < len(graph.draw_bar(10, 10))

    def test_a_row_with_one_frame_still_draws_something(self):
        """Rounded against a busy scale it would be a blank row that reads as
        a bucket nothing landed in."""
        assert CaptureGraph().draw_bar(1, 5000) != ""

    def test_an_empty_bucket_between_two_heard_ones_keeps_its_row(self):
        """Dropping it would leave -50 and -80 printed adjacent, which reads
        as two transmitters at similar range rather than two far apart."""
        graph = CaptureGraph()
        graph.record(-45.0, 9.0)
        graph.record(-75.0, 3.0)

        with patch("modules.core.live_panel.Table") as table_cls:
            graph._histogram_table()

        labels = [
            call.args[0] for call in table_cls.return_value.add_row.call_args_list
        ]
        assert labels == ["-50 to -40", "-60 to -50", "-70 to -60", "-80 to -70"]

    def test_nothing_heard_yet_draws_no_rows(self):
        with patch("modules.core.live_panel.Table") as table_cls:
            CaptureGraph()._histogram_table()

        assert table_cls.return_value.add_row.call_count == 0


# ═════════════════════════════════════════════════════════════════════════════
#  4.  Recent frames
# ═════════════════════════════════════════════════════════════════════════════


class TestRecentFrames:
    def test_only_the_last_few_frames_are_kept(self):
        """The panel is fixed-height by design — that is the whole point of it
        over the scrolling dump."""
        graph = CaptureGraph()
        for _ in range(RECENT_FRAMES + 5):
            graph.record(-50.0, 5.0, b"\x01")

        assert len(graph.recent) == RECENT_FRAMES

    def test_a_long_payload_is_cut_short_and_says_so(self):
        graph = CaptureGraph()
        graph.record(-50.0, 5.0, b"\xab" * (HEX_PREVIEW_BYTES + 10))

        _, length, _, preview = graph.recent[-1]
        assert length == HEX_PREVIEW_BYTES + 10
        assert preview == "ab" * HEX_PREVIEW_BYTES + "…"

    def test_a_short_payload_is_shown_whole(self):
        graph = CaptureGraph()
        graph.record(-50.0, 5.0, b"\xaa\xbb\xcc")

        assert graph.recent[-1][3] == "aabbcc"

    def test_the_newest_frame_is_drawn_first(self):
        graph = CaptureGraph()
        graph.record(-50.0, 5.0, b"\x01")
        graph.record(-60.0, 4.0, b"\x02")

        with patch("modules.core.live_panel.Table") as table_cls:
            graph._recent_table()

        payloads = [
            call.args[3] for call in table_cls.return_value.add_row.call_args_list
        ]
        assert payloads == ["02", "01"]


# ═════════════════════════════════════════════════════════════════════════════
#  5.  Rendering
# ═════════════════════════════════════════════════════════════════════════════


class TestRendering:
    def test_the_caption_carries_the_radio_settings(self):
        caption = CaptureGraph("LoRa", SUMMARY)._caption()

        assert "Frequency 915.000 MHz" in caption
        assert "Spreading Factor SF7" in caption
        assert "Ctrl+C to stop" in caption

    def test_fsk_drops_the_snr_column_it_would_never_fill(self):
        """The firmware reports no SNR for an FSK frame, so the column would
        be a session-long line of em dashes."""
        assert CaptureGraph("FSK").show_snr is False
        assert CaptureGraph("LoRa").show_snr is True

    def test_generate_draws_all_three_tables_without_raising(self):
        graph = CaptureGraph("LoRa", SUMMARY)
        graph.record(-42.0, 9.0, b"\xaa\xbb")

        with patch("modules.core.live_panel.Table") as table_cls:
            graph.generate()

        assert table_cls.call_count == 3

    def test_the_panel_renders_before_a_single_frame_arrives(self):
        """It is painted as soon as the capture starts, and a capture that
        hears nothing for a minute is the normal case, not an edge one."""
        with patch("modules.core.live_panel.Table") as table_cls:
            CaptureGraph("LoRa", SUMMARY).generate()

        assert table_cls.call_count == 3


# ═════════════════════════════════════════════════════════════════════════════
#  6.  Wiring into the capture loop
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def fake_device():
    device = MagicMock()
    device.lora_port = "/dev/ttyACM1"
    device.shell_port = "/dev/ttyACM2"
    return device


def _run_capture(fake_device, packet, readline, **kwargs):
    """Drive ``run_sx_bridge`` over ``readline`` with the ports faked out."""
    from modules.core.bridge import run_sx_bridge

    mock_shell = MagicMock()
    mock_shell.connect.return_value = True
    mock_shell.send_command.return_value = "STREAM mode"
    mock_lora = MagicMock()
    mock_lora.connect.return_value = True
    mock_lora.connection = MagicMock()
    mock_lora.connection.readline.side_effect = readline

    with patch("modules.core.bridge.ShellConnection", return_value=mock_shell), patch(
        "modules.core.bridge.LoRaConnection", return_value=mock_lora
    ), patch("modules.core.bridge.UnixPipe", return_value=MagicMock()), patch(
        "platform.system", return_value="Linux"
    ), patch(
        "modules.core.bridge._configure_lora", return_value=True
    ), patch(
        "modules.core.bridge.snifferSx"
    ) as mock_sniffer, patch(
        "modules.core.bridge.print_sx_session_report"
    ), patch(
        "modules.core.bridge.console"
    ) as mock_console, patch(
        "modules.core.bridge.CaptureGraph"
    ) as graph_cls:
        mock_sniffer.Packet.side_effect = [packet]
        run_sx_bridge(
            fake_device,
            frequency=915_000_000,
            bandwidth=125,
            spread_factor=7,
            coding_rate=5,
            tx_power=20,
            **kwargs,
        )

    return graph_cls, mock_console


class TestLiveWiring:
    PACKET = dict(
        pcap=b"LORA-RECORD", payload=b"\xaa\xbb\xcc", rssi=-42.0, snr=9.0, length=3
    )
    LINES = [
        b"RX: aabbcc | RSSI: -42 | SNR: 9\r\n",
        b"garbage line\r\n",
        KeyboardInterrupt(),
    ]

    def test_frames_and_stray_lines_reach_the_panel(self, fake_device):
        packet = MagicMock(is_fsk=False, **self.PACKET)
        graph_cls, _ = _run_capture(fake_device, packet, self.LINES, live=True)

        graph = graph_cls.return_value
        graph.record.assert_called_once_with(-42.0, 9.0, b"\xaa\xbb\xcc")
        graph.note_noise.assert_called_once()
        graph.stop.assert_called_once()

    def test_an_fsk_frame_reaches_it_without_an_snr(self, fake_device):
        packet = MagicMock(is_fsk=True, **self.PACKET)
        graph_cls, _ = _run_capture(fake_device, packet, self.LINES, live=True)

        graph_cls.return_value.record.assert_called_once_with(
            -42.0, None, b"\xaa\xbb\xcc"
        )

    def test_the_packet_dump_is_silenced_under_the_panel(self, fake_device):
        """A Live region and a scrolling hex dump cannot share a terminal —
        and --verbose alongside --live is what a user reaches for first."""
        packet = MagicMock(is_fsk=False, **self.PACKET)
        _, mock_console = _run_capture(
            fake_device, packet, self.LINES, live=True, verbose=True
        )

        assert not any(
            "aabbcc" in str(call) for call in mock_console.print.call_args_list
        )

    def test_without_the_flag_nothing_changes(self, fake_device):
        packet = MagicMock(is_fsk=False, **self.PACKET)
        graph_cls, mock_console = _run_capture(
            fake_device, packet, self.LINES, verbose=True
        )

        graph_cls.assert_not_called()
        assert any("aabbcc" in str(call) for call in mock_console.print.call_args_list)

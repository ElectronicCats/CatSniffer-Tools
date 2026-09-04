"""
test_cativity.py
================
Tests for Cativity submodules.

Covers:
  - modules/cativity/runner.py
  - modules/cativity/network.py
  - modules/cativity/graphs.py
  - modules/cativity/packets.py

Run with:
    pytest tests/test_cativity.py -v
"""

import time
import queue
import os
import sys
import pytest
from unittest.mock import MagicMock, patch

# Get the absolute path to the project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

# Create stubs and partial mocks to ensure imports don't fail
import sys

# Mocks for scapy to avoid dependency failures if not installed
sys.modules["scapy"] = MagicMock()
sys.modules["scapy.layers"] = MagicMock()
sys.modules["scapy.layers.dot15d4"] = MagicMock()
sys.modules["scapy.layers.zigbee"] = MagicMock()
sys.modules["scapy.config"] = MagicMock()

# Mocks for rich
sys.modules["rich.live"] = MagicMock()
sys.modules["rich.table"] = MagicMock()

# Import the classes to test
from modules.protocols.cativity.runner import CativityRunner
from modules.protocols.cativity.network import Network, NetworkStats
from modules.protocols.cativity.graphs import Graphs
from modules.protocols.cativity.packets import (
    is_beacon_response,
    is_beacon_request,
    is_association_request,
    is_association_response,
    is_disassociation_request,
)


# ═════════════════════════════════════════════════════════════════════════════
#  1.  TESTS FOR packets.py
# ═════════════════════════════════════════════════════════════════════════════


class TestPackets:
    """Tests for packet evaluation functions in packets.py."""

    def test_is_beacon_response(self):
        # mock frame containing Dot15d4Beacon and ZigBeeBeacon
        mock_frame = MagicMock()
        mock_frame.__contains__.side_effect = lambda layer: layer in (
            "Dot15d4Beacon",
            "ZigBeeBeacon",
        )

        # Patch the classes so the in operator works with strings or references to sys.modules mock
        with patch(
            "modules.protocols.cativity.packets.Dot15d4Beacon", "Dot15d4Beacon"
        ), patch("modules.protocols.cativity.packets.ZigBeeBeacon", "ZigBeeBeacon"):
            assert is_beacon_response(mock_frame) is True

    def test_is_beacon_request(self):
        mock_frame = MagicMock()
        mock_frame.__contains__.side_effect = lambda layer: layer == "Dot15d4Cmd"
        mock_frame.__getitem__.return_value = MagicMock(cmd_id=7)

        with patch(
            "modules.protocols.cativity.packets.Dot15d4Cmd", "Dot15d4Cmd"
        ), patch("modules.protocols.cativity.packets.BEACON_CMD_ID", 7):
            assert is_beacon_request(mock_frame) is True


# ═════════════════════════════════════════════════════════════════════════════
#  2.  TESTS FOR network.py
# ═════════════════════════════════════════════════════════════════════════════


class TestNetwork:
    """Tests for the Network class (and NetworkStats)."""

    @patch("modules.protocols.cativity.network.is_beacon_request", return_value=True)
    def test_network_stats_update(self, mock_is_req):
        stats = NetworkStats()
        mock_pkt = MagicMock()
        stats.update_network_stats(mock_pkt)
        assert stats.beacons_requests == 1

    @patch("modules.protocols.cativity.network.Dot15d4")
    def test_get_packet_filtered_all(self, mock_dot15d4):
        net = Network()
        mock_dot15d4.return_value = MagicMock()
        res = net.get_packet_filtered(b"data", "all")
        assert res == b"data"

    @patch("modules.protocols.cativity.network.Dot15d4")
    def test_get_packet_filtered_thread(self, mock_dot15d4):
        # If it DOESN'T have zigbee layer, count as thread
        net = Network()
        mock_pkt = MagicMock()
        mock_pkt.haslayer.return_value = False
        mock_dot15d4.return_value = mock_pkt
        res = net.get_packet_filtered(b"data", "thread")
        assert res == b"data"

    @patch("modules.protocols.cativity.network.Dot15d4")
    def test_dissect_packet(self, mock_dot15d4):
        net = Network()
        mock_pkt = MagicMock()
        mock_pkt.haslayer.return_value = True
        # Simulate source != coordinator
        mock_layer = MagicMock()
        mock_layer.fields.get.side_effect = lambda k, default: (
            0x1122 if k == "source" else default
        )
        mock_pkt.__getitem__.return_value = mock_layer
        mock_dot15d4.return_value = mock_pkt

        # First configure a fake parent simulating a coordinator packet first
        net.parent_addr_src = 0x0000

        res = net.dissect_packet(b"data")
        assert "4386" in res  # 0x1122 == 4386


# ═════════════════════════════════════════════════════════════════════════════
#  3.  TESTS FOR graphs.py
# ═════════════════════════════════════════════════════════════════════════════


class TestGraphs:
    """Tests for the Graphs class for visual representation."""

    def test_draw_bar(self):
        gr = Graphs()
        assert gr.draw_bar(0) == ""
        assert gr.draw_bar(5, char="X") == "XXXXX"
        # Exceed max (MAX_CHANNEL_ACTIVITY = 50)
        from modules.protocols.cativity.graphs import MAX_CHANNEL_ACTIVITY

        res = gr.draw_bar(MAX_CHANNEL_ACTIVITY + 10, char="A")
        assert "AAAAAAAA" in res
        assert "(60)" in res

    def test_generate_topology_graph(self):
        gr = Graphs()
        gr.topology_activity = {"0x1234": b"\x00\x11\x22\x33\x44\x55\x66\x77"}

        with patch("modules.protocols.cativity.graphs.Table") as mock_table:
            tb = MagicMock()
            mock_table.return_value = tb
            gr.generate_topology_graph()
            mock_table.assert_called_once()
            tb.add_row.assert_called()

    def test_generate_channel_graph(self):
        gr = Graphs()
        gr.channel_activity = {11: 5, 12: 10}
        gr.current_channel = 11

        with patch("modules.protocols.cativity.graphs.Table") as mock_table:
            tb = MagicMock()
            mock_table.return_value = tb
            gr.generate_channel_graph()
            assert tb.add_row.call_count == 2


# ═════════════════════════════════════════════════════════════════════════════
#  4.  TESTS FOR runner.py
# ═════════════════════════════════════════════════════════════════════════════


class TestCativityRunner:
    """Tests for the CativityRunner class."""

    def mock_device(self):
        dev = MagicMock()
        dev.bridge_port = "/dev/ttyACM0"
        return dev

    @patch("modules.protocols.cativity.runner.Catnip")
    def test_init(self, mock_catnip):
        dev = self.mock_device()
        runner = CativityRunner(device=dev)
        assert runner.current_channel == 11
        assert len(runner.channel_activity) == 16  # 11 to 26

    @patch("modules.protocols.cativity.runner.Catnip")
    def test_run_connection_failed(self, mock_catnip):
        dev = self.mock_device()
        runner = CativityRunner(device=dev, console=MagicMock())
        runner.catnip.connect.return_value = False

        runner.run()
        runner.console.print.assert_called_once()

    @patch("modules.protocols.cativity.runner.Catnip")
    @patch("threading.Thread")
    def test_run_success(self, mock_thread, mock_catnip):
        dev = self.mock_device()
        runner = CativityRunner(device=dev, console=MagicMock())
        runner.catnip.connect.return_value = True

        # Avoid infinite loop by hacking capture_started
        def mock_read_until(*args, **kwargs):
            runner.capture_started = False
            return b"test_data"

        runner.catnip.read_until = mock_read_until
        runner.run(channel=15)

        runner.catnip.write.assert_called()
        assert runner.current_channel == 15
        assert runner.fixed_channel is True
        mock_thread.assert_called()

    @patch("modules.protocols.cativity.runner.Catnip")
    def test_stop(self, mock_catnip):
        dev = self.mock_device()
        runner = CativityRunner(device=dev)
        runner.capture_started = True

        runner.stop()
        assert runner.capture_started is False
        runner.catnip.disconnect.assert_called_once()

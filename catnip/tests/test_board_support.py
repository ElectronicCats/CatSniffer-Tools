"""
test_board_support.py
=====================
Tests for CatSniffer board-generation support (v1/v2 SAMD21 + CC1352P1 vs
v3 RP2040 + CC1352P7).

Covers:
  - board.py: fw_version parsing, image/board matching, flash size gate
  - fw_aliases.py: per-board image catalog
  - fw_update.py: board-aware UF2 lookup and update decisions

Run with:
    pytest tests/test_board_support.py -v
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from modules.firmware import board as board_mod  # noqa: E402
from modules.firmware.board import (  # noqa: E402
    BOARD_V2,
    BOARD_V3,
    board_for_chip_size,
    image_allowed_for_board,
    image_fits_chip,
    image_variant,
    parse_board_line,
)
from modules.firmware import fw_aliases  # noqa: E402


V2_FW_VERSION = (
    "FW: dev-87c5174-dirty\r\nGit: 87c5174 (dirty)\r\nBuilt: 2026-09-03T00:00:00Z\r\n"
    "Compiler: GNU 12.2.0\r\nBoard: v2 SAMD21 CC1352P1\r\n"
)
V3_FW_VERSION_OLD = "FW: v3.1.0.0\r\nGit: abc1234 (clean)\r\nBuilt: 2026-01-01T00:00:00Z\r\n"
V3_FW_VERSION_NEW = V3_FW_VERSION_OLD + "Board: v3 RP2040 CC1352P7\r\n"


# ─────────────────────────────────────────────────────────────────────────────
# parse_board_line
# ─────────────────────────────────────────────────────────────────────────────


class TestParseBoardLine:
    def test_v2_line(self):
        assert parse_board_line(V2_FW_VERSION) is BOARD_V2

    def test_v3_line(self):
        assert parse_board_line(V3_FW_VERSION_NEW) is BOARD_V3

    def test_missing_line_is_v3(self):
        # Firmware older than the Board line is always an RP2040 build
        assert parse_board_line(V3_FW_VERSION_OLD) is BOARD_V3

    def test_empty_is_v3(self):
        assert parse_board_line("") is BOARD_V3
        assert parse_board_line(None) is BOARD_V3

    def test_case_insensitive(self):
        assert parse_board_line("board: V2 samd21") is BOARD_V2


# ─────────────────────────────────────────────────────────────────────────────
# detect_board (shell interaction mocked)
# ─────────────────────────────────────────────────────────────────────────────


class TestDetectBoard:
    def _shell(self, response, connected=True):
        shell = MagicMock()
        shell.connect.return_value = connected
        shell.send_command.return_value = response
        return shell

    def test_detects_v2(self):
        with patch("modules.core.usb_connection.ShellConnection", return_value=self._shell(V2_FW_VERSION)):
            assert board_mod.detect_board("/dev/ttyACM2") is BOARD_V2

    def test_no_shell_port(self):
        assert board_mod.detect_board(None) is None

    def test_unreachable_shell_is_unknown(self):
        with patch("modules.core.usb_connection.ShellConnection", return_value=self._shell("", connected=False)):
            assert board_mod.detect_board("/dev/ttyACM2") is None

    def test_garbage_reply_is_unknown(self):
        with patch("modules.core.usb_connection.ShellConnection", return_value=self._shell("Unknown command")):
            assert board_mod.detect_board("/dev/ttyACM2") is None


# ─────────────────────────────────────────────────────────────────────────────
# image matching
# ─────────────────────────────────────────────────────────────────────────────


class TestImageMatching:
    @pytest.mark.parametrize(
        "name,variant",
        [
            ("sniffle_cc1352p7_1M.hex", "CC1352P7"),
            ("airtag_scanner_CC1352P_7.hex", "CC1352P7"),
            ("sniffle_cc1352p1_cc2652p1_1M.hex", "CC1352P1"),
            ("sniffer_fw_Catsniffer_v3.x.hex", None),
        ],
    )
    def test_image_variant(self, name, variant):
        assert image_variant(name) == variant

    def test_p7_image_refused_on_v2(self):
        allowed, reason = image_allowed_for_board("sniffle_cc1352p7_1M.hex", BOARD_V2)
        assert not allowed
        assert "bootloader" in reason

    def test_p1_image_refused_on_v3(self):
        allowed, _ = image_allowed_for_board("sniffle_cc1352p1_cc2652p1_1M.hex", BOARD_V3)
        assert not allowed

    def test_matching_images_allowed(self):
        assert image_allowed_for_board("sniffle_cc1352p1_cc2652p1_1M.hex", BOARD_V2)[0]
        assert image_allowed_for_board("sniffle_cc1352p7_1M.hex", BOARD_V3)[0]

    def test_unnamed_variant_only_on_v3(self):
        assert image_allowed_for_board("sniffer_fw_Catsniffer_v3.x.hex", BOARD_V3)[0]
        assert not image_allowed_for_board("sniffer_fw_Catsniffer_v3.x.hex", BOARD_V2)[0]

    def test_unknown_board_never_allowed(self):
        assert not image_allowed_for_board("sniffle_cc1352p1_cc2652p1_1M.hex", None)[0]


class TestFlashSizeGate:
    def test_fits(self):
        assert image_fits_chip(0x58000, board_mod.CC1352P1_FLASH_SIZE)[0]

    def test_p7_image_too_large_for_p1(self):
        ok, reason = image_fits_chip(0xB0000, board_mod.CC1352P1_FLASH_SIZE)
        assert not ok
        assert "larger" in reason

    def test_unknown_chip_size(self):
        assert not image_fits_chip(100, 0)[0]

    def test_board_for_chip_size(self):
        assert board_for_chip_size(board_mod.CC1352P1_FLASH_SIZE) is BOARD_V2
        assert board_for_chip_size(board_mod.CC1352P7_FLASH_SIZE) is BOARD_V3
        assert board_for_chip_size(12345) is None


# ─────────────────────────────────────────────────────────────────────────────
# per-board catalog
# ─────────────────────────────────────────────────────────────────────────────


class TestBoardCatalog:
    def test_v3_default_unchanged(self):
        assert fw_aliases.get_filename_pattern("sniffle") == "sniffle_cc1352p7_1M"
        assert fw_aliases.get_filename_pattern("sniffle", "v3") == "sniffle_cc1352p7_1M"

    def test_v2_sniffle_is_p1_image(self):
        assert fw_aliases.get_filename_pattern("sniffle", "v2") == "sniffle_cc1352p1_cc2652p1_1M"

    def test_v2_has_no_p7_only_images(self):
        for fw_id in ("ti_sniffer", "airtag_scanner_cc1352p7", "airtag_spoofer_cc1352p7", "justworks_scanner_cc1352p7"):
            assert fw_aliases.get_filename_pattern(fw_id, "v2") is None

    def test_official_ids_for_board(self):
        assert "sniffle" in fw_aliases.official_ids_for_board("v2")
        assert "ti_sniffer" not in fw_aliases.official_ids_for_board("v2")
        assert "ti_sniffer" in fw_aliases.official_ids_for_board("v3")

    def test_v2_uf2_alias(self):
        assert fw_aliases.get_official_id("catsniffer-v2.0.1.0.uf2") == "catnip_v2"


# ─────────────────────────────────────────────────────────────────────────────
# fw_update board awareness
# ─────────────────────────────────────────────────────────────────────────────


class TestFwUpdateBoardAware:
    def test_parse_fw_version_keeps_board(self):
        from modules.firmware.fw_update import parse_fw_version_response

        parsed = parse_fw_version_response(V2_FW_VERSION)
        assert parsed["board"].startswith("v2")

    def test_find_board_uf2_picks_board_asset(self, tmp_path):
        from modules.firmware.fw_update import find_board_uf2

        (tmp_path / "catsniffer-v3.1.0.0.uf2").write_bytes(b"x")
        (tmp_path / "catsniffer-v2.0.1.0.uf2").write_bytes(b"x")
        flasher = MagicMock()
        flasher.get_releases_path.return_value = str(tmp_path)
        assert find_board_uf2(flasher, BOARD_V2).endswith("catsniffer-v2.0.1.0.uf2")
        assert find_board_uf2(flasher, BOARD_V3).endswith("catsniffer-v3.1.0.0.uf2")

    def test_find_board_uf2_none_when_absent(self, tmp_path):
        from modules.firmware.fw_update import find_board_uf2

        (tmp_path / "catsniffer-v3.1.0.0.uf2").write_bytes(b"x")
        flasher = MagicMock()
        flasher.get_releases_path.return_value = str(tmp_path)
        assert find_board_uf2(flasher, BOARD_V2) is None

    def test_v2_update_without_release_does_not_reboot(self):
        """A v2 with no v2 release must return False before any reboot."""
        from modules.firmware import fw_update

        flasher = MagicMock()
        flasher.release_tag = "v3.1.0.0"
        flasher.get_release_for_board.return_value = None
        device = MagicMock()
        device.shell_port = "/dev/ttyACM2"
        with patch.object(fw_update, "get_device_fw_version", return_value=fw_update.parse_fw_version_response(V2_FW_VERSION)), \
             patch.object(fw_update, "get_latest_software_version", return_value=None), \
             patch.object(fw_update, "enter_boot_mode") as reboot, \
             patch.object(fw_update, "_perform_rp2040_update") as perform:
            assert fw_update.check_and_update_rp2040(device=device, flasher=flasher) is False
            reboot.assert_not_called()
            perform.assert_not_called()

    def test_perform_update_needs_confirmation(self, tmp_path):
        from modules.firmware import fw_update

        (tmp_path / "catsniffer-v2.0.1.0.uf2").write_bytes(b"x")
        flasher = MagicMock()
        flasher.get_releases_path.return_value = str(tmp_path)
        device = MagicMock()
        device.shell_port = "/dev/ttyACM2"
        with patch.object(fw_update, "confirm_reboot", return_value=False), \
             patch.object(fw_update, "enter_boot_mode") as reboot:
            assert fw_update._perform_rp2040_update(device, flasher, board=BOARD_V2, tag="v2.0.1.0") is False
            reboot.assert_not_called()

    def test_perform_update_without_uf2_never_reboots(self, tmp_path):
        from modules.firmware import fw_update

        flasher = MagicMock()
        flasher.get_releases_path.return_value = str(tmp_path)
        flasher.fetch_board_uf2.return_value = None
        device = MagicMock()
        device.shell_port = "/dev/ttyACM2"
        with patch.object(fw_update, "enter_boot_mode") as reboot:
            assert fw_update._perform_rp2040_update(device, flasher, board=BOARD_V2, force=True) is False
            reboot.assert_not_called()

    def test_board_mount_point_uses_volume_name(self, tmp_path):
        from modules.firmware import fw_update

        with patch.object(fw_update.platform, "system", return_value="Darwin"), \
             patch.object(fw_update.os.path, "exists", side_effect=lambda p: p == "/Volumes/SNIFFER"):
            assert fw_update.find_board_mount_point(BOARD_V2) == "/Volumes/SNIFFER"
            assert fw_update.find_board_mount_point(BOARD_V3) is None

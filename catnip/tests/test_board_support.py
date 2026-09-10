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
import re
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
V3_FW_VERSION_OLD = (
    "FW: v3.1.0.0\r\nGit: abc1234 (clean)\r\nBuilt: 2026-01-01T00:00:00Z\r\n"
)
V3_FW_VERSION_NEW = V3_FW_VERSION_OLD + "Board: v3 RP2040 CC1352P7\r\n"


# ─────────────────────────────────────────────────────────────────────────────
# parse_board_line
# ─────────────────────────────────────────────────────────────────────────────


class TestParseBoardLine:
    def test_v2_line(self):
        assert parse_board_line(V2_FW_VERSION) is BOARD_V2

    def test_v3_line(self):
        assert parse_board_line(V3_FW_VERSION_NEW) is BOARD_V3

    def test_missing_line_with_v3_tag_is_v3(self):
        # RP2040 firmware older than the Board line names an explicit v3 tag
        assert parse_board_line(V3_FW_VERSION_OLD) is BOARD_V3

    def test_empty_is_unknown(self):
        assert parse_board_line("") is None
        assert parse_board_line(None) is None

    def test_case_insensitive(self):
        assert parse_board_line("board: V2 samd21") is BOARD_V2

    def test_no_board_line_and_no_v3_tag_is_unknown(self):
        # The dangerous case (D10): a reply that answers but names neither the
        # board nor a v3 tag must never be assumed to be a v3, or a CC1352P7
        # image would be allowed onto a CC1352P1.
        assert parse_board_line("FW: dev-87c5174-dirty\r\nGit: 87c5174\r\n") is None
        assert parse_board_line("FW: v2.1.0.0\r\n") is None
        assert parse_board_line("Unknown command\r\n") is None

    def test_unknown_board_blocks_every_image(self):
        for name in (
            "sniffle_cc1352p1_cc2652p1_1M.hex",
            "sniffle_cc1352p7_1M.hex",
            "sniffer_fw_Catsniffer_v3.x.hex",
        ):
            assert not image_allowed_for_board(name, parse_board_line("FW: dev-x"))[0]


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
        with patch(
            "modules.core.usb_connection.ShellConnection",
            return_value=self._shell(V2_FW_VERSION),
        ):
            assert board_mod.detect_board("/dev/ttyACM2") is BOARD_V2

    def test_no_shell_port(self):
        assert board_mod.detect_board(None) is None

    def test_unreachable_shell_is_unknown(self):
        with patch(
            "modules.core.usb_connection.ShellConnection",
            return_value=self._shell("", connected=False),
        ):
            assert board_mod.detect_board("/dev/ttyACM2") is None

    def test_garbage_reply_is_unknown(self):
        with patch(
            "modules.core.usb_connection.ShellConnection",
            return_value=self._shell("Unknown command"),
        ):
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
        allowed, _ = image_allowed_for_board(
            "sniffle_cc1352p1_cc2652p1_1M.hex", BOARD_V3
        )
        assert not allowed

    def test_matching_images_allowed(self):
        assert image_allowed_for_board("sniffle_cc1352p1_cc2652p1_1M.hex", BOARD_V2)[0]
        assert image_allowed_for_board("sniffle_cc1352p7_1M.hex", BOARD_V3)[0]

    def test_unnamed_variant_only_on_v3(self):
        assert image_allowed_for_board("sniffer_fw_Catsniffer_v3.x.hex", BOARD_V3)[0]
        assert not image_allowed_for_board("sniffer_fw_Catsniffer_v3.x.hex", BOARD_V2)[
            0
        ]

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
        assert (
            fw_aliases.get_filename_pattern("sniffle", "v2")
            == "sniffle_cc1352p1_cc2652p1_1M"
        )

    def test_v2_has_no_p7_only_images(self):
        for fw_id in (
            "ti_sniffer",
            "airtag_scanner_cc1352p7",
            "airtag_spoofer_cc1352p7",
            "justworks_scanner_cc1352p7",
        ):
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
        with patch.object(
            fw_update,
            "get_device_fw_version",
            return_value=fw_update.parse_fw_version_response(V2_FW_VERSION),
        ), patch.object(
            fw_update, "get_latest_software_version", return_value=None
        ), patch.object(
            fw_update, "enter_boot_mode"
        ) as reboot, patch.object(
            fw_update, "_perform_rp2040_update"
        ) as perform:
            assert (
                fw_update.check_and_update_rp2040(device=device, flasher=flasher)
                is False
            )
            reboot.assert_not_called()
            perform.assert_not_called()

    def test_perform_update_needs_confirmation(self, tmp_path):
        from modules.firmware import fw_update

        (tmp_path / "catsniffer-v2.0.1.0.uf2").write_bytes(b"x")
        flasher = MagicMock()
        flasher.get_releases_path.return_value = str(tmp_path)
        device = MagicMock()
        device.shell_port = "/dev/ttyACM2"
        with patch.object(
            fw_update, "confirm_reboot", return_value=False
        ), patch.object(fw_update, "enter_boot_mode") as reboot:
            assert (
                fw_update._perform_rp2040_update(
                    device, flasher, board=BOARD_V2, tag="v2.0.1.0"
                )
                is False
            )
            reboot.assert_not_called()

    def test_perform_update_without_uf2_never_reboots(self, tmp_path):
        from modules.firmware import fw_update

        flasher = MagicMock()
        flasher.get_releases_path.return_value = str(tmp_path)
        flasher.fetch_board_uf2.return_value = None
        device = MagicMock()
        device.shell_port = "/dev/ttyACM2"
        with patch.object(fw_update, "enter_boot_mode") as reboot:
            assert (
                fw_update._perform_rp2040_update(
                    device, flasher, board=BOARD_V2, force=True
                )
                is False
            )
            reboot.assert_not_called()

    def test_board_mount_point_uses_volume_name(self, tmp_path):
        from modules.firmware import fw_update

        with patch.object(
            fw_update.platform, "system", return_value="Darwin"
        ), patch.object(
            fw_update.os.path, "exists", side_effect=lambda p: p == "/Volumes/SNIFFER"
        ):
            assert fw_update.find_board_mount_point(BOARD_V2) == "/Volumes/SNIFFER"
            assert fw_update.find_board_mount_point(BOARD_V3) is None


# ─────────────────────────────────────────────────────────────────────────────
# board capabilities (the data that replaced the generation literals)
# ─────────────────────────────────────────────────────────────────────────────


class TestBoardCapabilities:
    CAPABILITIES = (
        "has_fw_id_storage",
        "can_self_program_cc1352",
        "ships_cc1352_hex_assets",
        "accepts_unnamed_images",
    )

    def test_every_board_declares_every_capability(self):
        for board in board_mod.BOARDS.values():
            for capability in self.CAPABILITIES:
                assert isinstance(
                    getattr(board, capability), bool
                ), f"{board.generation} does not declare {capability}"
            assert board.bridge_ring_bytes > 0

    def test_v2_lacks_what_it_physically_lacks(self):
        # No CONFIG_NVS (16 KB of SRAM), no RP2040 to run free_dap on, and its
        # release workflow publishes no CC1352 .hex assets.
        assert BOARD_V2.has_fw_id_storage is False
        assert BOARD_V2.can_self_program_cc1352 is False
        assert BOARD_V2.ships_cc1352_hex_assets is False
        assert BOARD_V2.accepts_unnamed_images is False
        assert BOARD_V2.bridge_ring_bytes < BOARD_V3.bridge_ring_bytes

    def test_v3_keeps_its_historical_behaviour(self):
        assert BOARD_V3.has_fw_id_storage is True
        assert BOARD_V3.can_self_program_cc1352 is True
        assert BOARD_V3.ships_cc1352_hex_assets is True
        assert BOARD_V3.accepts_unnamed_images is True


class TestBoardFromGeneration:
    @pytest.mark.parametrize("text", ["v2", "V2", " v2 ", "2"])
    def test_accepts_the_forms_a_user_types(self, text):
        assert board_mod.board_from_generation(text) is BOARD_V2

    def test_v3(self):
        assert board_mod.board_from_generation("v3") is BOARD_V3

    def test_unknown_is_none(self):
        assert board_mod.board_from_generation(None) is None
        assert board_mod.board_from_generation("") is None
        assert board_mod.board_from_generation("v4") is None


# ─────────────────────────────────────────────────────────────────────────────
# an unknown board never reaches a destructive operation
# ─────────────────────────────────────────────────────────────────────────────


class TestUnknownBoardIsRefused:
    def test_update_refuses_and_does_not_reboot(self):
        from modules.firmware import fw_update

        flasher = MagicMock()
        flasher.release_tag = "v3.1.0.0"
        device = MagicMock()
        device.shell_port = "/dev/ttyACM2"
        nameless = fw_update.parse_fw_version_response("FW: dev-87c5174-dirty\r\n")
        with patch.object(
            fw_update, "get_device_fw_version", return_value=nameless
        ), patch.object(
            fw_update, "get_latest_software_version", return_value=None
        ), patch.object(
            fw_update, "enter_boot_mode"
        ) as reboot, patch.object(
            fw_update, "_perform_rp2040_update"
        ) as perform:
            assert (
                fw_update.check_and_update_rp2040(device=device, flasher=flasher)
                is False
            )
            reboot.assert_not_called()
            perform.assert_not_called()

    def test_board_override_lets_the_update_proceed(self):
        from modules.firmware import fw_update

        flasher = MagicMock()
        flasher.release_tag = "v2.0.1.0"
        device = MagicMock()
        device.shell_port = "/dev/ttyACM2"
        nameless = fw_update.parse_fw_version_response("FW: dev-87c5174-dirty\r\n")
        with patch.object(
            fw_update, "get_device_fw_version", return_value=nameless
        ), patch.object(
            fw_update, "get_latest_software_version", return_value=None
        ), patch.object(
            fw_update, "_perform_rp2040_update", return_value=True
        ) as perform:
            assert (
                fw_update.check_and_update_rp2040(
                    device=device, flasher=flasher, board=BOARD_V2
                )
                is True
            )
            assert perform.call_args.kwargs["board"] is BOARD_V2

    def test_force_update_refuses_instead_of_assuming_v3(self):
        from modules.firmware import fw_update

        flasher = MagicMock()
        device = MagicMock()
        device.shell_port = "/dev/ttyACM2"
        with patch.object(board_mod, "detect_board", return_value=None), patch.object(
            fw_update, "_perform_rp2040_update"
        ) as perform:
            assert (
                fw_update.force_update_rp2040(device=device, flasher=flasher) is False
            )
            perform.assert_not_called()

    def test_flash_refuses_before_touching_the_chip(self):
        from modules.firmware.flasher import Flasher

        flasher = Flasher.__new__(Flasher)
        device = MagicMock()
        device.shell_port = "/dev/ttyACM2"
        with patch.object(board_mod, "detect_board", return_value=None), patch.object(
            Flasher, "get_local_firmware", return_value=["sniffle_cc1352p7_1M.hex"]
        ), patch.object(Flasher, "flash_firmware") as flash:
            assert flasher.find_flash_firmware("ble", device) is False
            flash.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# board-aware UF2 and release-tag resolution
# ─────────────────────────────────────────────────────────────────────────────


class TestResolveBoardUf2:
    def _flasher(self, tmp_path):
        flasher = MagicMock()
        flasher.get_releases_path.return_value = str(tmp_path)
        flasher.fetch_board_uf2.return_value = None
        return flasher

    def test_v2_never_falls_back_to_another_boards_uf2(self, tmp_path):
        from modules.firmware.fw_update import resolve_board_uf2

        (tmp_path / "catsniffer-v3.1.0.0.uf2").write_bytes(b"x")
        assert resolve_board_uf2(self._flasher(tmp_path), BOARD_V2) is None

    def test_v3_accepts_an_unnamed_uf2(self, tmp_path):
        from modules.firmware.fw_update import resolve_board_uf2

        (tmp_path / "firmware.uf2").write_bytes(b"x")
        assert resolve_board_uf2(self._flasher(tmp_path), BOARD_V3).endswith(
            "firmware.uf2"
        )

    def test_local_asset_wins_over_download(self, tmp_path):
        from modules.firmware.fw_update import resolve_board_uf2

        (tmp_path / "catsniffer-v2.0.1.0.uf2").write_bytes(b"x")
        flasher = self._flasher(tmp_path)
        assert resolve_board_uf2(flasher, BOARD_V2).endswith("catsniffer-v2.0.1.0.uf2")
        flasher.fetch_board_uf2.assert_not_called()


class TestExpectedTagForBoard:
    def test_uses_the_loaded_tag_when_it_belongs_to_the_board(self):
        from modules.firmware.fw_update import expected_tag_for_board

        flasher = MagicMock()
        flasher.release_tag = "v3.1.0.0"
        assert expected_tag_for_board(flasher, BOARD_V3) == "v3.1.0.0"
        flasher.get_release_for_board.assert_not_called()

    def test_queries_the_boards_own_release_line_otherwise(self):
        from modules.firmware.fw_update import expected_tag_for_board

        flasher = MagicMock()
        flasher.release_tag = "v3.1.0.0"
        flasher.get_release_for_board.return_value = {"tag_name": "v2.0.1.0"}
        assert expected_tag_for_board(flasher, BOARD_V2) == "v2.0.1.0"


# ─────────────────────────────────────────────────────────────────────────────
# structural rules that keep the abstraction from leaking back out
# ─────────────────────────────────────────────────────────────────────────────

import ast  # noqa: E402
import pathlib  # noqa: E402

_MODULES_DIR = pathlib.Path(PROJECT_ROOT) / "modules"
_BOARD_MODULE = _MODULES_DIR / "firmware" / "board.py"
_PY_SOURCES = [p for p in sorted(_MODULES_DIR.rglob("*.py")) if p != _BOARD_MODULE]


def _generation_literal_comparisons(path):
    """``(lineno, source)`` for every ``<x>.generation == "vN"`` comparison."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        touches_generation = any(
            isinstance(o, ast.Attribute) and o.attr == "generation" for o in operands
        )
        has_literal = any(
            isinstance(o, ast.Constant) and isinstance(o.value, str) for o in operands
        )
        if touches_generation and has_literal:
            yield node.lineno, ast.unparse(node)


@pytest.mark.unit
@pytest.mark.parametrize(
    "path", _PY_SOURCES, ids=lambda p: str(p.relative_to(_MODULES_DIR))
)
def test_no_generation_literal_outside_board_module(path):
    """Board differences belong in ``BoardInfo`` as data, not in branches.

    Every ``generation == "v3"`` is a rule about *why* the code paths differ
    written as a rule about *which board* it is, so the next board silently
    takes the wrong branch. ``board.py`` is the one place allowed to map a
    generation string to a board.
    """
    offenders = [
        f"{path.name}:{lineno}: {src}"
        for lineno, src in _generation_literal_comparisons(path)
    ]
    assert not offenders, (
        "compare a BoardInfo capability instead of the generation: " f"{offenders}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# the invariant the whole detection chain rests on (checked against firmware)
# ─────────────────────────────────────────────────────────────────────────────

_FIRMWARE_DIR = pathlib.Path(
    os.environ.get(
        "CATSNIFFER_FIRMWARE_DIR",
        pathlib.Path(PROJECT_ROOT).parent.parent / "CatSniffer-Firmware",
    )
)

_FW_TREES = {
    "v2": (
        _FIRMWARE_DIR / "SAMD21" / "catsniffer" / "src" / "shell_commands.c",
        BOARD_V2,
    ),
    "v3": (
        _FIRMWARE_DIR / "RP2040" / "catsniffer" / "src" / "shell_commands.c",
        BOARD_V3,
    ),
}


def _cmd_fw_version_body(source_path):
    """The body of ``cmd_fw_version()`` in a shell_commands.c file."""
    text = source_path.read_text(encoding="utf-8", errors="replace")
    # The first mention is the forward declaration; the definition is the one
    # followed by a body.
    match = re.search(r"cmd_fw_version\s*\([^)]*\)\s*\n?\{", text)
    assert match, f"cmd_fw_version() not found in {source_path}"
    end = text.index("\n}", match.end())
    return text[match.end() : end]


@pytest.mark.unit
@pytest.mark.parametrize("generation", sorted(_FW_TREES))
def test_firmware_always_emits_the_board_line(generation):
    """Both firmwares name their board in ``fw_version``, unconditionally.

    ``parse_board_line`` treats a reply without a ``Board:`` line as unknown
    and refuses to flash it; that refusal is only correct because no shipped
    firmware omits the line. The v2 firmware has emitted it since its first
    release, and this test is what keeps that true: if the line ever becomes
    conditional, detection silently degrades to "unknown" for real hardware.
    """
    source_path, board = _FW_TREES[generation]
    if not source_path.exists():
        pytest.skip(f"CatSniffer-Firmware tree not available at {source_path}")

    body = _cmd_fw_version_body(source_path)
    assert "Board: %s" in body, f"{generation} fw_version no longer prints Board:"
    assert body.count("Board:") == 1, "the Board: line looks conditional now"

    # The literal the firmware substitutes must be one parse_board_line reads.
    literals = re.findall(r'"([^"]*)"', body)
    board_names = [lit for lit in literals if re.match(r"^v[23]\s", lit)]
    assert board_names, f"{generation} names no board in fw_version"
    for name in board_names:
        assert parse_board_line(f"Board: {name}") is board
        assert board.mcu in name and board.cc_chip in name


# ─────────────────────────────────────────────────────────────────────────────
# "not supported on this board": the typed refusal and its two helpers
# ─────────────────────────────────────────────────────────────────────────────


class TestRequireCapability:
    def test_v3_can_program_its_own_cc1352(self):
        assert (
            board_mod.require_capability(
                BOARD_V3, "can_self_program_cc1352", "catnip restore"
            )
            is BOARD_V3
        )

    def test_v2_is_refused_with_the_reason_and_a_hint(self):
        from modules.core.exceptions import UnsupportedOnBoardError

        with pytest.raises(UnsupportedOnBoardError) as excinfo:
            board_mod.require_capability(
                BOARD_V2, "can_self_program_cc1352", "catnip restore"
            )
        message = str(excinfo.value)
        assert "catnip restore" in message
        assert "RP2040" in message  # says *why*, not just "unsupported"
        assert excinfo.value.hint  # and what hardware would work

    def test_unknown_board_is_refused_too(self):
        from modules.core.exceptions import UnsupportedOnBoardError

        with pytest.raises(UnsupportedOnBoardError):
            board_mod.require_capability(None, "can_self_program_cc1352", "catnip x")

    @pytest.mark.parametrize(
        "capability",
        ("has_fw_id_storage", "can_self_program_cc1352", "ships_cc1352_hex_assets"),
    )
    def test_every_capability_the_v2_lacks_has_a_written_reason(self, capability):
        from modules.core.exceptions import UnsupportedOnBoardError

        with pytest.raises(UnsupportedOnBoardError) as excinfo:
            board_mod.require_capability(BOARD_V2, capability, "feature")
        # A generic "lacks '<field>'" fallback would leak the field name.
        assert capability not in str(excinfo.value)

    def test_exit_code_is_its_own(self):
        from modules.core import exceptions

        assert (
            exceptions.UnsupportedOnBoardError.exit_code == exceptions.EXIT_UNSUPPORTED
        )
        assert exceptions.EXIT_UNSUPPORTED not in (
            exceptions.EXIT_ERROR,
            exceptions.EXIT_FIRMWARE,
            exceptions.EXIT_CONNECTION,
            exceptions.EXIT_USAGE,
        )


class TestRequireFirmwareForBoard:
    def test_ti_sniffer_is_refused_on_v2(self):
        from modules.core.exceptions import UnsupportedOnBoardError

        with pytest.raises(UnsupportedOnBoardError) as excinfo:
            board_mod.require_firmware_for_board(
                BOARD_V2, "ti_sniffer", "catnip sniff zigbee"
            )
        assert "ti_sniffer" in str(excinfo.value)
        assert "catnip sniff zigbee" in str(excinfo.value)
        # The hint lists what *is* available, so the user has somewhere to go.
        assert any("sniffle" in line for line in excinfo.value.hint)

    def test_sniffle_is_fine_on_v2(self):
        assert (
            board_mod.require_firmware_for_board(BOARD_V2, "sniffle", "catnip vhci")
            is None
        )

    def test_every_v3_image_is_fine_on_v3(self):
        for official_id in fw_aliases.official_ids_for_board("v3"):
            board_mod.require_firmware_for_board(BOARD_V3, official_id, "feature")

    def test_unknown_board_does_not_block_the_early_check(self):
        # The flashing path refuses an unknown board itself (T-01); this check
        # is informative and must not turn detection failure into a refusal.
        assert (
            board_mod.require_firmware_for_board(None, "ti_sniffer", "feature") is None
        )


class TestFileAvailableForBoard:
    def test_v2_sees_its_own_images_and_uf2(self):
        assert board_mod.file_available_for_board(
            "sniffle_cc1352p1_cc2652p1_1M.hex", BOARD_V2
        )
        assert board_mod.file_available_for_board("catsniffer-v2.1.0.0.uf2", BOARD_V2)

    def test_v2_does_not_see_p7_images_nor_the_v3_uf2(self):
        assert not board_mod.file_available_for_board(
            "sniffle_cc1352p7_1M.hex", BOARD_V2
        )
        assert not board_mod.file_available_for_board(
            "catsniffer-v3.1.0.1.uf2", BOARD_V2
        )

    def test_v3_does_not_see_the_v2_uf2(self):
        assert board_mod.file_available_for_board("catsniffer-v3.1.0.1.uf2", BOARD_V3)
        assert not board_mod.file_available_for_board(
            "catsniffer-v2.1.0.0.uf2", BOARD_V3
        )

    def test_unknown_board_hides_nothing(self):
        assert board_mod.file_available_for_board("anything.hex", None)


class TestRestoreRefusesOnV2:
    def test_v2_is_refused_before_any_tool_is_touched(self):
        from modules.core.exceptions import UnsupportedOnBoardError
        from modules.firmware import restore as restore_mod

        device = MagicMock()
        device.shell_port = "/dev/ttyACM2"
        with patch.object(
            restore_mod, "detect_board", return_value=BOARD_V2
        ), patch.object(restore_mod, "check_openocd") as openocd:
            with pytest.raises(UnsupportedOnBoardError):
                restore_mod.restore_cc1352(device=device)
            openocd.assert_not_called()

    def test_board_override_is_honoured(self):
        from modules.core.exceptions import UnsupportedOnBoardError
        from modules.firmware import restore as restore_mod

        with patch.object(restore_mod, "detect_board") as detect:
            with pytest.raises(UnsupportedOnBoardError):
                restore_mod.restore_cc1352(board=BOARD_V2)
            detect.assert_not_called()

    def test_unknown_board_still_lets_a_recovery_run(self):
        # The board being recovered is exactly the one that cannot answer.
        from modules.firmware import restore as restore_mod

        device = MagicMock()
        device.shell_port = "/dev/ttyACM2"
        with patch.object(restore_mod, "detect_board", return_value=None), patch.object(
            restore_mod, "check_openocd", return_value=None
        ) as openocd:
            assert restore_mod.restore_cc1352(device=device) is False
            openocd.assert_called_once()


class TestEarlyFirmwareCheck:
    """The gate guards the *flash*, not the board.

    A v2 already running a firmware catnip has no v2 image for keeps working
    (this happens: a v2 flashed with a CC1352P1 TI sniffer build by hand).
    What must never happen is trying to flash an image that does not exist
    for the connected generation.
    """

    def _session(self, verified, board=BOARD_V2, flasher=None):
        from modules.core import device_session as session_mod

        device = MagicMock()
        device.shell_port = "/dev/ttyACM3"
        patches = (
            patch.object(
                session_mod.device_utils, "get_device_or_exit", return_value=device
            ),
            patch.object(session_mod, "detect_board", return_value=board),
            patch.object(session_mod, "FirmwareVerifier"),
            patch.object(session_mod.device_utils, "send_identify_command"),
        )
        started = [p.start() for p in patches]
        started[2].return_value.verify.return_value = MagicMock(verified=verified)
        return session_mod, device, patches

    @staticmethod
    def _stop(patches):
        for p in patches:
            p.stop()

    def test_a_v2_already_running_the_firmware_is_left_alone(self):
        session_mod, device, patches = self._session(verified=True)
        try:
            flasher = MagicMock()
            with session_mod.device_session(
                None,
                required_firmware="ti_sniffer",
                feature="catnip sniff zigbee",
                flasher=flasher,
            ) as dev:
                assert dev is device
            flasher.find_flash_firmware.assert_not_called()
        finally:
            self._stop(patches)

    def test_a_v2_without_it_is_refused_before_the_flash(self):
        from modules.core.exceptions import UnsupportedOnBoardError

        session_mod, _, patches = self._session(verified=False)
        try:
            flasher = MagicMock()
            with pytest.raises(UnsupportedOnBoardError):
                with session_mod.device_session(
                    None,
                    required_firmware="ti_sniffer",
                    feature="catnip sniff zigbee",
                    flasher=flasher,
                ):
                    pass
            flasher.find_flash_firmware.assert_not_called()
        finally:
            self._stop(patches)

    def test_a_v2_missing_sniffle_still_gets_flashed(self):
        session_mod, _, patches = self._session(verified=False)
        try:
            flasher = MagicMock()
            flasher.find_flash_firmware.return_value = True
            with session_mod.device_session(
                None, required_firmware="sniffle", flasher=flasher
            ):
                pass
            flasher.find_flash_firmware.assert_called_once()
        finally:
            self._stop(patches)

    def test_an_unknown_board_is_not_blocked(self):
        session_mod, _, patches = self._session(verified=False, board=None)
        try:
            flasher = MagicMock()
            flasher.find_flash_firmware.return_value = True
            with session_mod.device_session(
                None, required_firmware="ti_sniffer", flasher=flasher
            ):
                pass
            flasher.find_flash_firmware.assert_called_once()
        finally:
            self._stop(patches)


class TestFlashListFiltersByBoard:
    """``flash --list`` offers what this board can take, not the catalogue.

    ``rich.table`` is mocked globally (see tests/conftest.py), so the rows are
    read from the Table mock instead of from the rendered output.
    """

    FIRMWARES = [
        "sniffle_cc1352p1_cc2652p1_1M.hex",
        "sniffle_cc1352p7_1M.hex",
        "sniffer_fw_Catsniffer_v3.x.hex",
    ]

    def _run(self, args, board, firmwares=None):
        from click.testing import CliRunner

        from modules.firmware import cli as fw_cli

        with patch.object(
            fw_cli.Flasher,
            "get_local_firmware",
            return_value=list(self.FIRMWARES if firmwares is None else firmwares),
        ), patch.object(
            fw_cli.Flasher, "parse_descriptions", return_value={}
        ), patch.object(
            fw_cli, "_board_for_list", return_value=board
        ), patch.object(
            fw_cli, "Table"
        ) as table, patch.object(
            fw_cli, "print_dim"
        ) as dim, patch.object(
            fw_cli, "print_info"
        ) as info, patch.object(
            fw_cli, "print_warning"
        ) as warning:
            result = CliRunner().invoke(fw_cli.flash, ["--list"] + args)
        listed = [call.args[1] for call in table.return_value.add_row.call_args_list]
        # The console is patched out by other suites when everything runs
        # together, so what the user is told is read from the printers.
        said = " ".join(
            str(call.args[0])
            for printer in (dim, info, warning)
            for call in printer.call_args_list
        )
        return result, listed, said

    def test_v2_list_hides_p7_images(self):
        result, listed, said = self._run([], BOARD_V2)
        assert result.exit_code == 0
        assert listed == ["sniffle_cc1352p1_cc2652p1_1M.hex"]
        assert "2 image(s) for other boards hidden" in said

    def test_all_shows_the_whole_catalogue(self):
        result, listed, said = self._run(["--all"], BOARD_V2)
        assert result.exit_code == 0
        assert sorted(listed) == sorted(self.FIRMWARES)

    def test_unknown_board_shows_everything(self):
        result, listed, said = self._run([], None)
        assert result.exit_code == 0
        assert sorted(listed) == sorted(self.FIRMWARES)
        assert "Board generation unknown" in said

    def test_a_v2_with_nothing_flashable_says_so_instead_of_an_empty_table(self):
        result, listed, said = self._run(
            [], BOARD_V2, firmwares=["sniffle_cc1352p7_1M.hex"]
        )
        assert result.exit_code == 0
        assert listed == []
        assert "None of the local images is built for" in said


# ─────────────────────────────────────────────────────────────────────────────
# the status parser: one firmware reports four extra sections, the other none
# ─────────────────────────────────────────────────────────────────────────────

# Captured verbatim from a real v2 board (SAMD21, FW v2.1.0.0) on 2026-09-10.
V2_STATUS = (
    "status\r\n"
    "Trace(4557): 01 03 04 30 01 02 04 01 03 04 30 01 02 04\r\n"
    "Mode: 0, Band: 0, Radio: LoRa, LoRa: initialized, LoRa Mode: Stream, "
    "FW: v2.1.0.0, CC1352 FW: unset (n/a)\r\n"
    "CC1352 loss: uart_overrun=0, ring_dropped=0 bytes, dma_regress=0\r\n"
    "Stack unused: main=200 lora=56 isr=440 bytes\r\n"
    "Last fault: none\r\n"
    "  thread 0x20000a20 prio=-11 stack=1024 unused=56\r\n"
    "  thread 0x20000f28 prio=0 stack=1536 unused=200"
)
# The RP2040 build stops after the loss line (RP2040/.../shell_commands.c).
V3_STATUS = (
    "status\r\n"
    "Mode: 0, Band: 0, Radio: LoRa, LoRa: initialized, LoRa Mode: Stream, "
    "FW: v3.1.0.0, CC1352 FW: sniffle (official)\r\n"
    "CC1352 loss: uart_overrun=0, ring_dropped=0 bytes"
)


class TestParseStatusResponse:
    def _parse(self, text):
        from modules.firmware.fw_status import parse_status_response

        return parse_status_response(text)

    def test_v2_extended_block_is_read_whole(self):
        status = self._parse(V2_STATUS)
        assert status.fields["FW"] == "v2.1.0.0"
        assert status.fields["CC1352 FW"] == "unset (n/a)"
        assert status.counters == {
            "uart_overrun": 0,
            "ring_dropped": 0,
            "dma_regress": 0,
        }
        assert status.stacks == {"main": 200, "lora": 56, "isr": 440}
        assert status.last_fault == "none"
        assert len(status.threads) == 2
        assert status.trace.startswith("Trace(")
        assert status.has_diagnostics is True

    def test_v3_minimal_block_is_not_mistaken_for_zeros(self):
        status = self._parse(V3_STATUS)
        assert status.fields["CC1352 FW"] == "sniffle (official)"
        # No dma_regress on this firmware: absent, not zero.
        assert "dma_regress" not in status.counters
        assert status.stacks == {}
        assert status.threads == ()
        assert status.last_fault is None
        assert status.has_diagnostics is False

    def test_the_echoed_command_is_not_data(self):
        assert "status" not in self._parse(V3_STATUS).unparsed

    def test_an_unknown_line_is_kept_verbatim_not_dropped(self):
        status = self._parse(V3_STATUS + "\r\nSomething new: 42")
        assert "Something new: 42" in status.unparsed

    def test_a_missing_section_never_raises(self):
        # Every section is optional, in any combination.
        assert self._parse("Mode: 0, Band: 0").counters == {}
        assert self._parse("CC1352 loss: uart_overrun=3").fields == {}
        assert self._parse("  thread 0x1 prio=0 stack=8 unused=4").threads[0].stack == 8

    @pytest.mark.parametrize("text", [None, "", "   \r\n"])
    def test_nothing_to_read_is_none(self, text):
        assert self._parse(text) is None

    def test_tightest_stack_spans_named_stacks_and_threads(self):
        status = self._parse(V2_STATUS)
        assert status.tightest_stack == ("lora", 56)

    def test_tightest_stack_is_none_when_nothing_reports_one(self):
        assert self._parse(V3_STATUS).tightest_stack is None


class TestStatusCommandShowsBoardTruth:
    def _run(self, board, shell_status, args=()):
        from click.testing import CliRunner

        from modules.device import cli as device_cli

        device = MagicMock()
        device.shell_port = "/dev/ttyACM3"
        with patch.object(
            device_cli, "get_device_or_exit", return_value=device
        ), patch.object(device_cli, "detect_board", return_value=board), patch.object(
            device_cli, "read_status", return_value=shell_status
        ), patch.object(
            device_cli, "FirmwareVerifier"
        ) as verifier, patch.object(
            device_cli, "Table"
        ) as table, patch.object(
            device_cli, "print_info"
        ) as info, patch.object(
            device_cli, "print_warning"
        ) as warning:
            verifier.return_value.detect.return_value = MagicMock(firmware_id=None)
            result = CliRunner().invoke(device_cli.status, list(args))
        rendered = " ".join(
            str(arg)
            for call in table.return_value.add_row.call_args_list
            for arg in call.args
        )
        said = " ".join(
            str(call.args[0])
            for printer in (info, warning)
            for call in printer.call_args_list
        )
        return result, rendered, said

    def _status(self, text):
        from modules.firmware.fw_status import parse_status_response

        return parse_status_response(text)

    def test_v2_capabilities_are_listed_as_unsupported(self):
        result, rendered, _ = self._run(BOARD_V2, self._status(V2_STATUS))
        assert result.exit_code == 0
        assert "Board can" in rendered
        assert "Stores the CC1352 firmware id" in rendered
        assert "yes" not in rendered.split("Board can")[1]

    def test_v3_capabilities_are_listed_as_supported(self):
        _, rendered, _ = self._run(BOARD_V3, self._status(V3_STATUS))
        assert "Can self-program the CC1352" in rendered
        assert "no " not in rendered.split("Board can")[1]

    def test_the_v2_diagnostics_reach_the_table(self):
        _, rendered, said = self._run(BOARD_V2, self._status(V2_STATUS))
        assert "stack unused: lora" in rendered
        assert "loss: dma_regress" in rendered
        assert "Last fault" in rendered
        assert "close to a stack overflow" in said

    def test_v3_shows_no_diagnostics_it_did_not_report(self):
        _, rendered, said = self._run(BOARD_V3, self._status(V3_STATUS))
        assert "stack unused" not in rendered
        assert "Last fault" not in rendered
        assert "close to a stack overflow" not in said
        assert "--diagnostics" not in said  # nothing extra to offer

    def test_diagnostics_flag_dumps_every_thread(self):
        _, _, said = self._run(BOARD_V2, self._status(V2_STATUS), args=["-D"])
        assert "thread 0x20000a20" in said
        assert "thread 0x20000f28" in said
        assert "Trace(" in said

    def test_a_silent_shell_still_renders_the_board(self):
        result, rendered, said = self._run(BOARD_V2, None)
        assert result.exit_code == 0
        assert "Board can" in rendered
        assert "stack unused" not in rendered


class TestMetadataStorageIsAskedOnce:
    def test_a_board_that_says_no_storage_is_believed(self):
        from modules.firmware.fw_metadata import FirmwareMetadata

        shell = MagicMock()
        shell.send_command.return_value = "ERR storage unavailable"
        assert FirmwareMetadata(shell).keeps_firmware_id() is False

        shell.send_command.return_value = "ERR not supported on this board"
        assert FirmwareMetadata(shell).keeps_firmware_id() is False

    def test_a_normal_answer_means_it_keeps_one(self):
        from modules.firmware.fw_metadata import FirmwareMetadata

        shell = MagicMock()
        shell.send_command.return_value = "OK cc1352_fw_id=sniffle type=official"
        assert FirmwareMetadata(shell).keeps_firmware_id() is True

    def test_a_broken_port_is_not_read_as_a_refusal(self):
        # "We could not ask" must not cut the retry loop short.
        from modules.firmware.fw_metadata import FirmwareMetadata

        shell = MagicMock()
        shell.send_command.side_effect = OSError("port went away")
        assert FirmwareMetadata(shell).keeps_firmware_id() is True

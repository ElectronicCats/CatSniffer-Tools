"""
test_cli_firmware.py
====================
Behaviour of ``modules/firmware/cli.py`` -- ``flash``, ``verify``, ``update``
and ``restore`` -- exercised as a real subprocess.

First slice of ``BOMBERCAT_PARITY.md`` section 4: one test file per CLI
module, so that what is *not* covered is visible.  These tests came out of the
``TestCLISubprocess`` grab bag in ``tests/test_catsniffer.py`` unchanged;
``update`` and ``restore`` have no coverage here yet, which is the point of
giving them a file of their own.

No hardware is required: every assertion is written to hold with or without a
CatSniffer plugged in.
"""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from modules.firmware.cli import _CAPABILITY_NEXT_STEP, flash, resolve_firmware


@pytest.mark.unit
class TestFlashRefreshCLI:
    """`catnip flash --refresh [--force]` -- CLI wiring only. The actual
    check/download logic lives in Flasher.refresh(), which is tested in
    test_catsniffer.py::TestFlasherRefresh; here Flasher itself is a stub so
    these tests hold with or without a real ``.catnip`` cache on disk.
    """

    def _run(self, args, refresh_result=None, refresh_error=None, local_firmware=None):
        from modules.firmware import cli as fw_cli

        fake_flasher = MagicMock()
        fake_flasher.get_local_firmware.return_value = list(
            local_firmware if local_firmware is not None else ["a.hex", "b.hex"]
        )
        if refresh_error is not None:
            fake_flasher.refresh.side_effect = refresh_error
        else:
            fake_flasher.refresh.return_value = refresh_result

        with patch.object(fw_cli, "Flasher", return_value=fake_flasher), patch.object(
            fw_cli, "print_error"
        ) as error, patch.object(fw_cli, "print_warning") as warning, patch.object(
            fw_cli, "print_success"
        ) as success, patch.object(
            fw_cli, "print_info"
        ) as info:
            result = CliRunner().invoke(flash, args)
        said = " ".join(
            str(call.args[0])
            for printer in (error, warning, success, info)
            for call in printer.call_args_list
        )
        return result, fake_flasher, said

    def test_force_without_refresh_is_rejected(self):
        result, flasher, said = self._run(["--force"])

        assert result.exit_code != 0
        assert "--force only makes sense together with --refresh" in said
        flasher.refresh.assert_not_called()

    def test_refresh_combined_with_list_is_rejected(self):
        result, flasher, said = self._run(["--refresh", "--list"])

        assert result.exit_code != 0
        assert "cannot be combined with --list" in said
        flasher.refresh.assert_not_called()

    def test_refresh_combined_with_a_firmware_name_is_rejected(self):
        result, flasher, said = self._run(["--refresh", "ble"])

        assert result.exit_code != 0
        assert "cannot be combined" in said
        flasher.refresh.assert_not_called()

    def test_refresh_reports_already_up_to_date(self):
        result, flasher, said = self._run(
            ["--refresh"],
            refresh_result={
                "previous_tag": "v3.2.0.0",
                "tag": "v3.2.0.0",
                "updated": False,
            },
        )

        assert result.exit_code == 0
        assert "Already up to date" in said
        assert "v3.2.0.0" in said
        flasher.refresh.assert_called_once_with(force=False)

    def test_refresh_reports_an_update(self):
        result, flasher, said = self._run(
            ["--refresh"],
            refresh_result={
                "previous_tag": "v3.1.0.0",
                "tag": "v3.2.0.0",
                "updated": True,
            },
        )

        assert result.exit_code == 0
        assert "Updated v3.1.0.0" in said
        assert "v3.2.0.0" in said
        flasher.refresh.assert_called_once_with(force=False)

    def test_force_reports_a_fresh_download_even_onto_the_same_tag(self):
        result, flasher, said = self._run(
            ["--refresh", "--force"],
            refresh_result={
                "previous_tag": "v3.2.0.0",
                "tag": "v3.2.0.0",
                "updated": True,
            },
        )

        assert result.exit_code == 0
        assert "--force" in said
        assert "Downloaded v3.2.0.0" in said
        assert "Updated" not in said
        flasher.refresh.assert_called_once_with(force=True)

    def test_refresh_network_failure_is_a_clean_error(self):
        from modules.core.exceptions import FirmwareError

        result, flasher, said = self._run(
            ["--refresh"], refresh_error=FirmwareError("could not reach GitHub: boom")
        )

        assert result.exit_code != 0
        assert "could not reach GitHub: boom" in said

    def test_refresh_disk_failure_is_a_clean_error(self):
        result, flasher, said = self._run(
            ["--refresh"], refresh_error=OSError("No space left on device")
        )

        assert result.exit_code != 0
        assert "could not update the firmware cache" in said
        assert "No space left on device" in said


@pytest.mark.unit
class TestFlashNextSteps:
    """`flash` suggests the matching `catnip sniff <x>` via firmware_registry
    capabilities (analisis-bombercat-vs-catnip.md, section 3)."""

    def test_ble_alias_suggests_sniff_ble(self):
        entry = resolve_firmware("ble")
        assert entry is not None
        suggested = [
            cmd for cap, cmd in _CAPABILITY_NEXT_STEP.items() if entry.can(cap)
        ]
        assert suggested == ["catnip sniff ble"]

    def test_zigbee_alias_suggests_sniff_zigbee_and_thread(self):
        entry = resolve_firmware("zigbee")
        assert entry is not None
        suggested = {
            cmd for cap, cmd in _CAPABILITY_NEXT_STEP.items() if entry.can(cap)
        }
        assert suggested == {"catnip sniff zigbee -c 15", "catnip sniff thread -c 15"}

    def test_unresolvable_firmware_suggests_nothing(self):
        assert resolve_firmware("not-a-real-firmware") is None


@pytest.mark.slow
class TestFlashCommand:
    def test_flash_help(self, run_catnip):
        result = run_catnip("flash", "--help")
        assert result.returncode == 0

    def test_flash_no_firmware_exits_nonzero(self, run_catnip):
        result = run_catnip("flash")
        # Without firmware should exit with error
        assert result.returncode != 0 or "No firmware" in result.stdout + result.stderr

    def test_flash_list_no_device_needed(self, run_catnip):
        """--list only reads local files, no hardware needed."""
        result = run_catnip("flash", "--list")
        # May fail if no releases, but shouldn't crash with traceback
        assert "Traceback" not in result.stderr or result.returncode == 0

    def test_flash_invalid_device_id(self, run_catnip):
        result = run_catnip("flash", "--device", "9999", "ble")
        assert result.returncode != 0 or "not found" in result.stdout + result.stderr


@pytest.mark.slow
class TestVerifyCommand:
    def test_verify_no_device(self, run_catnip):
        result = run_catnip("verify", "--device", "99")
        # Check if command either:
        # 1. Returns non-zero exit code, OR
        # 2. Returns zero exit code but shows "No device found" message
        assert (
            result.returncode != 0
            or "No CatSniffer device found!" in result.stdout + result.stderr
            or "not found" in result.stdout + result.stderr
        )

    def test_verify_device_flag(self, run_catnip):
        result = run_catnip("verify", "--device", "99")
        assert (
            result.returncode != 0
            or "No CatSniffer device(s) found" in result.stdout + result.stderr
        )

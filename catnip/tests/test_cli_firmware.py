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

import pytest


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

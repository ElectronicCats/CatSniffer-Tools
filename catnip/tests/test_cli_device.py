"""
test_cli_device.py
==================
Behaviour of ``modules/device/cli.py`` -- ``devices``, ``identify`` and
``status``.

Part of ``BOMBERCAT_PARITY.md`` section 4: one test file per CLI module.  It
is deliberately thin -- the single test below is everything the suite had for
this module, moved out of ``TestCLISubprocess`` in
``tests/test_catsniffer.py``.  ``identify`` and ``devices --debug`` are still
uncovered.
"""

import pytest

from modules.core.firmware_registry import get_firmware, next_steps_for


@pytest.mark.slow
class TestDevicesCommand:
    def test_devices_no_devices_connected(self, run_catnip):
        result = run_catnip("devices")
        # Without hardware should indicate no devices
        assert (
            result.returncode == 0 or "No CatSniffer" in result.stdout + result.stderr
        )


@pytest.mark.unit
class TestStatusNextSteps:
    """`status` suggests the same `catnip sniff <x>` as `flash`, driven by
    the same firmware_registry capabilities (analisis-bombercat-vs-catnip.md,
    section 7: the registry is the single source of truth for both)."""

    def test_known_sniffing_firmware_suggests_its_sniff_command(self):
        entry = get_firmware("ti_sniffer")
        assert entry is not None
        assert set(next_steps_for(entry)) == {
            "catnip sniff zigbee -c 15",
            "catnip sniff thread -c 15",
        }

    def test_firmware_without_sniff_capability_suggests_nothing(self):
        entry = get_firmware("catnip_v3")
        assert entry is not None
        assert next_steps_for(entry) == []

    def test_unknown_firmware_id_resolves_to_none(self):
        assert get_firmware("not-a-real-id") is None


@pytest.mark.slow
class TestStatusCommand:
    def test_status_help(self, run_catnip):
        result = run_catnip("status", "--help")
        assert result.returncode == 0

    def test_status_no_device(self, run_catnip):
        result = run_catnip("status", "--device", "9999")
        assert (
            result.returncode != 0
            or "No CatSniffer device found!" in result.stdout + result.stderr
        )

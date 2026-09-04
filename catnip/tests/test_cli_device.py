"""
test_cli_device.py
==================
Behaviour of ``modules/device/cli.py`` -- ``devices`` and ``identify``.

Part of ``BOMBERCAT_PARITY.md`` section 4: one test file per CLI module.  It
is deliberately thin -- the single test below is everything the suite had for
this module, moved out of ``TestCLISubprocess`` in
``tests/test_catsniffer.py``.  ``identify`` and ``devices --debug`` are still
uncovered.
"""

import pytest


@pytest.mark.slow
class TestDevicesCommand:
    def test_devices_no_devices_connected(self, run_catnip):
        result = run_catnip("devices")
        # Without hardware should indicate no devices
        assert (
            result.returncode == 0 or "No CatSniffer" in result.stdout + result.stderr
        )

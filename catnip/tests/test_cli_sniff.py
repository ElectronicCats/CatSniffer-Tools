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

import pytest


@pytest.mark.slow
class TestSniffGroup:
    def test_sniff_missing_required_args(self, run_catnip):
        result = run_catnip("sniff")
        # Should ask for arguments or show error
        assert result.returncode != 0 or "Error" in result.stdout + result.stderr

"""
test_firmware_verifier.py
==========================
Behaviour of ``modules/core/firmware_verifier.py`` -- ``FirmwareVerifier``.

Focuses on ``detect()``, the open-ended "what firmware is running?" query
added to back ``catnip status`` (analisis-bombercat-vs-catnip.md, section 7):
unlike ``verify()``, it doesn't know the expected id up front, so it has to
fall back honestly to "none" instead of guessing. ``verify()``/
``verify_with_retries()`` already had indirect coverage via
``device_session``; this file gives the module one of its own.
"""

from unittest.mock import patch

import pytest

from modules.core.firmware_verifier import Confidence, FirmwareVerifier


@pytest.mark.unit
class TestDetect:
    def test_metadata_hit_reports_metadata_confidence(self):
        verifier = FirmwareVerifier(
            bridge_port="/dev/ttyACM0", shell_port="/dev/ttyACM2"
        )
        with patch.object(
            verifier, "_read_metadata_firmware_id", return_value="ti_sniffer"
        ):
            result = verifier.detect()

        assert result.firmware_id == "ti_sniffer"
        assert result.confidence == Confidence.METADATA
        assert bool(result) is True

    def test_no_metadata_falls_back_to_direct_communication(self):
        verifier = FirmwareVerifier(
            bridge_port="/dev/ttyACM0", shell_port="/dev/ttyACM2"
        )
        with patch.object(
            verifier, "_read_metadata_firmware_id", return_value=None
        ), patch.object(
            verifier, "verify_direct", side_effect=lambda fw_id: fw_id == "sniffle"
        ):
            result = verifier.detect()

        assert result.firmware_id == "sniffle"
        assert result.confidence == Confidence.DIRECT

    def test_nothing_confirmed_reports_none_honestly(self):
        """No metadata and no direct check succeeds -> unknown, not a guess."""
        verifier = FirmwareVerifier(
            bridge_port="/dev/ttyACM0", shell_port="/dev/ttyACM2"
        )
        with patch.object(
            verifier, "_read_metadata_firmware_id", return_value=None
        ), patch.object(verifier, "verify_direct", return_value=False):
            result = verifier.detect()

        assert result.firmware_id is None
        assert result.confidence == Confidence.NONE
        assert bool(result) is False

    def test_no_shell_port_skips_metadata_and_still_tries_direct(self):
        verifier = FirmwareVerifier(bridge_port="/dev/ttyACM0", shell_port=None)
        assert verifier._read_metadata_firmware_id() is None

        with patch.object(
            verifier, "verify_direct", side_effect=lambda fw_id: fw_id == "ti_sniffer"
        ):
            result = verifier.detect()

        assert result.firmware_id == "ti_sniffer"
        assert result.confidence == Confidence.DIRECT

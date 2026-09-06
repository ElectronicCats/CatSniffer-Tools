"""
test_output.py
===============
Tests for the error-reporting helpers added to ``modules/utils/output.py``
as part of the typed exception hierarchy work: ``print_error_panel``,
``print_success_panel``, and ``redact_secrets``.
"""

import pytest

from modules.utils import output


@pytest.mark.unit
class TestRedactSecrets:
    def test_redacts_json_style_psk(self):
        text = 'config: {"psk": "AQ=="}'
        result = output.redact_secrets(text)
        assert "AQ==" not in result
        assert '"psk": "(redacted)"' in result

    def test_redacts_key_value_password(self):
        result = output.redact_secrets("wifi password=hunter2 --ssid home")
        assert "hunter2" not in result
        assert "(redacted)" in result

    def test_redacts_case_insensitively(self):
        result = output.redact_secrets("TOKEN: abc123")
        assert "abc123" not in result

    def test_leaves_unrelated_text_untouched(self):
        text = "Failed to send identification command: timeout"
        assert output.redact_secrets(text) == text


@pytest.mark.unit
class TestErrorPanels:
    def test_print_error_panel_calls_console(self, monkeypatch):
        printed = []
        monkeypatch.setattr(output.console, "print", printed.append)

        output.print_error_panel(
            "DeviceError",
            "No device found",
            why="It was unplugged",
            fix=["Reconnect the device", "Run 'catnip devices'"],
            notes=["Only USB is supported"],
        )

        assert len(printed) == 1

    def test_print_success_panel_calls_console(self, monkeypatch):
        printed = []
        monkeypatch.setattr(output.console, "print", printed.append)

        output.print_success_panel("Done", "Firmware flashed successfully")

        assert len(printed) == 1


@pytest.mark.unit
class TestNextSteps:
    def test_prints_each_suggested_step(self, monkeypatch):
        printed = []
        monkeypatch.setattr(output.console, "print", printed.append)

        output.print_next_steps(["catnip sniff ble", "catnip verify"])

        joined = "\n".join(printed)
        assert "catnip sniff ble" in joined
        assert "catnip verify" in joined

    def test_no_steps_prints_nothing(self, monkeypatch):
        printed = []
        monkeypatch.setattr(output.console, "print", printed.append)

        output.print_next_steps([])

        assert printed == []


@pytest.mark.unit
class TestRefuseOverwrite:
    def test_missing_file_is_always_fine(self, tmp_path):
        target = tmp_path / "does_not_exist.raw"
        assert output.refuse_overwrite(str(target)) is True

    def test_warn_mode_never_blocks_but_warns(self, tmp_path, monkeypatch):
        target = tmp_path / "capture.raw"
        target.write_text("existing data")
        printed = []
        monkeypatch.setattr(
            output.console, "print", lambda *a, **kw: printed.append(a[0] if a else "")
        )

        assert output.refuse_overwrite(str(target)) is True
        assert any("already exists" in line for line in printed)

    def test_block_mode_refuses_without_force(self, tmp_path):
        target = tmp_path / "export.csv"
        target.write_text("existing data")

        assert output.refuse_overwrite(str(target), mode="block") is False

    def test_block_mode_allows_with_force(self, tmp_path):
        target = tmp_path / "export.csv"
        target.write_text("existing data")

        assert output.refuse_overwrite(str(target), force=True, mode="block") is True


@pytest.mark.unit
class TestCsvSafe:
    @pytest.mark.parametrize("value", ["=cmd()", "+1+1", "-1+1", "@SUM(A1)"])
    def test_prefixes_formula_looking_values(self, value):
        assert output.csv_safe(value) == f"'{value}"

    def test_leaves_plain_values_untouched(self):
        assert output.csv_safe("sniffle") == "sniffle"

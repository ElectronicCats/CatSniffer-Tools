"""
Smoke tests for the ``catnip spam`` Click group (Phase 3).

The device session and the serial controller are mocked, so these run without
hardware and only exercise the CLI wiring: option parsing, which firmware the
session requires, and which controller calls each subcommand makes.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from modules.core.exceptions import FeatureUnavailable
from modules.protocols.cli.ble_spam import spam
from modules.protocols.ble_spam import (
    PowerProfile,
    SpamMode,
    SpamStats,
    SpamStatus,
    parse_line,
)
from modules.protocols.ble_spam.live import SpamLiveView


@contextmanager
def _fake_session(*_args, **_kwargs):
    dev = MagicMock()
    dev.bridge_port = "/dev/ttyFAKE0"
    yield dev


def _patched(controller):
    """Patch device_session, Flasher and BleSpamController.open for a command."""
    return (
        patch("modules.core.device_session.device_session", _fake_session),
        patch("modules.firmware.flasher.Flasher", MagicMock()),
        patch(
            "modules.protocols.ble_spam.BleSpamController.open",
            return_value=controller,
        ),
    )


def _run(args, controller, **kwargs):
    p1, p2, p3 = _patched(controller)
    with p1, p2, p3:
        return CliRunner().invoke(spam, args, **kwargs)


@pytest.mark.unit
class TestSpamGroup:
    def test_help_lists_subcommands(self):
        result = CliRunner().invoke(spam, ["--help"])
        assert result.exit_code == 0
        for sub in ("start", "stop", "status", "modes", "pwr", "int", "stats", "scan"):
            assert sub in result.output

    def test_modes_needs_no_hardware(self):
        result = CliRunner().invoke(spam, ["modes"])
        assert result.exit_code == 0
        for mode in SpamMode:
            assert mode.token in result.output

    def test_start_selects_mode_and_starts_without_stopping(self):
        ctrl = MagicMock()
        ctrl.status.return_value = SpamStatus(SpamMode.APPLE, running=True, models=22)

        result = _run(["start", "--mode", "apple", "--yes"], ctrl)

        assert result.exit_code == 0, result.output
        ctrl.set_mode.assert_called_once_with(SpamMode.APPLE)
        ctrl.start.assert_called_once_with()
        # `start` must leave the hardware emitting: never stop, just close.
        ctrl.stop.assert_not_called()
        ctrl.close.assert_called_once_with()

    def test_status_does_not_stop_an_active_cycle(self):
        ctrl = MagicMock()
        ctrl.status.return_value = SpamStatus(SpamMode.ALL, running=True, models=82)

        result = _run(["status"], ctrl)

        assert result.exit_code == 0, result.output
        ctrl.status.assert_called_once()
        ctrl.stop.assert_not_called()
        ctrl.close.assert_called_once_with()

    def test_stop_sends_stop(self):
        ctrl = MagicMock()

        result = _run(["stop"], ctrl)

        assert result.exit_code == 0, result.output
        ctrl.stop.assert_called_once_with()
        ctrl.close.assert_called_once_with()

    def test_invalid_mode_is_rejected(self):
        result = CliRunner().invoke(spam, ["start", "--mode", "nope"])
        assert result.exit_code != 0
        assert "nope" in result.output

    def test_run_starts_and_always_stops_on_exit(self):
        ctrl = MagicMock()
        # A finite event stream ends the live loop cleanly.
        ctrl.read_events.return_value = iter([])

        result = _run(["run", "--mode", "apple", "--yes"], ctrl)

        assert result.exit_code == 0, result.output
        ctrl.set_mode.assert_called_once_with(SpamMode.APPLE)
        ctrl.start.assert_called_once_with()
        # R5: a live session must halt the hardware on exit.
        ctrl.stop.assert_called_once_with()
        ctrl.close.assert_called_once_with()

    def test_run_stops_on_keyboard_interrupt(self):
        ctrl = MagicMock()
        ctrl.read_events.side_effect = KeyboardInterrupt

        result = _run(["run", "--yes"], ctrl)

        assert result.exit_code == 0, result.output
        ctrl.stop.assert_called_once_with()
        ctrl.close.assert_called_once_with()

    def test_run_scan_on_enables_and_disables_scan(self):
        ctrl = MagicMock()
        ctrl.read_events.return_value = iter([])

        result = _run(["run", "--scan", "on", "--yes"], ctrl)

        assert result.exit_code == 0, result.output
        # Scan is enabled after start and turned back off on exit (R5).
        ctrl.set_scan.assert_any_call(True)
        ctrl.set_scan.assert_any_call(False)
        ctrl.stop.assert_called_once_with()
        ctrl.close.assert_called_once_with()

    def test_run_without_scan_never_toggles_scan(self):
        ctrl = MagicMock()
        ctrl.read_events.return_value = iter([])

        result = _run(["run", "--yes"], ctrl)

        assert result.exit_code == 0, result.output
        ctrl.set_scan.assert_not_called()

    def test_run_scan_on_unavailable_still_halts_hardware(self):
        ctrl = MagicMock()
        # A build without SPAM_WITH_SCAN raises when enabling the scan.
        ctrl.set_scan.side_effect = FeatureUnavailable("no scan in this build")

        result = _run(["run", "--scan", "on", "--yes"], ctrl)

        assert result.exit_code != 0
        # The live loop never ran, but the hardware is still stopped/closed (R5).
        ctrl.read_events.assert_not_called()
        ctrl.stop.assert_called_once_with()
        ctrl.close.assert_called_once_with()


@pytest.mark.unit
class TestSpamRuntimeControls:
    """Phase 3: pwr / int / stats / scan and the start/run profile options."""

    def test_pwr_sets_profile_without_stopping(self):
        ctrl = MagicMock()

        result = _run(["pwr", "low"], ctrl)

        assert result.exit_code == 0, result.output
        ctrl.set_power.assert_called_once_with(PowerProfile.LOW)
        # Changing the profile must not begin or stop emission.
        ctrl.start.assert_not_called()
        ctrl.stop.assert_not_called()
        ctrl.close.assert_called_once_with()

    def test_pwr_rejects_unknown_profile(self):
        result = CliRunner().invoke(spam, ["pwr", "turbo"])
        assert result.exit_code != 0
        assert "turbo" in result.output

    def test_int_sets_interval_without_stopping(self):
        ctrl = MagicMock()

        result = _run(["int", "40", "60"], ctrl)

        assert result.exit_code == 0, result.output
        # Fase 5: the CLI confirms the firmware accepted the interval.
        ctrl.set_interval.assert_called_once_with(40, 60, confirm=True)
        ctrl.stop.assert_not_called()
        ctrl.close.assert_called_once_with()

    def test_int_out_of_range_fails_without_touching_hardware(self):
        ctrl = MagicMock()

        result = _run(["int", "10", "20"], ctrl)

        assert result.exit_code != 0
        assert "out of range" in str(result.exception)
        # Rejected on the host before the port is opened.
        ctrl.set_interval.assert_not_called()

    def test_stats_prints_greppable_telemetry(self):
        ctrl = MagicMock()
        ctrl.stats.return_value = SpamStats(
            cycles=100,
            stack_used=612,
            stack_size=1024,
            heap_free=4096,
            heap_total=8192,
            power=PowerProfile.BALANCED,
            int_min=64,
            int_max=96,
        )

        result = _run(["stats"], ctrl)

        assert result.exit_code == 0, result.output
        ctrl.stats.assert_called_once()
        assert "cycles=100" in result.output
        assert "stack=612/1024" in result.output
        assert "heap=4096/8192" in result.output
        assert "pwr=bal" in result.output
        assert "int=64-96" in result.output
        ctrl.stop.assert_not_called()
        ctrl.close.assert_called_once_with()

    def test_scan_on_toggles_scan(self):
        ctrl = MagicMock()

        result = _run(["scan", "on"], ctrl)

        assert result.exit_code == 0, result.output
        ctrl.set_scan.assert_called_once_with(True)
        ctrl.close.assert_called_once_with()

    def test_scan_off_toggles_scan(self):
        ctrl = MagicMock()

        result = _run(["scan", "off"], ctrl)

        assert result.exit_code == 0, result.output
        ctrl.set_scan.assert_called_once_with(False)

    def test_scan_without_feature_surfaces_typed_error(self):
        ctrl = MagicMock()
        ctrl.set_scan.side_effect = FeatureUnavailable(
            "no scan", hint=["Rebuild with SPAM_WITH_SCAN=1"]
        )

        result = _run(["scan", "on"], ctrl)

        # main_cli renders FeatureUnavailable cleanly; here it just propagates.
        assert result.exit_code != 0
        assert isinstance(result.exception, FeatureUnavailable)
        ctrl.close.assert_called_once_with()

    def test_start_applies_power_and_interval_before_emitting(self):
        ctrl = MagicMock()
        ctrl.status.return_value = SpamStatus(
            SpamMode.APPLE,
            running=True,
            models=22,
            power=PowerProfile.HIGH,
            int_min=40,
            int_max=60,
        )

        result = _run(
            ["start", "-m", "apple", "-p", "high", "-i", "40", "60", "--yes"], ctrl
        )

        assert result.exit_code == 0, result.output
        ctrl.set_power.assert_called_once_with(PowerProfile.HIGH)
        ctrl.set_interval.assert_called_once_with(40, 60)
        ctrl.start.assert_called_once_with()
        ctrl.stop.assert_not_called()

    def test_start_rejects_out_of_range_interval_before_emitting(self):
        ctrl = MagicMock()

        result = _run(["start", "-m", "apple", "-i", "10", "20", "--yes"], ctrl)

        assert result.exit_code != 0
        assert "out of range" in str(result.exception)
        ctrl.start.assert_not_called()


@pytest.mark.unit
class TestAuthorisedUseBarrier:
    """Emission never begins without an explicit go-ahead (Phase 5)."""

    def test_start_aborts_when_confirmation_declined(self):
        ctrl = MagicMock()

        # No --yes and "n" at the prompt: the command must abort before any
        # controller call that would begin emitting.
        result = _run(["start", "--mode", "apple"], ctrl, input="n\n")

        assert result.exit_code != 0
        ctrl.set_mode.assert_not_called()
        ctrl.start.assert_not_called()

    def test_start_proceeds_when_confirmation_accepted(self):
        ctrl = MagicMock()
        ctrl.status.return_value = SpamStatus(SpamMode.APPLE, running=True, models=22)

        result = _run(["start", "--mode", "apple"], ctrl, input="y\n")

        assert result.exit_code == 0, result.output
        ctrl.start.assert_called_once_with()

    def test_yes_flag_skips_the_prompt(self):
        ctrl = MagicMock()
        ctrl.status.return_value = SpamStatus(SpamMode.APPLE, running=True, models=22)

        # --yes with no stdin available: must not block on a prompt.
        result = _run(["start", "--mode", "apple", "--yes"], ctrl)

        assert result.exit_code == 0, result.output
        ctrl.start.assert_called_once_with()
        assert "Proceed with BLE advertising spam?" not in result.output

    def test_run_aborts_when_confirmation_declined(self):
        ctrl = MagicMock()

        result = _run(["run", "--mode", "apple"], ctrl, input="n\n")

        assert result.exit_code != 0
        ctrl.start.assert_not_called()
        ctrl.read_events.assert_not_called()


@pytest.mark.unit
class TestSpamLiveView:
    def test_folds_cycle_status_stats_and_error(self):
        view = SpamLiveView(SpamMode.APPLE)

        view.update(parse_line("SPAM: model Apple AirPods 1 (1/22)"))
        view.update(parse_line("SPAM: addr fc:99:ae:e0:7c:8b"))
        view.update(parse_line("SPAM: Beats Solo Pro (9/22)"))
        view.update(parse_line("SPAM: cycles=100"))
        view.update(parse_line("SPAM: mode=APPLE running=1 models=22"))
        view.update(parse_line("ERR: TRNG unavailable, fixed seed used"))

        assert view.mode is SpamMode.APPLE
        assert view.models == 22
        assert view.adverts == 2
        assert view.current_model == "Beats Solo Pro"
        assert (view.index, view.total) == (9, 22)
        assert view.cycles == 100
        assert view.addr == "fc:99:ae:e0:7c:8b"
        assert "TRNG" in view.last_error
        # Rendering must not raise with a fully populated view.
        assert view.render() is not None

    def test_renders_before_any_event(self):
        view = SpamLiveView(SpamMode.ALL)
        assert view.render() is not None

    def test_folds_telemetry_from_stats_line(self):
        view = SpamLiveView(SpamMode.APPLE)

        view.update(
            parse_line(
                "STATS: cycles=100 stack=320/1024 run=1 pwr=low int=128-160 "
                "heap=8192/16384"
            )
        )

        assert view.cycles == 100
        assert (view.stack_used, view.stack_size) == (320, 1024)
        assert (view.heap_free, view.heap_total) == (8192, 16384)
        assert view.power is PowerProfile.LOW
        assert (view.int_min, view.int_max) == (128, 160)
        assert view.render() is not None

    def test_folds_power_and_interval_from_extended_status(self):
        view = SpamLiveView(SpamMode.ALL)

        view.update(
            parse_line("SPAM: mode=APPLE running=1 models=22 rot=on pwr=bal int=64-96")
        )

        assert view.mode is SpamMode.APPLE
        assert view.power is PowerProfile.BALANCED
        assert (view.int_min, view.int_max) == (64, 96)

    def test_warn_flags_stack_and_renders_red(self):
        view = SpamLiveView(SpamMode.ALL)
        assert view.stack_warn is False

        view.update(parse_line("WARN: stack low 950/1024 B (>=80%)"))

        assert view.stack_warn is True
        assert view.render() is not None

    def test_scan_reports_feed_the_secondary_table(self):
        view = SpamLiveView(SpamMode.ALL)

        view.update(parse_line("SCAN: on (passive 160/80)"))  # state: not a report
        view.update(parse_line("SCAN: aa:bb:cc:dd:ee:ff rssi=-40 len=31"))
        view.update(parse_line("SCAN: 11:22:33:44:55:66 rssi=-72 len=20"))

        assert view.scan_reports == 2
        # Newest first.
        assert view.scan_recent[0][0] == "11:22:33:44:55:66"
        assert view.render() is not None

    def test_scan_feed_is_bounded(self):
        from modules.protocols.ble_spam.live import SCAN_FEED_MAX

        view = SpamLiveView(SpamMode.ALL)
        for i in range(SCAN_FEED_MAX + 5):
            view.update(parse_line(f"SCAN: aa:bb:cc:dd:ee:{i:02x} rssi=-{i} len=10"))

        assert view.scan_reports == SCAN_FEED_MAX + 5
        assert len(view.scan_recent) == SCAN_FEED_MAX


@pytest.mark.unit
class TestSpamCompletion:
    """Phase 6: shell tab-completion reaches ``spam`` and its modes.

    Completion is Click-native (the group is registered on the root and
    ``--mode`` is a ``click.Choice``), so there is no hand-written list to
    drift. These tests lock that in so a future refactor cannot silently drop
    ``spam`` or a mode from what users get on <TAB>.
    """

    def _completions(self, args, incomplete):
        from click.shell_completion import ShellComplete
        from modules.core.cli import build_cli

        sc = ShellComplete(build_cli(), {}, "catnip", "_CATNIP_COMPLETE")
        return [c.value for c in sc.get_completions(args, incomplete)]

    def test_spam_completes_at_root(self):
        assert "spam" in self._completions(["catnip"], "sp")

    def test_spam_subcommands_complete(self):
        subs = self._completions(["spam"], "")
        # Base commands and the hardened-firmware runtime controls all appear.
        assert {
            "modes",
            "run",
            "start",
            "status",
            "stop",
            "pwr",
            "int",
            "stats",
            "scan",
        } <= set(subs)

    def test_modes_complete_for_the_mode_option(self):
        modes = self._completions(["spam", "start", "--mode"], "")
        assert sorted(modes) == sorted(m.token for m in SpamMode)

    def test_power_profiles_complete_for_the_power_option(self):
        # click.Choice completes itself; lock the profiles in for --power and pwr.
        assert sorted(self._completions(["spam", "start", "--power"], "")) == [
            "bal",
            "high",
            "low",
        ]
        assert sorted(self._completions(["spam", "pwr"], "")) == ["bal", "high", "low"]

    def test_scan_states_complete_for_the_scan_argument(self):
        assert sorted(self._completions(["spam", "scan"], "")) == ["off", "on"]
        assert sorted(self._completions(["spam", "run", "--scan"], "")) == [
            "off",
            "on",
        ]

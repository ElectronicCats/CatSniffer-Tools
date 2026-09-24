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

from modules.protocols.cli.ble_spam import spam
from modules.protocols.ble_spam import SpamMode, SpamStatus, parse_line
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
        for sub in ("start", "stop", "status", "modes"):
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
        assert {"modes", "run", "start", "status", "stop"} <= set(subs)

    def test_modes_complete_for_the_mode_option(self):
        modes = self._completions(["spam", "start", "--mode"], "")
        assert sorted(modes) == sorted(m.token for m in SpamMode)

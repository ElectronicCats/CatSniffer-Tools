"""``catnip spam`` — BLE advertising-spam control (CC1352P7 firmware).

Host-side front end for the ``ble_spam_cc1352p_7`` firmware. Each subcommand
opens the CatSniffer bridge port, speaks the firmware's short line protocol
(see :mod:`modules.protocols.ble_spam`) and returns.

Responsible use: this drives a firmware that emits BLE advertising frames to
provoke pairing dialogs on nearby devices. It is a security-research / pentest
tool — use it only on devices you own or are explicitly authorised to test. No
new offensive capability is added here; the control the firmware already exposes
over UART is simply surfaced on the CLI, exactly as the CLI already does for the
AirTag and JustWorks firmwares.
"""

# External
import click

# Internal (lightweight; heavy backend is imported lazily inside each command)
from ...utils.cli_options import device_option
from ...utils.output import print_info, print_success, print_warning

# Must match ALIAS_TO_OFFICIAL_ID / the registry entry in firmware_registry.py.
OFFICIAL_ID = "ble_spam_cc1352p_7"

_MODE_CHOICE = ["all", "apple", "android", "windows", "samsung"]
# Firmware TX-power/interval profiles (`pwr high|bal|low`). Matches PowerProfile.
_POWER_CHOICE = ["high", "bal", "low"]
_SCAN_CHOICE = ["on", "off"]

_AUTH_WARNING = (
    "Emitting BLE advertising frames — use only on devices you own or are "
    "authorised to test."
)


def _yes_option():
    """``-y/--yes``: skip the authorised-use confirmation (for scripting)."""
    return click.option(
        "-y",
        "--yes",
        is_flag=True,
        default=False,
        help="Skip the authorised-use confirmation prompt.",
    )


def _baudrate_option():
    """``-b/--baudrate``: override the bridge baudrate (mirrors the inline one)."""
    return click.option(
        "-b",
        "--baudrate",
        type=int,
        default=None,
        help="Override the bridge baudrate (default: firmware value, 921600).",
    )


def _power_option():
    """``-p/--power``: pin a TX-power/interval profile at start."""
    return click.option(
        "-p",
        "--power",
        type=click.Choice(_POWER_CHOICE),
        default=None,
        help="TX-power/interval profile to apply before emitting.",
    )


def _interval_option():
    """``-i/--interval MIN MAX``: pin the advertising interval at start (0.625 ms units)."""
    return click.option(
        "-i",
        "--interval",
        type=int,
        nargs=2,
        default=None,
        metavar="MIN MAX",
        help="Advertising interval in 0.625 ms units (32..16384), e.g. -i 40 60.",
    )


def _scan_option():
    """``-s/--scan on|off``: enable the passive GAP scan feed during ``run``."""
    return click.option(
        "-s",
        "--scan",
        type=click.Choice(_SCAN_CHOICE),
        default=None,
        help="Enable the passive scan feed in the live view (needs SPAM_WITH_SCAN).",
    )


def _confirm_authorised(yes: bool) -> None:
    """Warn about authorised use and, unless *yes*, require confirmation.

    Mirrors the responsible-use barrier the CLI applies before other emitting
    actions. Declining raises ``click.Abort`` (exit 130), so the firmware is
    never started without an explicit go-ahead; ``--yes`` skips the prompt so
    the command stays scriptable.
    """
    print_warning(_AUTH_WARNING)
    if not yes:
        click.confirm("Proceed with BLE advertising spam?", abort=True)


def _print_status(status) -> None:
    """Print a :class:`SpamStatus` in a uniform, greppable form.

    The hardened firmware fills ``power``/``int_min``/``int_max``; against the
    base firmware they are ``None`` and simply omitted, so the line never breaks.
    """
    state = "running" if status.running else "stopped"
    parts = [f"mode={status.mode.token}", f"state={state}", f"models={status.models}"]
    if status.power is not None:
        parts.append(f"pwr={status.power.value}")
    if status.int_min is not None and status.int_max is not None:
        parts.append(f"int={status.int_min}-{status.int_max}")
    print_info(" ".join(parts))


def _apply_profile(ctrl, power, interval) -> None:
    """Apply optional ``--power`` / ``--interval`` on *ctrl* before starting.

    Shared by ``start`` and ``run``. ``interval`` is a ``(min, max)`` pair or
    ``None``; the controller re-validates it in the firmware's own domain.
    """
    from ...protocols.ble_spam import PowerProfile

    if power is not None:
        ctrl.set_power(PowerProfile.from_str(power))
    if interval is not None:
        ctrl.set_interval(interval[0], interval[1])


@click.group("spam", context_settings={"help_option_names": ["-h", "--help"]})
def spam():
    """BLE advertising-spam control (CC1352P7 'ble_spam' firmware).

    \b
    Examples:
        catnip spam modes                     # list vendor modes (no hardware)
        catnip spam start --mode apple        # select Apple mode and emit
        catnip spam start -m apple -p low     # ... at the low-power profile
        catnip spam run --mode apple          # emit with a live view (Ctrl+C)
        catnip spam status                    # mode / running / model count
        catnip spam pwr low                   # switch TX-power/interval profile
        catnip spam int 40 60                 # override interval (0.625 ms units)
        catnip spam stats                     # on-demand resource telemetry
        catnip spam scan on                   # passive GAP coexistence scan
        catnip spam stop                      # stop emitting

    Use only on devices you own or are authorised to test.
    """
    pass


@spam.command("modes")
def spam_modes():
    """List the available vendor modes (no device needed)."""
    from ...protocols.ble_spam import SpamMode

    print_info("Available spam modes:")
    for mode in SpamMode:
        click.echo(f"  {mode.token:<8} ({mode.short})")


@spam.command("start")
@device_option()
@click.option(
    "-m",
    "--mode",
    type=click.Choice(_MODE_CHOICE),
    default="all",
    show_default=True,
    help="Vendor advertising set to emit.",
)
@_baudrate_option()
@_power_option()
@_interval_option()
@_yes_option()
def spam_start(device, mode, baudrate, power, interval, yes):
    """Select a mode and start emitting.

    Leaves the firmware emitting after the command returns; run
    ``catnip spam stop`` to halt it. ``--power`` and ``--interval`` pin the
    profile/interval before emission begins.
    """
    from ...core.device_session import device_session
    from ...firmware.flasher import Flasher
    from ...protocols.ble_spam import (
        BAUDRATE,
        BleSpamController,
        SpamMode,
        validate_interval,
    )

    # Fail fast, before any confirmation or port open, on a bad interval.
    if interval is not None:
        validate_interval(interval[0], interval[1])

    _confirm_authorised(yes)

    with device_session(
        device,
        required_firmware=OFFICIAL_ID,
        feature="catnip spam",
        flasher=Flasher(),
        identify=False,
    ) as dev:
        # NOTE: no context manager here — its __exit__ sends `stop`, and `start`
        # must leave the hardware emitting. We close the port without stopping.
        ctrl = BleSpamController.open(dev.bridge_port, baudrate=baudrate or BAUDRATE)
        try:
            ctrl.set_mode(SpamMode.from_str(mode))
            _apply_profile(ctrl, power, interval)
            ctrl.start()
            print_success(f"Started BLE spam (mode={mode}).")
            _print_status(ctrl.status())
        finally:
            ctrl.close()


@spam.command("run")
@device_option()
@click.option(
    "-m",
    "--mode",
    type=click.Choice(_MODE_CHOICE),
    default="all",
    show_default=True,
    help="Vendor advertising set to emit.",
)
@_baudrate_option()
@_power_option()
@_interval_option()
@_scan_option()
@_yes_option()
def spam_run(device, mode, baudrate, power, interval, scan, yes):
    """Start emitting and show a live view of the cycle (Ctrl+C to stop).

    Unlike ``start``, this is an interactive session: it always stops the
    firmware and closes the port on exit, so the hardware is never left emitting.
    ``--power`` and ``--interval`` pin the profile/interval before emission;
    ``--scan on`` enables the passive-scan feed in the live view (needs a firmware
    built with ``SPAM_WITH_SCAN=1``).
    """
    from ...core.device_session import device_session
    from ...firmware.flasher import Flasher
    from ...protocols.ble_spam import (
        BAUDRATE,
        BleSpamController,
        SpamMode,
        validate_interval,
    )
    from ...protocols.ble_spam.live import run_live

    if interval is not None:
        validate_interval(interval[0], interval[1])

    _confirm_authorised(yes)

    selected = SpamMode.from_str(mode)
    with device_session(
        device,
        required_firmware=OFFICIAL_ID,
        feature="catnip spam",
        flasher=Flasher(),
        identify=False,
    ) as dev:
        ctrl = BleSpamController.open(dev.bridge_port, baudrate=baudrate or BAUDRATE)
        try:
            ctrl.set_mode(selected)
            _apply_profile(ctrl, power, interval)
            ctrl.start()
            if scan == "on":
                # FeatureUnavailable (no SPAM_WITH_SCAN) propagates to main_cli;
                # the finally below still halts the hardware first (R5).
                ctrl.set_scan(True)
            print_info(f"Live view (mode={mode}) — Ctrl+C to stop.")
            run_live(ctrl, selected)
        except KeyboardInterrupt:
            pass
        finally:
            # R5: a live session always leaves the hardware halted, even if the
            # loop raised. Turn scan off (best-effort), stop, then close, and
            # never let any of them mask the others.
            if scan == "on":
                try:
                    ctrl.set_scan(False)
                except Exception:
                    pass
            try:
                ctrl.stop()
            except Exception:
                pass
            ctrl.close()
            print_success("Stopped BLE spam.")


@spam.command("stop")
@device_option()
@click.option(
    "-b",
    "--baudrate",
    type=int,
    default=None,
    help="Override the bridge baudrate (default: firmware value, 921600).",
)
def spam_stop(device, baudrate):
    """Stop emitting."""
    from ...core.device_session import device_session
    from ...firmware.flasher import Flasher
    from ...protocols.ble_spam import BAUDRATE, BleSpamController

    with device_session(
        device,
        required_firmware=OFFICIAL_ID,
        feature="catnip spam",
        flasher=Flasher(),
        identify=False,
    ) as dev:
        ctrl = BleSpamController.open(dev.bridge_port, baudrate=baudrate or BAUDRATE)
        try:
            ctrl.stop()
            print_success("Stopped BLE spam.")
        finally:
            ctrl.close()


@spam.command("status")
@device_option()
@click.option(
    "-b",
    "--baudrate",
    type=int,
    default=None,
    help="Override the bridge baudrate (default: firmware value, 921600).",
)
def spam_status(device, baudrate):
    """Report the current mode, running state and model count."""
    from ...core.device_session import device_session
    from ...firmware.flasher import Flasher
    from ...protocols.ble_spam import BAUDRATE, BleSpamController

    with device_session(
        device,
        required_firmware=OFFICIAL_ID,
        feature="catnip spam",
        flasher=Flasher(),
        identify=False,
    ) as dev:
        # No context manager: querying status must not stop an active cycle.
        ctrl = BleSpamController.open(dev.bridge_port, baudrate=baudrate or BAUDRATE)
        try:
            _print_status(ctrl.status())
        finally:
            ctrl.close()


@spam.command("pwr")
@click.argument("profile", type=click.Choice(_POWER_CHOICE))
@device_option()
@_baudrate_option()
def spam_pwr(profile, device, baudrate):
    """Select a TX-power/interval profile (high|bal|low).

    Applies to a running or idle cycle; it does not begin new emission, so it
    needs no authorised-use confirmation. The coupled interval is echoed by
    ``catnip spam status``/``stats``.
    """
    from ...core.device_session import device_session
    from ...firmware.flasher import Flasher
    from ...protocols.ble_spam import (
        BAUDRATE,
        BleSpamController,
        PowerProfile,
    )

    with device_session(
        device,
        required_firmware=OFFICIAL_ID,
        feature="catnip spam",
        flasher=Flasher(),
        identify=False,
    ) as dev:
        # No context manager: changing the profile must not stop an active cycle.
        ctrl = BleSpamController.open(dev.bridge_port, baudrate=baudrate or BAUDRATE)
        try:
            ctrl.set_power(PowerProfile.from_str(profile))
            print_success(f"Power profile set to {profile}.")
        finally:
            ctrl.close()


@spam.command("int")
@click.argument("minimum", type=int)
@click.argument("maximum", type=int)
@device_option()
@_baudrate_option()
def spam_int(minimum, maximum, device, baudrate):
    """Override the advertising interval: MIN MAX in 0.625 ms units.

    \b
    Units are the firmware's raw 0.625 ms ticks; valid range is 32..16384
    (20 ms..10.24 s), with MIN <= MAX. Example:
        catnip spam int 40 60      # 25 ms .. 37.5 ms

    The range is checked on the host *before* the port is opened, so a bad
    interval fails immediately without touching hardware.
    """
    from ...core.device_session import device_session
    from ...firmware.flasher import Flasher
    from ...protocols.ble_spam import BAUDRATE, BleSpamController, validate_interval

    # D-C3/R4: validate in the firmware's domain before opening the port.
    validate_interval(minimum, maximum)

    with device_session(
        device,
        required_firmware=OFFICIAL_ID,
        feature="catnip spam",
        flasher=Flasher(),
        identify=False,
    ) as dev:
        # No context manager: setting the interval must not stop an active cycle.
        ctrl = BleSpamController.open(dev.bridge_port, baudrate=baudrate or BAUDRATE)
        try:
            ctrl.set_interval(minimum, maximum)
            print_success(f"Interval set to {minimum}-{maximum} (x0.625 ms).")
        finally:
            ctrl.close()


@spam.command("stats")
@device_option()
@_baudrate_option()
def spam_stats(device, baudrate):
    """Report on-demand resource telemetry (hardened firmware).

    Prints a greppable line: cycles, stack used/size, free/total heap and the
    active power profile / interval.
    """
    from ...core.device_session import device_session
    from ...firmware.flasher import Flasher
    from ...protocols.ble_spam import BAUDRATE, BleSpamController

    with device_session(
        device,
        required_firmware=OFFICIAL_ID,
        feature="catnip spam",
        flasher=Flasher(),
        identify=False,
    ) as dev:
        # No context manager: telemetry must not stop an active cycle.
        ctrl = BleSpamController.open(dev.bridge_port, baudrate=baudrate or BAUDRATE)
        try:
            s = ctrl.stats()
            parts = [
                f"cycles={s.cycles}",
                f"stack={s.stack_used}/{s.stack_size}",
                f"heap={s.heap_free}/{s.heap_total}",
            ]
            if s.power is not None:
                parts.append(f"pwr={s.power.value}")
            if s.int_min is not None and s.int_max is not None:
                parts.append(f"int={s.int_min}-{s.int_max}")
            print_info(" ".join(parts))
        finally:
            ctrl.close()


@spam.command("scan")
@click.argument("state", type=click.Choice(_SCAN_CHOICE))
@device_option()
@_baudrate_option()
def spam_scan(state, device, baudrate):
    """Toggle the passive GAP coexistence scan (on|off).

    Only available in a firmware image built with ``SPAM_WITH_SCAN=1``. On a
    build without it the command reports a clear error (rebuild/reflash) and
    exits non-zero — no traceback unless ``CATNIP_DEBUG=1``.
    """
    from ...core.device_session import device_session
    from ...firmware.flasher import Flasher
    from ...protocols.ble_spam import BAUDRATE, BleSpamController

    with device_session(
        device,
        required_firmware=OFFICIAL_ID,
        feature="catnip spam",
        flasher=Flasher(),
        identify=False,
    ) as dev:
        # No context manager: toggling scan must not stop an active cycle.
        ctrl = BleSpamController.open(dev.bridge_port, baudrate=baudrate or BAUDRATE)
        try:
            # FeatureUnavailable (no SPAM_WITH_SCAN) propagates to main_cli, which
            # renders it as a clean actionable panel with a non-zero exit code.
            ctrl.set_scan(state == "on")
            print_success(f"Scan {state}.")
        finally:
            ctrl.close()

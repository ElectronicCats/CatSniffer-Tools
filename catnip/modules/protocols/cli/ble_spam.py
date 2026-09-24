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


def _print_status(status) -> None:
    """Print a :class:`SpamStatus` in a uniform, greppable form."""
    state = "running" if status.running else "stopped"
    print_info(
        f"mode={status.mode.token} state={state} models={status.models}"
    )


@click.group("spam", context_settings={"help_option_names": ["-h", "--help"]})
def spam():
    """BLE advertising-spam control (CC1352P7 'ble_spam' firmware).

    \b
    Examples:
        catnip spam modes                     # list vendor modes (no hardware)
        catnip spam start --mode apple        # select Apple mode and emit
        catnip spam run --mode apple          # emit with a live view (Ctrl+C)
        catnip spam status                    # mode / running / model count
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
@click.option(
    "-b",
    "--baudrate",
    type=int,
    default=None,
    help="Override the bridge baudrate (default: firmware value, 921600).",
)
def spam_start(device, mode, baudrate):
    """Select a mode and start emitting.

    Leaves the firmware emitting after the command returns; run
    ``catnip spam stop`` to halt it.
    """
    from ...core.device_session import device_session
    from ...firmware.flasher import Flasher
    from ...protocols.ble_spam import BAUDRATE, BleSpamController, SpamMode

    print_warning(
        "Emitting BLE advertising frames — use only on devices you own or are "
        "authorised to test."
    )

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
@click.option(
    "-b",
    "--baudrate",
    type=int,
    default=None,
    help="Override the bridge baudrate (default: firmware value, 921600).",
)
def spam_run(device, mode, baudrate):
    """Start emitting and show a live view of the cycle (Ctrl+C to stop).

    Unlike ``start``, this is an interactive session: it always stops the
    firmware and closes the port on exit, so the hardware is never left emitting.
    """
    from ...core.device_session import device_session
    from ...firmware.flasher import Flasher
    from ...protocols.ble_spam import BAUDRATE, BleSpamController, SpamMode
    from ...protocols.ble_spam.live import run_live

    print_warning(
        "Emitting BLE advertising frames — use only on devices you own or are "
        "authorised to test."
    )

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
            ctrl.start()
            print_info(f"Live view (mode={mode}) — Ctrl+C to stop.")
            run_live(ctrl, selected)
        except KeyboardInterrupt:
            pass
        finally:
            # R5: a live session always leaves the hardware halted, even if the
            # loop raised. Stop first, then close, and never let either mask the
            # other.
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

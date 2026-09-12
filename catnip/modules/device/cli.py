"""``catnip devices|identify`` - device discovery and identification.

Registered one by one on the root group (they are not a Click group), see
section 3.2 of ``CLI_REFACTOR_PLAN.md``.
"""

# Internal
from ..core.catnip import catnip_get_devices
from ..core.device_utils import get_device_or_exit
from ..core.exceptions import ConnectionError as CatnipConnectionError, DeviceError
from ..core.firmware_registry import get_firmware, next_steps_for
from ..core.firmware_verifier import FirmwareVerifier
from ..core.usb_connection import ShellConnection, CATSNIFFER_VID, CATSNIFFER_PID
from ..firmware.board import capability_rows, detect_board
from ..firmware.fw_status import read_status, read_radio_configs

# External
import click
from rich.table import Table
from rich import box

from ..utils.cli_options import device_option
from ..utils.output import (
    console,
    STYLES,
    print_success,
    print_warning,
    print_info,
    print_empty_line,
    print_next_steps,
)


@click.command()
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Show raw USB port info for each interface (useful for diagnosing Windows port mapping).",
)
def devices(debug: bool) -> None:
    """List connected CatSniffer devices"""
    devs = catnip_get_devices()
    if not devs:
        print_warning("No CatSniffer devices found.")
        if debug:
            _print_raw_port_debug()
        return

    # Add a table to display devices
    table = Table(title=f"Found {len(devs)} CatSniffer device(s)", box=box.ROUNDED)
    table.add_column("Device", style=STYLES["device"], justify="left")
    table.add_column("Board", style="magenta", justify="left")
    table.add_column("Cat-Bridge (CC1352)", style="cyan", justify="left")
    table.add_column("Cat-LoRa (SX1262)", style="cyan", justify="left")
    table.add_column("Cat-Shell (Config)", style="cyan", justify="left")

    for dev in devs:
        bridge_status = dev.bridge_port or "[red]Not found[/red]"
        lora_status = dev.lora_port or "[red]Not found[/red]"
        shell_status = dev.shell_port or "[red]Not found[/red]"
        board = detect_board(dev.shell_port)
        board_status = board.label if board else "[yellow]unknown[/yellow]"

        table.add_row(str(dev), board_status, bridge_status, lora_status, shell_status)

    print_empty_line()
    console.print(table)

    if debug:
        _print_raw_port_debug()


def _print_raw_port_debug() -> None:
    """Print raw pyserial port info for all CatSniffer interfaces."""
    from serial.tools import list_ports

    cat_ports = [
        p
        for p in list_ports.comports()
        if p.vid == CATSNIFFER_VID and p.pid == CATSNIFFER_PID
    ]

    if not cat_ports:
        console.print("[red]No CatSniffer USB interfaces visible to pyserial.[/red]")
        return

    raw = Table(title="Raw USB port info (debug)", box=box.SIMPLE)
    raw.add_column("Port", style="cyan")
    raw.add_column("Description")
    raw.add_column("HWID")
    raw.add_column("Location")
    raw.add_column("Interface")
    raw.add_column("Serial#")

    for p in sorted(cat_ports, key=lambda x: x.device):
        raw.add_row(
            p.device,
            p.description or "",
            p.hwid or "",
            p.location or "",
            getattr(p, "interface", None) or "",
            p.serial_number or "",
        )

    console.print(raw)


@click.command()
@device_option()
def identify(device) -> None:
    """Send identification command to CatSniffer device"""
    dev = get_device_or_exit(device)

    if not dev.shell_port:
        raise DeviceError(
            "Shell port not available for this device!",
            hint=["Run 'catnip devices' to confirm all three ports were detected."],
        )

    print_info(f"Sending 'Identify' command to {dev} on port {dev.shell_port}...")

    try:
        shell = ShellConnection(port=dev.shell_port, timeout=1.0)
        with shell:
            response = shell.send_command("identify", timeout=1.0)
            if response:
                print_info(f"Response: {response}")

        print_success("Identification command sent successfully!")

    except Exception as e:
        raise CatnipConnectionError(
            f"Failed to send identification command: {e}",
            hint=[
                "Check that no other program (e.g. a serial monitor) has the port open.",
                f"Verify the shell port is still {dev.shell_port} with 'catnip devices'.",
                "Re-run with CATNIP_DEBUG=1 for the full traceback.",
            ],
        ) from e


# A stack this close to full is worth flagging: the SAMD21 build sizes its
# threads by hand against a 16 KB budget (SAMD21/catsniffer/prj.conf), so the
# headroom left is the number that says how near an overflow the board is.
_LOW_STACK_BYTES = 96


def _diagnostics_table(shell_status) -> Table:
    """The firmware's own health counters, as far as this board reports them.

    The SAMD21 build adds stack headroom, the last fault and a per-thread
    dump; the RP2040 build reports only the two loss counters. Rows are added
    for what is present, so neither firmware needs a branch here.
    """
    table = Table(title="Firmware diagnostics", box=box.ROUNDED)
    table.add_column("Field", style=STYLES["device"], justify="left")
    table.add_column("Value", justify="left")

    for label in ("FW", "Radio", "LoRa", "LoRa Mode", "CC1352 FW"):
        if label in shell_status.fields:
            table.add_row(label, shell_status.fields[label])

    for name, value in shell_status.counters.items():
        style = "" if value == 0 else "yellow"
        # ring_dropped is the only one counted in bytes; uart_overrun and
        # dma_regress are event counts, so the unit is not shared.
        reading = f"{value} bytes" if name == "ring_dropped" else str(value)
        table.add_row(
            f"loss: {name}", f"[{style}]{reading}[/{style}]" if style else reading
        )

    for name, unused in shell_status.stacks.items():
        low = unused < _LOW_STACK_BYTES
        table.add_row(
            f"stack unused: {name}",
            f"[red]{unused} bytes[/red]" if low else f"{unused} bytes",
        )

    if shell_status.last_fault is not None:
        clean = shell_status.last_fault.lower() == "none"
        table.add_row(
            "Last fault",
            (
                shell_status.last_fault
                if clean
                else f"[red]{shell_status.last_fault}[/red]"
            ),
        )
    if shell_status.threads:
        table.add_row("Threads", str(len(shell_status.threads)))
    return table


def _radio_config_table(lora_config, fsk_config) -> Table:
    """The SX1262's cached LoRa and FSK parameters, straight from the firmware.

    Shown side by side regardless of which modulation is currently active:
    a capture that comes up silent is often just a previous session of the
    *other* modulation that never switched back.
    """
    table = Table(title="Radio configuration (SX1262)", box=box.ROUNDED)
    table.add_column("Modulation", style=STYLES["device"], justify="left")
    table.add_column("Cached config", justify="left")
    table.add_row("LoRa", lora_config or "[yellow]no response[/yellow]")
    table.add_row("FSK", fsk_config or "[yellow]no response[/yellow]")
    return table


@click.command()
@device_option()
@click.option(
    "--diagnostics",
    "-D",
    is_flag=True,
    help="Also dump the per-thread stack report and the trace ring "
    "(only v2 boards report them)",
)
def status(device, diagnostics) -> None:
    """Show board, firmware and capabilities detected on a CatSniffer.

    Honest by design (Bombercat's `status` pattern, see
    analisis-bombercat-vs-catnip.md, section 7): unlike `sniff`/`flash`,
    which check for *one specific* firmware and flash it if missing, this
    only reports what it can actually confirm on the device right now, and
    says "unknown" rather than guessing.

    \b
    Examples:
        catnip status                 # first connected device
        catnip status --device 1      # a specific device by ID
        catnip status --diagnostics   # add the v2 stack/thread dump
    """
    dev = get_device_or_exit(device)
    board = detect_board(dev.shell_port)
    shell_status = read_status(dev.shell_port)
    detection = FirmwareVerifier(dev.bridge_port, dev.shell_port).detect()
    entry = get_firmware(detection.firmware_id) if detection.firmware_id else None

    table = Table(title=f"Status for {dev}", box=box.ROUNDED)
    table.add_column("Field", style=STYLES["device"], justify="left")
    table.add_column("Value", justify="left")
    table.add_row("Board", board.label if board else "[yellow]unknown[/yellow]")
    table.add_row("Bridge port (CC1352)", dev.bridge_port or "[red]not found[/red]")
    table.add_row("LoRa port (SX1262)", dev.lora_port or "[red]not found[/red]")
    table.add_row("Shell port (Config)", dev.shell_port or "[red]not found[/red]")
    if entry is not None:
        table.add_row("Firmware", f"{entry.display} ({entry.id})")
        table.add_row("Detected via", detection.confidence.value)
        table.add_row("Capabilities", ", ".join(sorted(entry.capabilities)) or "-")
    else:
        table.add_row("Firmware", "[yellow]unknown[/yellow]")

    # Why a feature is or is not available on this board, stated up front
    # instead of only when a command refuses (see PLAN_SOPORTE_V2.md, T-08).
    rows = capability_rows(board)
    if rows:
        table.add_row(
            "Board can",
            "\n".join(
                (
                    f"[green]yes[/green]  {label}"
                    if supported
                    else f"[yellow]no [/yellow]  {label}"
                )
                for label, supported in rows
            ),
        )

    print_empty_line()
    console.print(table)

    if shell_status is not None:
        print_empty_line()
        console.print(_diagnostics_table(shell_status))

        tightest = shell_status.tightest_stack
        if tightest is not None and tightest[1] < _LOW_STACK_BYTES:
            print_warning(
                f"Tightest stack ({tightest[0]}) has {tightest[1]} bytes left; "
                "this board is close to a stack overflow."
            )

        if diagnostics:
            if shell_status.trace:
                print_empty_line()
                print_info(shell_status.trace)
            for thread in shell_status.threads:
                print_info(
                    f"thread {thread.ident} prio={thread.priority} "
                    f"stack={thread.stack} unused={thread.unused}"
                )
            for line in shell_status.unparsed:
                # A firmware line this version does not know about: showing it
                # verbatim beats dropping it.
                print_info(line)
        elif shell_status.has_diagnostics:
            print_info("Run with --diagnostics for the per-thread stack report.")

    lora_config, fsk_config = read_radio_configs(dev.shell_port)
    if lora_config or fsk_config:
        print_empty_line()
        console.print(_radio_config_table(lora_config, fsk_config))

    print_next_steps(
        next_steps_for(entry) if entry is not None else ["catnip flash --list"]
    )

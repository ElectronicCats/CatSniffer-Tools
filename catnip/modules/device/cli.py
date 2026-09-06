"""``catnip devices|identify`` - device discovery and identification.

Registered one by one on the root group (they are not a Click group), see
section 3.2 of ``CLI_REFACTOR_PLAN.md``.
"""

# Internal
from ..core.catnip import catnip_get_devices
from ..core.device_utils import get_device_or_exit
from ..core.exceptions import ConnectionError as CatnipConnectionError, DeviceError
from ..core.usb_connection import ShellConnection, CATSNIFFER_VID, CATSNIFFER_PID
from ..firmware.board import detect_board

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

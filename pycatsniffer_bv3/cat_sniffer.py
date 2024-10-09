import binascii
import signal
import sys
import platform
import enum

try:
    import typer
    import serial
    from rich.console import Console
    from rich.table import Table
except ImportError:
    print("\x1b[31;1mError: The required library's is not installed.\x1b[0m")
    print(
        """\x1b[33;1mTry install PySerial with: pip install pyserial or pip3 install pyserial.\nAnd: pip install typer\x1b[0m"""
    )
    sys.exit(1)

from Modules import HexDumper, PcapDumper, Protocols, Fifo, Wireshark, Cmd
import Modules.SnifferCollector as SCollector
from Modules.Definitions import PROMPT_HEADER, DEFAULT_INIT_ADDRESS
from Modules.Utils import validate_access_address

HELP_PANEL_OUTPUT = "Output Options"

app = typer.Typer(
    name="PyCat-Sniffer CLI",
    help="PyCat-Sniffer CLI - For sniffing the TI CC1352 device communication inferfaces.",
    epilog=f"""\x1b[37:mFor more information, visit:\x1b[0m
\x1b[36mhttps://github.com/ElectronicCats/CatSniffer/tree/master
https://electroniccats.com/
https://pwnlab.mx/\x1b[0m""",
    add_completion=False,
    no_args_is_help=True,
    rich_help_panel=True,
    context_settings={"help_option_names": ["-h", "--help"]},
    rich_markup_mode="markdown",
)

sniffer_collector = SCollector.SnifferCollector()


def signal_handler(sig, frame):
    sniffer_collector.stop_workers()
    sniffer_collector.delete_all_workers()
    sys.exit(0)


@app.command("protocols")
def list_protocols():
    """List all protocols available and their respective channel range. **For more information**: python cat_sniffer.py protocols"""
    table = Table(show_header=True, header_style="bold green")
    table.add_column("Index", style="dim")
    table.add_column("Protocol", justify="center")
    table.add_column("Frequency", justify="center")
    table.add_column("Channel Range (INDEX - Frequency)", justify="center")

    protocols_list = Protocols.PROTOCOLSLIST.get_list_protocols()
    for index, protocol in enumerate(protocols_list):
        channel_range = protocol.value.get_channel_range()
        channel_range_str = f"[{channel_range[0][0]}] {channel_range[0][1]} - [{channel_range[-1][0]}] {channel_range[-1][1]}"
        table.add_row(
            str(index),
            protocol.value.get_name(),
            str(protocol.value.get_phy_label()),
            channel_range_str,
        )
    console = Console()
    console.print(table)


@app.command("ld")
def list_ports():
    """List all serial ports available in the system. **For more information**: python cat_sniffer.py ld --help"""
    ports = serial.tools.list_ports.comports()
    if len(ports) == 0:
        typer.echo("No ports found")
    else:
        for port in ports:
            typer.echo(port)


@app.command("lora", no_args_is_help=True, short_help="Sniff LoRa communication. 915MHz, 125kHz, SF7, CR 4/5")
def lora_sniff(comport: str = typer.Argument(
        default="/dev/ttyACM0", help="Serial port to use for sniffing."
    ),freq: float = typer.Option(
        915.0,
        "-frq",
        "--frequency",
        show_default=True,
        help="Set the Frequency in MHz. Range: 150 - 960 MHz.",
    ), channel: int = typer.Option(
        0,
        "-ch",
        "--channel",
        show_default=True,
        help="Set the Channel. Value between 0 and 63"
    ), bandwidth: int = typer.Option(
        7,
        "-bw",
        "--bandwidth",
        show_default=True,
        help="Set the Bandwidth in kHz. Index-Range: 0:7.8 1:10.4 2:15.6 3:20.8 4:31.25 5:41.7 6:62.5 7:125 8:250.0 9:500.0 kHz.",
    ), spread_factor: int = typer.Option(
        7,
        "-sf",
        "--spread-factor",
        show_default=True,
        help="Set the Spreading Factor. Range: 6 - 12.",
    ), coding_rate: int = typer.Option(
        5,
        "-cr",
        "--coding-rate",
        show_default=True,
        help="Set the Coding Rate. Range: 5 - 8",
    ),
    fifo: bool = typer.Option(
        False,
        "-ff",
        "--fifo",
        is_flag=True,
        show_default=True,
        help="Enable FIFO pipeline to communicate with wireshark.",
        rich_help_panel=HELP_PANEL_OUTPUT,
    ),
    fifo_name: str = typer.Option(
        Fifo.DEFAULT_FILENAME,
        "-ffn",
        "--fifo-name",
        show_default=True,
        help="If the fifo is True, set the FIFO file name.",
        rich_help_panel=HELP_PANEL_OUTPUT,
    ),
    wireshark: bool = typer.Option(
        False,
        "-ws",
        "--wireshark",
        is_flag=True,
        help=f"""Open Wireshark with the direct link to the FIFO.
**Note**: If you have wireshark installed, you can open it with the command: wireshark -k -i /tmp/{Fifo.DEFAULT_FILENAME}.
If you are running in Windows, you need first set the Environment Variable to call wireshark as command.""",
        rich_help_panel=HELP_PANEL_OUTPUT,
    )):
    if not sniffer_collector.set_board_uart(comport):
        typer.echo("Error: Invalid serial port not connection found")
        sys.exit(1)

    if freq < 150 or freq > 960:
        typer.echo("Error: Invalid frequency range")
        sys.exit(1)
    
    if bandwidth > 9:
        typer.echo("Error: Invalid bandwidth range")
        sys.exit(1)
    
    if spread_factor < 6 or spread_factor > 12:
        typer.echo("Error: Invalid spread factor range")
        sys.exit(1)

    if coding_rate < 5 or coding_rate > 8:
        typer.echo("Error: Invalid coding rate range")
        sys.exit(1)

    if channel < 0 and channel > 63:
        typer.echo("Error: Invalid channel range")
        sys.exit(1)

    sniffer_collector.set_is_catsniffer(2)
    sniffer_collector.set_lora_bandwidth(bandwidth)
    sniffer_collector.set_lora_channel(channel)
    sniffer_collector.set_lora_frequency(freq)
    sniffer_collector.set_lora_spread_factor(spread_factor)
    sniffer_collector.set_lora_coding_rate(coding_rate)
    output_workers = []

    if fifo or fifo_name != Fifo.DEFAULT_FILENAME:
        if platform.system() == "Windows":
            output_workers.append(Fifo.FifoWindows(fifo_name))
        else:
            output_workers.append(Fifo.FifoLinux(fifo_name))
        if wireshark:
            output_workers.append(Wireshark.Wireshark(fifo_name))

    sniffer_collector.set_output_workers(output_workers)
    sniffer_collector.run_workers()
    Cmd.CMDInterface(sniffer_collector).cmdloop()


@app.command("bsniff", no_args_is_help=True)
def board_sniff(comport: str = typer.Argument(
        default="/dev/ttyACM0", help="Serial port to use for sniffing."
    ),
    phy: str = typer.Option(
        1,
        "-phy",
        "--phy",
        help="Set the Phy Protocol. *To know the available protocols, run: python cat_sniffer.py protocols*",
    ),
    channel: int = typer.Option(
        11,
        "-ch",
        "--channel",
        help=f"Set the Protocol Channel to sniff.",
    ),
    dumpfile: bool = typer.Option(
        False,
        "-df",
        "--dump",
        is_flag=True,
        show_default=True,
        help="Enable Hex Dump output to file.",
        rich_help_panel=HELP_PANEL_OUTPUT,
    ),
    dumpfile_name: str = typer.Option(
        HexDumper.HexDumper().DEFAULT_FILENAME,
        "-dfn",
        "--dump-name",
        show_default=True,
        help="If the dumpfile is True, set the Hexfile name.",
        rich_help_panel=HELP_PANEL_OUTPUT,
    ),
    pcapfile: bool = typer.Option(
        False,
        "-pf",
        "--pcap",
        show_default=True,
        help="Enable PCAP output to file.",
        rich_help_panel=HELP_PANEL_OUTPUT,
    ),
    pcapfile_name: str = typer.Option(
        PcapDumper.PcapDumper().DEFAULT_FILENAME,
        "-pfn",
        "--pcap-name",
        show_default=True,
        help="If the pcapfile is True, set the PCAP file name.",
        rich_help_panel=HELP_PANEL_OUTPUT,
    ),
    fifo: bool = typer.Option(
        False,
        "-ff",
        "--fifo",
        is_flag=True,
        show_default=True,
        help="Enable FIFO pipeline to communicate with wireshark.",
        rich_help_panel=HELP_PANEL_OUTPUT,
    ),
    fifo_name: str = typer.Option(
        Fifo.DEFAULT_FILENAME,
        "-ffn",
        "--fifo-name",
        show_default=True,
        help="If the fifo is True, set the FIFO file name.",
        rich_help_panel=HELP_PANEL_OUTPUT,
    ),
    wireshark: bool = typer.Option(
        False,
        "-ws",
        "--wireshark",
        is_flag=True,
        help=f"""Open Wireshark with the direct link to the FIFO.
**Note**: If you have wireshark installed, you can open it with the command: wireshark -k -i /tmp/{Fifo.DEFAULT_FILENAME}.
If you are running in Windows, you need first set the Environment Variable to call wireshark as command.""",
        rich_help_panel=HELP_PANEL_OUTPUT,
    )):
    """Create a sniffer instance to sniff the communication between a compatible board and Wireshark. **For more information**: python cat_sniffer.py sniff --help"""
    if not sniffer_collector.set_board_uart(comport):
        typer.echo("Error: Invalid serial port not connection found")
        sys.exit(1)

    sniffer_collector.set_is_catsniffer(1)
    sniffer_collector.set_protocol_phy(phy)
    if channel not in sniffer_collector.get_protocol_phy().list_channel_range:
        typer.echo(f"Error: Invalid channel: {channel}.")
        sys.exit(1)
    
    sniffer_collector.set_protocol_channel(channel)
    output_workers = []
    
    if dumpfile or dumpfile_name != HexDumper.HexDumper.DEFAULT_FILENAME:
        output_workers.append(HexDumper.HexDumper(dumpfile_name))

    if pcapfile or pcapfile_name != PcapDumper.PcapDumper.DEFAULT_FILENAME:
        output_workers.append(PcapDumper.PcapDumper(pcapfile_name))

    if fifo or fifo_name != Fifo.DEFAULT_FILENAME:
        if platform.system() == "Windows":
            output_workers.append(Fifo.FifoWindows(fifo_name))
        else:
            output_workers.append(Fifo.FifoLinux(fifo_name))
        if wireshark:
            output_workers.append(Wireshark.Wireshark(fifo_name))

    sniffer_collector.set_output_workers(output_workers)
    sniffer_collector.run_workers()
    Cmd.CMDInterface(sniffer_collector).cmdloop()



@app.command("sniff", no_args_is_help=True)
def cli_sniff(
    comport: str = typer.Argument(
        default="/dev/ttyACM0", help="Serial port to use for sniffing."
    ),
    verbose: bool = typer.Option(
        False,
        "-v",
        "--verbose",
        is_flag=True,
        help="Enable verbose mode.",
        rich_help_panel=HELP_PANEL_OUTPUT,
    ),
    phy: str = typer.Option(
        0,
        "-phy",
        "--phy",
        help="Set the Phy Protocol. *To know the available protocols, run: python cat_sniffer.py protocols*",
    ),
    channel: int = typer.Option(
        37,
        "-ch",
        "--channel",
        help=f"Set the Protocol Channel to sniff.",
    ),

    hopping: bool = typer.Option(False,
        "-chop",
        "--hopp",
        is_flag=True,
        show_default=True,
        help="Enable Hopping channel for IEEE 802.15.4.",
        rich_help_panel=HELP_PANEL_OUTPUT,
    ),
    dumpfile: bool = typer.Option(
        False,
        "-df",
        "--dump",
        is_flag=True,
        show_default=True,
        help="Enable Hex Dump output to file.",
        rich_help_panel=HELP_PANEL_OUTPUT,
    ),
    dumpfile_name: str = typer.Option(
        HexDumper.HexDumper().DEFAULT_FILENAME,
        "-dfn",
        "--dump-name",
        show_default=True,
        help="If the dumpfile is True, set the Hexfile name.",
        rich_help_panel=HELP_PANEL_OUTPUT,
    ),
    pcapfile: bool = typer.Option(
        False,
        "-pf",
        "--pcap",
        show_default=True,
        help="Enable PCAP output to file.",
        rich_help_panel=HELP_PANEL_OUTPUT,
    ),
    pcapfile_name: str = typer.Option(
        PcapDumper.PcapDumper().DEFAULT_FILENAME,
        "-pfn",
        "--pcap-name",
        show_default=True,
        help="If the pcapfile is True, set the PCAP file name.",
        rich_help_panel=HELP_PANEL_OUTPUT,
    ),
    fifo: bool = typer.Option(
        False,
        "-ff",
        "--fifo",
        is_flag=True,
        show_default=True,
        help="Enable FIFO pipeline to communicate with wireshark.",
        rich_help_panel=HELP_PANEL_OUTPUT,
    ),
    fifo_name: str = typer.Option(
        Fifo.DEFAULT_FILENAME,
        "-ffn",
        "--fifo-name",
        show_default=True,
        help="If the fifo is True, set the FIFO file name.",
        rich_help_panel=HELP_PANEL_OUTPUT,
    ),
    wireshark: bool = typer.Option(
        False,
        "-ws",
        "--wireshark",
        is_flag=True,
        help=f"""Open Wireshark with the direct link to the FIFO.
**Note**: If you have wireshark installed, you can open it with the command: wireshark -k -i /tmp/{Fifo.DEFAULT_FILENAME}.
If you are running in Windows, you need first set the Environment Variable to call wireshark as command.""",
        rich_help_panel=HELP_PANEL_OUTPUT,
    ),
):
    """Create a sniffer instance to sniff the communication between the TI CC1352 device and the target device. **For more information**: python cat_sniffer.py sniff --help"""

    setup_sniffer(
        dumpfile,
        dumpfile_name,
        pcapfile,
        pcapfile_name,
        fifo,
        fifo_name,
        wireshark,
        verbose,
        comport,
        phy,
        channel,
        hopping
    )
    # Wait for a user interaction
    Cmd.CMDInterface(sniffer_collector).cmdloop()


def setup_sniffer(
    dumpfile,
    dumpfile_name,
    pcapfile,
    pcapfile_name,
    fifo,
    fifo_name,
    wireshark,
    verbose,
    comport,
    phy,
    channel,
    hopping
):
    output_workers = []

    if not sniffer_collector.set_board_uart(comport):
        typer.echo("Error: Invalid serial port not connection found")
        sys.exit(1)

    sniffer_collector.set_protocol_phy(phy)
    sniffer_collector.set_channel_hopping(hopping=hopping)
    
    if not hopping:
        if channel not in sniffer_collector.get_protocol_phy().list_channel_range:
            typer.echo(f"Error: Invalid channel: {channel}.")
            sys.exit(1)
    
    sniffer_collector.set_protocol_channel(channel)
    sniffer_collector.set_verbose_mode(verbose)

    if dumpfile or dumpfile_name != HexDumper.HexDumper.DEFAULT_FILENAME:
        output_workers.append(HexDumper.HexDumper(dumpfile_name))

    if pcapfile or pcapfile_name != PcapDumper.PcapDumper.DEFAULT_FILENAME:
        output_workers.append(PcapDumper.PcapDumper(pcapfile_name))

    if fifo or fifo_name != Fifo.DEFAULT_FILENAME:
        if platform.system() == "Windows":
            output_workers.append(Fifo.FifoWindows(fifo_name))
        else:
            output_workers.append(Fifo.FifoLinux(fifo_name))
        if wireshark:
            output_workers.append(Wireshark.Wireshark(fifo_name))

    sniffer_collector.set_output_workers(output_workers)
    sniffer_collector.run_workers()


if __name__ == "__main__":
    typer.echo(PROMPT_HEADER)
    signal.signal(signal.SIGINT, signal_handler)
    app()

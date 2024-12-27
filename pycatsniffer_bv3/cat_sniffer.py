import signal
import sys
import platform

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
BOARD_MODE = 1
CATSNIFFER_LORA_MODE = 2


class Catsniffer:
    def __init__(self, sniffer_collector: SCollector.SnifferCollector):
        self.sniffer_collector = sniffer_collector
        self.output_workers = []

    def start(
        self,
        comport: str = typer.Argument(
            default=SCollector.SnifferCollector().board_uart.find_catsniffer_serial_port(),
            help="The COM port to use.",
        ),
        phy: str = typer.Option(
            "ble",
            "-phy",
            "--phy",
            help="The PHY protocol to use. *To know the available protocols, run: python cat_sniffer.py protocols*",
        ),
        channel: int = typer.Option(
            37, "-c", "--channel", help="The channel to sniff."
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
        verbose: bool = typer.Option(
            False,
            "-v",
            "--verbose",
            is_flag=True,
            help="Enable verbose mode.",
            rich_help_panel=HELP_PANEL_OUTPUT,
        ),
    ):

        if not self.sniffer_collector.set_board_uart(comport):
            typer.echo("Error: Invalid serial port not connection found")
            sys.exit(1)

        get_protocol = Protocols.PROTOCOLSLIST.get_protocol_by_name(phy)
        if not get_protocol:
            print(f"\x1b[31;1m[!] PHY protocol not found: {phy}\x1b[0m")
            sys.exit(1)

        self.sniffer_collector.set_protocol_phy(phy)
        self.sniffer_collector.set_channel_hopping(hopping=False)
        if channel not in self.sniffer_collector.get_protocol_phy().list_channel_range:
            control_ble = Protocols.PROTOCOLSLIST.get_protocol_by_name("ble")
            if get_protocol != control_ble:
                control_channel = get_protocol.get_channel_range()[0][0]
                channel = control_channel

        self.sniffer_collector.set_protocol_channel(channel)
        self.sniffer_collector.set_verbose_mode(verbose)

        if dumpfile or dumpfile_name != HexDumper.HexDumper.DEFAULT_FILENAME:
            self.output_workers.append(HexDumper.HexDumper(dumpfile_name))

        if pcapfile or pcapfile_name != PcapDumper.PcapDumper.DEFAULT_FILENAME:
            self.output_workers.append(PcapDumper.PcapDumper(pcapfile_name))

        if fifo or fifo_name != Fifo.DEFAULT_FILENAME:
            if platform.system() == "Windows":
                self.output_workers.append(Fifo.FifoWindows(fifo_name))
            else:
                self.output_workers.append(Fifo.FifoLinux(fifo_name))
            if wireshark:
                self.output_workers.append(
                    Wireshark.Wireshark(fifo_name, get_protocol.get_profile())
                )

        self.sniffer_collector.set_output_workers(self.output_workers)
        self.sniffer_collector.run_workers()

        table_information = Table(title="Catsniffer Information")
        table_information.add_column("Information", style="cyan", no_wrap=True)
        table_information.add_column("Value", style="magenta", no_wrap=True)
        table_information.add_row("COM Port", comport)
        table_information.add_row("PHY", get_protocol.get_name())
        table_information.add_row("Channel", str(channel))
        console = Console()
        console.print(table_information)

        Cmd.CMDInterface(self.sniffer_collector).cmdloop()


class ProtocolsInformation:
    def __init__(self):
        self.protocol_list = Protocols.PROTOCOLSLIST.get_list_protocols()

    def get_protocols(self):
        table = Table(title="Available Protocols")
        table.add_column("Protocol", style="magenta", no_wrap=True)
        table.add_column("Base Frequency", style="green", no_wrap=True)
        table.add_column(
            "Channel Range (Index - Frequency)", style="yellow", no_wrap=True
        )
        table.add_column("*PHY Label", style="blue", no_wrap=True)
        for protocol in self.protocol_list:
            proto = protocol.value
            table.add_row(
                proto.get_name(),
                str(proto.get_base_frequency()),
                str(proto.get_channel_range()),
                proto.get_common_name_str(),
            )
        console = Console()
        console.print(table)
        console.print(
            "*Phy Label: The PHY label is the name of the PHY protocol used in the sniffer. You can use this label to set the PHY protocol in the sniff command."
        )


class CatsnifferLora:
    def __init__(self, sniffer_collector: SCollector.SnifferCollector):
        self.sniffer_collector = sniffer_collector
        self.output_workers = []

    def start(
        self,
        comport: str = typer.Argument(
            default=SCollector.SnifferCollector().board_uart.find_catsniffer_serial_port(),
            help="The COM port to use.",
        ),
        freq: float = typer.Option(
            915.0,
            "-frq",
            "--frequency",
            show_default=True,
            help="Set the Frequency in MHz. Range: 150 - 960 MHz.",
        ),
        channel: int = typer.Option(
            0,
            "-ch",
            "--channel",
            show_default=True,
            help="Set the Channel. Value between 0 and 63",
        ),
        bandwidth: int = typer.Option(
            7,
            "-bw",
            "--bandwidth",
            show_default=True,
            help="Set the Bandwidth in kHz. Index-Range: 0:7.8 1:10.4 2:15.6 3:20.8 4:31.25 5:41.7 6:62.5 7:125 8:250.0 9:500.0 kHz.",
        ),
        spread_factor: int = typer.Option(
            7,
            "-sf",
            "--spread-factor",
            show_default=True,
            help="Set the Spreading Factor. Range: 6 - 12.",
        ),
        coding_rate: int = typer.Option(
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
        ),
        verbose: bool = typer.Option(
            False,
            "-v",
            "--verbose",
            is_flag=True,
            help="Enable verbose mode.",
            rich_help_panel=HELP_PANEL_OUTPUT,
        ),
    ):

        if not self.sniffer_collector.set_board_uart(comport):
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

        if channel < 0 or channel > 63:
            typer.echo("Error: Invalid channel range")
            sys.exit(1)
        self.sniffer_collector.set_is_catsniffer(CATSNIFFER_LORA_MODE)
        self.sniffer_collector.set_lora_bandwidth(bandwidth)
        self.sniffer_collector.set_lora_channel(channel)
        self.sniffer_collector.set_lora_frequency(freq)
        self.sniffer_collector.set_lora_spread_factor(spread_factor)
        self.sniffer_collector.set_lora_coding_rate(coding_rate)
        if fifo or fifo_name != Fifo.DEFAULT_FILENAME:
            if platform.system() == "Windows":
                self.output_workers.append(Fifo.FifoWindows(fifo_name))
            else:
                self.output_workers.append(Fifo.FifoLinux(fifo_name))
            if wireshark:
                self.output_workers.append(Wireshark.Wireshark(fifo_name))

        self.sniffer_collector.set_output_workers(self.output_workers)
        self.sniffer_collector.run_workers()
        Cmd.CMDInterface(self.sniffer_collector).cmdloop()


class BoardsWireshark:
    def __init__(self, sniffer_collector: SCollector.SnifferCollector):
        self.sniffer_collector = sniffer_collector
        self.output_workers = []

    def start(
        self,
        comport: str = typer.Argument(
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
        ),
    ):
        if not self.sniffer_collector.set_board_uart(comport):
            typer.echo("Error: Invalid serial port not connection found")
            sys.exit(1)

        self.sniffer_collector.set_is_catsniffer(1)
        get_protocol = Protocols.PROTOCOLSLIST.get_protocol_by_name(phy)
        if not get_protocol:
            print(f"\x1b[31;1m[!] PHY protocol not found: {phy}\x1b[0m")
            sys.exit(1)

        self.sniffer_collector.set_protocol_phy(phy)
        if channel not in self.sniffer_collector.get_protocol_phy().list_channel_range:
            control_ble = Protocols.PROTOCOLSLIST.get_protocol_by_name("ble")
            if get_protocol != control_ble:
                control_channel = get_protocol.get_channel_range()[0][0]
                channel = control_channel

        self.sniffer_collector.set_protocol_channel(channel)

        if dumpfile or dumpfile_name != HexDumper.HexDumper.DEFAULT_FILENAME:
            self.output_workers.append(HexDumper.HexDumper(dumpfile_name))

        if pcapfile or pcapfile_name != PcapDumper.PcapDumper.DEFAULT_FILENAME:
            self.output_workers.append(PcapDumper.PcapDumper(pcapfile_name))

        if fifo or fifo_name != Fifo.DEFAULT_FILENAME:
            if platform.system() == "Windows":
                self.output_workers.append(Fifo.FifoWindows(fifo_name))
            else:
                self.output_workers.append(Fifo.FifoLinux(fifo_name))
            if wireshark:
                self.output_workers.append(Wireshark.Wireshark(fifo_name))

        self.sniffer_collector.set_output_workers(self.output_workers)
        self.sniffer_collector.run_workers()
        Cmd.CMDInterface(self.sniffer_collector).cmdloop()


class CLICatsniffer:
    def __init__(self):
        self.app = typer.Typer(
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
        self.sniffer_collector = SCollector.SnifferCollector()
        self.catsniffer = Catsniffer(self.sniffer_collector)
        self.boards_wireshark = BoardsWireshark(self.sniffer_collector)
        self.catsniffer_lora = CatsnifferLora(self.sniffer_collector)
        self.protocols = ProtocolsInformation()
        self.app.command(
            "sniff",
            no_args_is_help=True,
            short_help="Create a sniffer instance to sniff the communication between the TI CC1352 device and the target device. **For more information**: python cat_sniffer.py sniff --help",
        )(self.catsniffer.start)
        self.app.command(
            "lora",
            no_args_is_help=True,
            short_help="Sniff LoRa communication. 915MHz, 125kHz, SF7, CR 4/5",
        )(self.catsniffer_lora.start)
        self.app.command(
            "bsniff",
            no_args_is_help=True,
            short_help="Sniff the communication between Minino or compatible device and the Wireshark.",
        )(self.boards_wireshark.start)
        self.app.command(
            "protocols", short_help="Show the information about the available protocols"
        )(self.protocols.get_protocols)


if __name__ == "__main__":
    typer.echo(PROMPT_HEADER)
    cli = CLICatsniffer()
    try:
        cli.app()
    except KeyboardInterrupt:
        print("\x1b[31;1m[!] Exiting...\x1b[0m")
        sys.exit(1)
    except Exception as e:
        print(f"\x1b[31;1m[!] Error: {e}\x1b[0m")
        sys.exit(1)

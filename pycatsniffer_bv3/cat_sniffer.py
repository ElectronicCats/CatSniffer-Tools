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
                self.output_workers.append(Wireshark.Wireshark(fifo_name))

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
        self.protocols = ProtocolsInformation()
        self.app.command("sniff", no_args_is_help=True)(self.catsniffer.start)
        self.app.command("protocols")(self.protocols.get_protocols)


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

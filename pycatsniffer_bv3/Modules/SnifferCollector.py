import time
import struct
import threading
import typer
import sys
import platform
from traceback import format_exception
from .Worker import WorkerManager
from .UART import UART
from .Pcap import Pcap
from .Packets import GeneralUARTPacket, IEEEUARTPacket, BLEUARTPacket, LoraUARTPacket
from .Definitions import DEFAULT_TIMEOUT_JOIN
from .Protocols import (
    PROTOCOL_BLE,
    PROTOCOL_ZIGBEE,
    PROTOCOL_LORA,
    PROTOCOL_THREAD,
    PROTOCOLSLIST,
)
from .Utils import LOG_ERROR, LOG_WARNING, LOG_INFO


class TrivialLogger:
    def _log(self, msg, *args, exc_info=None, **kwargs):
        msg = msg % args
        print(msg, file=sys.stderr)
        if exc_info:
            if isinstance(exc_info, BaseException):
                exc_info = (type(exc_info), exc_info, exc_info.__traceback__)
            elif not isinstance(exc_info, tuple):
                exc_info = sys.exc_info()
            exc_str = "".join(format_exception(*exc_info))
            print(exc_str, file=sys.stderr)

    debug = _log
    info = _log
    warning = _log
    error = _log
    critical = _log
    exception = _log


class SnifferCollector(threading.Thread):
    """Worker class for the sniffer collector"""

    def __init__(self, logger=None):
        super().__init__()
        self.sniffer_data = None
        self.sniffer_worker = WorkerManager()
        self.board_uart = UART()
        self.output_workers = []
        self.protocol = PROTOCOL_BLE
        self.protocol_freq_channel = 37
        self.protocol_linktype = PROTOCOL_BLE.get_pcap_header()
        self.initiator_address = None
        self.verbose_mode = False
        self.pcap_size = 0
        # QUEUE
        self.data_queue_lock = threading.Lock()
        self.sniffer_recv_cancel = False
        # Boards
        self.is_catsniffer = 0
        # Hopping
        self.last_timestamp = None
        self.time_hopper = 0.2  # Seconds
        self.last_channel_index = 0
        self.hopping_channel = False
        self.hopp_channels = []
        self.lora_bandwidth = 0
        self.lora_channel = 0
        self.lora_frequency = 0
        self.lora_spreading_factor = 0
        self.lora_coding_rate = 0
        self.logger = logger if logger else TrivialLogger()

    def set_is_catsniffer(self, is_catsniffer: int):
        self.is_catsniffer = is_catsniffer

    def set_lora_bandwidth(self, bandwidth: int):
        self.lora_bandwidth = bandwidth

    def set_lora_frequency(self, frequency: float):
        self.lora_frequency = frequency

    def set_lora_spread_factor(self, spreading_factor: int):
        self.lora_spreading_factor = spreading_factor

    def set_lora_coding_rate(self, coding_rate: int):
        self.lora_coding_rate = coding_rate

    def set_lora_channel(self, channel: int):
        if channel > -1 and channel < 64:
            freq = 902300000 + channel * 125000
            frequency = freq / 1000000
            self.lora_frequency = round(frequency, 2)
        else:
            freq = 903000000 + (channel - 64) * 500000
            frequency = freq / 1000000
            self.lora_frequency = round(frequency, 2)
        self.lora_channel = channel

    def set_output_workers(self, output_workers):
        self.output_workers = output_workers

    def set_board_uart(self, board_uart) -> bool:
        self.board_uart.set_serial_port(board_uart)
        return self.board_uart.is_valid_connection()

    def set_verbose_mode(self, verbose_mode: bool):
        self.verbose_mode = verbose_mode

    def get_protocol_channels(self):
        return self.protocol.get_channel_range()

    def get_protocol_channels_str(self):
        return self.protocol.get_channel_range_bytes()

    def get_protocol_phy(self):
        return self.protocol

    def get_channel(self):
        return self.protocol_freq_channel

    def open_board_uart(self):
        self.board_uart.open()

    def set_channel_hopping(self, hopping: bool):
        self.hopping_channel = hopping

    def set_protocol_phy(self, phy: str):
        """Set the phy protocol for the sniffer"""
        get_protocol = PROTOCOLSLIST.get_protocol_by_name(phy)
        self.protocol = get_protocol
        self.protocol_linktype = get_protocol.get_pcap_header()

    def set_protocol_channel(self, channel: int):
        """Set the protocol channel for the sniffer"""
        get_channel = self.protocol.get_channel_range_bytes(channel)
        self.protocol_freq_channel = get_channel[0]

    def close_board_uart(self):
        self.board_uart.close()

    def set_recv_cancel(self, recv_cancel: bool):
        self.sniffer_recv_cancel = recv_cancel

    def set_initiator_address(self, initiator_address: bytes):
        self.initiator_address = initiator_address

    def send_command_stop(self):
        """Send the stop command to the sniffer"""
        get_protocol_command = self.protocol.command_stop()
        self.board_uart.send(get_protocol_command.raw_packet)

    def send_command_init_address(self, address: bytes):
        """Send the init address command to the sniffer"""
        get_protocol_command = self.protocol.command_cfg_init_address(address)
        self.board_uart.send(get_protocol_command.raw_packet)

    def send_command_start(self):
        """Send the start command to the sniffer"""
        get_protocol_commands = self.protocol.command_startup(
            self.protocol_freq_channel
        )
        if self.initiator_address:
            get_protocol_commands.insert(
                4, self.protocol.command_cfg_init_address(self.initiator_address)
            )
        for command in get_protocol_commands:
            self.board_uart.send(command.raw_packet)
            time.sleep(0.1)

    def get_interface(self):
        interface_bytes = self.board_uart.get_serial_port()
        if platform.system() == "Windows":
            interface_bytes = interface_bytes.encode("utf-8").ljust(8, b"\x00")
        else:
            interface_bytes = interface_bytes.split("tty")[1]
            if len(interface_bytes) > 8:
                interface_bytes = interface_bytes[-8:].encode("utf-8")
            else:
                interface_bytes = interface_bytes.encode("utf-8")
        return interface_bytes

    def handle_sniffer_data(self):
        while not self.sniffer_recv_cancel:
            if self.sniffer_recv_cancel:
                break
            if self.sniffer_data:
                # Send to the dumpers
                for output_worker in self.output_workers:
                    if output_worker.type_worker == "raw":
                        output_worker.add_data(self.sniffer_data.payload)
                    elif output_worker.type_worker == "pcap":
                        try:
                            version = b"\x00"
                            interfaceType = b"\x00"
                            interfaceId = bytes.fromhex("0300")
                            protocol = b"\x03"
                            phy = bytes.fromhex("05")
                            if self.protocol == PROTOCOL_BLE:
                                protocol = b"\x03"
                                phy = bytes.fromhex("05")
                            elif (
                                self.protocol == PROTOCOL_ZIGBEE
                                or self.protocol == PROTOCOL_THREAD
                            ):
                                protocol = b"\x02"
                                phy = bytes.fromhex("03")

                            if self.is_catsniffer == 1:
                                interfaceId = bytes.fromhex("0200")

                            if self.is_catsniffer == PROTOCOL_LORA:
                                protocol = b"\x05"
                                phy = bytes.fromhex("06")

                            if self.is_catsniffer == 2:
                                self.protocol_linktype = 148
                                packet = (
                                    version
                                    + int(self.sniffer_data.packet_length).to_bytes(
                                        2, "little"
                                    )
                                    + interfaceId
                                    + protocol
                                    + phy
                                    + int(self.lora_frequency).to_bytes(4, "little")
                                    + int(self.lora_bandwidth).to_bytes(1, "little")
                                    + int(self.lora_spreading_factor).to_bytes(
                                        1, "little"
                                    )
                                    + int(self.lora_coding_rate).to_bytes(1, "little")
                                    + struct.pack("<f", self.sniffer_data.rssi)
                                    + struct.pack("<f", self.sniffer_data.snr)
                                    + self.sniffer_data.payload
                                )
                            else:
                                packet = (
                                    version
                                    + self.sniffer_data.packet_length.to_bytes(
                                        2, "little"
                                    )
                                    + interfaceType
                                    + interfaceId
                                    + protocol
                                    + phy
                                    + int(
                                        self.protocol.get_channel_range_bytes(
                                            self.protocol_freq_channel
                                        )[1]
                                    ).to_bytes(4, "little")
                                    + int(
                                        self.protocol.get_channel_range_bytes(
                                            self.protocol_freq_channel
                                        )[0]
                                    ).to_bytes(2, "little")
                                    + self.sniffer_data.rssi.to_bytes(1, "little")
                                    + self.sniffer_data.status.to_bytes(1, "little")
                                    + self.sniffer_data.connect_evt
                                    + self.sniffer_data.conn_info.to_bytes(1, "little")
                                    + self.sniffer_data.payload
                                )
                            pcap_file = Pcap(packet, time.time())
                            output_worker.set_linktype(self.protocol_linktype)
                            output_worker.add_data(pcap_file.get_pcap())
                        except struct.error as e:
                            LOG_ERROR(f"Error: {str(e)}")
                            LOG_ERROR(f"Packet: {self.sniffer_data}")
                            continue
                    else:
                        time.sleep(0.01)
                        continue
                self.sniffer_data = None
            else:
                time.sleep(0.01)

    def dissector(self, packet: bytes) -> bytes:
        """Dissector the packet"""
        if self.is_catsniffer == 2:
            data_packet = LoraUARTPacket(packet)
            return data_packet

        general_packet = GeneralUARTPacket(packet)
        if general_packet.is_command_response_packet():
            return None

        packet = None
        try:
            if self.protocol == PROTOCOL_BLE:
                data_packet = BLEUARTPacket(general_packet.packet_bytes)
                packet = data_packet
            elif self.protocol == PROTOCOL_ZIGBEE or self.protocol == PROTOCOL_THREAD:
                ieee_packet = IEEEUARTPacket(general_packet.packet_bytes)
                packet = ieee_packet
            else:
                self.logger.error("Protocol not supported yet")
                LOG_WARNING("Protocol not supported yet")
                LOG_WARNING(f"Packet -> {general_packet}")
        except Exception as e:
            self.logger.error(f"Dissector Error -> {e}")
            LOG_WARNING(f"Dissector Error -> {e}")
            LOG_WARNING(f"Packet -> {general_packet}")
            return packet

        if self.verbose_mode:
            LOG_INFO(f"\nRECV -> {packet}\n")

        return packet

    def hopper_worker(self):
        while not self.sniffer_recv_cancel:
            if self.hopping_channel:
                if self.last_timestamp is None:
                    self.last_timestamp = time.time()
                if (time.time() - self.last_timestamp) >= self.time_hopper:
                    self.last_timestamp = time.time()
                    if len(self.hopp_channels) == 0:
                        self.hopp_channels = self.protocol.get_channel_range()

                    if self.last_channel_index > (len(self.hopp_channels) - 1):
                        self.last_channel_index = 0
                    self.set_protocol_channel(
                        self.hopp_channels[self.last_channel_index][0]
                    )
                    self.last_channel_index += 1
                    self.send_command_start()
            time.sleep(0.1)

    def set_and_send_lora_config(self):
        lora_cmd_bandwidth = f"set_bw {self.lora_bandwidth}\r\n"
        lora_cmd_channel = f"set_chann {self.lora_channel}\r\n"
        # lora_cmd_frequency = f"set_freq {self.lora_frequency}\r\n"
        lora_cmd_spreading_factor = f"set_sf {self.lora_spreading_factor}\r\n"
        lora_cmd_coding_rate = f"set_cr {self.lora_coding_rate}\r\n"
        self.board_uart.send(bytes(lora_cmd_bandwidth, "utf-8"))
        self.board_uart.send(bytes(lora_cmd_channel, "utf-8"))
        # self.board_uart.send(bytes(lora_cmd_frequency, "utf-8"))
        self.board_uart.send(bytes(lora_cmd_coding_rate, "utf-8"))
        self.board_uart.send(bytes(lora_cmd_spreading_factor, "utf-8"))
        self.board_uart.send(b"set_rx\r\n")
        self.logger.info(f"Bandwidth: {self.lora_bandwidth}")
        self.logger.info(f"Channel: {self.lora_channel}")
        self.logger.info(f"Frequency: {self.lora_frequency}")
        self.logger.info(f"Spreading Factor: {self.lora_spreading_factor}")
        self.logger.info(f"Coding Rate: {self.lora_coding_rate}")

    def recv_worker(self):
        try:
            if self.board_uart.is_connected() == False:
                self.board_uart.open()

            self.board_uart.set_is_catsniffer(self.is_catsniffer)

            if self.is_catsniffer == 0:
                self.send_command_start()
            else:
                if self.is_catsniffer == 2:
                    self.set_and_send_lora_config()
                    lora_cmd_frequency = f"set_freq {self.lora_frequency}\r\n"
                    self.board_uart.send(bytes(lora_cmd_frequency, "utf-8"))
                    self.logger.info(f"Bandwidth: {self.lora_bandwidth}")
                    self.logger.info(f"Channel: {self.lora_channel}")
                    self.logger.info(f"Frequency: {self.lora_frequency}")
                    self.logger.info(f"Spreading Factor: {self.lora_spreading_factor}")
                    self.logger.info(f"Coding Rate: {self.lora_coding_rate}")
                    self.board_uart.send(b"set_rx\r\n")
                self.board_uart.set_serial_baudrate(115200)

            while not self.sniffer_recv_cancel:
                frame = self.board_uart.recv()
                if frame is not None:
                    packet_frame = self.dissector(frame)
                    if packet_frame:
                        self.sniffer_data = packet_frame
                time.sleep(0.01)
        except Exception as e:
            LOG_ERROR(e)
        finally:
            self.close_board_uart()

    def run_workers(self):
        # Open output workers
        for output_worker in self.output_workers:
            output_worker.start()

        self.sniffer_worker.add_worker(
            threading.Thread(target=self.recv_worker, daemon=True)
        )
        self.sniffer_worker.add_worker(
            threading.Thread(target=self.handle_sniffer_data, daemon=True)
        )
        if self.hopping_channel:
            self.sniffer_worker.add_worker(
                threading.Thread(target=self.hopper_worker, daemon=True)
            )
        # threading.Thread(target=self.hopper_worker, daemon=True).start()
        self.sniffer_worker.start_all_workers()

    def stop_workers(self):
        typer.echo("Stoping workers")
        self.send_command_stop()
        self.sniffer_recv_cancel = True
        time.sleep(0.5)
        for output_worker in self.output_workers:
            output_worker.stop_worker()
        self.sniffer_worker.stop_all_workers()

    def delete_all_workers(self):
        typer.echo("Cleaning Workers")
        for output_worker in self.output_workers:
            output_worker.stop_thread()
            output_worker.join(DEFAULT_TIMEOUT_JOIN)
        sys.exit(0)

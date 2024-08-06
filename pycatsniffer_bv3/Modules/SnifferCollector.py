import time
import struct
import threading
import typer
import sys
from .Worker import WorkerManager
from .UART import UART
from .Pcap import Pcap
from .Packets import GeneralUARTPacket, IEEEUARTPacket, BLEUARTPacket, LoraUARTPacket
from .Definitions import DEFAULT_TIMEOUT_JOIN
from .Protocols import PROTOCOL_BLE, PROTOCOL_IEEE, PROTOCOL_LORA, PROTOCOLSLIST
from .Utils import LOG_ERROR, LOG_WARNING, LOG_INFO


class SnifferCollector(threading.Thread):
    """Worker class for the sniffer collector"""

    def __init__(self):
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
        self.is_catsniffer = True
        # Hopping
        self.last_timestamp = None
        self.time_hopper = 0.2 # Seconds
        self.last_channel_index = 0
        self.hopping_channel = False
        self.hopp_channels = []

    def set_is_catsniffer(self, is_catsniffer: bool):   
        self.is_catsniffer = is_catsniffer

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

    def set_protocol_phy(self, phy: int):
        """Set the phy protocol for the sniffer"""
        get_protocol = PROTOCOLSLIST.get_list_protocols()[int(phy)].value
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
                            elif self.protocol == PROTOCOL_IEEE:
                                protocol = b"\x02"
                                phy = bytes.fromhex("03")
                            elif self.protocol == PROTOCOL_LORA:
                                protocol = b"\x05"
                                phy = bytes.fromhex("06")

                            if self.protocol == PROTOCOL_LORA:
                                self.protocol_linktype = 146
                                packet = (
                                    version
                                    + self.sniffer_data.packet_length.to_bytes(2, "little")
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
                                    + self.sniffer_data.rssi
                                    + b"\x80"
                                    # + self.sniffer_data.connect_evt
                                    # + self.sniffer_data.conn_info.to_bytes(1, "little")
                                    + self.sniffer_data.payload
                                )
                            else:
                                packet = (
                                    version
                                    + self.sniffer_data.packet_length.to_bytes(2, "little")
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
        if self.protocol == PROTOCOL_LORA:
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
            elif self.protocol == PROTOCOL_IEEE:
                ieee_packet = IEEEUARTPacket(general_packet.packet_bytes)
                packet = ieee_packet
            else:
                LOG_WARNING("Protocol not supported yet")
                LOG_WARNING(f"Packet -> {general_packet}")
        except Exception as e:
            LOG_WARNING(f"\nDissector Error -> {e}")
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
                        print(self.hopp_channels)

                    if self.last_channel_index > (len(self.hopp_channels) - 1):
                        self.last_channel_index = 0
                    self.set_protocol_channel(self.hopp_channels[self.last_channel_index][0])
                    #self.send_command_stop()
                    print("Channel: ", self.protocol_freq_channel)
                    self.last_channel_index += 1
                    self.send_command_start()
            time.sleep(0.1)


    def recv_worker(self):
        try:
            if self.board_uart.is_connected() == False:
                self.board_uart.open()

            self.board_uart.set_is_catsniffer(self.is_catsniffer)

            if self.is_catsniffer:
                self.send_command_start()
            else:
                self.board_uart.set_serial_baudrate(115200)
            
            self.board_uart.send(b"set_rx\r\n")

            while not self.sniffer_recv_cancel:
                frame = self.board_uart.recv()
                print(f"FRAME -> {frame}")
                if frame is not None:
                    packet_frame = self.dissector(frame)
                    print(f"PACKET -> {packet_frame}")
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
        #threading.Thread(target=self.hopper_worker, daemon=True).start()
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

import time
import struct
import threading
import binascii
from .Worker import WorkerManager
from .UART import UART
from .Pcap import Pcap
from .Fifo import FifoLinux
from .Packets import GeneralUARTPacket, DataUARTPacket, IEEEUARTPacket, BLEUARTPacket
from .Definitions import PCAP_MAX_PACKET_SIZE, VERSION_NUMBER
from .Protocols import PROTOCOL_BLE, PROTOCOL_IEEE, PROTOCOLSLIST
from .Logger import SnifferLogger


class SnifferCollector(threading.Thread, SnifferLogger):
    """Worker class for the sniffer collector"""
    def __init__(self):
        super().__init__()
        self.logger                = SnifferLogger().get_logger()
        self.sniffer_data          = None
        self.sniffer_worker        = WorkerManager()
        self.board_uart            = UART()
        self.output_workers        = []
        self.protocol              = PROTOCOL_BLE
        self.protocol_freq_channel = 37
        self.protocol_linktype     = PROTOCOL_BLE.get_pcap_header()
        self.initiator_address     = None
        self.verbose_mode          = False
        self.pcap_size             = 0
        # QUEUE
        self.data_queue_lock = threading.Lock()
        self.sniffer_recv_cancel = False
    
    
    def set_output_workers(self, output_workers):
        self.output_workers = output_workers
    
    def set_board_uart(self, board_uart) -> bool:
        self.board_uart.set_serial_port(board_uart)
        return self.board_uart.is_valid_connection()
    
    def set_verbose_mode(self, verbose_mode: bool):
        self.verbose_mode = verbose_mode
    
    def get_protocol_phy(self):
        return self.protocol

    def get_channel(self):
        return self.protocol_freq_channel

    def open_board_uart(self):
        self.board_uart.open()
    
    def set_protocol_phy(self, phy: int):
        """ Set the phy protocol for the sniffer"""
        get_protocol = PROTOCOLSLIST.get_list_protocols()[int(phy)].value
        self.protocol = get_protocol
        self.protocol_linktype = get_protocol.get_pcap_header()
    
    def set_protocol_channel(self, channel: int):
        """ Set the protocol channel for the sniffer"""
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
        self.logger.debug("Send start command")
        get_protocol_commands = self.protocol.command_startup(self.protocol_freq_channel)
        if self.initiator_address:
            get_protocol_commands.insert(4, self.protocol.command_cfg_init_address(self.initiator_address))
        for command in get_protocol_commands:
            self.board_uart.send(command.raw_packet)
            time.sleep(0.1) 
    
    def handle_sniffer_data(self):
        while not self.sniffer_recv_cancel:
            if self.sniffer_data:
                # Send to the dumpers
                for output_worker in self.output_workers:
                    if output_worker.type_worker == "raw":
                        output_worker.add_data(self.sniffer_data.payload)
                    elif output_worker.type_worker == "pcap":
                        version = b'\x00'
                        interfaceType = b'\x00'
                        interfaceId   = bytes.fromhex('0300')
                        protocol      = b'\x03'
                        if self.protocol == PROTOCOL_BLE:
                            protocol = b'\x03'
                        elif self.protocol == PROTOCOL_IEEE:
                            protocol = b'\x02'
                        phy           = bytes.fromhex('05')
                        freq          = bytes.fromhex('62090000')

                        packet = (version + 
                            self.sniffer_data.packet_length.to_bytes(2) + 
                            interfaceType + 
                            interfaceId +
                            protocol +
                            phy +
                            freq +
                            self.sniffer_data.channel +
                            self.sniffer_data.rssi.to_bytes(1) +
                            self.sniffer_data.status.to_bytes(1) +
                            #self.sniffer_data.connect_evt + 
                            #self.sniffer_data.conn_info.to_bytes(1) + 
                            self.sniffer_data.payload
                        )
                        try:
                            pcap_file = Pcap(packet, self.sniffer_data.timestamp)
                            output_worker.set_linktype(self.protocol_linktype)
                            output_worker.add_data(pcap_file.get_pcap())
                        except struct.error as e:
                            print(e)
                            continue
                    else:
                        continue
            else:
                time.sleep(0.01)

    def dissector(self, packet: bytes) -> bytes:
        """Dissector the packet"""
        general_packet = GeneralUARTPacket(packet)
        if general_packet.is_command_response_packet():
            print("Command response packet: ", general_packet.packet_bytes)
            return None

        packet = None
        try:
            if self.protocol == PROTOCOL_BLE:
                data_packet = BLEUARTPacket(general_packet.packet_bytes)
                #print("BLE Packet: ", data_packet)
                packet = data_packet
            else:
                ieee_packet = IEEEUARTPacket(general_packet.packet_bytes)
                #print("IEEE Packet: ", ieee_packet)
                packet = ieee_packet
        except Exception as e:
            print("\nDissector Error -> ", e)
            print("Packet -> ", general_packet)
            return packet

        if self.verbose_mode:
            print("RECV -> ", packet)

        return packet
        

    def recv_worker(self):
        try:
            if self.board_uart.is_connected() == False:
                self.board_uart.open()
            
            self.send_command_start()
            
            while not self.sniffer_recv_cancel:
                time.sleep(0.01)
                frame = self.board_uart.recv()
                if frame is not None:
                    
                    packet_frame = self.dissector(frame)
                    if packet_frame:
                        self.sniffer_data = packet_frame
                    #pcap_file = Pcap(data_packet.packet_bytes[12:-4], data_packet.timestamp)
        
                    #self.fifo_worker.set_linktype(self.protocol_linktype)
                    #self.fifo_worker.add_data(pcap_file.get_pcap())
        except Exception as e:
            #TODO: Hanlde exception
            print(e)
        finally:
            self.close_board_uart()
    
    def run_workers(self):
        # Open output workers
        for output_worker in self.output_workers:
            output_worker.start()
        
        self.sniffer_worker.add_worker(threading.Thread(target=self.recv_worker, daemon=True))
        self.sniffer_worker.add_worker(threading.Thread(target=self.handle_sniffer_data, daemon=True))
        self.sniffer_worker.start_all_workers()
    
    def stop_workers(self):
        self.sniffer_recv_cancel = True
        for output_worker in self.output_workers:
            output_worker.stop()
        print("STOPPING OUTPUT WORKER")
        self.sniffer_worker.stop_all_workers()
        self.output_workers = []
        
    def delete_all_workers(self):
        for output_worker in self.output_workers:
            output_worker.join()
        self.sniffer_worker.delete_all_workers()
        self.output_workers = []
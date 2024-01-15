import time
import struct
import threading
import binascii
from .Worker import WorkerManager
from .UART import UART
from .Pcap import Pcap
from .Fifo import FifoLinux
from .Packets import GeneralUARTPacket, DataUARTPacket
from .Definitions import PCAP_MAX_PACKET_SIZE
from .Protocols import PROTOCOL_BLE, PROTOCOLSLIST
from .Logger import SnifferLogger


class SnifferCollector(threading.Thread, SnifferLogger):
    """Worker class for the sniffer collector"""
    def __init__(self):
        super().__init__()
        self.logger = SnifferLogger().get_logger()
        self.sniffer_data = []
        self.sniffer_worker = WorkerManager()
        self.board_uart = UART()
        self.output_workers = []
        self.fifo_worker = FifoLinux()
        self.wireshark_data = 0
        self.protocol = PROTOCOL_BLE
        self.protocol_freq_channel = 37
        self.initiator_address = None
        self.verbose_mode = False
        self.pcap_size = 0
        # QUEUE
        self.data_queue_lock = threading.Lock()
        self.sniffer_recv_cancel = False
    
    
    def set_output_workers(self, output_workers):
        self.output_workers = output_workers
    
    def set_board_uart(self, board_uart):
        self.board_uart.set_serial_port(board_uart)
    
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
            print(command.raw_packet)
            self.board_uart.send(command.raw_packet)
            time.sleep(0.1)
    
    def handle_sniffer_data(self):
        while not self.sniffer_recv_cancel:
            if self.sniffer_data:
                data = self.sniffer_data.pop(0)
                # Send to the dumpers
                for output_worker in self.output_workers:
                    if output_worker.type_worker == "raw":
                        output_worker.add_data(data)
                    elif output_worker.type_worker == "pcap":
                        self.logger.debug("[SC_RECV] - %s", data)
                        general_packet = GeneralUARTPacket(data)
                        if general_packet.is_data_packet():
                            try:
                                data_packet = DataUARTPacket(general_packet.packet_bytes)
                                
                                #packet = bytes.fromhex('003e000004000305620900002500bc') + data_packet.payload
                                version = b'\x00'
                                # 6 bytes timestamp
                                # 1 byte channel
                                # 2 byte Connection Event
                                # 1 byte Info
                                # 4 Access Address
                                payload       = data_packet.packet_bytes[11:-4]
                                length        = data_packet.packet_length
                                interfaceType = b'\x00'
                                interfaceId   = bytes.fromhex('0300')
                                protocol      = b'\x03'
                                phy           = bytes.fromhex('05')
                                freq          = bytes.fromhex('62090000')
                                channel       = payload[:2]
                                rssi          = data_packet.packet_bytes[-4]
                                status        = data_packet.packet_bytes[-3]
                                blepi         = payload[2:]
                                connection_evt = blepi[:2]
                                con_info = blepi[2]
                                # print("TIMESTAMP", data_packet.timestamp)
                                # print("VERSION", version)
                                # print("PAYLOAD", payload)
                                # print("LENGTH", length)
                                # print("INTERFACE TYPE", interfaceType)
                                # print("INTERFACE ID", interfaceId)
                                # print("PROTOCOL", protocol)
                                # print("PHY", phy)
                                # print("FREQ", freq)
                                # print("CHANNEL", channel)
                                # print("RSSI", rssi)
                                # print("STATUS", status)
                                # print("CONNECTION EVT", connection_evt)
                                # print("CON INFO", con_info)
                                # print("BLEPI", binascii.hexlify(blepi))
                                # print("\n")

                                packet = (version + length.to_bytes(2) + interfaceType + interfaceId + protocol + phy + freq + channel + rssi.to_bytes(1) + status.to_bytes(1) + 
                                            connection_evt + con_info.to_bytes(1) + 
                                            blepi[2:]
                                        )
                                
                                pcap_file = Pcap(packet, data_packet.timestamp)
                                output_worker.add_data(pcap_file.get_pcap())
                                self.pcap_size += len(pcap_file.get_pcap())
                                #TODO: Handle Max PCAP size
                                if self.pcap_size == PCAP_MAX_PACKET_SIZE:
                                    self.logger.debug("[PCAP_SIZE] - %s", self.pcap_size)
                                    self.pcap_size = 0
                            except struct.error as e:
                                self.logger.error(e)
                                continue
                        else:
                            print("Not a data packet", data)
                    else:
                        continue
            else:
                time.sleep(0.1)
    
    def recv_worker(self):
        try:
            if self.board_uart.is_connected() == False:
                self.board_uart.open()
            
            self.send_command_start()
            
            while not self.sniffer_recv_cancel:
                time.sleep(0.01)
                frame = self.board_uart.recv()
                if frame is not None:
                    self.sniffer_data.append(frame)
                    if self.verbose_mode:
                        print(f"[RECV] -> {frame}")
                    self.logger.debug("[SC_RECV] - %s", frame)
                    self.logger.debug("[SC_RECV] - %s", frame)
                    self.wireshark_data += 1
                    general_packet = GeneralUARTPacket(frame)
                    if general_packet.is_data_packet():
                        try:
                            data_packet = DataUARTPacket(general_packet.packet_bytes)
                            
                            #packet = bytes.fromhex('003e000004000305620900002500bc') + data_packet.payload
                            version = b'\x00'
                            # 6 bytes timestamp
                            # 1 byte channel
                            # 2 byte Connection Event
                            # 1 byte Info
                            # 4 Access Address
                            payload       = data_packet.packet_bytes[11:-4]
                            length        = data_packet.packet_length
                            interfaceType = b'\x00'
                            interfaceId   = bytes.fromhex('0300')
                            protocol      = b'\x03'
                            phy           = bytes.fromhex('05')
                            freq          = bytes.fromhex('62090000')
                            channel       = payload[:2]
                            rssi          = data_packet.packet_bytes[-4]
                            status        = data_packet.packet_bytes[-3]
                            blepi         = payload[2:]
                            connection_evt = blepi[:2]
                            con_info = blepi[2]
                            # print("TIMESTAMP", data_packet.timestamp)
                            # print("VERSION", version)
                            # print("PAYLOAD", payload)
                            # print("LENGTH", length)
                            # print("INTERFACE TYPE", interfaceType)
                            # print("INTERFACE ID", interfaceId)
                            # print("PROTOCOL", protocol)
                            # print("PHY", phy)
                            # print("FREQ", freq)
                            # print("CHANNEL", channel)
                            # print("RSSI", rssi)
                            # print("STATUS", status)
                            # print("CONNECTION EVT", connection_evt)
                            # print("CON INFO", con_info)
                            # print("BLEPI", binascii.hexlify(blepi))
                            # print("\n")

                            packet = (version + length.to_bytes(2) + interfaceType + interfaceId + protocol + phy + freq + channel + rssi.to_bytes(1) + status.to_bytes(1) + 
                                        #connection_evt + con_info.to_bytes(1) + 
                                        blepi[2:]
                                    )
                            
                            pcap_file = Pcap(packet, data_packet.timestamp)
                            
                            self.fifo_worker.add_data(pcap_file.get_pcap())
                            self.pcap_size += len(pcap_file.get_pcap())
                            #TODO: Handle Max PCAP size
                            if self.pcap_size == PCAP_MAX_PACKET_SIZE:
                                self.logger.debug("[PCAP_SIZE] - %s", self.pcap_size)
                                self.pcap_size = 0
                        except struct.error as e:
                            self.logger.error(e)
                            continue
                    else:
                        print("Not a frame packet", frame)
        except Exception as e:
            #TODO: Hanlde exception
            print(e)
            self.logger.error(e)
        finally:
            self.close_board_uart()
    
    def run_workers(self):
        # Open output workers
        for output_worker in self.output_workers:
            output_worker.start()
        
        self.sniffer_worker.add_worker(threading.Thread(target=self.recv_worker, daemon=True))
        self.sniffer_worker.add_worker(threading.Thread(target=self.handle_sniffer_data, daemon=True))
        self.sniffer_worker.add_worker(threading.Thread(target=self.fifo_worker.open, daemon=True))
        self.sniffer_worker.start_all_workers()
    
    def stop_workers(self):
        print("="*10, "STOP WORKERS", "="*10)
        print("Data proceced:", self.wireshark_data)
        
        self.sniffer_recv_cancel = True
        for output_worker in self.output_workers:
            output_worker.stop()
        self.sniffer_worker.stop_all_workers()
        self.output_workers = []
        
    def delete_all_workers(self):
        self.sniffer_worker.delete_all_workers()
        self.output_workers = []
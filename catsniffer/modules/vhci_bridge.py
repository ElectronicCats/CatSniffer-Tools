#!/usr/bin/env python3
"""
vhci_bridge.py - Virtual HCI bridge: CatSniffer as /dev/hciX on Linux.

Makes CatSniffer appear as a standard Bluetooth controller to BlueZ,
enabling use with btmon, gatttool, bleak, bettercap, and all standard
Linux BLE tools.

Usage:
    sudo python vhci_bridge.py -p /dev/ttyUSB0

Then use standard tools:
    btmon -i hci1
    gatttool -i hci1 -b AA:BB:CC:DD:EE:FF -I
    bettercap -iface hci1
"""

import os
import sys
import struct
import threading
import logging
import signal
import time
from struct import pack, unpack
from typing import Optional, Callable

# Serial communication
import serial
from serial import Serial

# Rich console for output
from rich.console import Console
from rich.logging import RichHandler

console = Console()

# HCI packet type indicators
HCI_CMD = 0x01
HCI_ACL = 0x02
HCI_SCO = 0x03
HCI_EVT = 0x04

# HCI opcodes we handle
OP_RESET = 0x0C03
OP_READ_LOCAL_VERSION = 0x1001
OP_READ_LOCAL_COMMANDS = 0x1002
OP_READ_LOCAL_FEATURES = 0x1003
OP_READ_BD_ADDR = 0x1009
OP_SET_EVENT_MASK = 0x0C01
OP_LE_SET_EVENT_MASK = 0x2001
OP_LE_READ_BUFFER_SIZE = 0x2002
OP_LE_READ_LOCAL_FEATURES = 0x2003
OP_LE_SET_RANDOM_ADDR = 0x2005
OP_LE_SET_ADV_PARAMS = 0x2006
OP_LE_READ_ADV_TX_POWER = 0x2007
OP_LE_SET_ADV_DATA = 0x2008
OP_LE_SET_SCAN_RSP_DATA = 0x2009
OP_LE_SET_ADV_ENABLE = 0x200A
OP_LE_SET_SCAN_PARAMS = 0x200B
OP_LE_SET_SCAN_ENABLE = 0x200C
OP_LE_CREATE_CONN = 0x200D
OP_LE_CREATE_CONN_CANCEL = 0x200E
OP_LE_READ_WHITE_LIST_SIZE = 0x200F
OP_LE_CLEAR_WHITE_LIST = 0x2010
OP_LE_ADD_DEV_WHITE_LIST = 0x2011
OP_LE_REMOVE_DEV_WHITE_LIST = 0x2012
OP_LE_CONN_UPDATE = 0x2013
OP_LE_SET_HOST_CHAN_CLASS = 0x2014
OP_LE_READ_CHAN_MAP = 0x2015
OP_LE_READ_REMOTE_FEATURES = 0x2016
OP_LE_ENCRYPT = 0x2017
OP_LE_RAND = 0x2018
OP_LE_START_ENCRYPTION = 0x2019
OP_DISCONNECT = 0x0406
OP_READ_RSSI = 0x1405

# HCI event codes
EVT_DISCONN_COMPLETE = 0x05
EVT_ENCRYPTION_CHANGE = 0x08
EVT_CMD_COMPLETE = 0x0E
EVT_CMD_STATUS = 0x0F
EVT_HW_ERROR = 0x10
EVT_NUM_COMPLETED_PACKETS = 0x13
EVT_LE_META = 0x3E

# LE Meta subevent codes
LE_CONN_COMPLETE = 0x01
LE_ADV_REPORT = 0x02
LE_CONN_UPDATE_COMPLETE = 0x03
LE_READ_REMOTE_FEATURES_COMPLETE = 0x04
LE_LTK_REQUEST = 0x05

# Sniffle message types
SNIFFLE_MSG_PACKET = 0x10
SNIFFLE_MSG_DEBUG = 0x11
SNIFFLE_MSG_MARKER = 0x12
SNIFFLE_MSG_STATE = 0x13
SNIFFLE_MSG_MEASUREMENT = 0x14

# Sniffer states
class SnifferState:
    STATIC = 0
    ADVERT_SEEK = 1
    ADVERT_HOP = 2
    DATA = 3
    PAUSED = 4
    INITIATING = 5
    MASTER = 6
    SLAVE = 7
    ADVERTISING = 8
    SCANNING = 9

log = logging.getLogger('vhci_bridge')


def hci_evt(code: int, payload: bytes) -> bytes:
    """Build a complete HCI Event packet (type byte included)."""
    return bytes([HCI_EVT, code, len(payload)]) + payload


def hci_cmd_complete(opcode: int, payload: bytes) -> bytes:
    """Build HCI Command Complete event."""
    return hci_evt(EVT_CMD_COMPLETE,
                   bytes([1]) + pack('<H', opcode) + payload)


def hci_cmd_status(opcode: int, status: int = 0) -> bytes:
    """Build HCI Command Status event."""
    return hci_evt(EVT_CMD_STATUS,
                   bytes([status, 1]) + pack('<H', opcode))


class SniffleProtocol:
    """Sniffle protocol handler for CC1352 communication."""
    
    def __init__(self, serial_port: str, baudrate: int = 2000000):
        self.ser = Serial(serial_port, baudrate, timeout=1.0)
        self._sync()
        
    def _sync(self):
        """Synchronize with Sniffle firmware."""
        self.ser.write(b'@@@@@@@@\r\n')
        time.sleep(0.1)
        self.ser.reset_input_buffer()
        
    def _send_cmd(self, cmd_byte_list: list):
        """Send a command to Sniffle."""
        from base64 import b64encode
        b0 = (len(cmd_byte_list) + 3) // 3
        cmd = bytes([b0, *cmd_byte_list])
        msg = b64encode(cmd) + b'\r\n'
        self.ser.write(msg)
        
    def cmd_reset(self):
        """Reset Sniffle state."""
        self._send_cmd([0x17])
        
    def cmd_setaddr(self, addr: bytes, is_random: bool = True):
        """Set BD_ADDR."""
        if len(addr) != 6:
            raise ValueError("Invalid MAC address")
        self._send_cmd([0x1B, 1 if is_random else 0, *addr])
        
    def cmd_scan(self):
        """Start scanning for advertisements."""
        self._send_cmd([0x22])
        
    def cmd_pause_done(self, pause_when_done: bool = False):
        """Pause when done."""
        self._send_cmd([0x11, 0x01 if pause_when_done else 0x00])
        
    def cmd_advertise(self, adv_data: bytes, scan_rsp_data: bytes = b''):
        """Start advertising."""
        if len(adv_data) > 31:
            raise ValueError("advData too long!")
        if len(scan_rsp_data) > 31:
            raise ValueError("scanRspData too long!")
        padded_adv = [len(adv_data), *adv_data] + [0] * (31 - len(adv_data))
        padded_scan = [len(scan_rsp_data), *scan_rsp_data] + [0] * (31 - len(scan_rsp_data))
        self._send_cmd([0x1C, *padded_adv, *padded_scan])
        
    def cmd_connect(self, peer_addr: bytes, ll_data: bytes, is_random: bool = True):
        """Initiate connection to peer."""
        if len(peer_addr) != 6:
            raise ValueError("Invalid peer address")
        if len(ll_data) != 22:
            raise ValueError("Invalid LLData")
        self._send_cmd([0x1A, 1 if is_random else 0, *peer_addr, *ll_data])
        
    def initiate_conn(self, peer_addr: bytes, is_random: bool = True,
                      interval: int = 24, latency: int = 1) -> int:
        """Initiate connection with auto-generated LLData."""
        from random import randint
        
        ll_data = []
        # Access address
        ll_data.extend([randint(0, 255) for _ in range(4)])
        # Initial CRC
        ll_data.extend([randint(0, 255) for _ in range(3)])
        # WinSize, WinOffset, Interval, Latency, Timeout
        ll_data.append(3)
        ll_data.extend(pack("<H", randint(5, 15)))
        ll_data.extend(pack("<H", interval))
        ll_data.extend(pack("<H", latency))
        ll_data.extend(pack("<H", 50))
        # Channel Map
        ll_data.extend([0xFF, 0xFF, 0xFF, 0xFF, 0x1F])
        # Hop, SCA = 0
        ll_data.append(randint(5, 16))
        
        self.cmd_connect(peer_addr, bytes(ll_data), is_random)
        return unpack("<L", bytes(ll_data[:4]))[0]
        
    def cmd_transmit(self, llid: int, pdu: bytes, event: int = 0):
        """Transmit LL PDU in active connection."""
        if not (0 <= llid <= 3):
            raise ValueError("Out of bounds LLID")
        if len(pdu) > 255:
            raise ValueError("Too long PDU")
        self._send_cmd([0x19, event & 0xFF, event >> 8, llid, len(pdu), *pdu])
        
    def cmd_disconnect(self, reason: int = 0x13):
        """Disconnect by sending LL_TERMINATE_IND."""
        # LL_TERMINATE_IND opcode = 0x02
        self.cmd_transmit(3, bytes([0x02, 0x01, reason]))
        
    def _recv_msg(self) -> tuple:
        """Receive a message from Sniffle."""
        from base64 import b64decode
        from binascii import Error as BAError
        
        while True:
            # Minimum packet is 4 bytes base64 + 2 bytes CRLF
            pkt = self.ser.read(6)
            if len(pkt) < 6:
                continue
                
            try:
                data = b64decode(pkt[:4])
            except BAError:
                self.ser.readline()
                continue
                
            word_cnt = data[0]
            if word_cnt:
                pkt += self.ser.read((word_cnt - 1) * 4)
                
            if pkt[-2:] != b'\r\n':
                self.ser.readline()
                continue
                
            try:
                data = b64decode(pkt[:-2])
            except BAError:
                self.ser.readline()
                continue
                
            return data[1], data[2:]
            
    def recv_and_decode(self):
        """Receive and decode a Sniffle message."""
        mtype, mbody = self._recv_msg()
        
        if mtype == SNIFFLE_MSG_PACKET:
            return self._decode_packet(mbody)
        elif mtype == SNIFFLE_MSG_STATE:
            return self._decode_state(mbody)
        elif mtype == SNIFFLE_MSG_DEBUG:
            return {'type': 'debug', 'msg': mbody.decode('latin-1', errors='ignore')}
        elif mtype == SNIFFLE_MSG_MARKER:
            return {'type': 'marker'}
        elif mtype == SNIFFLE_MSG_MEASUREMENT:
            return {'type': 'measurement', 'value': mbody}
            
        return None
        
    def _decode_packet(self, raw: bytes) -> dict:
        """Decode a packet message."""
        if len(raw) < 10:
            return None
            
        ts, length, event, rssi, chan = unpack("<LHHbB", raw[:10])
        body = raw[10:]
        
        pkt_dir = length >> 15
        length &= 0x7FFF
        
        if len(body) != length:
            return None
            
        phy = chan >> 6
        chan &= 0x3F
        
        return {
            'type': 'packet',
            'ts': ts,
            'rssi': rssi,
            'chan': chan,
            'phy': phy,
            'event': event,
            'body': body,
            'dir': pkt_dir
        }
        
    def _decode_state(self, raw: bytes) -> dict:
        """Decode a state message."""
        if len(raw) < 1:
            return None
        return {
            'type': 'state',
            'new_state': raw[0]
        }
        
    def close(self):
        """Close serial connection."""
        self.ser.close()


class VHCIBridge:
    """
    Virtual HCI bridge daemon.
    
    Translates between BlueZ HCI commands and Sniffle protocol,
    making CatSniffer appear as a standard Bluetooth controller.
    """
    
    def __init__(self, serial_port: str, bd_addr: Optional[bytes] = None):
        self.sniffle = SniffleProtocol(serial_port)
        self.bd_addr = bd_addr or bytes([0xCA, 0x75, 0x4F, 0xEE, 0x01, 0xC0])
        
        # Connection state
        self.conn_handle = 0x0001
        self.active_conn = False
        self.peer_addr = None
        self.peer_addr_type = 0
        
        # Scanning state
        self.scanning = False
        self.scan_params = {'type': 0, 'interval': 0x0010, 'window': 0x0010}
        
        # Advertising state
        self.adv_params = {
            'min_interval': 0x0800,
            'max_interval': 0x0800,
            'type': 0,
            'own_addr_type': 0,
            'peer_addr': b'\x00' * 6,
            'peer_addr_type': 0,
            'channel_map': 0x07,
            'filter_policy': 0
        }
        self.adv_data = b''
        self.scan_rsp_data = b''
        self.advertising = False
        
        # VHCI file descriptor
        self.vhci_fd = None
        self.running = False
        
        # Threads
        self._sniffle_rx_thread = None
        self._hci_rx_thread = None
        
    def start(self):
        """Start the bridge daemon."""
        # Open /dev/vhci
        try:
            self.vhci_fd = os.open('/dev/vhci', os.O_RDWR)
        except PermissionError:
            log.error("Permission denied. Run with sudo.")
            sys.exit(1)
        except FileNotFoundError:
            log.error("/dev/vhci not found. Load vhci module: sudo modprobe hci_vhci")
            sys.exit(1)
            
        log.info("Opened /dev/vhci fd=%d", self.vhci_fd)
        
        # Reset Sniffle
        self.sniffle.cmd_reset()
        time.sleep(0.2)
        
        # Start threads
        self.running = True
        
        self._sniffle_rx_thread = threading.Thread(
            target=self._sniffle_rx_loop,
            daemon=True,
            name='sniffle-rx'
        )
        self._sniffle_rx_thread.start()
        
        self._hci_rx_thread = threading.Thread(
            target=self._hci_rx_loop,
            daemon=True,
            name='hci-rx'
        )
        self._hci_rx_thread.start()
        
        log.info("Bridge running. Waiting for BlueZ to bind...")
        
    def stop(self):
        """Stop the bridge daemon."""
        self.running = False
        if self.vhci_fd is not None:
            os.close(self.vhci_fd)
        self.sniffle.close()
        
    def _write_hci(self, data: bytes):
        """Send HCI packet to BlueZ via vhci."""
        if self.vhci_fd is not None:
            os.write(self.vhci_fd, data)
            
    # ------------------------------------------------------------------
    # BlueZ -> Sniffle: handle incoming HCI commands
    # ------------------------------------------------------------------
    
    def _hci_rx_loop(self):
        """Read HCI commands from BlueZ and process them."""
        while self.running:
            try:
                raw = os.read(self.vhci_fd, 260)
                if not raw:
                    continue
                    
                pkt_type = raw[0]
                if pkt_type == HCI_CMD:
                    self._handle_hci_cmd(raw[1:])
                elif pkt_type == HCI_ACL:
                    self._handle_hci_acl(raw[1:])
                    
            except OSError as e:
                if self.running:
                    log.error("vhci read error: %s", e)
                break
                
    def _handle_hci_cmd(self, data: bytes):
        """Process an HCI command from BlueZ."""
        if len(data) < 3:
            return
            
        opcode, plen = unpack('<HB', data[:3])
        params = data[3:3 + plen]
        
        log.debug("HCI CMD opcode=0x%04X len=%d", opcode, plen)
        
        # --- Initialization commands (synthesize responses locally) ---
        if opcode == OP_RESET:
            self.sniffle.cmd_reset()
            time.sleep(0.1)
            self._write_hci(hci_cmd_complete(opcode, b'\x00'))
            
        elif opcode == OP_READ_LOCAL_VERSION:
            # HCI ver 1.0, rev 0, LMP ver 10 (BT 5.0), manuf 0x05F1 (Electronic Cats), LMP sub 0
            payload = pack('<BBHBHH', 0x00, 0x01, 0x0000, 0x0A, 0x05F1, 0x0000)
            self._write_hci(hci_cmd_complete(opcode, b'\x00' + payload))
            
        elif opcode == OP_READ_LOCAL_COMMANDS:
            # 64-byte bitmask of supported commands
            cmds = bytearray(64)
            cmds[5] |= (1 << 6)   # Disconnect
            cmds[14] |= (1 << 3)  # Reset
            cmds[24] |= (1 << 5)  # Set Event Mask
            cmds[25] |= (1 << 0)  # LE Set Event Mask
            cmds[25] |= (1 << 1)  # LE Read Buffer Size
            cmds[25] |= (1 << 2)  # LE Read Local Supported Features
            cmds[25] |= (1 << 4)  # LE Set Random Address
            cmds[25] |= (1 << 5)  # LE Set Advertising Parameters
            cmds[25] |= (1 << 6)  # LE Read Advertising Channel TX Power
            cmds[25] |= (1 << 7)  # LE Set Advertising Data
            cmds[26] |= (1 << 0)  # LE Set Scan Response Data
            cmds[26] |= (1 << 1)  # LE Set Advertise Enable
            cmds[26] |= (1 << 2)  # LE Set Scan Parameters
            cmds[26] |= (1 << 3)  # LE Set Scan Enable
            cmds[26] |= (1 << 4)  # LE Create Connection
            cmds[26] |= (1 << 5)  # LE Create Connection Cancel
            cmds[26] |= (1 << 6)  # LE Read White List Size
            cmds[26] |= (1 << 7)  # LE Clear White List
            cmds[27] |= (1 << 0)  # LE Add Device To White List
            cmds[27] |= (1 << 1)  # LE Remove Device From White List
            cmds[27] |= (1 << 4)  # LE Encrypt
            cmds[27] |= (1 << 5)  # LE Rand
            cmds[28] |= (1 << 3)  # Read RSSI
            self._write_hci(hci_cmd_complete(opcode, b'\x00' + bytes(cmds)))
            
        elif opcode == OP_READ_LOCAL_FEATURES:
            # Features page 0: LE Supported (bit 6 of byte 4)
            feat = bytearray(8)
            feat[4] |= (1 << 6)  # LE Supported
            self._write_hci(hci_cmd_complete(opcode, b'\x00' + bytes(feat)))
            
        elif opcode == OP_READ_BD_ADDR:
            self._write_hci(hci_cmd_complete(opcode, b'\x00' + self.bd_addr))
            
        elif opcode == OP_SET_EVENT_MASK:
            self._write_hci(hci_cmd_complete(opcode, b'\x00'))
            
        elif opcode == OP_LE_SET_EVENT_MASK:
            self._write_hci(hci_cmd_complete(opcode, b'\x00'))
            
        elif opcode == OP_LE_READ_BUFFER_SIZE:
            # 1 ACL buffer, max 251 bytes each
            self._write_hci(hci_cmd_complete(opcode,
                pack('<HBHB', 0x00, 251, 0x01, 0x00)))
                
        elif opcode == OP_LE_READ_LOCAL_FEATURES:
            # LE Encryption + Connection Parameter Request + Extended Reject
            self._write_hci(hci_cmd_complete(opcode,
                b'\x00' + pack('<Q', 0x0000000000000003)))
                
        elif opcode == OP_LE_READ_ADV_TX_POWER:
            # Return TX power level (0 dBm typical)
            self._write_hci(hci_cmd_complete(opcode, b'\x00\x00'))
            
        elif opcode == OP_LE_READ_WHITE_LIST_SIZE:
            # No white list support
            self._write_hci(hci_cmd_complete(opcode, b'\x00\x00'))
            
        elif opcode == OP_LE_CLEAR_WHITE_LIST:
            self._write_hci(hci_cmd_complete(opcode, b'\x00'))
            
        elif opcode == OP_LE_ADD_DEV_WHITE_LIST:
            self._write_hci(hci_cmd_complete(opcode, b'\x00'))
            
        elif opcode == OP_LE_REMOVE_DEV_WHITE_LIST:
            self._write_hci(hci_cmd_complete(opcode, b'\x00'))
            
        elif opcode == OP_LE_ENCRYPT:
            # Not implemented - return error
            self._write_hci(hci_cmd_complete(opcode, b'\x01'))
            
        elif opcode == OP_LE_RAND:
            # Return random number
            from random import randint
            rand_bytes = bytes([randint(0, 255) for _ in range(8)])
            self._write_hci(hci_cmd_complete(opcode, b'\x00' + rand_bytes))
            
        elif opcode == OP_READ_RSSI:
            if self.active_conn:
                # Return RSSI (simulated)
                self._write_hci(hci_cmd_complete(opcode, b'\x00' + pack('<Hb', self.conn_handle, -50)))
            else:
                self._write_hci(hci_cmd_complete(opcode, b'\x02'))  # Unknown connection
                
        # --- Address configuration ---
        elif opcode == OP_LE_SET_RANDOM_ADDR:
            if len(params) >= 6:
                self.sniffle.cmd_setaddr(params[:6], is_random=True)
            self._write_hci(hci_cmd_complete(opcode, b'\x00'))
            
        # --- Advertising commands ---
        elif opcode == OP_LE_SET_ADV_PARAMS:
            if len(params) >= 15:
                self.adv_params['min_interval'] = unpack('<H', params[0:2])[0]
                self.adv_params['max_interval'] = unpack('<H', params[2:4])[0]
                self.adv_params['type'] = params[4]
                self.adv_params['own_addr_type'] = params[5]
                self.adv_params['peer_addr_type'] = params[6]
                self.adv_params['peer_addr'] = params[7:13]
                self.adv_params['channel_map'] = params[13]
                self.adv_params['filter_policy'] = params[14]
            self._write_hci(hci_cmd_complete(opcode, b'\x00'))
            
        elif opcode == OP_LE_SET_ADV_DATA:
            self.adv_data = params[1:1 + params[0]] if len(params) > 0 else b''
            self._write_hci(hci_cmd_complete(opcode, b'\x00'))
            
        elif opcode == OP_LE_SET_SCAN_RSP_DATA:
            self.scan_rsp_data = params[1:1 + params[0]] if len(params) > 0 else b''
            self._write_hci(hci_cmd_complete(opcode, b'\x00'))
            
        elif opcode == OP_LE_SET_ADV_ENABLE:
            enable = params[0] if len(params) > 0 else 0
            if enable and not self.advertising:
                self.sniffle.cmd_advertise(self.adv_data, self.scan_rsp_data)
                self.advertising = True
            elif not enable and self.advertising:
                self.sniffle.cmd_pause_done(pause_when_done=True)
                self.advertising = False
            self._write_hci(hci_cmd_complete(opcode, b'\x00'))
            
        # --- Scanning commands ---
        elif opcode == OP_LE_SET_SCAN_PARAMS:
            if len(params) >= 7:
                self.scan_params['type'] = params[0]
                self.scan_params['interval'] = unpack('<H', params[1:3])[0]
                self.scan_params['window'] = unpack('<H', params[3:5])[0]
            self._write_hci(hci_cmd_complete(opcode, b'\x00'))
            
        elif opcode == OP_LE_SET_SCAN_ENABLE:
            enable = params[0] if len(params) > 0 else 0
            if enable and not self.scanning:
                self.sniffle.cmd_scan()
                self.scanning = True
            elif not enable and self.scanning:
                self.sniffle.cmd_pause_done(pause_when_done=True)
                self.scanning = False
            self._write_hci(hci_cmd_complete(opcode, b'\x00'))
            
        # --- Connection commands ---
        elif opcode == OP_LE_CREATE_CONN:
            if len(params) >= 25:
                peer_addr_type = params[4]
                peer_addr = params[5:11]
                self.peer_addr = bytes(reversed(peer_addr))
                self.peer_addr_type = peer_addr_type
                is_random = (peer_addr_type in (1, 0x11))
                self.sniffle.initiate_conn(self.peer_addr, is_random=is_random)
                # Command Status (pending) - Connection Complete comes later
                self._write_hci(hci_cmd_status(opcode, status=0))
            else:
                self._write_hci(hci_cmd_complete(opcode, b'\x01'))  # Invalid params
                
        elif opcode == OP_LE_CREATE_CONN_CANCEL:
            self.sniffle.cmd_reset()
            self._write_hci(hci_cmd_complete(opcode, b'\x00'))
            
        elif opcode == OP_DISCONNECT:
            if len(params) >= 3:
                handle, reason = unpack('<HB', params[:3])
                self.sniffle.cmd_disconnect(reason)
                self._write_hci(hci_cmd_status(opcode, status=0))
            else:
                self._write_hci(hci_cmd_complete(opcode, b'\x01'))
                
        else:
            log.warning("Unhandled HCI CMD opcode=0x%04X - sending generic OK", opcode)
            self._write_hci(hci_cmd_complete(opcode, b'\x00'))
            
    def _handle_hci_acl(self, data: bytes):
        """Handle ACL data from BlueZ - forward to Sniffle."""
        if len(data) < 4:
            return
        if not self.active_conn:
            return
            
        handle_flags, total_len = unpack('<HH', data[:4])
        l2cap_payload = data[4:4 + total_len]
        
        # LLID=2 (L2CAP start/continuation)
        self.sniffle.cmd_transmit(2, l2cap_payload)
        
    # ------------------------------------------------------------------
    # Sniffle -> BlueZ: forward received BLE packets as HCI events
    # ------------------------------------------------------------------
    
    def _sniffle_rx_loop(self):
        """Receive Sniffle packets and convert to HCI events for BlueZ."""
        while self.running:
            try:
                msg = self.sniffle.recv_and_decode()
                if msg is None:
                    continue
                    
                if msg['type'] == 'packet':
                    self._handle_sniffle_packet(msg)
                elif msg['type'] == 'state':
                    self._handle_sniffle_state(msg)
                    
            except Exception as e:
                if self.running:
                    log.error("Sniffle RX error: %s", e)
                    
    def _handle_sniffle_packet(self, msg: dict):
        """Process a packet from Sniffle and forward to BlueZ."""
        chan = msg['chan']
        body = msg['body']
        
        if chan >= 37:
            # Advertising channel packet
            self._forward_adv_report(msg)
        else:
            # Data channel packet
            if self.active_conn:
                self._forward_acl_data(msg)
                
    def _handle_sniffle_state(self, msg: dict):
        """Handle state changes from Sniffle."""
        new_state = msg['new_state']
        log.debug("Sniffle state: %d", new_state)
        
        if new_state == SnifferState.MASTER:
            # Connection established (we are central)
            self.active_conn = True
            self._send_conn_complete()
        elif new_state == SnifferState.STATIC:
            # Disconnected
            if self.active_conn:
                self.active_conn = False
                self._send_disconn_complete(0x13)  # Supervision timeout
                
    def _forward_adv_report(self, msg: dict):
        """Convert advertising packet to HCI LE Advertising Report."""
        body = msg['body']
        if len(body) < 8:
            return
            
        # Parse advertising PDU header
        pdu_type = body[0] & 0x0F
        tx_add = (body[0] >> 6) & 1
        rx_add = (body[0] >> 7) & 1
        
        # Extract advertiser address (bytes 2-7)
        adv_addr = body[2:8]
        
        # Extract advertising data
        adv_data = body[8:] if len(body) > 8 else b''
        
        # Map PDU type to HCI event type
        type_map = {
            0: 0x00,  # ADV_IND
            1: 0x01,  # ADV_DIRECT_IND
            2: 0x02,  # ADV_NONCONN_IND
            3: 0x02,  # SCAN_REQ - shouldn't appear as adv report
            4: 0x03,  # SCAN_RSP
            5: 0x04,  # CONNECT_IND
            6: 0x00,  # ADV_SCAN_IND (treat as ADV_IND)
        }
        event_type = type_map.get(pdu_type, 0x00)
        
        # Build LE Advertising Report
        # Subevent 0x02 = LE Advertising Report
        # num_reports=1, event_type, addr_type, addr(6), data_len, data, rssi
        report = pack('<BBBB', LE_ADV_REPORT, 1, event_type, tx_add)
        report += adv_addr
        report += pack('B', len(adv_data)) + adv_data
        report += pack('b', msg['rssi'])
        self._write_hci(hci_evt(EVT_LE_META, report))
        
    def _send_conn_complete(self):
        """Send HCI LE Connection Complete event."""
        # Subevent 0x01 = LE Connection Complete
        payload = pack('<BBHBB', LE_CONN_COMPLETE, 0x00,  # status OK
                       self.conn_handle, 0x00,  # role = central
                       self.peer_addr_type)
        payload += (self.peer_addr or b'\x00' * 6)
        payload += pack('<HHH', 24, 0, 2000)  # interval, latency, timeout
        payload += bytes([0x00])  # clock accuracy
        self._write_hci(hci_evt(EVT_LE_META, payload))
        log.info("Connection complete -> hci handle 0x%04X", self.conn_handle)
        
    def _forward_acl_data(self, msg: dict):
        """Convert data packet to HCI ACL Data packet."""
        body = msg['body']
        if len(body) < 2:
            return
            
        # Skip LL header (first 2 bytes), extract L2CAP
        l2cap = body[2:] if len(body) > 2 else b''
        if not l2cap:
            return
            
        # HCI ACL: handle (12b) + PB flags (2b) + BC flags (2b), total_len
        handle_flags = (self.conn_handle & 0x0FFF) | (0x02 << 12)  # PB=2 (start)
        acl = pack('<HH', handle_flags, len(l2cap)) + l2cap
        self._write_hci(bytes([HCI_ACL]) + acl)
        
    def _send_disconn_complete(self, reason: int):
        """Send HCI Disconnection Complete event."""
        payload = pack('<BHB', 0x00,  # status OK
                       self.conn_handle,
                       reason)
        self._write_hci(hci_evt(EVT_DISCONN_COMPLETE, payload))
        log.info("Disconnection complete, reason=0x%02X", reason)


def main():
    """Main entry point for the vhci bridge."""
    import argparse
    
    # Parse arguments
    ap = argparse.ArgumentParser(description='CatSniffer Virtual HCI Bridge')
    ap.add_argument('-p', '--port', default=None,
                    help='CatSniffer serial port (auto-detect if not specified)')
    ap.add_argument('-d', '--device', type=int, default=None,
                    help='CatSniffer device ID (use first if not specified)')
    ap.add_argument('-a', '--addr', default=None,
                    help='BD_ADDR to present to BlueZ (e.g., C0:FF:EE:C0:FF:EE)')
    ap.add_argument('-v', '--verbose', action='store_true',
                    help='Enable verbose logging')
    args = ap.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s %(name)s %(levelname)s: %(message)s',
        handlers=[RichHandler()]
    )
    
    # Get serial port
    if args.port:
        serial_port = args.port
    else:
        # Try to auto-detect CatSniffer
        try:
            sys.path.insert(0, '/home/wero1414/CatSniffer-Workspace/CatSniffer-Tools/catsniffer')
            from modules.catsniffer import catsniffer_get_device
            device = catsniffer_get_device(args.device)
            if device is None:
                console.print("[red]No CatSniffer device found![/red]")
                console.print("Specify port with -p /dev/ttyUSBx")
                sys.exit(1)
            serial_port = device.bridge_port
            console.print(f"[green]Found CatSniffer: {device.bridge_port}[/green]")
        except ImportError as e:
            console.print(f"[red]Could not import catsniffer module: {e}[/red]")
            console.print("Specify port with -p /dev/ttyUSBx")
            sys.exit(1)
            
    # Parse BD_ADDR
    bd_addr = None
    if args.addr:
        bd_addr = bytes(int(x, 16) for x in args.addr.split(':'))
        
    # Check for root
    if os.geteuid() != 0:
        console.print("[yellow]Warning: Not running as root. May not have access to /dev/vhci[/yellow]")
        
    # Start bridge
    bridge = VHCIBridge(serial_port, bd_addr)
    
    def signal_handler(sig, frame):
        console.print("\n[yellow]Shutting down...[/yellow]")
        bridge.stop()
        sys.exit(0)
        
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    bridge.start()
    
    console.print("[green]Bridge running. Check: hciconfig -a[/green]")
    console.print("[cyan]Use:  btmon -i hci1[/cyan]")
    console.print("[cyan]Use:  gatttool -i hci1 -b TARGET -I[/cyan]")
    
    # Keep running
    while bridge.running:
        time.sleep(1)


if __name__ == '__main__':
    main()

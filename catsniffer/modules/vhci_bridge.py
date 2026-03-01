#!/usr/bin/env python3
"""
vhci_bridge.py - CatSniffer as /dev/hciX on Linux

Uses Sniffle protocol to communicate with CC1352 firmware.
Implements HCI, L2CAP, ATT, and GATT layers.
"""

import os
import sys
import time
import select
import fcntl
import struct
import logging
import signal
from base64 import b64encode, b64decode
from binascii import Error as BAError
from random import randint, randrange
from collections import deque

import serial
from serial import Serial
from rich.console import Console
from rich.logging import RichHandler

console = Console()
log = logging.getLogger('vhci')

# HCI packet types
HCI_CMD = 0x01
HCI_ACL = 0x02
HCI_EVT = 0x04

# HCI event codes
EVT_CMD_COMPLETE = 0x0E
EVT_CMD_STATUS = 0x0F
EVT_DISCONN_COMPLETE = 0x05
EVT_LE_META = 0x3E
EVT_NUM_COMPLETED_PACKETS = 0x13

# LE Meta subevent codes
LE_CONN_COMPLETE = 0x01
LE_ADV_REPORT = 0x02
LE_DATA_LEN_CHANGE = 0x07

# Sniffle message types
SNIFFLE_MSG_PACKET = 0x10
SNIFFLE_MSG_DEBUG = 0x11
SNIFFLE_MSG_MARKER = 0x12
SNIFFLE_MSG_STATE = 0x13

# Sniffle constants
BLE_ADV_AA = 0x8E89BED6
BLE_ADV_CRCI = 0x555555

# L2CAP constants
L2CAP_ATT_CID = 0x0004
L2CAP_SIGNALLING_CID = 0x0005
L2CAP_SMP_CID = 0x0006

# ATT opcodes
ATT_OP_ERROR = 0x01
ATT_OP_MTU_REQ = 0x02
ATT_OP_MTU_RSP = 0x03
ATT_OP_FIND_INFO_REQ = 0x04
ATT_OP_FIND_INFO_RSP = 0x05
ATT_OP_FIND_BY_TYPE_REQ = 0x06
ATT_OP_FIND_BY_TYPE_RSP = 0x07
ATT_OP_READ_BY_TYPE_REQ = 0x08
ATT_OP_READ_BY_TYPE_RSP = 0x09
ATT_OP_READ_REQ = 0x0A
ATT_OP_READ_RSP = 0x0B
ATT_OP_READ_BLOB_REQ = 0x0C
ATT_OP_READ_BLOB_RSP = 0x0D
ATT_OP_READ_MULTIPLE_REQ = 0x0E
ATT_OP_READ_MULTIPLE_RSP = 0x0F
ATT_OP_READ_BY_GROUP_REQ = 0x10
ATT_OP_READ_BY_GROUP_RSP = 0x11
ATT_OP_WRITE_REQ = 0x12
ATT_OP_WRITE_RSP = 0x13
ATT_OP_WRITE_CMD = 0x52
ATT_OP_PREP_WRITE_REQ = 0x16
ATT_OP_PREP_WRITE_RSP = 0x17
ATT_OP_EXEC_WRITE_REQ = 0x18
ATT_OP_EXEC_WRITE_RSP = 0x19
ATT_OP_HANDLE_NTF = 0x1B
ATT_OP_HANDLE_IND = 0x1D
ATT_OP_HANDLE_CNF = 0x1E
ATT_OP_READ_MULTIPLE_VAR_REQ = 0x20
ATT_OP_READ_MULTIPLE_VAR_RSP = 0x21

# ATT Error codes
ATT_ERR_INVALID_HANDLE = 0x01
ATT_ERR_READ_NOT_PERMITTED = 0x02
ATT_ERR_WRITE_NOT_PERMITTED = 0x03
ATT_ERR_INVALID_PDU = 0x04
ATT_ERR_INSUFFICIENT_AUTH = 0x05
ATT_ERR_REQUEST_NOT_SUPPORTED = 0x06
ATT_ERR_INVALID_OFFSET = 0x07
ATT_ERR_INSUFFICIENT_AUTHOR = 0x08
ATT_ERR_PREPARE_QUEUE_FULL = 0x09
ATT_ERR_ATTR_NOT_FOUND = 0x0A
ATT_ERR_ATTR_NOT_LONG = 0x0B
ATT_ERR_INSUFFICIENT_KEY_SIZE = 0x0C
ATT_ERR_INVALID_VAL_LENGTH = 0x0D
ATT_ERR_UNLIKELY = 0x0E
ATT_ERR_INSUFFICIENT_ENC = 0x0F
ATT_ERR_UNSUPPORTED_GROUP = 0x10
ATT_ERR_INSUFFICIENT_RESOURCES = 0x11

# GATT UUIDs (16-bit)
GATT_UUID_PRIMARY_SERVICE = 0x2800
GATT_UUID_SECONDARY_SERVICE = 0x2801
GATT_UUID_INCLUDE = 0x2802
GATT_UUID_CHARACTERISTIC = 0x2803

# Sniffer states
class SnifferState:
    STATIC = 0
    ADVERT_SEEK = 1
    ADVERT_HOP = 2
    DATA = 3
    PAUSED = 4
    INITIATING = 5
    CENTRAL = 6
    PERIPHERAL = 7
    ADVERTISING = 8
    SCANNING = 9


def hci_cc(op, data=b''):
    return bytes([HCI_EVT, EVT_CMD_COMPLETE, 4 + len(data), 1]) + struct.pack('<H', op) + data


def hci_cs(op, status=0):
    return bytes([HCI_EVT, EVT_CMD_STATUS, 4, status, 1]) + struct.pack('<H', op)


class L2CAPChannel:
    """L2CAP channel for segmentation/reassembly."""
    def __init__(self, cid, mtu=23):
        self.cid = cid
        self.mtu = mtu
        self.tx_mtu = 23
        self.rx_buffer = b''
        
class ATTClient:
    """ATT protocol client for GATT operations."""
    def __init__(self, bridge):
        self.bridge = bridge
        self.mtu = 23
        self.pending_req = None
        self.pending_cb = None
        self.req_timeout = 5.0
        
    def send_req(self, pdu, callback=None):
        """Queue an ATT request and send."""
        self.pending_req = pdu
        self.pending_cb = callback
        self.bridge.send_l2cap(L2CAP_ATT_CID, pdu)
        
    def handle_pdu(self, pdu):
        """Handle incoming ATT PDU."""
        if not pdu:
            return
            
        opcode = pdu[0]
        
        # Handle responses
        if opcode in (ATT_OP_MTU_RSP, ATT_OP_FIND_INFO_RSP, ATT_OP_FIND_BY_TYPE_RSP,
                      ATT_OP_READ_BY_TYPE_RSP, ATT_OP_READ_RSP, ATT_OP_READ_BLOB_RSP,
                      ATT_OP_READ_MULTIPLE_RSP, ATT_OP_READ_BY_GROUP_RSP,
                      ATT_OP_WRITE_RSP, ATT_OP_PREP_WRITE_RSP, ATT_OP_EXEC_WRITE_RSP):
            if self.pending_cb:
                self.pending_cb(pdu)
                self.pending_cb = None
            self.pending_req = None
            
        elif opcode == ATT_OP_ERROR:
            log.warning("ATT Error: %s", pdu.hex())
            if self.pending_cb:
                self.pending_cb(pdu)
                self.pending_cb = None
            self.pending_req = None
            
        elif opcode in (ATT_OP_HANDLE_NTF, ATT_OP_HANDLE_IND):
            # Notification/Indication
            if len(pdu) >= 3:
                handle = struct.unpack('<H', pdu[1:3])[0]
                value = pdu[3:]
                log.info("Notification handle=0x%04X value=%s", handle, value.hex())
                
    def exchange_mtu(self, mtu=517):
        """Exchange MTU with peer."""
        self.mtu = mtu
        pdu = struct.pack('<BHH', ATT_OP_MTU_REQ, mtu, 0)[:3]
        pdu = bytes([ATT_OP_MTU_REQ]) + struct.pack('<H', mtu)
        self.send_req(pdu, self._mtu_rsp)
        
    def _mtu_rsp(self, pdu):
        if pdu[0] == ATT_OP_MTU_RSP and len(pdu) >= 3:
            peer_mtu = struct.unpack('<H', pdu[1:3])[0]
            self.mtu = min(self.mtu, peer_mtu)
            log.info("ATT MTU exchanged: %d", self.mtu)
            
    def discover_services(self, start=0x0001, end=0xFFFF, uuid=None):
        """Discover primary services."""
        if uuid:
            uuid_bytes = uuid.to_bytes(2, 'little') if uuid < 0x10000 else uuid.to_bytes(16, 'little')
            pdu = struct.pack('<BHH', ATT_OP_FIND_BY_TYPE_REQ, start, end) + \
                  struct.pack('<H', GATT_UUID_PRIMARY_SERVICE) + uuid_bytes
        else:
            pdu = struct.pack('<BHHHH', ATT_OP_READ_BY_GROUP_REQ, start, end, GATT_UUID_PRIMARY_SERVICE)
        self.send_req(pdu, self._services_rsp)
        
    def _services_rsp(self, pdu):
        opcode = pdu[0]
        if opcode == ATT_OP_READ_BY_GROUP_RSP:
            length = pdu[1]
            services = []
            for i in range(2, len(pdu), length):
                if i + length <= len(pdu):
                    start_handle = struct.unpack('<H', pdu[i:i+2])[0]
                    end_handle = struct.unpack('<H', pdu[i+2:i+4])[0]
                    uuid_bytes = pdu[i+4:i+length]
                    uuid = int.from_bytes(uuid_bytes, 'little')
                    services.append((start_handle, end_handle, uuid))
                    log.info("Service: 0x%04X-0x%04X UUID=%s", start_handle, end_handle, 
                            uuid_bytes.hex())
            return services
        elif opcode == ATT_OP_ERROR:
            log.info("Service discovery complete or error")
            
    def discover_characteristics(self, start=0x0001, end=0xFFFF):
        """Discover characteristics in a service."""
        pdu = struct.pack('<BHHHH', ATT_OP_READ_BY_TYPE_REQ, start, end, 
                          GATT_UUID_CHARACTERISTIC)
        self.send_req(pdu, self._chars_rsp)
        
    def _chars_rsp(self, pdu):
        opcode = pdu[0]
        if opcode == ATT_OP_READ_BY_TYPE_RSP:
            length = pdu[1]
            chars = []
            for i in range(2, len(pdu), length):
                if i + length <= len(pdu):
                    handle = struct.unpack('<H', pdu[i:i+2])[0]
                    props = pdu[i+2]
                    value_handle = struct.unpack('<H', pdu[i+3:i+5])[0]
                    uuid_bytes = pdu[i+5:i+length]
                    uuid = int.from_bytes(uuid_bytes, 'little')
                    chars.append((handle, props, value_handle, uuid))
                    log.info("Characteristic: handle=0x%04X props=0x%02X value=0x%04X UUID=%s",
                            handle, props, value_handle, uuid_bytes.hex())
            return chars
            
    def read(self, handle):
        """Read characteristic value."""
        pdu = struct.pack('<BH', ATT_OP_READ_REQ, handle)
        self.send_req(pdu, self._read_rsp)
        
    def _read_rsp(self, pdu):
        opcode = pdu[0]
        if opcode == ATT_OP_READ_RSP:
            value = pdu[1:]
            log.info("Read value: %s", value.hex())
            return value
            
    def write(self, handle, value, with_response=True):
        """Write characteristic value."""
        if with_response:
            pdu = struct.pack('<BH', ATT_OP_WRITE_REQ, handle) + value
            self.send_req(pdu, self._write_rsp)
        else:
            pdu = struct.pack('<BH', ATT_OP_WRITE_CMD, handle) + value
            self.bridge.send_l2cap(L2CAP_ATT_CID, pdu)
            
    def _write_rsp(self, pdu):
        if pdu[0] == ATT_OP_WRITE_RSP:
            log.info("Write successful")


class Bridge:
    def __init__(self, port):
        self.port = port
        self.bdaddr = bytes([0xC0, 0xFF, 0xEE, 0xC0, 0xFF, 0xEE])
        self.ser = None
        self.vhci = None
        self.running = False
        self.rx_buf = b''
        self.conn_handle = 1
        self.active_conn = False
        self.peer_addr = None
        self.peer_addr_type = 0
        self.vhci_flags = 0
        
        # Advertising state
        self.adv_addr = None
        self.adv_data = b'\x02\x01\x06'
        self.scan_rsp_data = b''
        self.adv_params = {}
        self.advertising = False
        self.scanning = False
        
        # L2CAP/ATT/GATT
        self.acl_mtu = 251
        self.acl_pending = 0
        self.tx_queue = deque(maxlen=8)
        self.att = None
        
        # ACL reassembly
        self.acl_rx_buf = {}
        
    def start(self):
        self.ser = Serial(self.port, 2000000, timeout=1.0)
        
        log.info("Synchronizing with Sniffle firmware...")
        self.ser.write(b'@@@@@@@@\r\n')
        time.sleep(0.2)
        self.ser.reset_input_buffer()
        self.rx_buf = b''
        
        log.info("Resetting sniffer...")
        self._send_cmd([0x17])
        time.sleep(0.5)
        self.ser.reset_input_buffer()
        self.rx_buf = b''
        
        self.ser.timeout = 0
        
        self.vhci = os.open('/dev/vhci', os.O_RDWR)
        init = os.read(self.vhci, 260)
        log.info("VHCI init: %s", init.hex())
        self.vhci_flags = fcntl.fcntl(self.vhci, fcntl.F_GETFL)
        log.info("Started")
        self.running = True
        
    def stop(self):
        self.running = False
        if self.vhci:
            try:
                os.close(self.vhci)
            except:
                pass
        if self.ser:
            try:
                self.ser.close()
            except:
                pass
        
    def _send_cmd(self, cmd_bytes):
        b0 = (len(cmd_bytes) + 3) // 3
        cmd = bytes([b0] + cmd_bytes)
        self.ser.write(b64encode(cmd) + b'\r\n')
        log.debug("TX cmd: %s", cmd.hex())
        
    def _send_tx_packet(self, llid, data, event_ctr=0):
        """Send data packet via COMMAND_TRANSMIT (0x19)."""
        # Format: [eventCtr_lo, eventCtr_hi, LLID, len, data...]
        pkt = [event_ctr & 0xFF, (event_ctr >> 8) & 0xFF, llid, len(data)] + list(data)
        self._send_cmd([0x19] + pkt)
        log.debug("TX L2CAP: LLID=%d len=%d", llid, len(data))
        
    def _recv_msg(self):
        while True:
            if len(self.rx_buf) < 8:
                return None, None
            crlf_pos = self.rx_buf.find(b'\r\n')
            if crlf_pos < 0:
                return None, None
            line = self.rx_buf[:crlf_pos]
            self.rx_buf = self.rx_buf[crlf_pos + 2:]
            if len(line) == 0 or line.startswith(b'@@'):
                continue
            if len(line) % 4 != 0:
                continue
            try:
                data = b64decode(line)
            except BAError:
                continue
            if len(data) < 2:
                continue
            return data[1], data[2:]
        
    def send_l2cap(self, cid, sdu):
        """Send L2CAP SDU (handles segmentation)."""
        # L2CAP header: length (2), cid (2)
        l2cap_pdu = struct.pack('<HH', len(sdu), cid) + sdu
        
        # Fragment into ACL packets
        offset = 0
        first = True
        while offset < len(l2cap_pdu):
            chunk = l2cap_pdu[offset:offset + self.acl_mtu]
            if first:
                pb_flag = 0x00  # First fragment
                first = False
            else:
                pb_flag = 0x01  # Continuation
            self._queue_acl(chunk, pb_flag)
            offset += len(chunk)
            
    def _queue_acl(self, data, pb_flag=0):
        """Queue ACL data for transmission."""
        # ACL header: handle+flags (2), length (2)
        acl_handle = self.conn_handle | (pb_flag << 12)
        acl_pkt = struct.pack('<HH', acl_handle, len(data)) + data
        # Convert to HCI ACL packet and send
        hci_pkt = bytes([HCI_ACL]) + acl_pkt
        try:
            os.write(self.vhci, hci_pkt)
            log.debug("Sent ACL: %s", acl_pkt.hex())
        except Exception as e:
            log.error("ACL write error: %s", e)
            
    def handle_hci(self, data):
        if len(data) < 3:
            return
        op, plen = struct.unpack('<HB', data[:3])
        params = data[3:3+plen]
        log.info("HCI CMD: 0x%04X", op)
        
        if op == 0x0C03:  # Reset
            self._send_cmd([0x17])
            time.sleep(0.1)
            os.write(self.vhci, hci_cc(op, b'\x00'))
            
        elif op == 0x1001:  # Read Local Version
            payload = struct.pack('<BBHBHH', 0x00, 0x01, 0x0000, 0x0A, 0x05F1, 0x0000)
            os.write(self.vhci, hci_cc(op, b'\x00' + payload))
            
        elif op == 0x1002:  # Read Local Supported Commands
            cmds = bytearray(64)
            cmds[5] |= (1 << 6)
            cmds[14] |= (1 << 3)
            cmds[24] |= (1 << 5)
            cmds[25] |= 0xFF
            cmds[26] |= 0x3F
            cmds[28] |= (1 << 3)
            os.write(self.vhci, hci_cc(op, b'\x00' + bytes(cmds)))
            
        elif op == 0x1003:  # Read Local Supported Features
            feat = bytearray(8)
            feat[4] |= (1 << 6)
            os.write(self.vhci, hci_cc(op, b'\x00' + bytes(feat)))
            
        elif op == 0x1005:  # Read Buffer Size
            os.write(self.vhci, hci_cc(op, b'\x00' + struct.pack('<BHBHB', 1, 255, 0, 15, 0)))
            
        elif op == 0x1009:  # Read BD_ADDR
            os.write(self.vhci, hci_cc(op, b'\x00' + self.bdaddr[::-1]))
            
        elif op == 0x0C14:  # Read Local Name
            os.write(self.vhci, hci_cc(op, b'\x00' + b'CatSniffer' + b'\x00' * 238))
            
        elif op == 0x0C01:  # Set Event Mask
            os.write(self.vhci, hci_cc(op, b'\x00'))
            
        elif op == 0x2001:  # LE Set Event Mask
            os.write(self.vhci, hci_cc(op, b'\x00'))
            
        elif op == 0x2002:  # LE Read Buffer Size
            os.write(self.vhci, hci_cc(op, b'\x00' + struct.pack('<HB', 251, 15)))
            
        elif op == 0x2003:  # LE Read Local Supported Features
            os.write(self.vhci, hci_cc(op, b'\x00' + bytes([0x03] + [0]*7)))
            
        elif op == 0x2005:  # LE Set Random Address
            if plen >= 6:
                self.adv_addr = params[:6]
                self._send_cmd([0x1B, 1] + list(params[:6]))
                log.info("Set advertising address: %s", params[:6][::-1].hex())
            os.write(self.vhci, hci_cc(op, b'\x00'))
            
        elif op == 0x200B:  # LE Set Scan Parameters
            os.write(self.vhci, hci_cc(op, b'\x00'))
            
        elif op == 0x200C:  # LE Set Scan Enable
            enable = params[0] if plen > 0 else 0
            log.info("Scan enable: %d", enable)
            os.write(self.vhci, hci_cc(op, b'\x00'))
            
            if enable and self.advertising:
                self._send_cmd([0x11, 0])
                self.advertising = False
                
            if enable and not self.scanning:
                cmd = [0x10, 37]
                cmd.extend(struct.pack('<L', BLE_ADV_AA))
                cmd.append(0)
                cmd.extend(struct.pack('<L', BLE_ADV_CRCI))
                self._send_cmd(cmd)
                time.sleep(0.05)
                self._send_cmd([0x22])
                self.scanning = True
            elif not enable and self.scanning:
                self._send_cmd([0x11, 0])
                self.scanning = False
                
        elif op == 0x2007:  # LE Read Adv TX Power
            os.write(self.vhci, hci_cc(op, b'\x00\x05'))
            
        elif op == 0x2006:  # LE Set Advertising Parameters
            if plen >= 15:
                self.adv_params = {
                    'min_interval': struct.unpack('<H', params[0:2])[0],
                    'max_interval': struct.unpack('<H', params[2:4])[0],
                    'type': params[4],
                    'own_addr_type': params[5],
                    'channel_map': params[13],
                }
            os.write(self.vhci, hci_cc(op, b'\x00'))
            
        elif op == 0x2008:  # LE Set Advertising Data
            if plen >= 1:
                data_len = params[0]
                self.adv_data = params[1:1+data_len] if data_len > 0 else b''
                log.info("Set adv data: %s", self.adv_data.hex())
            os.write(self.vhci, hci_cc(op, b'\x00'))
            
        elif op == 0x2009:  # LE Set Scan Response Data
            if plen >= 1:
                data_len = params[0]
                self.scan_rsp_data = params[1:1+data_len] if data_len > 0 else b''
                log.info("Set scan rsp: %s", self.scan_rsp_data.hex())
            os.write(self.vhci, hci_cc(op, b'\x00'))
            
        elif op == 0x200A:  # LE Set Advertise Enable
            enable = params[0] if plen > 0 else 0
            log.info("Advertise enable: %d", enable)
            os.write(self.vhci, hci_cc(op, b'\x00'))
            
            if enable and not self.advertising:
                if self.scanning:
                    self._send_cmd([0x11, 0])
                    self.scanning = False
                    
                if self.adv_addr:
                    self._send_cmd([0x1B, 1] + list(self.adv_addr))
                    time.sleep(0.05)
                
                adv_type = self.adv_params.get('type', 0)
                mode = 0  # ADV_IND
                
                padded_adv = [len(self.adv_data)] + list(self.adv_data) + [0] * (31 - len(self.adv_data))
                padded_scan = [len(self.scan_rsp_data)] + list(self.scan_rsp_data) + [0] * (31 - len(self.scan_rsp_data))
                
                cmd = [0x1C, mode] + padded_adv + padded_scan
                self._send_cmd(cmd)
                self.advertising = True
                log.info("Advertising started with MAC: %s", 
                        (self.adv_addr or self.bdaddr)[::-1].hex())
                
            elif not enable and self.advertising:
                self._send_cmd([0x11, 0])
                self.advertising = False
                log.info("Advertising stopped")
                
        elif op == 0x200D:  # LE Create Connection
            if plen >= 25:
                peer_addr_type = params[4]
                peer_addr = params[5:11]
                self.peer_addr = bytes(reversed(peer_addr))
                self.peer_addr_type = peer_addr_type
                is_random = (peer_addr_type in (1, 0x11))
                
                if self.scanning or self.advertising:
                    self._send_cmd([0x11, 0])
                    self.scanning = False
                    self.advertising = False
                    
                if self.adv_addr:
                    self._send_cmd([0x1B, 1] + list(self.adv_addr))
                    time.sleep(0.05)
                
                lldata = []
                lldata.extend([randrange(0x100) for _ in range(4)])
                lldata.extend([randrange(0x100) for _ in range(3)])
                lldata.append(3)
                lldata.extend(struct.pack("<H", randint(5, 15)))
                lldata.extend(struct.pack("<H", 24))
                lldata.extend(struct.pack("<H", 1))
                lldata.extend(struct.pack("<H", 50))
                lldata.extend([0xFF, 0xFF, 0xFF, 0xFF, 0x1F])
                lldata.append(randint(5, 16))
                
                self._send_cmd([0x1A, 1 if is_random else 0] + list(self.peer_addr) + lldata)
                os.write(self.vhci, hci_cs(op, 0))
                log.info("Connecting to %s", self.peer_addr.hex())
            else:
                os.write(self.vhci, hci_cc(op, b'\x01'))
                
        elif op == 0x200E:  # LE Create Connection Cancel
            self._send_cmd([0x17])
            os.write(self.vhci, hci_cc(op, b'\x00'))
            
        elif op == 0x0406:  # Disconnect
            if plen >= 3:
                handle, reason = struct.unpack('<HB', params[:3])
                self._send_cmd([0x19, 0, 0, 3, 3, 0x02, 0x01, reason])
                os.write(self.vhci, hci_cs(op, 0))
            else:
                os.write(self.vhci, hci_cc(op, b'\x01'))
                
        elif op == 0x1405:  # Read RSSI
            if self.active_conn:
                os.write(self.vhci, hci_cc(op, b'\x00' + struct.pack('<Hb', self.conn_handle, -50)))
            else:
                os.write(self.vhci, hci_cc(op, b'\x02'))
                
        # ACL data handling
        elif op == 0x0C1B:  # Read Data Block Size
            os.write(self.vhci, hci_cc(op, b'\x00' + struct.pack('<HIHH', 1, 251, 1, 15)))
            
        elif op == 0x0C27:  # Read Default Data Length
            os.write(self.vhci, hci_cc(op, b'\x00' + struct.pack('<HH', 27, 328)))
            
        elif op == 0x201C:  # LE Read Suggested Default Data Length
            os.write(self.vhci, hci_cc(op, b'\x00' + struct.pack('<HHHH', 251, 2120, 251, 2120)))
            
        elif op in (0x0C13, 0x0C24, 0x0C6D):
            os.write(self.vhci, hci_cc(op, b'\x00'))
        elif op == 0x0C16:
            os.write(self.vhci, hci_cc(op, b'\x00' + struct.pack('<H', 0x8000)))
        elif op == 0x0C23:
            os.write(self.vhci, hci_cc(op, b'\x00' + struct.pack('<BH', 0, 0)))
        elif op in (0x0C38, 0x0C39):
            os.write(self.vhci, hci_cc(op, b'\x00\x00'))
        else:
            log.warning("Unhandled: 0x%04X", op)
            os.write(self.vhci, hci_cc(op, b'\x00'))
            
    def handle_acl(self, data):
        """Handle incoming ACL data from BlueZ (host -> controller)."""
        if len(data) < 4:
            return
            
        handle_flags, length = struct.unpack('<HH', data[:4])
        handle = handle_flags & 0x0FFF
        pb_flag = (handle_flags >> 12) & 0x03
        
        acl_data = data[4:4+length]
        if len(acl_data) < length:
            log.warning("ACL truncated: expected %d, got %d", length, len(acl_data))
            return
            
        log.debug("ACL RX: handle=0x%04X pb=%d len=%d", handle, pb_flag, length)
        
        if pb_flag == 0x00:  # First fragment (or complete)
            self.acl_rx_buf[handle] = acl_data
        elif pb_flag == 0x01:  # Continuation
            if handle in self.acl_rx_buf:
                self.acl_rx_buf[handle] += acl_data
            else:
                log.warning("ACL continuation without start")
                return
                
        # Check if we have complete L2CAP frame
        if handle in self.acl_rx_buf:
            buf = self.acl_rx_buf[handle]
            if len(buf) >= 4:
                l2cap_len, cid = struct.unpack('<HH', buf[:4])
                if len(buf) >= 4 + l2cap_len:
                    # Complete L2CAP frame
                    l2cap_sdu = buf[4:4+l2cap_len]
                    self.handle_l2cap(cid, l2cap_sdu)
                    # Remove processed data
                    self.acl_rx_buf[handle] = buf[4+l2cap_len:]
                    
    def handle_l2cap(self, cid, sdu):
        """Handle L2CAP SDU."""
        log.debug("L2CAP: cid=0x%04X len=%d", cid, len(sdu))
        
        if cid == L2CAP_ATT_CID:
            self.handle_att(sdu)
        elif cid == L2CAP_SIGNALLING_CID:
            self.handle_l2cap_sig(sdu)
        elif cid == L2CAP_SMP_CID:
            self.handle_smp(sdu)
        else:
            log.warning("Unknown L2CAP CID: 0x%04X", cid)
            
    def handle_att(self, pdu):
        """Handle ATT PDU from host (forward to device)."""
        if not pdu:
            return
        opcode = pdu[0]
        log.info("ATT TX: opcode=0x%02X %s", opcode, pdu.hex())
        
        # Forward to device via COMMAND_TRANSMIT
        # LLID = 0x02 for L2CAP data
        self._send_tx_packet(0x02, struct.pack('<HH', len(pdu) + 4, L2CAP_ATT_CID) + pdu)
        
    def handle_l2cap_sig(self, pdu):
        """Handle L2CAP signalling."""
        if len(pdu) < 4:
            return
        code, ident, length = struct.unpack('<BBH', pdu[:4])
        log.debug("L2CAP SIG: code=0x%02X ident=%d len=%d", code, ident, length)
        
        # Forward to device
        self._send_tx_packet(0x02, struct.pack('<HH', len(pdu) + 4, L2CAP_SIGNALLING_CID) + pdu)
        
    def handle_smp(self, pdu):
        """Handle SMP (Security Manager Protocol)."""
        if not pdu:
            return
        code = pdu[0]
        log.info("SMP: code=0x%02X", code)
        
        # Forward to device
        self._send_tx_packet(0x02, struct.pack('<HH', len(pdu) + 4, L2CAP_SMP_CID) + pdu)
            
    def handle_packet(self, raw):
        if len(raw) < 10:
            return
        ts, length, event, rssi, chan_phy = struct.unpack("<LHHbB", raw[:10])
        body = raw[10:]
        pkt_len = length & 0x7FFF
        chan = chan_phy & 0x3F
        
        # Data channel packets (0-36)
        if chan < 37:
            self.handle_data_packet(body, pkt_len, chan)
            return
            
        # Advertising channel (37-39)
        if len(body) != pkt_len or pkt_len < 6:
            return
            
        pdu_type = body[0] & 0x0F
        tx_add = (body[0] >> 6) & 1
        adv_addr = body[2:8]
        adv_data = body[8:] if pkt_len > 8 else b''
        type_map = {0: 0, 1: 1, 2: 2, 4: 3, 5: 4, 6: 0}
        evt_type = type_map.get(pdu_type, 0)
        report = struct.pack('<BBBB', LE_ADV_REPORT, 1, evt_type, tx_add)
        report += adv_addr
        report += struct.pack('B', len(adv_data)) + adv_data
        report += struct.pack('b', rssi)
        evt = bytes([HCI_EVT, EVT_LE_META, len(report)]) + report
        try:
            os.write(self.vhci, evt)
        except Exception as e:
            log.error("Write error: %s", e)
            
    def handle_data_packet(self, body, pkt_len, chan):
        """Handle data channel packet (connected state)."""
        if pkt_len < 2:
            return
            
        # Parse LL header
        llid = body[0] & 0x03
        nesn = (body[0] >> 2) & 1
        sn = (body[0] >> 3) & 1
        md = (body[0] >> 4) & 1
        data_len = body[1]
        
        if llid == 0x00:  # Reserved
            return
        elif llid == 0x01:  # L2CAP continuation or empty
            if data_len == 0:
                return  # Empty PDU
            log.debug("LL continuation: %d bytes", data_len)
        elif llid == 0x02:  # L2CAP start
            log.debug("LL data: %d bytes", data_len)
        elif llid == 0x03:  # LL Control
            opcode = body[2] if data_len > 0 else 0
            log.debug("LL Control: opcode=0x%02X", opcode)
            self.handle_ll_control(body[2:2+data_len])
            return
            
        # Forward as HCI ACL
        ll_data = body[2:2+data_len]
        if len(ll_data) < 4:
            return
            
        # Parse L2CAP header
        l2cap_len, cid = struct.unpack('<HH', ll_data[:4])
        
        # Build ACL packet
        handle_flags = self.conn_handle  # PB flag = 0 (first/complete)
        acl_pkt = struct.pack('<HH', handle_flags, len(ll_data)) + ll_data
        hci_pkt = bytes([HCI_ACL]) + acl_pkt
        
        try:
            os.write(self.vhci, hci_pkt)
            log.debug("Sent ACL to host: cid=0x%04X len=%d", cid, l2cap_len)
        except Exception as e:
            log.error("ACL to host error: %s", e)
            
    def handle_ll_control(self, data):
        """Handle LL Control PDUs."""
        if not data:
            return
        opcode = data[0]
        log.info("LL Control: opcode=0x%02X data=%s", opcode, data.hex())
        
        # TODO: Handle connection update, channel map, etc.
            
    def handle_state(self, raw):
        if len(raw) < 1:
            return
        state = raw[0]
        log.info("State: %d", state)
        if state == SnifferState.CENTRAL:
            self.active_conn = True
            self.att = ATTClient(self)
            self._send_conn_complete(role=0)
        elif state == SnifferState.PERIPHERAL:
            self.active_conn = True
            self.att = ATTClient(self)
            self._send_conn_complete(role=1)
        elif state == SnifferState.STATIC:
            if self.active_conn:
                self.active_conn = False
                self.att = None
                self._send_disconn_complete(0x13)
                
    def _send_conn_complete(self, role=0):
        payload = struct.pack('<BBBBB', LE_CONN_COMPLETE, 0x00,
                              self.conn_handle & 0xFF,
                              (self.conn_handle >> 8) & 0x0F, role)
        payload += bytes([self.peer_addr_type]) + (self.peer_addr or b'\x00'*6)
        payload += struct.pack('<HHH', 24, 0, 2000) + bytes([0x00])
        os.write(self.vhci, bytes([HCI_EVT, EVT_LE_META, len(payload)]) + payload)
        log.info("Connection complete -> 0x%04X", self.conn_handle)
        
    def _send_disconn_complete(self, reason):
        payload = struct.pack('<BHB', 0x00, self.conn_handle, reason)
        os.write(self.vhci, bytes([HCI_EVT, EVT_DISCONN_COMPLETE, len(payload)]) + payload)
        log.info("Disconnection complete, reason=0x%02X", reason)
        
    def run(self):
        while self.running:
            fcntl.fcntl(self.vhci, fcntl.F_SETFL, self.vhci_flags | os.O_NONBLOCK)
            
            # Check for HCI commands from BlueZ
            try:
                r, _, _ = select.select([self.vhci], [], [], 0.001)
                while r:
                    try:
                        d = os.read(self.vhci, 260)
                        if d:
                            if d[0] == HCI_CMD:
                                self.handle_hci(d[1:])
                            elif d[0] == HCI_ACL:
                                self.handle_acl(d[1:])
                        r, _, _ = select.select([self.vhci], [], [], 0)
                    except BlockingIOError:
                        break
            except Exception as e:
                if self.running:
                    log.error("VHCI error: %s", e)
                    
            try:
                if self.ser.in_waiting > 0:
                    self.rx_buf += self.ser.read(self.ser.in_waiting)
            except:
                pass
                
            while True:
                mt, mb = self._recv_msg()
                if mt is None:
                    break
                if mt == SNIFFLE_MSG_PACKET:
                    self.handle_packet(mb)
                elif mt == SNIFFLE_MSG_STATE:
                    self.handle_state(mb)
                elif mt == SNIFFLE_MSG_DEBUG:
                    log.debug("Debug: %s", mb.decode('latin-1', errors='ignore'))


class VHCIBridge(Bridge):
    pass


def main():
    import argparse
    ap = argparse.ArgumentParser(description='CatSniffer Virtual HCI Bridge')
    ap.add_argument('-p', '--port', required=True)
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, handlers=[RichHandler()])
    if os.geteuid() != 0:
        console.print("[yellow]Warning: Need root for /dev/vhci[/yellow]")
    b = Bridge(args.port)
    signal.signal(signal.SIGINT, lambda s,f: (b.stop(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda s,f: (b.stop(), sys.exit(0)))
    b.start()
    console.print("[green]Running. Check: hciconfig -a[/green]")
    b.run()


if __name__ == '__main__':
    main()

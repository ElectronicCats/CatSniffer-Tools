#!/usr/bin/env python3
"""
vhci_bridge.py - CatSniffer as /dev/hciX on Linux

Uses Sniffle protocol to communicate with CC1352 firmware.
Based on: https://github.com/nccgroup/Sniffle
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

# LE Meta subevent codes
LE_CONN_COMPLETE = 0x01
LE_ADV_REPORT = 0x02

# Sniffle message types
SNIFFLE_MSG_PACKET = 0x10
SNIFFLE_MSG_DEBUG = 0x11
SNIFFLE_MSG_MARKER = 0x12
SNIFFLE_MSG_STATE = 0x13
SNIFFLE_MSG_MEASUREMENT = 0x14

# Sniffle constants
BLE_ADV_AA = 0x8E89BED6
BLE_ADV_CRCI = 0x555555

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
    """Build HCI Command Complete event."""
    return bytes([HCI_EVT, EVT_CMD_COMPLETE, 4 + len(data), 1]) + struct.pack('<H', op) + data


def hci_cs(op, status=0):
    """Build HCI Command Status event."""
    return bytes([HCI_EVT, EVT_CMD_STATUS, 4, status, 1]) + struct.pack('<H', op)


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
        
    def _recv_msg(self):
        """Receive and decode a Sniffle message."""
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
                
            # Don't validate word_cnt - just extract type and body
            msg_type = data[1]
            msg_body = data[2:]
            
            return msg_type, msg_body
        
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
                self._send_cmd([0x1B, 1] + list(params[:6]))
            os.write(self.vhci, hci_cc(op, b'\x00'))
            
        elif op == 0x200B:  # LE Set Scan Parameters
            os.write(self.vhci, hci_cc(op, b'\x00'))
            
        elif op == 0x200C:  # LE Set Scan Enable
            enable = params[0] if plen > 0 else 0
            log.info("Scan enable: %d", enable)
            os.write(self.vhci, hci_cc(op, b'\x00'))
            if enable:
                cmd = [0x10, 37]
                cmd.extend(struct.pack('<L', BLE_ADV_AA))
                cmd.append(0)
                cmd.extend(struct.pack('<L', BLE_ADV_CRCI))
                self._send_cmd(cmd)
                time.sleep(0.05)
                self._send_cmd([0x22])
            else:
                self._send_cmd([0x11, 0])
                
        elif op == 0x2007:  # LE Read Adv TX Power
            os.write(self.vhci, hci_cc(op, b'\x00\x05'))
            
        elif op in (0x2006, 0x2008, 0x2009, 0x200A):  # Adv params/data/enable
            os.write(self.vhci, hci_cc(op, b'\x00'))
            
        elif op == 0x200D:  # LE Create Connection
            if plen >= 25:
                peer_addr_type = params[4]
                peer_addr = params[5:11]
                self.peer_addr = bytes(reversed(peer_addr))
                self.peer_addr_type = peer_addr_type
                is_random = (peer_addr_type in (1, 0x11))
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
                
        # Generic handlers
        elif op in (0x0C13, 0x0C24, 0x0C6D):
            os.write(self.vhci, hci_cc(op, b'\x00'))
        elif op == 0x0C16:
            os.write(self.vhci, hci_cc(op, b'\x00' + struct.pack('<H', 0x8000)))
        elif op == 0x0C23:
            os.write(self.vhci, hci_cc(op, b'\x00' + struct.pack('<BH', 0, 0)))
        elif op in (0x0C38, 0x0C39):
            os.write(self.vhci, hci_cc(op, b'\x00\x00'))
        elif op == 0x201C:
            os.write(self.vhci, hci_cc(op, b'\x00' + struct.pack('<HHHH', 251, 2120, 251, 2120)))
        else:
            log.warning("Unhandled: 0x%04X", op)
            os.write(self.vhci, hci_cc(op, b'\x00'))
            
    def handle_packet(self, raw):
        """Handle a Sniffle packet message (type 0x10)."""
        if len(raw) < 10:
            return
            
        ts, length, event, rssi, chan_phy = struct.unpack("<LHHbB", raw[:10])
        body = raw[10:]
        
        pkt_len = length & 0x7FFF
        chan = chan_phy & 0x3F
        
        if chan < 37:  # Only advertising channels
            return
            
        if len(body) != pkt_len:
            return
            
        if pkt_len < 6:
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
            log.debug("Adv report: %s rssi=%d", adv_addr.hex(), rssi)
        except Exception as e:
            log.error("Write error: %s", e)
            
    def handle_state(self, raw):
        if len(raw) < 1:
            return
        state = raw[0]
        log.info("State: %d", state)
        
        if state == SnifferState.CENTRAL:
            self.active_conn = True
            self._send_conn_complete()
        elif state == SnifferState.STATIC:
            if self.active_conn:
                self.active_conn = False
                self._send_disconn_complete(0x13)
                
    def _send_conn_complete(self):
        payload = struct.pack('<BBBBB', LE_CONN_COMPLETE, 0x00,
                              self.conn_handle & 0xFF,
                              (self.conn_handle >> 8) & 0x0F, 0x00)
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
            
            try:
                r, _, _ = select.select([self.vhci], [], [], 0.001)
                while r:
                    try:
                        d = os.read(self.vhci, 260)
                        if d and d[0] == HCI_CMD:
                            self.handle_hci(d[1:])
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

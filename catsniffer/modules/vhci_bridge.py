#!/usr/bin/env python3
"""
vhci_bridge.py - Virtual HCI bridge: CatSniffer as /dev/hciX on Linux.
Uses raw os calls for serial to avoid pyserial/vhci interaction issues.
"""

import os
import sys
import termios
import select
import signal
import time
import logging
from struct import pack, unpack
from base64 import b64encode, b64decode
from binascii import Error as BAError
from rich.console import Console
from rich.logging import RichHandler

console = Console()

# HCI constants
HCI_CMD = 0x01
HCI_ACL = 0x02
HCI_EVT = 0x04
EVT_CMD_COMPLETE = 0x0E
EVT_CMD_STATUS = 0x0F
EVT_LE_META = 0x3E
EVT_DISCONN_COMPLETE = 0x05
LE_CONN_COMPLETE = 0x01
LE_ADV_REPORT = 0x02

# HCI opcodes
OP_RESET = 0x0C03
OP_READ_LOCAL_VERSION = 0x1001
OP_READ_LOCAL_COMMANDS = 0x1002
OP_READ_LOCAL_FEATURES = 0x1003
OP_READ_BD_ADDR = 0x1009
OP_LE_SET_SCAN_ENABLE = 0x200C
OP_LE_CREATE_CONN = 0x200D
OP_DISCONNECT = 0x0406

SNIFFLE_MSG_PACKET = 0x10
SNIFFLE_MSG_STATE = 0x13

log = logging.getLogger('vhci_bridge')


def hci_evt(code, payload):
    return bytes([HCI_EVT, code, len(payload)]) + payload

def hci_cmd_complete(opcode, payload):
    return hci_evt(EVT_CMD_COMPLETE, bytes([1]) + pack('<H', opcode) + payload)

def hci_cmd_status(opcode, status=0):
    return hci_evt(EVT_CMD_STATUS, bytes([status, 1]) + pack('<H', opcode))


class VHCIBridge:
    def __init__(self, port, bd_addr=None):
        self.port = port
        self.bd_addr = bd_addr or bytes([0xCA, 0x75, 0x4F, 0xEE, 0x01, 0xC0])
        self.ser_fd = None
        self.vhci_fd = None
        self.running = False
        self.conn_handle = 1
        self.active_conn = False
        self.peer_addr = None
        self.peer_addr_type = 0
        self.rx_buf = b''
        
    def _ser_write(self, data):
        os.write(self.ser_fd, data)
        
    def _ser_read(self, n=4096):
        try:
            return os.read(self.ser_fd, n)
        except BlockingIOError:
            return b''
            
    def _send_cmd(self, cmd_bytes):
        b0 = (len(cmd_bytes) + 3) // 3
        self._ser_write(b64encode(bytes([b0, *cmd_bytes])) + b'\r\n')
        
    def _recv_msg(self):
        """Try to decode one Sniffle message from rx_buf."""
        while len(self.rx_buf) >= 6:
            pkt = self.rx_buf[:6]
            try:
                data = b64decode(pkt[:4])
            except BAError:
                self.rx_buf = self.rx_buf[1:]
                continue
                
            word_cnt = data[0]
            total_len = word_cnt * 4 if word_cnt else 4
            
            if len(self.rx_buf) < total_len + 2:  # +2 for CRLF
                return None  # Need more data
                
            pkt = self.rx_buf[:total_len + 2]
            if pkt[-2:] != b'\r\n':
                self.rx_buf = self.rx_buf[1:]
                continue
                
            self.rx_buf = self.rx_buf[total_len + 2:]
            
            try:
                data = b64decode(pkt[:-2])
            except BAError:
                continue
                
            return data[1], data[2:]
        return None
        
    def start(self):
        # Open serial with raw os calls
        self.ser_fd = os.open(self.port, os.O_RDWR | os.O_NONBLOCK)
        attrs = termios.tcgetattr(self.ser_fd)
        attrs[2] = termios.B2000000 | termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[3] = 0
        attrs[4] = termios.B2000000
        attrs[5] = termios.B2000000
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(self.ser_fd, termios.TCSANOW, attrs)
        
        # Sync with Sniffle
        self._ser_write(b'@@@@@@@@\r\n')
        time.sleep(0.1)
        termios.tcflush(self.ser_fd, termios.TCIFLUSH)
        log.info("Serial opened: %s fd=%d", self.port, self.ser_fd)
        
        # Open vhci
        self.vhci_fd = os.open('/dev/vhci', os.O_RDWR)
        # Read initial vendor packet (ignored for now)
        init = os.read(self.vhci_fd, 260)
        log.info("Opened /dev/vhci fd=%d, init=%s", self.vhci_fd, init.hex())
        
        self.running = True
        
    def stop(self):
        self.running = False
        if self.vhci_fd:
            os.close(self.vhci_fd)
        if self.ser_fd:
            os.close(self.ser_fd)
            
    def _write_hci(self, data):
        if self.vhci_fd is None:
            return
        log.debug("HCI TX: %s", data.hex())
        try:
            os.write(self.vhci_fd, data)
        except OSError as e:
            if e.errno == 6:  # ENXIO - device closed
                self.running = False
                log.error("VHCI device closed by kernel")
            raise
        
    def _handle_hci_cmd(self, data):
        if len(data) < 3:
            return
        opcode, plen = unpack('<HB', data[:3])
        params = data[3:3+plen]
        log.debug("HCI CMD 0x%04X", opcode)
        
        if opcode == OP_RESET:
            self._send_cmd([0x17])
            time.sleep(0.05)
            resp = hci_cmd_complete(opcode, b'\x00')
            log.debug("Reset response: %s", resp.hex())
            self._write_hci(resp)
        elif opcode == OP_READ_LOCAL_VERSION:
            # Format: Status(1) + HCI_Version(1) + HCI_Revision(2) + LMP_Version(1) + Mfr(2) + LMP_Sub(2) = 9 bytes
            ver = pack('<BHBHH', 1, 0, 0x0A, 0x05F1, 0)  # 8 bytes after status
            resp = hci_cmd_complete(opcode, b'\x00' + ver)
            log.debug("Version response: %s", resp.hex())
            self._write_hci(resp)
        elif opcode == OP_READ_LOCAL_COMMANDS:
            # Return: Status (1) + Commands (64) = 65 bytes
            cmds = bytearray(64)
            # Set supported commands as bitmask
            cmds[0] = 0x00   # None in byte 0
            cmds[1] = 0x00   # None in byte 1
            cmds[2] = 0x00   # None in byte 2
            cmds[3] = 0x00   # None in byte 3
            cmds[4] = 0x00   # None in byte 4
            cmds[5] = 1<<6   # Disconnect
            cmds[6] = 0x00
            cmds[7] = 0x00
            cmds[10] |= 1<<3  # Reset
            cmds[14] |= 1<<3  # Read Local Name (maybe?)
            cmds[24] |= 1<<5  # Set Event Mask
            cmds[25] = 0xFF   # LE commands
            cmds[26] = 0xFF   # More LE commands
            cmds[27] = 0x33   # Even more LE
            cmds[28] |= 1<<3  # Read RSSI
            resp = hci_cmd_complete(opcode, b'\x00' + bytes(cmds))
            log.debug("Commands response: %d bytes", len(b'\x00' + bytes(cmds)))
            self._write_hci(resp)
        elif opcode == OP_READ_LOCAL_FEATURES:
            # Page 0 features - need to indicate LE support
            # Byte 4, bit 6 = LE Supported (Controller)
            # For a LE-only controller, we need proper features
            feat = bytearray(8)
            feat[4] = 0x40  # LE Supported
            resp = hci_cmd_complete(opcode, b'\x00' + bytes(feat))
            log.debug("Features response: %s", resp.hex())
            self._write_hci(resp)
        elif opcode == OP_READ_BD_ADDR:
            resp = hci_cmd_complete(opcode, b'\x00' + self.bd_addr)
            log.debug("BD_ADDR response: %s (addr=%s)", resp.hex(), self.bd_addr.hex())
            self._write_hci(resp)
        elif opcode == 0x1005:  # Read Buffer Size
            # Format: Status(1) + NumCompletedPackets(1) + ACLLen(2) + SCOLen(1) + ACLNum(2) + SCONum(1) = 8 bytes
            buf = pack('<BBHBHB', 0x00, 0x01, 255, 0, 15, 0)  # 8 bytes total
            resp = hci_cmd_complete(opcode, buf)
            log.debug("Buffer Size response: %s (len=%d)", resp.hex(), len(buf))
            self._write_hci(resp)
        elif opcode == 0x0C23:  # Read Flow Control Mode
            # Kernel expects 4 bytes: Status(1) + Flow_Control_Mode(1) + ???(2)
            # Based on BT core spec 5.4: Status + Flow_Control_Mode = 2 bytes
            # But kernel checks for 4... let's try padding
            resp = hci_cmd_complete(opcode, pack('<BBH', 0x00, 0x00, 0x00))
            log.debug("Flow Control Mode response: %s (len=%d)", resp.hex(), len(pack('<BBH', 0x00, 0x00, 0x00)))
            self._write_hci(resp)
        elif opcode == 0x0C14:  # Read Local Name
            # Return: Status (1) + Local_Name (248) = 249 bytes
            name = b'CatSniffer\x00' + b'\x00' * (248 - 11)  # Pad to 248 bytes
            resp = hci_cmd_complete(opcode, b'\x00' + name)
            log.debug("Local Name response: %d bytes", len(b'\x00' + name))
            self._write_hci(resp)
        elif opcode == 0x0C38:  # Read Inquiry Mode
            # Return: Status (1) + Inquiry_Mode (1) = 2 bytes
            resp = hci_cmd_complete(opcode, pack('<BB', 0x00, 0x00))
            log.debug("Inquiry Mode response: %s", resp.hex())
            self._write_hci(resp)
        elif opcode == 0x2003:  # LE Read Local Supported Features
            # Return: Status (1) + LE_Features (8) = 9 bytes
            le_feat = bytes([0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])  # Encryption + Connection Params
            resp = hci_cmd_complete(opcode, b'\x00' + le_feat)
            log.debug("LE Features response: %d bytes", len(b'\x00' + le_feat))
            self._write_hci(resp)
        elif opcode == 0x2002:  # LE Read Buffer Size
            # Return: Status (1) + LE_ACL_Packet_Length (2) + Total_Num_LE_ACL_Packets (1) = 4 bytes
            resp = hci_cmd_complete(opcode, pack('<BHB', 0x00, 251, 15))
            log.debug("LE Buffer Size response: %s", resp.hex())
            self._write_hci(resp)
        elif opcode == 0x201C:  # LE Read Maximum Data Length
            # Return: Status (1) + MaxTxOctets (2) + MaxTxTime (2) + MaxRxOctets (2) + MaxRxTime (2) = 9 bytes
            resp = hci_cmd_complete(opcode, pack('<BHHHH', 0x00, 251, 2120, 251, 2120))
            log.debug("LE Max Data Len response: %s", resp.hex())
            self._write_hci(resp)
        # More BR/EDR commands we need to stub
        elif opcode == 0x0C39:  # Read Inquiry Response Transmit Power Level
            resp = hci_cmd_complete(opcode, pack('<Bb', 0x00, 0))
            self._write_hci(resp)
        elif opcode == 0x0C16:  # Read Page Timeout
            resp = hci_cmd_complete(opcode, pack('<BH', 0x00, 0x8000))
            log.debug("Page Timeout response: %s", resp.hex())
            self._write_hci(resp)
        elif opcode == 0x0C6D:  # Read Extended Page Timeout (or similar)
            resp = hci_cmd_complete(opcode, b'\x00')
            self._write_hci(resp)
        elif opcode == 0x0C13:  # Read Page Scan Activity
            # For LE-only device, just return status
            resp = hci_cmd_complete(opcode, b'\x00')
            self._write_hci(resp)
        elif opcode == 0x0C24:  # Read Class of Device
            # Returns: Status (1) + Class_of_Device (3) = 4 bytes
            # But kernel says "4 > 1"... let me check the spec
            # Actually for LE-only device, just return error or minimal
            resp = hci_cmd_complete(opcode, b'\x00')  # Just status
            self._write_hci(resp)
        elif opcode in (0x0C01, 0x0C02, 0x2001, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009,
                        0x200A, 0x200B, 0x200F, 0x2010, 0x2011, 0x2012, 0x2017, 0x2018, 0x1405):
            self._write_hci(hci_cmd_complete(opcode, b'\x00'))
        elif opcode == OP_LE_SET_SCAN_ENABLE:
            if params and params[0]:
                self._send_cmd([0x22])
            else:
                self._send_cmd([0x11, 0])
            self._write_hci(hci_cmd_complete(opcode, b'\x00'))
        elif opcode == OP_LE_CREATE_CONN:
            if len(params) >= 25:
                self.peer_addr = bytes(reversed(params[5:11]))
                self.peer_addr_type = params[4]
                from random import randint
                ll = [randint(0,255) for _ in range(7)]
                ll += [3, 5, 0, 24, 0, 1, 0, 50, 0, 0xFF, 0xFF, 0xFF, 0xFF, 0x1F, randint(5,16)]
                self._send_cmd([0x1A, 1 if self.peer_addr_type in (1,0x11) else 0, *self.peer_addr, *ll])
                self._write_hci(hci_cmd_status(opcode, 0))
            else:
                self._write_hci(hci_cmd_complete(opcode, b'\x01'))
        elif opcode == OP_DISCONNECT:
            self._send_cmd([0x19, 0, 0, 3, 3, 0x02, 0x01, params[2] if len(params) > 2 else 0x13])
            self._write_hci(hci_cmd_status(opcode, 0))
        else:
            log.warning("Unhandled opcode 0x%04X", opcode)
            self._write_hci(hci_cmd_complete(opcode, b'\x00'))
            
    def _decode_packet(self, raw):
        if len(raw) < 10:
            return None
        ts, length, event, rssi, chan = unpack("<LHHbB", raw[:10])
        body = raw[10:]
        length &= 0x7FFF
        if len(body) != length:
            return None
        return {'ts': ts, 'rssi': rssi, 'chan': chan & 0x3F, 'body': body}
        
    def _handle_sniffle_packet(self, msg):
        chan, body = msg['chan'], msg['body']
        if len(body) < 8:
            return
        try:
            if chan >= 37:
                pdu_type = body[0] & 0x0F
                tx_add = (body[0] >> 6) & 1
                adv_addr = body[2:8]
                adv_data = body[8:] if len(body) > 8 else b''
                type_map = {0:0, 1:1, 2:2, 4:3, 5:4, 6:0}
                report = pack('<BBBB', LE_ADV_REPORT, 1, type_map.get(pdu_type,0), tx_add)
                report += adv_addr + pack('B', len(adv_data)) + adv_data + pack('b', msg['rssi'])
                self._write_hci(hci_evt(EVT_LE_META, report))
            elif self.active_conn and len(body) > 2:
                l2cap = body[2:]
                h = (self.conn_handle & 0xFFF) | (2 << 12)
                self._write_hci(bytes([HCI_ACL]) + pack('<HH', h, len(l2cap)) + l2cap)
        except OSError as e:
            log.error("Failed to write HCI: %s", e)
            
    def _handle_sniffle_state(self, raw):
        if not raw:
            return
        state = raw[0]
        if state == 6:  # MASTER
            self.active_conn = True
            payload = pack('<BBHBB', LE_CONN_COMPLETE, 0, self.conn_handle, 0, self.peer_addr_type)
            payload += (self.peer_addr or b'\x00'*6) + pack('<HHH', 24, 0, 2000) + b'\x00'
            self._write_hci(hci_evt(EVT_LE_META, payload))
            log.info("Connected")
        elif state == 0 and self.active_conn:
            self.active_conn = False
            self._write_hci(hci_evt(EVT_DISCONN_COMPLETE, pack('<BHB', 0, self.conn_handle, 0x13)))
            log.info("Disconnected")
            
    def run(self):
        while self.running:
            r, _, _ = select.select([self.vhci_fd, self.ser_fd], [], [], 0.1)
            
            if self.ser_fd in r:
                data = self._ser_read()
                if data:
                    self.rx_buf += data
                    while True:
                        result = self._recv_msg()
                        if not result:
                            break
                        mtype, mbody = result
                        if mtype == SNIFFLE_MSG_PACKET:
                            msg = self._decode_packet(mbody)
                            if msg:
                                self._handle_sniffle_packet(msg)
                        elif mtype == SNIFFLE_MSG_STATE:
                            self._handle_sniffle_state(mbody)
                            
            if self.vhci_fd in r:
                try:
                    raw = os.read(self.vhci_fd, 260)
                    if not raw:
                        continue
                    if raw and raw[0] == HCI_CMD:
                        self._handle_hci_cmd(raw[1:])
                    elif raw and raw[0] == HCI_ACL:
                        pass  # TODO: handle ACL
                except BlockingIOError:
                    pass


def main():
    import argparse
    ap = argparse.ArgumentParser(description='CatSniffer VHCI Bridge')
    ap.add_argument('-p', '--port', help='Serial port')
    ap.add_argument('-d', '--device', type=int, help='Device ID')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()
    
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(message)s', handlers=[RichHandler()])
    
    port = args.port
    if not port:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from catsniffer import catsniffer_get_device
            dev = catsniffer_get_device(args.device)
            if not dev:
                console.print("[red]No device[/red]")
                sys.exit(1)
            port = dev.bridge_port
        except Exception as e:
            console.print(f"[red]Error: {e}. Specify -p PORT[/red]")
            sys.exit(1)
            
    if os.geteuid() != 0:
        console.print("[yellow]Need root for /dev/vhci[/yellow]")
        
    bridge = VHCIBridge(port)
    
    def stop_handler(s, f):
        bridge.stop()
        sys.exit(0)
    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    
    bridge.start()
    console.print("[green]Bridge running. Check: hciconfig -a[/green]")
    console.print("[cyan]Use: btmon -i hci1[/cyan]")
    bridge.run()


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""vhci_bridge.py - CatSniffer as /dev/hciX"""

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

import serial
from serial import Serial
from rich.console import Console
from rich.logging import RichHandler

console = Console()
log = logging.getLogger('vhci')

HCI_CMD = 0x01
HCI_EVT = 0x04
EVT_CMD_COMPLETE = 0x0E

def hci_cc(opcode, data=b''):
    """Build Command Complete event"""
    return bytes([HCI_EVT, EVT_CMD_COMPLETE, 4 + len(data), 1]) + struct.pack('<H', opcode) + data

class Bridge:
    def __init__(self, port):
        self.port = port
        self.bdaddr = bytes([0xC0, 0xFF, 0xEE, 0xC0, 0xFF, 0xEE])
        self.ser = None
        self.vhci = None
        self.running = False
        self.buf = b''
        
    def start(self):
        # Serial
        self.ser = Serial(self.port, 2000000, timeout=0)
        self.ser.write(b'@@@@@@@@\r\n')
        time.sleep(0.1)
        self.ser.reset_input_buffer()
        
        # VHCI - read init first (blocking), then set nonblock
        self.vhci = os.open('/dev/vhci', os.O_RDWR)
        init = os.read(self.vhci, 260)
        flags = fcntl.fcntl(self.vhci, fcntl.F_GETFL)
        fcntl.fcntl(self.vhci, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        log.info("Started: serial=%s vhci=%d init=%s", self.port, self.vhci, init.hex())
        
        self.running = True
        
    def stop(self):
        self.running = False
        if self.vhci: os.close(self.vhci)
        if self.ser: self.ser.close()
        
    def send_sniffle(self, cmd):
        b0 = (len(cmd) + 3) // 3
        self.ser.write(b64encode(bytes([b0] + cmd)) + b'\r\n')
        
    def recv_sniffle(self):
        while len(self.buf) >= 6:
            try:
                d = b64decode(self.buf[:4])
            except BAError:
                self.buf = self.buf[1:]
                continue
            wc = d[0]
            need = wc * 4 + 2 if wc else 6
            if len(self.buf) < need:
                return None
            pkt = self.buf[:need]
            self.buf = self.buf[need:]
            if pkt[-2:] != b'\r\n':
                continue
            try:
                d = b64decode(pkt[:-2])
                return d[1], d[2:]
            except:
                pass
        return None
        
    def handle_cmd(self, data):
        if len(data) < 3:
            return
        op, plen = struct.unpack('<HB', data[:3])
        params = data[3:3+plen]
        
        responses = {
            0x0C03: b'\x00',  # Reset
            0x0C14: b'\x00' + b'CatSniffer' + b'\x00'*238,  # Local Name (248 bytes)
            0x0C16: b'\x00' + struct.pack('<H', 0x8000),  # Page Timeout (2 bytes)
            0x0C18: b'\x00' + struct.pack('<H', 0x0000),  # Write Scan Enable (2 bytes)
            0x0C23: b'\x00' + struct.pack('<BH', 0, 0),  # Flow Control Mode: 4 bytes
            0x0C24: b'\x00',  # Class of Device - just status
            0x0C38: b'\x00' + struct.pack('<B', 0),  # Inquiry Mode (1 byte)
            0x0C39: b'\x00' + struct.pack('<b', 0),  # Inquiry TX Power (1 byte)
            0x1001: b'\x00' + struct.pack('<BHBHH', 1, 0, 0x0A, 0x05F1, 0),  # Version (9 bytes)
            0x1002: b'\x00' + bytes(64),  # Commands (65 bytes)
            0x1003: b'\x00' + bytes([0]*4 + [0x40] + [0]*3),  # Features (9 bytes)
            0x1005: b'\x00' + struct.pack('<BHBHB', 1, 255, 0, 15, 0),  # Buffer Size (8 bytes)
            0x1009: b'\x00' + self.bdaddr[::-1],  # BD_ADDR (7 bytes, reversed for HCI)
            0x2001: b'\x00',  # LE Set Event Mask
            0x2002: b'\x00' + struct.pack('<HB', 251, 15),  # LE Buffer Size (4 bytes)
            0x2003: b'\x00' + bytes([0x03] + [0]*7),  # LE Features (9 bytes)
            0x201C: b'\x00' + struct.pack('<HHHH', 251, 2120, 251, 2120),  # LE Max Data Length (9 bytes)
        }
        
        if op in responses:
            os.write(self.vhci, hci_cc(op, responses[op]))
        else:
            os.write(self.vhci, hci_cc(op, b'\x00'))
            
    def run(self):
        while self.running:
            r, _, _ = select.select([self.vhci, self.ser.fd], [], [], 0.05)
            
            # HCI commands - process ALL available
            while self.vhci in r:
                try:
                    d = os.read(self.vhci, 260)
                    if d and d[0] == HCI_CMD:
                        self.handle_cmd(d[1:])
                    r, _, _ = select.select([self.vhci], [], [], 0)
                except:
                    break
                    
            # Serial data
            if self.ser.fd in r:
                try:
                    d = self.ser.read(self.ser.in_waiting)
                    self.buf += d
                except:
                    pass
                    
            # Process sniffle messages
            while True:
                msg = self.recv_sniffle()
                if not msg:
                    break
                # TODO: forward to HCI

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('-p', '--port', required=True)
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()
    
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, handlers=[RichHandler()])
    
    b = Bridge(args.port)
    signal.signal(signal.SIGINT, lambda s,f: b.stop())
    b.start()
    console.print("[green]Running[/green]")
    b.run()

if __name__ == '__main__':
    main()

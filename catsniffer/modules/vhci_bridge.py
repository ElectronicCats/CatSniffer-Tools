#!/usr/bin/env python3
"""
vhci_bridge.py - CatSniffer VHCI Bridge with GATT command interface

Usage:
  sudo python3 vhci_bridge.py -p /dev/ttyACM0
  # In another terminal:
  python3 -c "import socket; s=socket.socket(socket.AF_UNIX); s.connect('/tmp/catsniffer.sock'); s.send(b'status\n'); print(s.recv(4096))"
"""

import os, sys, time, select, fcntl, struct, logging, signal, socket, json, subprocess, re
from base64 import b64encode, b64decode
from binascii import Error as BAError
from random import randrange, randint
import serial
from serial import Serial
from rich.console import Console
from rich.logging import RichHandler

console = Console()
log = logging.getLogger('vhci')

HCI_CMD, HCI_ACL, HCI_EVT = 0x01, 0x02, 0x04
EVT_CMD_COMPLETE, EVT_CMD_STATUS, EVT_DISCONN_COMPLETE, EVT_LE_META = 0x0E, 0x0F, 0x05, 0x3E
LE_CONN_COMPLETE, LE_ADV_REPORT = 0x01, 0x02
SNIFFLE_MSG_PACKET, SNIFFLE_MSG_STATE = 0x10, 0x13
BLE_ADV_AA, BLE_ADV_CRCI = 0x8E89BED6, 0x555555
L2CAP_ATT_CID = 0x0004
ATT_OP_MTU_REQ, ATT_OP_MTU_RSP = 0x02, 0x03
ATT_OP_READ_BY_TYPE_REQ, ATT_OP_READ_BY_TYPE_RSP = 0x08, 0x09
ATT_OP_READ_REQ, ATT_OP_READ_RSP = 0x0A, 0x0B
ATT_OP_READ_BLOB_REQ, ATT_OP_READ_BLOB_RSP = 0x0C, 0x0D
ATT_OP_READ_BY_GROUP_REQ, ATT_OP_READ_BY_GROUP_RSP = 0x10, 0x11
ATT_OP_WRITE_REQ, ATT_OP_WRITE_RSP, ATT_OP_WRITE_CMD = 0x12, 0x13, 0x52
ATT_OP_ERROR, ATT_OP_HANDLE_NTF = 0x01, 0x1B
GATT_UUID_PRIMARY_SERVICE, GATT_UUID_CHARACTERISTIC = 0x2800, 0x2803

# LL Control opcodes
LL_LENGTH_REQ = 0x14
LL_LENGTH_RSP = 0x15

def hci_cc(op, data=b''): return bytes([HCI_EVT, EVT_CMD_COMPLETE, 4+len(data), 1]) + struct.pack('<H', op) + data
def hci_cs(op, st=0): return bytes([HCI_EVT, EVT_CMD_STATUS, 4, st, 1]) + struct.pack('<H', op)

class GATTClient:
    def __init__(self, bridge):
        self.bridge = bridge
        self.mtu = 23
        self.services = []
        self.characteristics = []
        self.response = None
        
    def connect(self, addr_str, addr_type=0):
        addr = bytes.fromhex(addr_str.replace(':', ''))[::-1]
        if len(addr) != 6: return {"error": "Invalid address"}
        self.bridge.peer_addr = addr
        self.bridge.peer_addr_type = addr_type
        
        # Stop any ongoing operation
        if self.bridge.scanning:
            self.bridge._send_cmd([0x11, 0])
            self.bridge.scanning = False
        time.sleep(0.1)
        
        # Set advertising channel 37 with advertising AA (like Sniffle initiator)
        self.bridge._send_cmd([0x10, 37] + list(struct.pack("<L", 0x8E89BED6)) + [0] + list(struct.pack("<L", 0x555555)))
        time.sleep(0.05)
        
        # Pause after done
        self.bridge._send_cmd([0x11, 1])
        time.sleep(0.05)
        
        # Set MAC filter for target
        self.bridge._send_cmd([0x13] + list(addr) + [1 if addr_type else 0])
        time.sleep(0.05)
        
        # Set our own random static address
        our_addr = [randrange(256) for _ in range(6)]
        our_addr[5] |= 0xC0
        self.bridge._send_cmd([0x1B, 1] + our_addr)
        time.sleep(0.05)
        
        # LLData: accessAddr[4], crcInit[3], winSize, winOffset[2], interval[2], latency[2], timeout[2], chanMap[5], hop
        lldata = [randrange(256) for _ in range(4)] + [randrange(256) for _ in range(3)] + [3] + list(struct.pack('<H', randint(5,15))) + list(struct.pack('<HHH', 24, 1, 50)) + [0xFF,0xFF,0xFF,0xFF,0x1F, randint(5,16)]
        self.bridge._send_cmd([0x1A, addr_type] + list(addr) + lldata)
        return {"status": "connecting", "address": addr_str, "addr_type": addr_type}
        
    def disconnect(self):
        if self.bridge.active_conn:
            self.bridge._send_cmd([0x19, 0, 0, 3, 3, 0x02, 0x01, 0x13])
            return {"status": "disconnecting"}
        return {"error": "Not connected"}
        
    def exchange_mtu(self, mtu=517):
        if not self.bridge.active_conn: return {"error": "Not connected"}
        self.mtu = mtu
        pdu = bytes([ATT_OP_MTU_REQ]) + struct.pack('<H', mtu)
        self._send_att(pdu)
        return self._wait_response()
        
    def discover_services(self):
        if not self.bridge.active_conn: return {"error": "Not connected"}
        self.services = []
        start = 0x0001
        while start < 0xFFFF:
            pdu = struct.pack('<BHHHH', ATT_OP_READ_BY_GROUP_REQ, start, 0xFFFF, GATT_UUID_PRIMARY_SERVICE)
            self._send_att(pdu)
            resp = self._wait_response()
            if 'error' in resp or 'services' not in resp: break
            for s in resp.get('services', []):
                self.services.append(s)
                start = s['end'] + 1
            if resp.get('done'): break
        return {"services": self.services}
        
    def discover_characteristics(self, start=0x0001, end=0xFFFF):
        if not self.bridge.active_conn: return {"error": "Not connected"}
        self.characteristics = []
        while start < end:
            pdu = struct.pack('<BHHHH', ATT_OP_READ_BY_TYPE_REQ, start, end, GATT_UUID_CHARACTERISTIC)
            self._send_att(pdu)
            resp = self._wait_response()
            if 'error' in resp or 'characteristics' not in resp: break
            for c in resp.get('characteristics', []):
                self.characteristics.append(c)
                start = c['handle'] + 1
            if resp.get('done'): break
        return {"characteristics": self.characteristics}
        
    def read(self, handle):
        if not self.bridge.active_conn: return {"error": "Not connected"}
        self._send_att(struct.pack('<BH', ATT_OP_READ_REQ, handle))
        return self._wait_response()
        
    def write(self, handle, data, with_response=True):
        if not self.bridge.active_conn: return {"error": "Not connected"}
        if isinstance(data, str): data = bytes.fromhex(data)
        if with_response:
            self._send_att(struct.pack('<BH', ATT_OP_WRITE_REQ, handle) + data)
            return self._wait_response()
        self._send_att(struct.pack('<BH', ATT_OP_WRITE_CMD, handle) + data)
        return {"status": "written"}
        
    def _send_att(self, pdu):
        self.response = None
        self.bridge._send_tx_packet(0x02, struct.pack('<HH', len(pdu)+4, L2CAP_ATT_CID) + pdu)
        
    def _wait_response(self, timeout=5.0):
        start = time.time()
        while time.time() - start < timeout:
            if self.response: return self.response
            time.sleep(0.01)
        return {"error": "timeout"}
        
    def handle_att(self, pdu):
        if not pdu: return
        op = pdu[0]
        if op == ATT_OP_ERROR and len(pdu) >= 4:
            self.response = {"error": f"ATT error 0x{pdu[4]:02X}"}
        elif op == ATT_OP_MTU_RSP and len(pdu) >= 3:
            self.mtu = min(self.mtu, struct.unpack('<H', pdu[1:3])[0])
            self.response = {"mtu": self.mtu}
        elif op == ATT_OP_READ_BY_GROUP_RSP:
            ln = pdu[1] if len(pdu) > 1 else 0
            svcs = [{"start": struct.unpack('<H', pdu[i:i+2])[0], "end": struct.unpack('<H', pdu[i+2:i+4])[0], "uuid": pdu[i+4:i+ln].hex()} for i in range(2, len(pdu), ln) if i+ln <= len(pdu)]
            self.services.extend(svcs)
            self.response = {"services": svcs, "done": len(pdu) < 2+ln*4}
        elif op == ATT_OP_READ_BY_TYPE_RSP:
            ln = pdu[1] if len(pdu) > 1 else 0
            chars = [{"handle": struct.unpack('<H', pdu[i:i+2])[0], "properties": pdu[i+2], "value_handle": struct.unpack('<H', pdu[i+3:i+5])[0], "uuid": pdu[i+5:i+ln].hex()} for i in range(2, len(pdu), ln) if i+ln <= len(pdu)]
            self.characteristics.extend(chars)
            self.response = {"characteristics": chars, "done": len(pdu) < 2+ln*4}
        elif op == ATT_OP_READ_RSP:
            self.response = {"value": pdu[1:].hex()}
        elif op == ATT_OP_WRITE_RSP:
            self.response = {"status": "ok"}
        elif op == ATT_OP_HANDLE_NTF and len(pdu) >= 3:
            log.info("Notification: 0x%04X = %s", struct.unpack('<H', pdu[1:3])[0], pdu[3:].hex())

class CommandServer:
    def __init__(self, bridge, path='/tmp/catsniffer.sock'):
        self.bridge, self.path = bridge, path
        self.server, self.clients, self.running = None, [], False
        
    def start(self):
        try: os.unlink(self.path)
        except: pass
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        self.server.listen(5)
        self.server.setblocking(False)
        self.running = True
        log.info("Command socket: %s", self.path)
        
    def stop(self):
        self.running = False
        for c in self.clients: 
            try: c.close()
            except: pass
        if self.server:
            try: self.server.close()
            except: pass
        try: os.unlink(self.path)
        except: pass
        
    def poll(self):
        if not self.running: return
        try:
            conn, _ = self.server.accept()
            conn.setblocking(False)
            self.clients.append(conn)
        except BlockingIOError: pass
        for c in self.clients[:]:
            try:
                data = c.recv(4096)
                if not data: self.clients.remove(c); continue
                resp = self.handle(data.decode().strip())
                if resp: c.send((json.dumps(resp)+'\n').encode())
            except BlockingIOError: pass
            except: 
                try: self.clients.remove(c)
                except: pass
                
    def handle(self, cmd):
        p = cmd.split()
        if not p: return {"error": "Empty"}
        op, args = p[0].lower(), p[1:]
        
        if op == 'help': 
            return {"commands": ["connect <addr>", "disconnect", "scan [timeout]", "mtu [size]", 
                                "services", "characteristics [start] [end]", "read <handle>", 
                                "write <handle> <hex>", "status"]}
        if op == 'connect': 
            if not args: return {"error": "Usage: connect <addr> [addr_type]"}
            addr = args[0]
            addr_type = int(args[1]) if len(args) > 1 else 0
            return self.bridge.gatt.connect(addr, addr_type)
        if op == 'disconnect': 
            return self.bridge.gatt.disconnect()
        if op == 'scan':
            timeout = int(args[0]) if args else 5
            return self._scan(timeout)
        if op == 'mtu': 
            return self.bridge.gatt.exchange_mtu(int(args[0]) if args else 517)
        if op == 'services': 
            return self.bridge.gatt.discover_services()
        if op == 'characteristics':
            start = int(args[0], 16) if args else 0x0001
            end = int(args[1], 16) if len(args) > 1 else 0xFFFF
            return self.bridge.gatt.discover_characteristics(start, end)
        if op == 'read': 
            return self.bridge.gatt.read(int(args[0], 16)) if args else {"error": "Usage: read <handle>"}
        if op == 'write': 
            return self.bridge.gatt.write(int(args[0], 16), args[1]) if len(args) >= 2 else {"error": "Usage: write <handle> <hex>"}
        if op == 'status': 
            return {"connected": self.bridge.active_conn, 
                   "address": self.bridge.peer_addr[::-1].hex() if self.bridge.peer_addr else None, 
                   "mtu": self.bridge.gatt.mtu}
        return {"error": f"Unknown: {op}"}
        
    def _scan(self, timeout=5):
        """Scan for BLE devices directly via firmware."""
        from base64 import b64decode
        
        # Pause any ongoing operation
        self.bridge._send_cmd([0x11, 0])
        time.sleep(0.1)
        
        # Set channel 37 with advertising access address and CRC
        self.bridge._send_cmd([0x10, 37] + list(struct.pack("<L", 0x8E89BED6)) + [0] + list(struct.pack("<L", 0x555555)))
        time.sleep(0.05)
        
        # Start scan
        self.bridge._send_cmd([0x22])
        
        devices = {}
        rx_buf = b""
        start = time.time()
        
        while time.time() - start < timeout:
            if self.bridge.ser.in_waiting > 0:
                rx_buf += self.bridge.ser.read(self.bridge.ser.in_waiting)
            
            while b"\r\n" in rx_buf:
                pos = rx_buf.find(b"\r\n")
                line = rx_buf[:pos]
                rx_buf = rx_buf[pos+2:]
                
                if len(line) >= 4 and len(line) % 4 == 0:
                    try:
                        data = b64decode(line)
                        if len(data) >= 2 and data[1] == 0x10:
                            mb = data[2:]
                            if len(mb) >= 10:
                                body = mb[10:]
                                pkt_len = (mb[4] | (mb[5] << 8)) & 0x7FFF
                                chan = mb[9] & 0x3F
                                if chan >= 37 and len(body) == pkt_len and pkt_len >= 6:
                                    pdu_type = body[0] & 0x0F
                                    # Only connectable: ADV_IND (0) or ADV_DIRECT_IND (1)
                                    if pdu_type in (0, 1):
                                        addr = body[2:8][::-1].hex()
                                        addr_fmt = ":".join([addr[i:i+2] for i in range(0, 12, 2)])
                                        rssi = mb[8] if mb[8] < 128 else mb[8] - 256
                                        tx_type = (body[0] >> 6) & 0x01
                                        if addr_fmt not in devices or devices[addr_fmt]["rssi"] < rssi:
                                            devices[addr_fmt] = {"rssi": rssi, "addr_type": tx_type}
                    except:
                        pass
            time.sleep(0.01)
        
        # Stop scan
        self.bridge._send_cmd([0x11, 0])
        
        return {"devices": list(devices.keys()), "count": len(devices), "details": devices}

class Bridge:
    def __init__(self, port, sock_path='/tmp/catsniffer.sock'):
        self.port, self.sock_path = port, sock_path
        self.bdaddr = bytes([0xC0, 0xFF, 0xEE, 0xC0, 0xFF, 0xEE])
        self.ser = self.vhci = None
        self.running = False
        self.rx_buf = b''
        self.conn_handle = 1
        self.active_conn = False
        self.peer_addr = None
        self.peer_addr_type = 0
        self.vhci_flags = 0
        self.adv_addr = None
        self.adv_data = b'\x02\x01\x06'
        self.scan_rsp_data = b''
        self.advertising = self.scanning = False
        self.gatt = GATTClient(self)
        self.cmd_server = None
        
    def start(self):
        self.ser = Serial(self.port, 2000000, timeout=1.0)
        log.info("Sync...")
        self.ser.write(b'@@@@@@@@\r\n')
        time.sleep(0.2)
        self.ser.reset_input_buffer()
        self.rx_buf = b''
        log.info("Reset...")
        self._send_cmd([0x17])
        time.sleep(0.5)
        self.ser.reset_input_buffer()
        self.rx_buf = b''
        self.ser.timeout = 0
        self.vhci = os.open('/dev/vhci', os.O_RDWR)
        os.read(self.vhci, 260)
        self.vhci_flags = fcntl.fcntl(self.vhci, fcntl.F_GETFL)
        self.cmd_server = CommandServer(self, self.sock_path)
        self.cmd_server.start()
        log.info("Started")
        self.running = True
        
    def stop(self):
        self.running = False
        if self.cmd_server: self.cmd_server.stop()
        if self.vhci:
            try: os.close(self.vhci)
            except: pass
        if self.ser:
            try: self.ser.close()
            except: pass
        
    def _send_cmd(self, cmd):
        b0 = (len(cmd) + 3) // 3
        self.ser.write(b64encode(bytes([b0] + cmd)) + b'\r\n')
        log.debug("TX: %s", bytes([b0]+cmd).hex())
        
    def _send_tx_packet(self, llid, data, ev=0):
        self._send_cmd([0x19, ev&0xFF, (ev>>8)&0xFF, llid, len(data)] + list(data))
        
    def _recv_msg(self):
        while True:
            if len(self.rx_buf) < 8: return None, None
            pos = self.rx_buf.find(b'\r\n')
            if pos < 0: return None, None
            line = self.rx_buf[:pos]
            self.rx_buf = self.rx_buf[pos+2:]
            if not line or line.startswith(b'@@'): continue
            if len(line) % 4 != 0: continue
            try: data = b64decode(line)
            except: continue
            if len(data) < 2: continue
            return data[1], data[2:]
            
    def handle_hci(self, data):
        if len(data) < 3: return
        op, plen = struct.unpack('<HB', data[:3])
        params = data[3:3+plen]
        log.info("HCI: 0x%04X", op)
        if op == 0x0C03: self._send_cmd([0x17]); os.write(self.vhci, hci_cc(op, b'\x00'))
        elif op == 0x1001: os.write(self.vhci, hci_cc(op, b'\x00'+struct.pack('<BBHBHH',0,1,0,10,0x05F1,0)))
        elif op == 0x1002: os.write(self.vhci, hci_cc(op, b'\x00'+bytes([0]*64)))
        elif op == 0x1003: os.write(self.vhci, hci_cc(op, b'\x00'+bytes([0,0,0,0,0x40,0,0,0])))
        elif op == 0x1005: os.write(self.vhci, hci_cc(op, b'\x00'+struct.pack('<BHBHB',1,255,0,15,0)))
        elif op == 0x1009: os.write(self.vhci, hci_cc(op, b'\x00'+self.bdaddr[::-1]))
        elif op == 0x0C14: os.write(self.vhci, hci_cc(op, b'\x00'+b'CatSniffer'+b'\x00'*238))
        elif op == 0x2002: os.write(self.vhci, hci_cc(op, b'\x00'+struct.pack('<HB',251,15)))
        elif op == 0x2003: os.write(self.vhci, hci_cc(op, b'\x00'+bytes([3]+[0]*7)))
        elif op == 0x2005:
            if plen >= 6: self.adv_addr = params[:6]; self._send_cmd([0x1B,1]+list(params[:6]))
            os.write(self.vhci, hci_cc(op, b'\x00'))
        elif op == 0x200C:
            en = params[0] if plen > 0 else 0
            os.write(self.vhci, hci_cc(op, b'\x00'))
            if en: self._send_cmd([0x10,37]+list(struct.pack('<L',BLE_ADV_AA))+[0]+list(struct.pack('<L',BLE_ADV_CRCI))); time.sleep(0.05); self._send_cmd([0x22]); self.scanning = True
            else: self._send_cmd([0x11,0]); self.scanning = False
        elif op == 0x200A:
            en = params[0] if plen > 0 else 0
            os.write(self.vhci, hci_cc(op, b'\x00'))
            if en and not self.advertising:
                if self.adv_addr: self._send_cmd([0x1B,1]+list(self.adv_addr))
                self._send_cmd([0x1C,0]+[len(self.adv_data)]+list(self.adv_data)+[0]*(31-len(self.adv_data))+[len(self.scan_rsp_data)]+list(self.scan_rsp_data)+[0]*(31-len(self.scan_rsp_data)))
                self.advertising = True
            elif not en and self.advertising: self._send_cmd([0x11,0]); self.advertising = False
        else: os.write(self.vhci, hci_cc(op, b'\x00'))
        
    def handle_packet(self, raw):
        if len(raw) < 10: return
        ts, ln, ev, rssi, cp = struct.unpack("<LHHbB", raw[:10])
        body, pkt_len, chan = raw[10:], ln & 0x7FFF, cp & 0x3F
        log.debug("Packet: chan=%d len=%d rssi=%d", chan, pkt_len, rssi)
        if chan < 37:
            if pkt_len < 2: return
            llid, dlen = body[0] & 3, body[1]
            log.debug("Data: chan=%d llid=%d dlen=%d body=%s", chan, llid, dlen, body[:min(20,len(body))].hex())
            if llid == 3:
                # LL Control PDU - respond to LENGTH_REQ
                if dlen >= 1:
                    opcode = body[2]
                    if opcode == LL_LENGTH_REQ and dlen >= 16:
                        # Echo back their params as LENGTH_RSP
                        params = body[3:17]
                        self._send_cmd([0x19, 0, 0, 3, 15, LL_LENGTH_RSP] + list(params))
                        log.debug("Sent LL_LENGTH_RSP")
                return
            lldata = body[2:2+dlen]
            if len(lldata) >= 4:
                l2len, cid = struct.unpack('<HH', lldata[:4])
                if cid == L2CAP_ATT_CID: self.gatt.handle_att(lldata[4:4+l2len])
                try: os.write(self.vhci, bytes([HCI_ACL])+struct.pack('<HH',self.conn_handle,len(lldata))+lldata)
                except: pass
            return
        if len(body) != pkt_len or pkt_len < 6: return
        pdu_type = body[0] & 0x0F
        adv_addr = body[2:8]
        adv_data = body[8:] if pkt_len > 8 else b''
        evt_type = {0:0,1:1,2:2,4:3,5:4,6:0}.get(pdu_type, 0)
        rpt = struct.pack('<BBBB', LE_ADV_REPORT, 1, evt_type, (body[0]>>6)&1) + adv_addr + struct.pack('B',len(adv_data)) + adv_data + struct.pack('b',rssi)
        try: os.write(self.vhci, bytes([HCI_EVT, EVT_LE_META, len(rpt)]) + rpt)
        except: pass
        
    def handle_state(self, raw):
        if not raw: return
        st = raw[0]
        log.info("State: %d", st)
        if st in (6, 7):  # CENTRAL or PERIPHERAL
            self.active_conn = True
            role = 0 if st == 6 else 1
            pl = struct.pack('<BBBBB', LE_CONN_COMPLETE, 0, self.conn_handle&0xFF, (self.conn_handle>>8)&0x0F, role) + bytes([self.peer_addr_type or 0]) + (self.peer_addr or b'\x00'*6) + struct.pack('<HHH',24,0,2000) + b'\x00'
            try:
                os.write(self.vhci, bytes([HCI_EVT, EVT_LE_META, len(pl)]) + pl)
            except Exception as e:
                log.warning("VHCI write failed: %s", e)
            log.info("Connected")
        elif st == 0 and self.active_conn:
            self.active_conn = False
            pl = struct.pack('<BHB', 0, self.conn_handle, 0x13)
            try:
                os.write(self.vhci, bytes([HCI_EVT, EVT_DISCONN_COMPLETE, len(pl)]) + pl)
            except:
                pass
            log.info("Disconnected")
        
    def run(self):
        while self.running:
            fcntl.fcntl(self.vhci, fcntl.F_SETFL, self.vhci_flags | os.O_NONBLOCK)
            try:
                r, _, _ = select.select([self.vhci], [], [], 0.001)
                while r:
                    try:
                        d = os.read(self.vhci, 260)
                        if d and d[0] == HCI_CMD: self.handle_hci(d[1:])
                        r, _, _ = select.select([self.vhci], [], [], 0)
                    except BlockingIOError: break
            except: pass
            try:
                if self.ser.in_waiting: self.rx_buf += self.ser.read(self.ser.in_waiting)
            except: pass
            while True:
                mt, mb = self._recv_msg()
                if mt is None: break
                if mt == SNIFFLE_MSG_PACKET: self.handle_packet(mb)
                elif mt == SNIFFLE_MSG_STATE: self.handle_state(mb)
            if self.cmd_server: self.cmd_server.poll()

def main():
    import argparse
    ap = argparse.ArgumentParser(description='CatSniffer VHCI Bridge')
    ap.add_argument('-p', '--port', required=True)
    ap.add_argument('-s', '--socket', default='/tmp/catsniffer.sock')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, handlers=[RichHandler()])
    if os.geteuid() != 0: console.print("[yellow]Warning: Need root[/yellow]")
    b = Bridge(args.port, args.socket)
    signal.signal(signal.SIGINT, lambda s,f: (b.stop(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda s,f: (b.stop(), sys.exit(0)))
    b.start()
    console.print(f"[green]Running. Socket: {args.socket}[/green]")
    b.run()

if __name__ == '__main__':
    main()

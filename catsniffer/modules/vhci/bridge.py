"""
VHCI Bridge - Main bridge class connecting VHCI to Sniffle firmware
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
from random import randrange, randint
from serial import Serial
from serial.tools.list_ports import comports

from .constants import *
from .commands import HCICommandDispatcher
from . import events


class VHCIBridge:
    """Bridge between Linux VHCI and Sniffle firmware"""

    def __init__(self, serport, logger=None):
        self.logger = logger or logging.getLogger('vhci')
        self.log = self.logger

        # Serial port
        self.serport = serport
        self.ser = None
        self.rx_buf = b''

        # VHCI
        self.vhci = None
        self.vhci_flags = 0

        # State
        self.running = False
        self.state = STATE_STATIC

        # Controller info
        self.bd_addr = bytes([0xC0, 0xFF, 0xEE, 0xC0, 0xFF, 0xEE])  # Random static
        self.local_name = b'CatSniffer'
        self.conn_accept_timeout = 0x7D00  # 32000 slots = 20 seconds

        # Connection state
        self.conn_handle = 0x0001
        self.active_conn = False
        self.peer_addr = None
        self.peer_addr_type = 0
        self.last_rssi = -60  # Default RSSI
        
        # Connection parameters
        self.conn_interval = 0x0018  # 30ms
        self.conn_latency = 0x0000
        self.conn_timeout = 0x01F4   # 5000ms = 5s
        
        # Channel map (all channels enabled)
        self.channel_map = bytes([0xFF, 0xFF, 0x1F, 0x00, 0x00])  # 37 channels
        
        # White list
        self.white_list = []  # List of (addr_type, addr) tuples
        self.white_list_max = 16
        
        # Resolving list (for privacy)
        self.resolving_list = []  # List of (peer_irk, peer_addr_type, peer_addr, local_irk)
        self.resolving_list_max = 16
        self.address_resolution_enabled = False

        # Scan state
        self.scanning = False
        self.scan_type = 0  # 0 = passive, 1 = active
        self.scan_interval = 0x0010
        self.scan_window = 0x0010

        # Advertising state
        self.advertising = False
        self.adv_type = 0  # ADV_IND
        self.adv_interval = 0x00A0  # 100 ms
        self.adv_data = b''
        self.scan_rsp_data = b''

        # Event masks
        self.event_mask = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x3F])
        self.le_event_mask = bytes([0x1F, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

        # BR/EDR state (not used for LE-only, but needed for BlueZ)
        self.page_timeout = 0x2000
        self.scan_enable = 0x00
        self.class_of_device = bytes([0x1F, 0x00, 0x00])

        # Extended Inquiry Response
        self.eir_data = bytes(240)
        self.fec_required = 0x00

        # Suggested default data length
        self.suggested_tx_octets = 27
        self.suggested_tx_time = 328

        # Command dispatcher
        self.dispatcher = HCICommandDispatcher(self)

    def start(self):
        """Initialize and start the bridge"""
        # Open serial port
        self.log.info("Opening serial port: %s", self.serport)
        self.ser = Serial(self.serport, 2000000, timeout=0.5)  # Shorter timeout

        # Sync with firmware - send markers and flush
        self.log.info("Syncing with firmware...")
        try:
            self.ser.write(b'@@@@@@@@\r\n')
            self.ser.flush()
            time.sleep(0.1)
            self.ser.reset_input_buffer()
        except Exception as e:
            self.log.warning("Sync warning: %s", e)
        self.rx_buf = b''

        # Reset firmware
        self.log.info("Resetting firmware...")
        try:
            self._send_sniffle_cmd([SNIFFLE_RESET])
            time.sleep(0.3)
            self.ser.reset_input_buffer()
        except Exception as e:
            self.log.warning("Reset warning: %s", e)
        self.rx_buf = b''

        # Set serial to non-blocking
        self.ser.timeout = 0

        # Open VHCI device
        self.log.info("Opening VHCI device...")
        self.vhci = os.open('/dev/vhci', os.O_RDWR)

        # Create VHCI controller
        # HCI_VENDOR_PKT (0xFF) + HCI_PRIMARY (0)
        self.log.debug("Sending VHCI create request...")
        os.write(self.vhci, bytes([0xFF, 0x00]))

        # Read response (blocking, short timeout)
        # Response format: pkt_type (1), opcode (1), index (1)
        import select as sel
        readable, _, _ = sel.select([self.vhci], [], [], 2.0)
        if readable:
            rsp = os.read(self.vhci, 260)
            self.log.info("VHCI response: %s (len=%d)", rsp.hex() if rsp else "empty", len(rsp))
            if len(rsp) >= 3:
                self.hci_index = rsp[2]
                self.log.info("Created hci%d", self.hci_index)
        else:
            self.log.error("VHCI response timeout!")
            self.hci_index = 1

        self.vhci_flags = fcntl.fcntl(self.vhci, fcntl.F_GETFL)

        self.log.info("Bridge started")
        self.running = True

    def stop(self):
        """Stop the bridge"""
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

    def run(self):
        """Main loop"""
        while self.running:
            # Process HCI commands from host
            self._process_vhci()

            # Process messages from firmware
            self._process_sniffle()

            # Small sleep to avoid busy loop
            time.sleep(0.001)

    def _process_vhci(self):
        """Process incoming HCI packets from VHCI"""
        fcntl.fcntl(self.vhci, fcntl.F_SETFL, self.vhci_flags | os.O_NONBLOCK)
        try:
            r, _, _ = select.select([self.vhci], [], [], 0)
            while r:
                try:
                    data = os.read(self.vhci, 260)
                    if data:
                        self._handle_hci_packet(data)
                    r, _, _ = select.select([self.vhci], [], [], 0)
                except BlockingIOError:
                    break
        except Exception as e:
            self.log.debug("VHCI read error: %s", e)

    def _handle_hci_packet(self, data):
        """Handle HCI packet from host"""
        if not data:
            return

        pkt_type = data[0]

        if pkt_type == HCI_CMD:
            self._handle_hci_command(data[1:])
        elif pkt_type == HCI_ACL:
            self._handle_hci_acl(data[1:])
        else:
            self.log.warning("Unknown HCI packet type: 0x%02X", pkt_type)

    def _handle_hci_command(self, data):
        """Handle HCI command packet"""
        if len(data) < 3:
            return

        opcode = struct.unpack('<H', data[0:2])[0]
        param_len = data[2]
        params = data[3:3+param_len] if param_len > 0 else b''

        self.log.debug("HCI CMD: opcode=0x%04X len=%d", opcode, param_len)

        # Dispatch to handler
        response = self.dispatcher.dispatch(opcode, params)

        # Send response to VHCI
        if response:
            try:
                os.write(self.vhci, response)
            except Exception as e:
                self.log.error("VHCI write error: %s", e)

    def _handle_hci_acl(self, data):
        """Handle HCI ACL packet (TX from host)"""
        if len(data) < 4:
            return

        handle_flags = struct.unpack('<H', data[0:2])[0]
        handle = handle_flags & 0x0FFF
        pb_flags = (handle_flags >> 12) & 0x03
        data_len = struct.unpack('<H', data[2:4])[0]
        acl_data = data[4:4+data_len]

        self.log.debug("ACL TX: handle=0x%04X pb=%d len=%d", handle, pb_flags, data_len)

        # Send to firmware via Sniffle transmit
        if self.active_conn and acl_data:
            self._send_acl_to_sniffle(acl_data)

    def _send_acl_to_sniffle(self, acl_data):
        """Send ACL data to Sniffle firmware"""
        # Build Sniffle transmit command
        # Format: opcode, eventCtr[2], LLID, len, pdu
        llid = 0x03  # L2CAP start
        pdu_len = len(acl_data)
        event_ctr = 0  # TODO: track event counter

        cmd = [SNIFFLE_TRANSMIT, event_ctr & 0xFF, (event_ctr >> 8) & 0xFF, llid, pdu_len]
        cmd.extend(acl_data)

        self._send_sniffle_cmd(cmd)

    def _process_sniffle(self):
        """Process incoming messages from Sniffle firmware"""
        try:
            if self.ser.in_waiting:
                self.rx_buf += self.ser.read(self.ser.in_waiting)
        except:
            pass

        while True:
            msg_type, msg_body = self._recv_sniffle_msg()
            if msg_type is None:
                break

            if msg_type == SNIFFLE_MSG_PACKET:
                self._handle_sniffle_packet(msg_body)
            elif msg_type == SNIFFLE_MSG_STATE:
                self._handle_sniffle_state(msg_body)
            elif msg_type == SNIFFLE_MSG_DEBUG:
                self.log.debug("Sniffle debug: %s", msg_body.decode('latin-1', errors='replace'))

    def _recv_sniffle_msg(self):
        """Receive and decode a Sniffle message"""
        # Minimum: 4 bytes base64 + 2 bytes CRLF
        if len(self.rx_buf) < 6:
            return None, None

        # Find CRLF
        pos = self.rx_buf.find(b'\r\n')
        if pos < 0:
            return None, None

        line = self.rx_buf[:pos]
        self.rx_buf = self.rx_buf[pos+2:]

        if not line:
            return None, None

        # Decode base64
        try:
            data = b64decode(line)
        except:
            return None, None

        if len(data) < 2:
            return None, None

        return data[1], data[2:]

    def _handle_sniffle_packet(self, body):
        """Handle packet message from Sniffle"""
        if len(body) < 10:
            return

        ts, ln, ev, rssi, cp = struct.unpack("<LHHbB", body[:10])
        pkt_len = ln & 0x7FFF
        chan = cp & 0x3F
        pkt_data = body[10:]

        self.log.debug("Packet: chan=%d len=%d rssi=%d", chan, pkt_len, rssi)
        
        # Store last RSSI
        self.last_rssi = rssi

        if chan >= 37:
            # Advertising channel - generate LE Advertising Report
            self._handle_adv_packet(chan, pkt_data, pkt_len, rssi)
        else:
            # Data channel - generate ACL packet
            self._handle_data_packet(chan, pkt_data, pkt_len, rssi)

    def _handle_adv_packet(self, chan, pkt_data, pkt_len, rssi):
        """Handle advertising channel packet"""
        if pkt_len < 6 or len(pkt_data) < pkt_len:
            return

        pdu_header = pkt_data[0]
        pdu_type = pdu_header & 0x0F
        tx_addr = (pdu_header >> 6) & 0x01

        # Extract address
        if len(pkt_data) >= 8:
            adv_addr = pkt_data[2:8]
            adv_data = pkt_data[8:pkt_len] if pkt_len > 8 else b''

            # Map PDU type to event type
            evt_type_map = {
                0: 0x00,  # ADV_IND -> Connectable undirected
                1: 0x01,  # ADV_DIRECT_IND -> Connectable directed
                2: 0x02,  # ADV_NONCONN_IND -> Scannable undirected
                3: 0x03,  # SCAN_REQ -> Non-connectable undirected
                4: 0x04,  # SCAN_RSP -> Scan response
                5: 0x00,  # CONNECT_IND
                6: 0x00,  # ADV_SCAN_IND
            }
            evt_type = evt_type_map.get(pdu_type, 0x00)

            # Generate LE Advertising Report event
            event = events.le_advertising_report(
                event_type=evt_type,
                addr_type=tx_addr,
                addr=adv_addr,
                data=adv_data,
                rssi=rssi
            )

            try:
                os.write(self.vhci, event)
            except:
                pass

    def _handle_data_packet(self, chan, pkt_data, pkt_len, rssi):
        """Handle data channel packet"""
        if not self.active_conn or pkt_len < 2:
            return

        llid = pkt_data[0] & 0x03
        dlen = pkt_data[1]
        lldata = pkt_data[2:2+dlen] if len(pkt_data) >= 2+dlen else pkt_data[2:]

        self.log.debug("Data packet: llid=%d dlen=%d", llid, dlen)

        # Build ACL packet
        # Handle with PB=2 (first flushable)
        acl_handle = (self.conn_handle & 0x0FFF) | (0x02 << 12)
        acl_len = len(lldata) + 4  # L2CAP header + data

        # Build L2CAP header
        if len(lldata) >= 4:
            l2cap_len, l2cap_cid = struct.unpack('<HH', lldata[:4])
            acl_data = lldata
        else:
            return

        # Build ACL packet
        acl_pkt = struct.pack('<HH', acl_handle, len(acl_data)) + acl_data

        # Send to VHCI
        hci_acl = bytes([HCI_ACL]) + acl_pkt
        try:
            os.write(self.vhci, hci_acl)
        except:
            pass

    def _handle_sniffle_state(self, body):
        """Handle state change message from Sniffle"""
        if not body:
            return

        new_state = body[0]
        self.log.info("State change: %d -> %d", self.state, new_state)
        self.state = new_state

        if new_state in (STATE_CENTRAL, STATE_PERIPHERAL):
            # Connection established
            self.active_conn = True
            role = 0x00 if new_state == STATE_CENTRAL else 0x01

            self.log.info("Connection established! Role=%d, Peer=%s", 
                          role, (self.peer_addr or b'\x00'*6)[::-1].hex())

            # Generate LE Connection Complete event
            event = events.le_connection_complete(
                status=0x00,
                handle=self.conn_handle,
                role=role,
                peer_addr_type=self.peer_addr_type,
                peer_addr=self.peer_addr or b'\x00'*6,
                interval=0x0018,
                latency=0x0000,
                timeout=0x01F4
            )

            self.log.debug("Sending Connection Complete event: %s", event.hex())

            try:
                os.write(self.vhci, event)
                self.log.info("Connection Complete event sent!")
            except Exception as e:
                self.log.error("Failed to send Connection Complete: %s", e)

        elif new_state in (STATE_STATIC, STATE_PAUSED) and self.active_conn:
            # Disconnected
            self.active_conn = False

            self.log.info("Disconnected! State=%d", new_state)

            # Generate Disconnect Complete event
            event = events.disconnect_complete(
                status=0x00,
                handle=self.conn_handle,
                reason=0x13  # Remote user terminated
            )

            self.log.debug("Sending Disconnect Complete event: %s", event.hex())

            try:
                os.write(self.vhci, event)
                self.log.info("Disconnect Complete event sent!")
            except Exception as e:
                self.log.error("Failed to send Disconnect Complete: %s", e)

    # ==================== Sniffle Command Methods ====================

    def _send_sniffle_cmd(self, cmd_bytes):
        """Send command to Sniffle firmware"""
        b0 = (len(cmd_bytes) + 3) // 3
        msg = b64encode(bytes([b0] + cmd_bytes)) + b'\r\n'
        self.ser.write(msg)

    def sniffle_reset(self):
        """Reset Sniffle firmware"""
        self._send_sniffle_cmd([SNIFFLE_RESET])

    def sniffle_set_addr(self, addr):
        """Set own address"""
        if len(addr) != 6:
            return
        self._send_sniffle_cmd([SNIFFLE_SET_ADDR, 1] + list(addr))  # 1 = random

    def start_scanning(self, filter_dups=False):
        """Start BLE scanning"""
        self.scanning = True

        # Set channel 37 with advertising access address
        self._send_sniffle_cmd([SNIFFLE_SET_CHAN_AA_PHY, 37] +
                               list(struct.pack("<L", BLE_ADV_AA)) +
                               [PHY_1M, 0] +
                               list(struct.pack("<L", BLE_ADV_CRCI)))

        # Start scan
        self._send_sniffle_cmd([SNIFFLE_SCAN])

    def stop_scanning(self):
        """Stop BLE scanning"""
        self.scanning = False
        self._send_sniffle_cmd([SNIFFLE_PAUSE_DONE, 0x01])

    def start_advertising(self):
        """Start advertising"""
        self.advertising = True

        # Set address
        self.sniffle_set_addr(self.bd_addr)

        # Set advertising data
        adv_data = self.adv_data[:31] if self.adv_data else b''
        scan_rsp = self.scan_rsp_data[:31] if self.scan_rsp_data else b''

        # Pad to 31 bytes each
        adv_data = list(adv_data) + [0] * (31 - len(adv_data))
        scan_rsp = list(scan_rsp) + [0] * (31 - len(scan_rsp))

        # Map adv_type to Sniffle mode
        mode_map = {0: 0, 2: 2, 3: 3}  # ADV_IND, ADV_NONCONN_IND, ADV_SCAN_IND
        mode = mode_map.get(self.adv_type, 0)

        cmd = [SNIFFLE_ADVERTISE, mode, len(self.adv_data)] + adv_data[:31] + \
              [len(self.scan_rsp_data)] + scan_rsp[:31]
        self._send_sniffle_cmd(cmd)

    def stop_advertising(self):
        """Stop advertising"""
        self.advertising = False
        self._send_sniffle_cmd([SNIFFLE_PAUSE_DONE, 0x01])

    def initiate_connection(self, peer_addr, peer_addr_type,
                            interval_min, interval_max, latency, timeout):
        """Initiate BLE connection"""
        self.peer_addr = peer_addr
        self.peer_addr_type = peer_addr_type

        # Disable follow mode (we initiate, not follow)
        self._send_sniffle_cmd([SNIFFLE_FOLLOW, 0x00])

        # Set own address
        addr = [randrange(256) for _ in range(6)]
        addr[5] |= 0xC0  # Static random
        self.bd_addr = bytes(addr)
        self.sniffle_set_addr(self.bd_addr)

        # Set channel
        self._send_sniffle_cmd([SNIFFLE_SET_CHAN_AA_PHY, 37] +
                               list(struct.pack("<L", BLE_ADV_AA)) +
                               [PHY_1M, 0] +
                               list(struct.pack("<L", BLE_ADV_CRCI)))

        # Build LLData
        lldata = []
        lldata.extend([randrange(256) for _ in range(4)])  # Access address
        lldata.extend([randrange(256) for _ in range(3)])  # CRC init
        lldata.append(3)  # WinSize
        lldata.extend(struct.pack('<H', randint(5, 15)))  # WinOffset
        lldata.extend(struct.pack('<HHH', interval_min, latency, timeout))  # Interval, Latency, Timeout
        lldata.extend([0xFF, 0xFF, 0xFF, 0xFF, 0x1F])  # Channel map
        lldata.append(randint(5, 16))  # Hop

        # Send connect command
        cmd = [SNIFFLE_CONNECT, peer_addr_type] + list(peer_addr) + lldata
        self._send_sniffle_cmd(cmd)

    def cancel_connection(self):
        """Cancel ongoing connection attempt"""
        self._send_sniffle_cmd([SNIFFLE_PAUSE_DONE, 0x01])

    def disconnect(self):
        """Disconnect current connection"""
        self._send_sniffle_cmd([SNIFFLE_PAUSE_DONE, 0x01])

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

_SNIFFLE_CMD_NAMES = {
    SNIFFLE_SET_CHAN_AA_PHY: "SET_CHAN",
    SNIFFLE_PAUSE_DONE: "PAUSE",
    SNIFFLE_RSSI_FILTER: "RSSI",
    SNIFFLE_MAC_FILTER: "MAC",
    SNIFFLE_ADV_HOP: "ADV_HOP",
    SNIFFLE_FOLLOW: "FOLLOW",
    SNIFFLE_AUX_ADV: "AUXADV",
    SNIFFLE_RESET: "RESET",
    SNIFFLE_MARKER: "MARKER",
    SNIFFLE_TRANSMIT: "TRANSMIT",
    SNIFFLE_CONNECT: "CONNECT",
    SNIFFLE_SET_ADDR: "SET_ADDR",
    SNIFFLE_ADVERTISE: "ADVERTISE",
    SNIFFLE_INTERVAL_PRELOAD: "INTVL",
    SNIFFLE_SCAN: "SCAN",
    SNIFFLE_PHY_PRELOAD: "PHY",
    SNIFFLE_TX_POWER: "TXPWR",
}


class VHCIBridge:
    """Bridge between Linux VHCI and Sniffle firmware"""

    def __init__(self, serport, logger=None):
        self.logger = logger or logging.getLogger("vhci")
        self.log = self.logger

        # Serial port
        self.serport = serport
        self.ser = None
        self.rx_buf = b""

        # VHCI
        self.vhci = None
        self.vhci_flags = 0

        # State
        self.running = False
        self.state = STATE_STATIC

        # Controller info
        self.bd_addr = bytes([0xC0, 0xFF, 0xEE, 0xC0, 0xFF, 0xEE])  # Random static
        self.local_name = b"CatSniffer"
        self.conn_accept_timeout = 0x7D00  # 32000 slots = 20 seconds

        # Connection state
        self.conn_handle = 0x0001
        self.active_conn = False
        self.peer_addr = None
        self.peer_addr_type = 0
        self.last_rssi = -60  # Default RSSI
        self._conn_established_time = 0.0
        self._last_acl_from_bluez = (
            0.0  # Timestamp of last ACL packet received from BlueZ
        )
        self._acl_total_this_conn = (
            0  # Total ACL packets this connection (detects real sessions)
        )

        # Connection parameters
        self.conn_interval = 0x0018  # 30ms
        self.conn_latency = 0x0000
        self.conn_timeout = 0x01F4  # 5000ms = 5s

        # Channel map (all channels enabled)
        self.channel_map = bytes([0xFF, 0xFF, 0x1F, 0x00, 0x00])  # 37 channels

        # White list
        self.white_list = []  # List of (addr_type, addr) tuples
        self.white_list_max = 16

        # Resolving list (for privacy)
        self.resolving_list = (
            []
        )  # List of (peer_irk, peer_addr_type, peer_addr, local_irk)
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
        self.adv_data = b""
        self.scan_rsp_data = b""

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

        # Rate-limit timestamp for serial RX logging
        self._last_rx_log = 0.0

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
            self.ser.write(b"@@@@@@@@\r\n")
            self.ser.flush()
            time.sleep(0.1)
            self.ser.reset_input_buffer()
        except Exception as e:
            self.log.warning("Sync warning: %s", e)
        self.rx_buf = b""

        # Verify firmware is responding before reset
        self.log.info("Checking firmware response...")
        marker = struct.pack("<I", 0xDEADBEEF)
        self.ser.write(b64encode(bytes([5, 0x18]) + marker) + b"\r\n")
        self.ser.flush()
        time.sleep(0.5)

        if self.ser.in_waiting == 0:
            self.log.error("CatSniffer not responding! Is it in bootloader mode?")
            self.log.error("Check: ls -la /dev/ttyACM*")
            raise RuntimeError(
                "CatSniffer firmware not responding - device may be in bootloader mode"
            )

        self.ser.reset_input_buffer()

        # Reset firmware
        self.log.info("Resetting firmware...")
        try:
            self._send_sniffle_cmd([SNIFFLE_RESET])
            time.sleep(0.3)
            self.ser.reset_input_buffer()
        except Exception as e:
            self.log.warning("Reset warning: %s", e)
        self.rx_buf = b""

        # Set serial to non-blocking
        self.ser.timeout = 0

        # Open VHCI device
        self.log.info("Opening VHCI device...")
        self.vhci = os.open("/dev/vhci", os.O_RDWR)

        # Create VHCI controller
        # HCI_VENDOR_PKT (0xFF) + HCI_PRIMARY (0)
        self.log.debug("Sending VHCI create request...")
        os.write(self.vhci, bytes([0xFF, 0x00]))

        # Read response (blocking, short timeout)
        # Response format: pkt_type (1), opcode (1), index_lo (1), index_hi (1)
        readable, _, _ = select.select([self.vhci], [], [], 2.0)
        if readable:
            rsp = os.read(self.vhci, 260)
            self.log.info(
                "VHCI response: %s (len=%d)", rsp.hex() if rsp else "empty", len(rsp)
            )
            if len(rsp) >= 4:
                self.hci_index = rsp[2] | (rsp[3] << 8)
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
        heartbeat = 0
        # Delay advertising reports for 1 second to let BlueZ initialize
        startup_done = False
        startup_time = time.time()
        while self.running:
            # Process HCI commands from host
            self._process_vhci()

            # Process messages from firmware (but delay adv reports)
            if startup_done:
                self._process_sniffle()
            elif time.time() - startup_time > 1.0:
                startup_done = True
                self._process_sniffle()
            else:
                # Just read serial to prevent buffer overflow
                if self.ser.in_waiting:
                    self.ser.read(self.ser.in_waiting)

            # Watchdog: force disconnect stale connections BlueZ never properly closes.
            # Threshold adapts: short (10s) if no real session happened (bettercap
            # abandoned after its timeout), long (60s) for interactive tools like
            # bluetoothctl that are idle between commands.
            if self.active_conn:
                acl_silence = time.time() - self._last_acl_from_bluez
                threshold = 60.0 if self._acl_total_this_conn > 5 else 10.0
                if acl_silence > threshold:
                    self.log.warning(
                        "Watchdog: no ACL from BlueZ for %.1fs (total=%d, threshold=%.0fs) — forcing disconnect",
                        acl_silence,
                        self._acl_total_this_conn,
                        threshold,
                    )
                    self.active_conn = False
                    self._send_sniffle_cmd([SNIFFLE_PAUSE_DONE, 0x01])
                    event = events.disconnect_complete(
                        0x00, self.conn_handle, 0x08
                    )  # Connection timeout
                    try:
                        os.write(self.vhci, event)
                    except Exception as e:
                        self.log.error("Watchdog disconnect event failed: %s", e)
                    if self.scanning:
                        self.start_scanning()

            # Heartbeat every 1000 iterations
            heartbeat += 1
            if heartbeat % 1000 == 0:
                self.log.debug(
                    "Heartbeat: state=%d rx_buf=%d", self.state, len(self.rx_buf)
                )

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

        opcode = struct.unpack("<H", data[0:2])[0]
        param_len = data[2]
        params = data[3 : 3 + param_len] if param_len > 0 else b""

        self.log.info(
            "HCI CMD: opcode=0x%04X len=%d params=%s", opcode, param_len, params.hex()
        )

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

        handle_flags = struct.unpack("<H", data[0:2])[0]
        handle = handle_flags & 0x0FFF
        pb_flags = (handle_flags >> 12) & 0x03
        data_len = struct.unpack("<H", data[2:4])[0]
        acl_data = data[4 : 4 + data_len]

        self.log.debug("ACL TX: handle=0x%04X pb=%d len=%d", handle, pb_flags, data_len)
        self._last_acl_from_bluez = time.time()
        self._acl_total_this_conn += 1

        # Send to firmware via Sniffle transmit
        if self.active_conn and acl_data:
            self._send_acl_to_sniffle(acl_data)

    def _send_acl_to_sniffle(self, acl_data):
        """Send ACL data to Sniffle firmware"""
        # LLID=0x02: L2CAP start (or complete) fragment — NOT 0x03 which is LL Control
        llid = 0x02
        pdu_len = len(acl_data)
        event_ctr = 0

        cmd = [
            SNIFFLE_TRANSMIT,
            event_ctr & 0xFF,
            (event_ctr >> 8) & 0xFF,
            llid,
            pdu_len,
        ]
        cmd.extend(acl_data)
        self._send_sniffle_cmd(cmd)

        # Notify BlueZ that the TX slot was consumed so it can send more ACL data
        ncp = events.number_of_completed_packets([(self.conn_handle, 1)])
        try:
            os.write(self.vhci, ncp)
        except Exception as e:
            self.log.error("Failed to send NCP event: %s", e)

    def _process_sniffle(self):
        """Process incoming messages from Sniffle firmware"""
        try:
            if self.ser.in_waiting:
                data = self.ser.read(self.ser.in_waiting)
                self.rx_buf += data
                now = time.time()
                if now - self._last_rx_log > 1.0:
                    self.log.debug(
                        "Serial RX: %d bytes, buffer: %d bytes",
                        len(data),
                        len(self.rx_buf),
                    )
                    self._last_rx_log = now
        except Exception:
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
                self.log.debug(
                    "Sniffle debug: %s", msg_body.decode("latin-1", errors="replace")
                )

    def _recv_sniffle_msg(self):
        """Receive and decode a Sniffle message"""
        # Minimum: 4 bytes base64 + 2 bytes CRLF
        if len(self.rx_buf) < 6:
            return None, None

        # Find CRLF
        pos = self.rx_buf.find(b"\r\n")
        if pos < 0:
            return None, None

        line = self.rx_buf[:pos]
        self.rx_buf = self.rx_buf[pos + 2 :]

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
            log_fn = self.log.debug if pkt_len == 2 else self.log.info
            log_fn(
                "DATA CHANNEL: chan=%d len=%d rssi=%d state=%d",
                chan,
                pkt_len,
                rssi,
                self.state,
            )
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
            adv_data = pkt_data[8:pkt_len] if pkt_len > 8 else b""

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
                rssi=rssi,
            )

            try:
                os.write(self.vhci, event)
                self.log.debug(
                    "Sent adv report: addr=%s type=%d", adv_addr[::-1].hex(), evt_type
                )
            except Exception as e:
                self.log.error("Failed to send adv report: %s", e)

    def _handle_data_packet(self, chan, pkt_data, pkt_len, rssi):
        """Handle data channel packet"""
        if not self.active_conn or pkt_len < 2:
            return

        llid = pkt_data[0] & 0x03
        dlen = pkt_data[1]
        lldata = pkt_data[2 : 2 + dlen] if len(pkt_data) >= 2 + dlen else pkt_data[2:]

        # Keepalives (llid=1, dlen=0) are very frequent — log at DEBUG only
        if dlen == 0:
            self.log.debug("Data packet: keepalive llid=%d chan=%d", llid, chan)
            return
        self.log.info(
            "Data packet: llid=%d dlen=%d data=%s", llid, dlen, lldata[:8].hex()
        )

        # LLID=3 is an LL Control PDU — Sniffle firmware does NOT auto-respond to them.
        # We must respond to certain procedures so the peer's ATT stack is not stalled.
        if llid == 0x03:
            self._handle_ll_control(lldata)
            return

        # LLID=1: L2CAP continuation fragment — forward with PB=1 (no L2CAP header)
        if llid == 0x01:
            if dlen > 0 and lldata:
                acl_handle = (self.conn_handle & 0x0FFF) | (0x01 << 12)
                acl_pkt = struct.pack("<HH", acl_handle, len(lldata)) + lldata
                hci_acl = bytes([HCI_ACL]) + acl_pkt
                try:
                    os.write(self.vhci, hci_acl)
                    self.log.info(
                        "ACL CONT → BlueZ: len=%d data=%s", len(lldata), lldata.hex()
                    )
                except Exception as e:
                    self.log.error("Failed to send ACL continuation: %s", e)
            return

        # Build ACL packet (LLID=2: first/complete L2CAP fragment)
        # Handle with PB=2 (first flushable)
        acl_handle = (self.conn_handle & 0x0FFF) | (0x02 << 12)

        # Build L2CAP header
        if len(lldata) >= 4:
            l2cap_len, l2cap_cid = struct.unpack("<HH", lldata[:4])
            acl_data = lldata
        else:
            return

        # Build ACL packet
        acl_pkt = struct.pack("<HH", acl_handle, len(acl_data)) + acl_data

        # Send to VHCI
        hci_acl = bytes([HCI_ACL]) + acl_pkt
        try:
            os.write(self.vhci, hci_acl)
            self.log.info(
                "ACL RX → BlueZ: l2cap_len=%d cid=0x%04X data=%s",
                l2cap_len,
                l2cap_cid,
                lldata[4:].hex(),
            )
        except Exception as e:
            self.log.error("Failed to send ACL packet: %s", e)

    def _handle_ll_control(self, lldata):
        """Handle received LL Control PDU (LLID=3) from peer.

        Sniffle firmware does NOT respond to these automatically in CENTRAL mode.
        We must respond to at least LL_VERSION_IND and LL_FEATURE_REQ so that
        NimBLE's LL procedure completes and its ATT layer can send responses.
        """
        if not lldata:
            return
        opcode = lldata[0]

        if opcode == 0x0C:  # LL_VERSION_IND
            # Peer is asking for our version. Respond with our own LL_VERSION_IND.
            peer_ver = lldata[1] if len(lldata) > 1 else 0
            peer_cid = struct.unpack("<H", lldata[2:4])[0] if len(lldata) >= 4 else 0
            self.log.info(
                "LL_VERSION_IND from peer: VersNr=0x%02X CompId=0x%04X",
                peer_ver,
                peer_cid,
            )
            # LL_VERSION_IND: opcode(1) + VersNr(1) + CompId(2) + SubVersNr(2) = 6 bytes
            rsp = bytes([0x0C, 0x09, 0x5F, 0x00, 0x00, 0x00])  # BLE 5.0, company 0x005F
            self._send_ll_pdu(rsp)
            self.log.info("Sent LL_VERSION_IND response")

        elif opcode == 0x08:  # LL_FEATURE_REQ
            # Central can also receive LL_FEATURE_REQ from peripheral.
            self.log.info("LL_FEATURE_REQ from peer")
            # LL_FEATURE_RSP: opcode(1) + FeatureSet(8) = 9 bytes
            # Report basic LE features: Encryption, Conn Param Req, LE Data Length Extension
            features = bytes([0x3F, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
            rsp = bytes([0x09]) + features
            self._send_ll_pdu(rsp)
            self.log.info("Sent LL_FEATURE_RSP")

        elif opcode == 0x09:  # LL_FEATURE_RSP (response to our LL_FEATURE_REQ)
            self.log.info(
                "LL_FEATURE_RSP from peer: features=%s",
                lldata[1:9].hex() if len(lldata) >= 9 else lldata[1:].hex(),
            )

        elif (
            opcode == 0x0E
        ):  # LL_SLAVE_FEATURE_REQ (peripheral requesting central's features)
            self.log.info("LL_SLAVE_FEATURE_REQ from peer")
            features = bytes([0x3F, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
            rsp = bytes([0x09]) + features  # LL_FEATURE_RSP
            self._send_ll_pdu(rsp)
            self.log.info("Sent LL_FEATURE_RSP for LL_SLAVE_FEATURE_REQ")

        elif opcode == 0x14:  # LL_LENGTH_REQ (data length extension)
            self.log.info("LL_LENGTH_REQ from peer")
            # LL_LENGTH_RSP: opcode(1) + MaxRxOctets(2) + MaxRxTime(2) + MaxTxOctets(2) + MaxTxTime(2)
            rsp = bytes([0x15]) + struct.pack("<HHHH", 251, 2120, 251, 2120)
            self._send_ll_pdu(rsp)
            self.log.info("Sent LL_LENGTH_RSP")

        elif opcode == 0x02:  # LL_TERMINATE_IND
            reason = lldata[1] if len(lldata) > 1 else 0x00
            self.log.info("LL_TERMINATE_IND from peer: reason=0x%02X", reason)
            # Connection will drop naturally via state change to STATIC/PAUSED

        else:
            self.log.debug("LL Control PDU opcode=0x%02X (ignored)", opcode)

    def _send_ll_pdu(self, ll_payload):
        """Send an LL Control PDU (LLID=3) via TRANSMIT command"""
        event_ctr = 0
        cmd = [
            SNIFFLE_TRANSMIT,
            event_ctr & 0xFF,
            (event_ctr >> 8) & 0xFF,
            0x03,
            len(ll_payload),
        ]
        cmd.extend(ll_payload)
        self._send_sniffle_cmd(cmd)

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
            self._conn_established_time = time.time()
            self._last_acl_from_bluez = time.time()  # Grace period starts now
            self._acl_total_this_conn = 0
            role = 0x00 if new_state == STATE_CENTRAL else 0x01

            self.log.info(
                "Connection established! Role=%d, Peer=%s",
                role,
                (self.peer_addr or b"\x00" * 6)[::-1].hex(),
            )

            # Generate LE Connection Complete event
            event = events.le_connection_complete(
                status=0x00,
                handle=self.conn_handle,
                role=role,
                peer_addr_type=self.peer_addr_type,
                peer_addr=self.peer_addr or b"\x00" * 6,
                interval=0x0018,
                latency=0x0000,
                timeout=0x01F4,
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
                reason=0x13,  # Remote user terminated
            )

            self.log.debug("Sending Disconnect Complete event: %s", event.hex())

            try:
                os.write(self.vhci, event)
                self.log.info("Disconnect Complete event sent!")
            except Exception as e:
                self.log.error("Failed to send Disconnect Complete: %s", e)

            # BlueZ won't resend LE_SET_SCAN_ENABLE if it thinks scanning is already
            # on. Sniffle just went to PAUSED, so proactively restart scanning.
            if self.scanning:
                self.log.info("Auto-restarting scan after disconnect")
                self.start_scanning()

    # ==================== Sniffle Command Methods ====================

    def _send_sniffle_cmd(self, cmd_bytes):
        """Send command to Sniffle firmware"""
        b0 = (len(cmd_bytes) + 3) // 3
        opcode = cmd_bytes[0] if cmd_bytes else 0
        self.log.info(
            "CMD: %s (%s)",
            _SNIFFLE_CMD_NAMES.get(opcode, f"0x{opcode:02x}"),
            bytes(cmd_bytes[:15]).hex(),
        )
        msg = b64encode(bytes([b0] + cmd_bytes)) + b"\r\n"
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
        # Preload PHY to 1M (firmware defaults to 2M)
        self._send_sniffle_cmd([SNIFFLE_PHY_PRELOAD, PHY_1M])

        self._send_sniffle_cmd(
            [SNIFFLE_SET_CHAN_AA_PHY]
            + list(struct.pack("<BLBL", 37, BLE_ADV_AA, PHY_1M, BLE_ADV_CRCI))
        )

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
        adv_data = self.adv_data[:31] if self.adv_data else b""
        scan_rsp = self.scan_rsp_data[:31] if self.scan_rsp_data else b""

        # Pad to 31 bytes each
        adv_data = list(adv_data) + [0] * (31 - len(adv_data))
        scan_rsp = list(scan_rsp) + [0] * (31 - len(scan_rsp))

        # Map adv_type to Sniffle mode
        mode_map = {0: 0, 2: 2, 3: 3}  # ADV_IND, ADV_NONCONN_IND, ADV_SCAN_IND
        mode = mode_map.get(self.adv_type, 0)

        cmd = (
            [SNIFFLE_ADVERTISE, mode, len(self.adv_data)]
            + adv_data[:31]
            + [len(self.scan_rsp_data)]
            + scan_rsp[:31]
        )
        self._send_sniffle_cmd(cmd)

    def stop_advertising(self):
        """Stop advertising"""
        self.advertising = False
        self._send_sniffle_cmd([SNIFFLE_PAUSE_DONE, 0x01])

    def initiate_connection(
        self, peer_addr, peer_addr_type, interval_min, interval_max, latency, timeout
    ):
        """Initiate BLE connection"""
        self.peer_addr = peer_addr
        self.peer_addr_type = peer_addr_type

        # Set channel first (as in initiator.py)
        self._send_sniffle_cmd(
            [SNIFFLE_SET_CHAN_AA_PHY]
            + list(struct.pack("<BLBL", 37, BLE_ADV_AA, PHY_1M, BLE_ADV_CRCI))
        )

        # Pause after done (required for initiator mode)
        self._send_sniffle_cmd([SNIFFLE_PAUSE_DONE, 0x01])

        # Disable follow mode (we initiate, not follow)
        self._send_sniffle_cmd([SNIFFLE_FOLLOW, 0x00])

        # Turn off RSSI filter
        self._send_sniffle_cmd([SNIFFLE_RSSI_FILTER])

        # Enable aux advertising (initiator needs this)
        self._send_sniffle_cmd([SNIFFLE_AUX_ADV, 0x01])

        # Set MAC filter for target (no hop3 for initiator)
        self._send_sniffle_cmd([SNIFFLE_MAC_FILTER] + list(peer_addr))

        # Set own address (random static)
        addr = [randrange(256) for _ in range(6)]
        addr[5] |= 0xC0  # Static random
        self.bd_addr = bytes(addr)
        self.sniffle_set_addr(self.bd_addr)

        # Set TX power to +5 dBm
        self._send_sniffle_cmd([SNIFFLE_TX_POWER, 5])

        # Reset preloaded interval
        self._send_sniffle_cmd([SNIFFLE_INTERVAL_PRELOAD])

        # Flush old packets: send marker and wait for it to echo back (like mark_and_flush)
        marker_val = struct.pack("<I", randint(0, 0xFFFFFFFF))
        self._send_sniffle_cmd([SNIFFLE_MARKER] + list(marker_val))
        flush_deadline = time.time() + 0.5
        while time.time() < flush_deadline:
            if self.ser.in_waiting:
                self.rx_buf += self.ser.read(self.ser.in_waiting)
            msg_type, msg_body = self._recv_sniffle_msg()
            if msg_type == SNIFFLE_MSG_MARKER and msg_body[:4] == marker_val:
                break  # Marker echoed back — buffer is clean
            time.sleep(0.005)

        self.log.info("Flush complete, buffer cleared")

        # Build LLData
        lldata = []
        lldata.extend([randrange(256) for _ in range(4)])  # Access address
        lldata.extend([randrange(256) for _ in range(3)])  # CRC init
        lldata.append(3)  # WinSize
        lldata.extend(struct.pack("<H", randint(5, 15)))  # WinOffset
        lldata.extend(
            struct.pack("<HHH", interval_min, latency, timeout)
        )  # Interval, Latency, Timeout
        lldata.extend([0xFF, 0xFF, 0xFF, 0xFF, 0x1F])  # Channel map
        lldata.append(randint(5, 16))  # Hop

        # Store access address for decoder (like initiator.py: hw.decoder_state.cur_aa = _aa)
        self.conn_aa = struct.unpack("<I", bytes(lldata[:4]))[0]

        # Send connect command
        cmd = [SNIFFLE_CONNECT, peer_addr_type] + list(peer_addr) + lldata
        self._send_sniffle_cmd(cmd)

        self.log.info(
            "Connect sent: peer=%s aa=0x%08X", peer_addr[::-1].hex(), self.conn_aa
        )

    def cancel_connection(self):
        """Cancel ongoing connection attempt"""
        self._send_sniffle_cmd([SNIFFLE_PAUSE_DONE, 0x01])

    def disconnect(self):
        """Disconnect current connection"""
        self._send_sniffle_cmd([SNIFFLE_PAUSE_DONE, 0x01])

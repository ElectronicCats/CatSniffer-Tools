"""
VHCI Commands - HCI command handlers
"""

import struct
import time
import random
from .constants import *
from . import events


class HCICommandDispatcher:
    """Dispatches HCI commands to appropriate handlers"""

    def __init__(self, bridge):
        self.bridge = bridge

        # Map opcodes to handler methods
        self.handlers = {
            # Baseband
            OP_RESET: self.handle_reset,
            OP_SET_EVENT_MASK: self.handle_set_event_mask,
            OP_READ_LOCAL_NAME: self.handle_read_local_name,
            OP_WRITE_LOCAL_NAME: self.handle_write_local_name,
            OP_READ_CONN_ACCEPT_TIMEOUT: self.handle_read_conn_accept_timeout,
            OP_WRITE_CONN_ACCEPT_TIMEOUT: self.handle_write_conn_accept_timeout,
            OP_READ_PAGE_TIMEOUT: self.handle_read_page_timeout,
            OP_WRITE_PAGE_TIMEOUT: self.handle_write_page_timeout,
            OP_READ_SCAN_ENABLE: self.handle_read_scan_enable,
            OP_WRITE_SCAN_ENABLE: self.handle_write_scan_enable,
            OP_READ_CLASS_OF_DEVICE: self.handle_read_class_of_device,
            OP_WRITE_CLASS_OF_DEVICE: self.handle_write_class_of_device,
            OP_READ_NUM_SUPPORTED_IAC: self.handle_read_num_supported_iac,
            OP_READ_CURRENT_IAC_LAP: self.handle_read_current_iac_lap,
            OP_READ_EXTENDED_INQUIRY_RESPONSE: self.handle_read_extended_inquiry_response,
            OP_WRITE_EXTENDED_INQUIRY_RESPONSE: self.handle_write_extended_inquiry_response,
            OP_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT: self.handle_write_secure_connections_host_support,
            # Informational
            OP_READ_LOCAL_VERSION: self.handle_read_local_version,
            OP_READ_LOCAL_SUPPORTED_COMMANDS: self.handle_read_local_supported_commands,
            OP_READ_LOCAL_SUPPORTED_FEATURES: self.handle_read_local_supported_features,
            OP_READ_BUFFER_SIZE: self.handle_read_buffer_size,
            OP_READ_BD_ADDR: self.handle_read_bd_addr,
            OP_READ_LOCAL_EXT_FEATURES: self.handle_read_local_ext_features,
            OP_READ_DATA_BLOCK_SIZE: self.handle_read_data_block_size,
            # Link Control
            OP_DISCONNECT: self.handle_disconnect,
            # Status Parameters
            OP_READ_RSSI: self.handle_read_rssi,
            # LE
            OP_LE_SET_EVENT_MASK: self.handle_le_set_event_mask,
            OP_LE_READ_BUFFER_SIZE: self.handle_le_read_buffer_size,
            OP_LE_READ_LOCAL_SUPPORTED_FEATURES: self.handle_le_read_local_supported_features,
            OP_LE_SET_RANDOM_ADDRESS: self.handle_le_set_random_address,
            OP_LE_SET_ADVERTISING_PARAMETERS: self.handle_le_set_advertising_parameters,
            OP_LE_READ_ADVERTISING_CHANNEL_TX_POWER: self.handle_le_read_advertising_channel_tx_power,
            OP_LE_SET_ADVERTISING_DATA: self.handle_le_set_advertising_data,
            OP_LE_SET_SCAN_RESPONSE_DATA: self.handle_le_set_scan_response_data,
            OP_LE_SET_ADVERTISE_ENABLE: self.handle_le_set_advertise_enable,
            OP_LE_SET_SCAN_PARAMETERS: self.handle_le_set_scan_parameters,
            OP_LE_SET_SCAN_ENABLE: self.handle_le_set_scan_enable,
            OP_LE_CREATE_CONNECTION: self.handle_le_create_connection,
            OP_LE_CREATE_CONNECTION_CANCEL: self.handle_le_create_connection_cancel,
            OP_LE_READ_WHITE_LIST_SIZE: self.handle_le_read_white_list_size,
            OP_LE_CLEAR_WHITE_LIST: self.handle_le_clear_white_list,
            OP_LE_ADD_DEVICE_TO_WHITE_LIST: self.handle_le_add_device_to_white_list,
            OP_LE_REMOVE_DEVICE_FROM_WHITE_LIST: self.handle_le_remove_device_from_white_list,
            OP_LE_READ_CHANNEL_MAP: self.handle_le_read_channel_map,
            OP_LE_READ_SUPPORTED_STATES: self.handle_le_read_supported_states,
            OP_LE_SET_DATA_LENGTH: self.handle_le_set_data_length,
            OP_LE_READ_SUGGESTED_DEFAULT_DATA_LENGTH: self.handle_le_read_suggested_default_data_length,
            OP_LE_WRITE_SUGGESTED_DEFAULT_DATA_LENGTH: self.handle_le_write_suggested_default_data_length,
            OP_LE_READ_MAXIMUM_DATA_LENGTH: self.handle_le_read_maximum_data_length,
            OP_LE_RAND: self.handle_le_rand,
            OP_LE_ENCRYPT: self.handle_le_encrypt,
            # Status Parameters
            OP_READ_FAILED_CONTACT_COUNTER: self.handle_read_failed_contact_counter,
            OP_RESET_FAILED_CONTACT_COUNTER: self.handle_reset_failed_contact_counter,
            OP_READ_LINK_QUALITY: self.handle_read_link_quality,
            OP_READ_AFH_CHANNEL_MAP: self.handle_read_afh_channel_map,
            OP_READ_CLOCK: self.handle_read_clock,
            # LE Connection Management
            OP_LE_CONNECTION_UPDATE: self.handle_le_connection_update,
            OP_LE_SET_HOST_CHANNEL_CLASSIFICATION: self.handle_le_set_host_channel_classification,
            OP_LE_READ_REMOTE_USED_FEATURES: self.handle_le_read_remote_used_features,
            # LE Encryption (stubs)
            OP_LE_START_ENCRYPTION: self.handle_le_start_encryption,
            OP_LE_LONG_TERM_KEY_REQUEST_REPLY: self.handle_le_long_term_key_request_reply,
            OP_LE_LONG_TERM_KEY_REQUEST_NEGATIVE_REPLY: self.handle_le_long_term_key_request_negative_reply,
            # LE Direct Test Mode
            OP_LE_RECEIVER_TEST: self.handle_le_receiver_test,
            OP_LE_TRANSMITTER_TEST: self.handle_le_transmitter_test,
            OP_LE_TEST_END: self.handle_le_test_end,
            # LE Connection Parameter Request
            OP_LE_REMOTE_CONNECTION_PARAMETER_REQUEST_REPLY: self.handle_le_remote_conn_param_request_reply,
            OP_LE_REMOTE_CONNECTION_PARAMETER_REQUEST_NEGATIVE_REPLY: self.handle_le_remote_conn_param_request_negative_reply,
            # LE Cryptographic (stubs)
            OP_LE_READ_LOCAL_P256_PUBLIC_KEY: self.handle_le_read_local_p256_public_key,
            OP_LE_GENERATE_DHKEY: self.handle_le_generate_dhkey,
            # LE Resolving List
            OP_LE_ADD_DEVICE_TO_RESOLVING_LIST: self.handle_le_add_device_to_resolving_list,
            OP_LE_REMOVE_DEVICE_FROM_RESOLVING_LIST: self.handle_le_remove_device_from_resolving_list,
            OP_LE_CLEAR_RESOLVING_LIST: self.handle_le_clear_resolving_list,
            OP_LE_READ_RESOLVING_LIST_SIZE: self.handle_le_read_resolving_list_size,
            OP_LE_READ_PEER_RESOLVABLE_ADDRESS: self.handle_le_read_peer_resolvable_address,
            OP_LE_READ_LOCAL_RESOLVABLE_ADDRESS: self.handle_le_read_local_resolvable_address,
            OP_LE_SET_ADDRESS_RESOLUTION_ENABLE: self.handle_le_set_address_resolution_enable,
            OP_LE_SET_RESOLVABLE_PRIVATE_ADDRESS_TIMEOUT: self.handle_le_set_resolvable_private_address_timeout,
            # LE PHY
            OP_LE_READ_PHY: self.handle_le_read_phy,
            OP_LE_SET_DEFAULT_PHY: self.handle_le_set_default_phy,
            OP_LE_SET_PHY: self.handle_le_set_phy,
        }

    def dispatch(self, opcode, params):
        """Dispatch command to handler, return event response"""
        handler = self.handlers.get(opcode)
        if handler:
            try:
                return handler(opcode, params)
            except Exception as e:
                self.bridge.log.error("Handler error for opcode 0x%04X: %s", opcode, e)
                return events.command_complete(opcode, bytes([0x01]))  # Unknown error
        else:
            # Unknown command - return success anyway (many are optional)
            self.bridge.log.debug("Unhandled opcode 0x%04X, returning success", opcode)
            return events.command_complete(opcode, bytes([0x00]))

    # ==================== Baseband Commands ====================

    def handle_reset(self, opcode, params):
        """Reset the controller"""
        self.bridge.log.info("Reset command")
        self.bridge.sniffle_reset()
        self.bridge.state = STATE_STATIC
        self.bridge.scanning = False
        self.bridge.advertising = False
        self.bridge.active_conn = False
        return events.command_complete(opcode, bytes([0x00]))

    def handle_set_event_mask(self, opcode, params):
        """Set event mask"""
        if len(params) >= 8:
            self.bridge.event_mask = params[:8]
        return events.command_complete(opcode, bytes([0x00]))

    def handle_read_local_name(self, opcode, params):
        """Read local name"""
        return events.cc_read_local_name(opcode, self.bridge.local_name)

    def handle_write_local_name(self, opcode, params):
        """Write local name"""
        if len(params) >= 1:
            # Extract name up to first null or 248 bytes
            name_end = params.find(b"\x00")
            if name_end >= 0:
                self.bridge.local_name = params[:name_end]
            else:
                self.bridge.local_name = params[:248]
        return events.command_complete(opcode, bytes([0x00]))

    def handle_read_conn_accept_timeout(self, opcode, params):
        """Read connection accept timeout"""
        data = bytes([0x00]) + struct.pack("<H", self.bridge.conn_accept_timeout)
        return events.command_complete(opcode, data)

    def handle_write_conn_accept_timeout(self, opcode, params):
        """Write connection accept timeout"""
        if len(params) >= 2:
            self.bridge.conn_accept_timeout = struct.unpack("<H", params[:2])[0]
        return events.command_complete(opcode, bytes([0x00]))

    def handle_read_page_timeout(self, opcode, params):
        """Read page timeout"""
        data = bytes([0x00]) + struct.pack("<H", 0x2000)  # Default 8192 slots
        return events.command_complete(opcode, data)

    def handle_write_page_timeout(self, opcode, params):
        """Write page timeout"""
        if len(params) >= 2:
            self.bridge.page_timeout = struct.unpack("<H", params[:2])[0]
        return events.command_complete(opcode, bytes([0x00]))

    def handle_read_scan_enable(self, opcode, params):
        """Read scan enable"""
        data = bytes([0x00, 0x00])  # No scan
        return events.command_complete(opcode, data)

    def handle_write_scan_enable(self, opcode, params):
        """Write scan enable"""
        if len(params) >= 1:
            self.bridge.scan_enable = params[0]
        return events.command_complete(opcode, bytes([0x00]))

    def handle_read_class_of_device(self, opcode, params):
        """Read class of device"""
        data = bytes([0x00, 0x1F, 0x00, 0x00])  # Unclassified device
        return events.command_complete(opcode, data)

    def handle_write_class_of_device(self, opcode, params):
        """Write class of device"""
        if len(params) >= 3:
            self.bridge.class_of_device = params[:3]
        return events.command_complete(opcode, bytes([0x00]))

    def handle_read_num_supported_iac(self, opcode, params):
        """Read Number of Supported IAC"""
        # Response: status(1) + num_iac(1)
        return events.command_complete(opcode, bytes([0x00, 0x01]))  # 1 IAC supported

    def handle_read_current_iac_lap(self, opcode, params):
        """Read Current IAC LAP"""
        # Response: status(1) + num_current_iac(1) + iac_lap(s)
        # Return 1 IAC: GIAC (0x9E8B33)
        return events.command_complete(opcode, bytes([0x00, 0x01, 0x33, 0x8B, 0x9E]))

    def handle_read_extended_inquiry_response(self, opcode, params):
        """Read Extended Inquiry Response"""
        # Format: status(1) + fec_required(1) + eir_data(240)
        eir_data = bytes([0x00, 0x00]) + bytes(240)  # FEC not required, empty EIR
        return events.command_complete(opcode, eir_data)

    def handle_write_extended_inquiry_response(self, opcode, params):
        """Write Extended Inquiry Response"""
        if len(params) >= 1:
            self.bridge.fec_required = params[0]
            self.bridge.eir_data = params[1:241] if len(params) > 1 else bytes(240)
        return events.command_complete(opcode, bytes([0x00]))

    def handle_write_secure_connections_host_support(self, opcode, params):
        """Handle Write Secure Connections Host Support (0x0C6D)"""
        # Just acknowledge - we don't actually support secure connections
        return events.command_complete(opcode, bytes([0x00]))

    # ==================== Informational Commands ====================

    def handle_read_local_version(self, opcode, params):
        """Read local version information"""
        return events.cc_read_local_version(opcode)

    def handle_read_local_supported_commands(self, opcode, params):
        """Read supported commands bitmask"""
        return events.cc_read_local_supported_commands(opcode)

    def handle_read_local_supported_features(self, opcode, params):
        """Read LMP features"""
        return events.cc_read_local_supported_features(opcode)

    def handle_read_buffer_size(self, opcode, params):
        """Read buffer size"""
        return events.cc_read_buffer_size(opcode)

    def handle_read_bd_addr(self, opcode, params):
        """Read BD_ADDR"""
        return events.cc_read_bd_addr(opcode, self.bridge.bd_addr)

    def handle_read_local_ext_features(self, opcode, params):
        """Read Local Extended Features"""
        page = params[0] if len(params) >= 1 else 0
        if page == 0:
            # Same as Read_Local_Supported_Features: LE-only (bits 37+38)
            features = bytes([0x00, 0x00, 0x00, 0x00, 0x60, 0x00, 0x00, 0x00])
        else:
            features = bytes(8)
        data = bytes([0x00, 0x01]) + features
        return events.command_complete(opcode, data)

    def handle_read_data_block_size(self, opcode, params):
        """Read Data Block Size"""
        data = bytes([0x00]) + struct.pack("<HHH", 251, 1, 15)
        return events.command_complete(opcode, data)

    def handle_read_rssi(self, opcode, params):
        """Read RSSI of current connection"""
        if len(params) >= 2:
            handle = struct.unpack("<H", params[:2])[0]
            rssi = self.bridge.last_rssi
            # RSSI is signed, convert to byte
            rssi_byte = rssi if rssi >= 0 else (256 + rssi)
            data = bytes([0x00]) + struct.pack("<H", handle) + bytes([rssi_byte])
            return events.command_complete(opcode, data)
        return events.command_complete(opcode, bytes([0x02]))

    # ==================== Link Control Commands ====================

    def handle_disconnect(self, opcode, params):
        """Disconnect connection"""
        if len(params) >= 3:
            handle = struct.unpack("<H", params[:2])[0]
            reason = params[2]
            self.bridge.log.info(
                "Disconnect handle=0x%04X reason=0x%02X", handle, reason
            )
            self.bridge.disconnect()
            # Response comes later via disconnect complete event
            return events.command_status(opcode, 0x00)
        return events.command_complete(opcode, bytes([0x02]))  # Unknown connection

    # ==================== LE Commands ====================

    def handle_le_set_event_mask(self, opcode, params):
        """LE Set Event Mask"""
        if len(params) >= 8:
            self.bridge.le_event_mask = params[:8]
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_read_buffer_size(self, opcode, params):
        """LE Read Buffer Size"""
        return events.cc_le_read_buffer_size(opcode)

    def handle_le_read_local_supported_features(self, opcode, params):
        """LE Read Local Supported Features"""
        return events.cc_le_read_supported_features(opcode)

    def handle_le_set_random_address(self, opcode, params):
        """LE Set Random Address"""
        if len(params) >= 6:
            addr = params[:6]
            self.bridge.bd_addr = addr
            self.bridge.sniffle_set_addr(addr)
            self.bridge.log.info("Set random address: %s", addr[::-1].hex())
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_set_advertising_parameters(self, opcode, params):
        """LE Set Advertising Parameters"""
        if len(params) >= 15:
            interval_min, interval_max = struct.unpack("<HH", params[0:4])
            adv_type = params[4]
            self.bridge.adv_interval = (interval_min + interval_max) // 2
            self.bridge.adv_type = adv_type
            self.bridge.log.debug(
                "Adv params: interval=%d type=%d", self.bridge.adv_interval, adv_type
            )
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_read_advertising_channel_tx_power(self, opcode, params):
        """LE Read Advertising Channel TX Power"""
        data = bytes([0x00, 0x05])  # +5 dBm
        return events.command_complete(opcode, data)

    def handle_le_set_advertising_data(self, opcode, params):
        """LE Set Advertising Data"""
        if len(params) >= 1:
            data_len = params[0]
            self.bridge.adv_data = params[1 : 1 + min(data_len, 31)]
            self.bridge.log.debug("Adv data: %s", self.bridge.adv_data.hex())
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_set_scan_response_data(self, opcode, params):
        """LE Set Scan Response Data"""
        if len(params) >= 1:
            data_len = params[0]
            self.bridge.scan_rsp_data = params[1 : 1 + min(data_len, 31)]
            self.bridge.log.debug("Scan rsp data: %s", self.bridge.scan_rsp_data.hex())
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_set_advertise_enable(self, opcode, params):
        """LE Set Advertise Enable"""
        if len(params) >= 1:
            enable = params[0]
            if self.bridge.active_conn:
                # Don't touch Sniffle state while a connection is active —
                # advertising while CENTRAL would flip the firmware to ADVERTISING(8)
                self.bridge.log.info(
                    "Advertising: %s (suppressed while connected)",
                    "enabled" if enable else "disabled",
                )
            elif enable:
                self.bridge.start_advertising()
                self.bridge.log.info("Advertising: enabled")
            else:
                self.bridge.stop_advertising()
                self.bridge.log.info("Advertising: disabled")
            self.bridge.advertising = bool(enable)
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_set_scan_parameters(self, opcode, params):
        """LE Set Scan Parameters"""
        if len(params) >= 7:
            scan_type = params[0]
            interval, window = struct.unpack("<HH", params[1:5])
            self.bridge.scan_type = scan_type
            self.bridge.scan_interval = interval
            self.bridge.scan_window = window
            self.bridge.log.debug(
                "Scan params: type=%d interval=%d window=%d",
                scan_type,
                interval,
                window,
            )
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_set_scan_enable(self, opcode, params):
        """LE Set Scan Enable"""
        if len(params) >= 2:
            enable = params[0]
            filter_dups = params[1]
            if self.bridge.active_conn or self.bridge.state == STATE_INITIATING:
                # Don't touch Sniffle state while connecting or connected
                self.bridge.log.info(
                    "Scanning: %s (suppressed, state=%d)",
                    "enabled" if enable else "disabled",
                    self.bridge.state,
                )
            elif enable:
                self.bridge.start_scanning(filter_dups)
                self.bridge.log.info("Scanning: enabled")
            else:
                self.bridge.stop_scanning()
                self.bridge.log.info("Scanning: disabled")
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_create_connection(self, opcode, params):
        """LE Create Connection"""
        if len(params) >= 25:
            scan_interval, scan_window = struct.unpack("<HH", params[0:4])
            initiator_filter = params[4]
            peer_addr_type = params[5]
            peer_addr = params[6:12]
            # params[12] = Own_Address_Type (1 byte); connection params start at [13]
            conn_interval_min, conn_interval_max, conn_latency, supervision_timeout = (
                struct.unpack("<HHHH", params[13:21])
            )

            self.bridge.log.info(
                "LE Create Conn to %s type=%d", peer_addr[::-1].hex(), peer_addr_type
            )

            # Initiate connection
            self.bridge.initiate_connection(
                peer_addr,
                peer_addr_type,
                conn_interval_min,
                conn_interval_max,
                conn_latency,
                supervision_timeout,
            )

            # Return Command Status (connection complete comes later)
            return events.command_status(opcode, 0x00)

        return events.command_complete(opcode, bytes([0x02]))  # Unknown connection

    def handle_le_create_connection_cancel(self, opcode, params):
        """LE Create Connection Cancel"""
        # Don't send PAUSE_DONE if the firmware is already connecting or connected —
        # BlueZ fires this when its own timer expires, but the firmware may still
        # succeed. Sending PAUSE_DONE here would cause CENTRAL→PAUSED immediately.
        if self.bridge.state not in (STATE_INITIATING, STATE_CENTRAL, STATE_PERIPHERAL):
            self.bridge.cancel_connection()
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_read_white_list_size(self, opcode, params):
        """LE Read White List Size"""
        data = bytes([0x00, 0x00])  # Size = 0 (not implemented)
        return events.command_complete(opcode, data)

    def handle_le_clear_white_list(self, opcode, params):
        """LE Clear White List"""
        self.bridge.white_list = []
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_add_device_to_white_list(self, opcode, params):
        """LE Add Device To White List"""
        if len(params) >= 7:
            addr_type = params[0]
            addr = params[1:7]
            if len(self.bridge.white_list) < self.bridge.white_list_max:
                # Check if already in list
                if (addr_type, addr) not in self.bridge.white_list:
                    self.bridge.white_list.append((addr_type, addr))
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_remove_device_from_white_list(self, opcode, params):
        """LE Remove Device From White List"""
        if len(params) >= 7:
            addr_type = params[0]
            addr = params[1:7]
            try:
                self.bridge.white_list.remove((addr_type, addr))
            except (ValueError, AttributeError):
                pass  # Not in list, ignore
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_read_channel_map(self, opcode, params):
        """LE Read Channel Map - Return current channel map"""
        if len(params) >= 2:
            handle = struct.unpack("<H", params[0:2])[0]

            # Return channel map (5 bytes, 37 channels = 0x1FFFFFFFFF)
            # All channels enabled for CatSniffer
            chan_map = getattr(
                self.bridge, "channel_map", bytes([0xFF, 0xFF, 0x1F, 0x00, 0x00])
            )

            # Response: status(1) + handle(2) + channel_map(5)
            data = bytes([0x00]) + struct.pack("<H", handle) + chan_map
            self.bridge.log.debug(
                "Read Channel Map: handle=0x%04X map=%s", handle, chan_map.hex()
            )
            return events.command_complete(opcode, data)
        return events.command_complete(opcode, bytes([0x01]))

    def handle_le_read_supported_states(self, opcode, params):
        """LE Read Supported States"""
        return events.cc_le_read_supported_states(opcode)

    def handle_le_set_data_length(self, opcode, params):
        """LE Set Data Length"""
        if len(params) >= 6:
            handle = struct.unpack("<H", params[0:2])[0]
            tx_octets, tx_time = struct.unpack("<HH", params[2:6])
            self.bridge.log.debug(
                "Set data length: handle=0x%04X octets=%d time=%d",
                handle,
                tx_octets,
                tx_time,
            )
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_read_suggested_default_data_length(self, opcode, params):
        """LE Read Suggested Default Data Length"""
        return events.cc_le_read_suggested_default_data_length(opcode)

    def handle_le_write_suggested_default_data_length(self, opcode, params):
        """LE Write Suggested Default Data Length"""
        if len(params) >= 4:
            self.bridge.suggested_tx_octets = struct.unpack("<H", params[:2])[0]
            self.bridge.suggested_tx_time = struct.unpack("<H", params[2:4])[0]
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_read_maximum_data_length(self, opcode, params):
        """LE Read Maximum Data Length"""
        return events.cc_le_read_max_data_length(opcode)

    def handle_le_rand(self, opcode, params):
        """LE Random"""
        rand_val = random.randint(0, 0xFFFFFFFFFFFFFFFF)
        data = bytes([0x00]) + struct.pack("<Q", rand_val)
        return events.command_complete(opcode, data)

    def handle_le_encrypt(self, opcode, params):
        """LE Encrypt - stub returning zeros"""
        if len(params) >= 32:
            encrypted = bytes(16)
            return events.command_complete(opcode, bytes([0x00]) + encrypted)
        return events.command_complete(opcode, bytes([0x02]))

    # ==================== Status Parameters ====================

    def handle_read_failed_contact_counter(self, opcode, params):
        """Read Failed Contact Counter - BR/EDR only"""
        data = bytes([0x00]) + struct.pack("<HH", 0x0000, 0x0000)  # handle, counter
        return events.command_complete(opcode, data)

    def handle_reset_failed_contact_counter(self, opcode, params):
        """Reset Failed Contact Counter - BR/EDR only"""
        return events.command_complete(opcode, bytes([0x00]))

    def handle_read_link_quality(self, opcode, params):
        """Read Link Quality - BR/EDR only"""
        data = bytes([0x00]) + struct.pack("<HB", 0x0000, 0xFF)  # handle, quality
        return events.command_complete(opcode, data)

    def handle_read_afh_channel_map(self, opcode, params):
        """Read AFH Channel Map - BR/EDR only"""
        data = bytes([0x00]) + struct.pack("<H", 0x0000) + bytes(10)  # handle, map
        return events.command_complete(opcode, data)

    def handle_read_clock(self, opcode, params):
        """Read Clock - BR/EDR only"""
        data = bytes([0x00]) + struct.pack("<HBI", 0x0000, 0x00, 0x00000000)
        return events.command_complete(opcode, data)

    # ==================== LE Connection Management ====================

    def handle_le_connection_update(self, opcode, params):
        """LE Connection Update"""
        if len(params) >= 14:
            handle = struct.unpack("<H", params[0:2])[0]
            # Store new connection parameters
            self.bridge.conn_interval = struct.unpack("<H", params[6:8])[0]
            self.bridge.conn_latency = struct.unpack("<H", params[8:10])[0]
            self.bridge.conn_timeout = struct.unpack("<H", params[10:12])[0]
            self.bridge.log.debug(
                "Connection update: handle=0x%04X interval=%d",
                handle,
                self.bridge.conn_interval,
            )
        return events.command_status(opcode, 0x00)

    def handle_le_set_host_channel_classification(self, opcode, params):
        """LE Set Host Channel Classification"""
        if len(params) >= 5:
            self.bridge.channel_map = params[:5]
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_read_remote_used_features(self, opcode, params):
        """LE Read Remote Used Features - returns status then immediately sends features event"""
        if len(params) >= 2:
            handle = struct.unpack("<H", params[:2])[0]
            evt = events.le_read_remote_features_complete(handle)
            try:
                import os

                os.write(self.bridge.vhci, evt)
                self.bridge.log.debug(
                    "Sent LE Remote Features Complete for handle 0x%04X", handle
                )
            except Exception as e:
                self.bridge.log.error("Failed to send LE Remote Features event: %s", e)
            return events.command_status(opcode, 0x00)
        return events.command_complete(opcode, bytes([0x02]))

    # ==================== LE Encryption (Stubs) ====================

    def handle_le_start_encryption(self, opcode, params):
        """LE Start Encryption - not supported"""
        return events.command_status(opcode, 0x00)

    def handle_le_long_term_key_request_reply(self, opcode, params):
        """LE Long Term Key Request Reply - not supported"""
        if len(params) >= 18:
            handle = struct.unpack("<H", params[:2])[0]
            return events.command_complete(
                opcode, bytes([0x00]) + struct.pack("<H", handle)
            )
        return events.command_complete(opcode, bytes([0x02]))

    def handle_le_long_term_key_request_negative_reply(self, opcode, params):
        """LE Long Term Key Request Negative Reply"""
        if len(params) >= 2:
            handle = struct.unpack("<H", params[:2])[0]
            return events.command_complete(
                opcode, bytes([0x00]) + struct.pack("<H", handle)
            )
        return events.command_complete(opcode, bytes([0x02]))

    # ==================== LE Direct Test Mode ====================

    def handle_le_receiver_test(self, opcode, params):
        """LE Receiver Test"""
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_transmitter_test(self, opcode, params):
        """LE Transmitter Test"""
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_test_end(self, opcode, params):
        """LE Test End"""
        data = bytes([0x00, 0x00, 0x00])  # status + packet count
        return events.command_complete(opcode, data)

    # ==================== LE Connection Parameter Request ====================

    def handle_le_remote_conn_param_request_reply(self, opcode, params):
        """LE Remote Connection Parameter Request Reply"""
        if len(params) >= 14:
            handle = struct.unpack("<H", params[:2])[0]
            return events.command_complete(
                opcode, bytes([0x00]) + struct.pack("<H", handle)
            )
        return events.command_complete(opcode, bytes([0x02]))

    def handle_le_remote_conn_param_request_negative_reply(self, opcode, params):
        """LE Remote Connection Parameter Request Negative Reply"""
        if len(params) >= 3:
            handle = struct.unpack("<H", params[:2])[0]
            reason = params[2]
            return events.command_complete(
                opcode, bytes([0x00]) + struct.pack("<H", handle)
            )
        return events.command_complete(opcode, bytes([0x02]))

    # ==================== LE Cryptographic (Stubs) ====================

    def handle_le_read_local_p256_public_key(self, opcode, params):
        """LE Read Local P256 Public Key - generates event later"""
        return events.command_status(opcode, 0x00)

    def handle_le_generate_dhkey(self, opcode, params):
        """LE Generate DHKey - generates event later"""
        return events.command_status(opcode, 0x00)

    # ==================== LE Resolving List ====================

    def handle_le_add_device_to_resolving_list(self, opcode, params):
        """LE Add Device To Resolving List"""
        if len(params) >= 39:  # addr_type(1) + addr(6) + peer_irk(16) + local_irk(16)
            addr_type = params[0]
            addr = params[1:7]
            peer_irk = params[7:23]
            local_irk = params[23:39]
            if len(self.bridge.resolving_list) < self.bridge.resolving_list_max:
                entry = (peer_irk, addr_type, addr, local_irk)
                if entry not in self.bridge.resolving_list:
                    self.bridge.resolving_list.append(entry)
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_remove_device_from_resolving_list(self, opcode, params):
        """LE Remove Device From Resolving List"""
        if len(params) >= 7:
            addr_type = params[0]
            addr = params[1:7]
            for entry in self.bridge.resolving_list[:]:
                if entry[1] == addr_type and entry[2] == addr:
                    self.bridge.resolving_list.remove(entry)
                    break
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_clear_resolving_list(self, opcode, params):
        """LE Clear Resolving List"""
        self.bridge.resolving_list = []
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_read_resolving_list_size(self, opcode, params):
        """LE Read Resolving List Size"""
        data = bytes([0x00, self.bridge.resolving_list_max])
        return events.command_complete(opcode, data)

    def handle_le_read_peer_resolvable_address(self, opcode, params):
        """LE Read Peer Resolvable Address"""
        if len(params) >= 7:
            # Return empty address (RPA resolution not implemented)
            data = bytes([0x00]) + bytes(6)
            return events.command_complete(opcode, data)
        return events.command_complete(opcode, bytes([0x02]))

    def handle_le_read_local_resolvable_address(self, opcode, params):
        """LE Read Local Resolvable Address"""
        if len(params) >= 7:
            data = bytes([0x00]) + bytes(6)
            return events.command_complete(opcode, data)
        return events.command_complete(opcode, bytes([0x02]))

    def handle_le_set_address_resolution_enable(self, opcode, params):
        """LE Set Address Resolution Enable"""
        if len(params) >= 1:
            self.bridge.address_resolution_enabled = params[0] != 0
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_set_resolvable_private_address_timeout(self, opcode, params):
        """LE Set Resolvable Private Address Timeout"""
        return events.command_complete(opcode, bytes([0x00]))

    # ==================== LE PHY ====================

    def handle_le_read_phy(self, opcode, params):
        """LE Read PHY"""
        if len(params) >= 2:
            handle = struct.unpack("<H", params[:2])[0]
            # tx_phy(1) + rx_phy(1) - 1 = LE 1M
            data = bytes([0x00]) + struct.pack("<H", handle) + bytes([0x01, 0x01])
            return events.command_complete(opcode, data)
        return events.command_complete(opcode, bytes([0x02]))

    def handle_le_set_default_phy(self, opcode, params):
        """LE Set Default PHY"""
        return events.command_complete(opcode, bytes([0x00]))

    def handle_le_set_phy(self, opcode, params):
        """LE Set PHY"""
        if len(params) >= 7:
            handle = struct.unpack("<H", params[:2])[0]
            return events.command_status(opcode, 0x00)
        return events.command_complete(opcode, bytes([0x02]))

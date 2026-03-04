"""
VHCI Events - HCI event generation functions
"""

import struct
from .constants import *


def command_complete(opcode, data=b''):
    """Generate Command Complete event"""
    # Event header: type, code, length
    # Payload: num_hci_packets (1), opcode (2), return_params
    payload = bytes([1]) + struct.pack('<H', opcode) + data
    return bytes([HCI_EVT, EVT_CMD_COMPLETE, len(payload)]) + payload


def command_status(opcode, status=0x00):
    """Generate Command Status event"""
    # Status, num_hci_packets, opcode
    payload = bytes([status, 1]) + struct.pack('<H', opcode)
    return bytes([HCI_EVT, EVT_CMD_STATUS, len(payload)]) + payload


def le_meta_event(subevent, data=b''):
    """Generate LE Meta event"""
    payload = bytes([subevent]) + data
    return bytes([HCI_EVT, EVT_LE_META, len(payload)]) + payload


def le_connection_complete(status=0x00, handle=0x0000, role=0x00,
                           peer_addr_type=0x00, peer_addr=b'\x00'*6,
                           interval=0x0018, latency=0x0000, timeout=0x01F4,
                           mca=0x00):
    """Generate LE Connection Complete event"""
    data = bytes([
        status,
    ]) + struct.pack('<H', handle) + bytes([
        role,
        peer_addr_type,
    ]) + peer_addr + struct.pack('<HHH', interval, latency, timeout) + bytes([mca])
    return le_meta_event(LE_CONN_COMPLETE, data)


def le_advertising_report(event_type=0x00, addr_type=0x00, addr=b'\x00'*6,
                          data=b'', rssi=-60):
    """Generate LE Advertising Report event"""
    # num_reports, event_type, addr_type, addr, data_len, data, rssi
    rssi_byte = rssi if rssi >= 0 else (256 + rssi)
    report = bytes([1, event_type, addr_type]) + addr + bytes([len(data)]) + data + bytes([rssi_byte])
    return le_meta_event(LE_ADV_REPORT, report)


def le_read_remote_features_complete(handle, features=None):
    """LE Read Remote Features Complete event (subevent 0x04)"""
    if features is None:
        # Encryption, conn param request, extended reject, LE ping, data length extension
        features = bytes([0x3F, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    data = bytes([0x00]) + struct.pack('<H', handle) + features
    return le_meta_event(0x04, data)


def disconnect_complete(status=0x00, handle=0x0000, reason=0x13):
    """Generate Disconnect Complete event"""
    payload = bytes([status]) + struct.pack('<H', handle) + bytes([reason])
    return bytes([HCI_EVT, EVT_DISCONN_COMPLETE, len(payload)]) + payload


def number_of_completed_packets(handles_and_counts):
    """Generate Number of Completed Packets event
    handles_and_counts: list of (handle, count) tuples
    """
    num_handles = len(handles_and_counts)
    payload = bytes([num_handles])
    for handle, count in handles_and_counts:
        payload += struct.pack('<HH', handle, count)
    return bytes([HCI_EVT, EVT_NUM_COMPLETED_PACKETS, len(payload)]) + payload


# Pre-built responses for common commands

def cc_read_local_version(opcode):
    """Response for Read Local Version Information"""
    # Response format: status(1) + hci_version(1) + hci_revision(2) + 
    #                  lmp_version(1) + manufacturer(2) + lmp_subversion(2)
    # Total: 9 bytes
    data = bytes([0x00,        # status
                  0x09,        # HCI version 4.2
                  0x06, 0x00,  # HCI revision
                  0x08,        # LMP version 4.2
                  0x5F, 0x00,  # manufacturer
                  0x00, 0x00]) # subversion
    return command_complete(opcode, data)


def cc_read_local_supported_commands(opcode):
    """Response for Read Local Supported Commands"""
    # 64-byte bitmask of supported commands
    # Set bits for commands we actually support
    commands = bytearray(64)

    # Link Control
    commands[0] |= 0x40  # Disconnect

    # Baseband
    commands[2] |= 0x08  # Reset

    # Informational
    commands[4] |= 0x01 | 0x02 | 0x04 | 0x08 | 0x80  # Read Local Version/Commands/Features/BD_ADDR/Buffer
    commands[5] |= 0x02  # Read Data Block Size

    # LE (starting at byte 25)
    # Commands 0x2001-0x200F: bytes 25-26
    commands[25] = 0xFF  # 0x2001-0x2008
    commands[26] = 0x7F  # 0x2009-0x200F (excluding 0x2010)

    # Commands 0x2010-0x201F: bytes 27-28
    commands[27] = 0xFF  # 0x2010-0x2017
    commands[28] = 0x07  # 0x2018-0x201A (Rand, Start Enc, LTK Reply)

    # Commands 0x201C-0x202F
    commands[29] |= 0x0F  # 0x201C-0x201F
    commands[30] |= 0x30  # 0x2022-0x2023
    commands[31] |= 0x80  # 0x202F

    data = bytes([0x00]) + bytes(commands)
    return command_complete(opcode, data)


def cc_read_local_supported_features(opcode):
    """Response for Read Local Supported Features"""
    # 8-byte LMP features bitmask
    # Bit 37 (byte4 bit5) = BR/EDR Not Supported  → 0x20
    # Bit 38 (byte4 bit6) = LE Supported          → 0x40
    # Both set = pure LE-only controller; BlueZ will not send BR/EDR commands
    features = bytes([0x00, 0x00, 0x00, 0x00, 0x60, 0x00, 0x00, 0x00])
    data = bytes([0x00]) + features
    return command_complete(opcode, data)


def cc_read_buffer_size(opcode):
    """Response for Read Buffer Size (BR/EDR ACL/SCO buffers)"""
    # LE-only controller: return 0 for all BR/EDR buffers.
    # BlueZ then uses LE_Read_Buffer_Size for LE traffic instead.
    data = bytes([0x00]) + struct.pack('<HBHH', 0, 0, 0, 0)
    return command_complete(opcode, data)


def cc_read_bd_addr(opcode, addr):
    """Response for Read BD_ADDR"""
    data = bytes([0x00]) + addr
    return command_complete(opcode, data)


def cc_read_local_name(opcode, name=b'CatSniffer'):
    """Response for Read Local Name"""
    # 248 bytes, null-terminated
    name_data = name + b'\x00' * (248 - len(name))
    data = bytes([0x00]) + name_data
    return command_complete(opcode, data)


def cc_le_read_buffer_size(opcode):
    """Response for LE Read Buffer Size"""
    # ACL MTU: 251, packets: 15
    data = bytes([0x00]) + struct.pack('<HB', 251, 15)
    return command_complete(opcode, data)


def cc_le_read_supported_features(opcode):
    """Response for LE Read Local Supported Features"""
    # 8-byte LE features
    # Bit 0: Encryption, Bit 1: Connection Param Request, Bit 2: Extended Reject
    # Bit 3: Slave-initiated Features Exchange, Bit 4: LE Ping
    # Bit 5: LE Data Packet Length Extension, Bit 6: LL Privacy
    # Bit 7: Extended Scanner Filter Policies
    # More complete feature set for a central device
    features = bytes([0x3F, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])  # Bits 0-5 set
    data = bytes([0x00]) + features
    return command_complete(opcode, data)


def cc_le_read_supported_states(opcode):
    """Response for LE Read Supported States"""
    # 8-byte bitmask of supported states
    # State 0: Non-connectable Advertising
    # State 1: Scannable Advertising
    # State 2: Connectable Advertising
    # State 3: High Duty Cycle Directed Advertising
    # etc.
    states = bytes([0xFF, 0x1F, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    data = bytes([0x00]) + states
    return command_complete(opcode, data)


def cc_le_read_max_data_length(opcode):
    """Response for LE Read Maximum Data Length"""
    # Max TX octets/time, Max RX octets/time
    data = bytes([0x00]) + struct.pack('<HHHH', 251, 2120, 251, 2120)
    return command_complete(opcode, data)


def cc_le_read_suggested_default_data_length(opcode):
    """Response for LE Read Suggested Default Data Length"""
    # Suggested TX octets/time
    data = bytes([0x00]) + struct.pack('<HH', 27, 328)
    return command_complete(opcode, data)

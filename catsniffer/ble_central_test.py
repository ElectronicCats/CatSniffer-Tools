#!/usr/bin/env python3
"""
BLE Central Test Script
Connects to ESP32-C3 (34:85:18:00:35:F6) using hci0 and performs GATT operations
"""

import sys
import time
import struct
import socket
import json

# Try bleak first (most reliable)
try:
    import asyncio
    from bleak import BleakClient, BleakScanner
    from bleak.backends.characteristic import BleakGATTCharacteristic
    HAS_BLEAK = True
except ImportError:
    HAS_BLEAK = False
    print("bleak not installed, trying bluepy...")

# Try bluepy as fallback
try:
    from bluepy.btle import Peripheral, Scanner, UUID
    HAS_BLUEPY = True
except ImportError:
    HAS_BLUEPY = False

# Target device
ESP32_ADDR = "34:85:18:00:35:F6"
ESP32_ADDR_TYPE = "public"

# Heart Rate Service UUID
HEART_RATE_SERVICE = "0000180d-0000-1000-8000-00805f9b34fb"
HEART_RATE_MEASUREMENT = "00002a37-0000-1000-8000-00805f9b34fb"


async def test_with_bleak():
    """Test using bleak library (recommended)"""
    print("=== Testing with bleak ===\n")
    
    # Scan first
    print("1. Scanning for devices...")
    devices = await BleakScanner.discover(timeout=5)
    
    target = None
    for d in devices:
        print(f"   Found: {d.address} ({d.name or 'Unknown'}) rssi={d.rssi}")
        if d.address.lower() == ESP32_ADDR.lower():
            target = d
            
    if not target:
        print(f"\nESP32 ({ESP32_ADDR}) not found in scan!")
        return
        
    print(f"\n2. Connecting to {ESP32_ADDR}...")
    
    async with BleakClient(ESP32_ADDR, adapter='hci0') as client:
        print(f"   Connected: {client.is_connected}")
        
        # Get services
        print("\n3. Discovering services...")
        services = client.services
        
        for service in services:
            print(f"\n   Service: {service.uuid}")
            for char in service.characteristics:
                props = char.properties
                print(f"      Characteristic: {char.uuid}")
                print(f"         Handle: {char.handle}")
                print(f"         Properties: {props}")
                
                # Try to read if readable
                if "read" in props:
                    try:
                        value = await client.read_gatt_char(char.uuid)
                        print(f"         Value: {value.hex() if isinstance(value, bytes) else value}")
                    except Exception as e:
                        print(f"         Read error: {e}")
        
        # Read heart rate specifically
        print("\n4. Reading Heart Rate Measurement...")
        try:
            hr_data = await client.read_gatt_char(HEART_RATE_MEASUREMENT)
            print(f"   Heart Rate Data: {hr_data.hex()}")
            if len(hr_data) >= 2:
                # Heart Rate format: flags byte + heart rate
                flags = hr_data[0]
                if flags & 0x01:
                    # 16-bit heart rate
                    hr = struct.unpack('<H', hr_data[1:3])[0]
                else:
                    # 8-bit heart rate
                    hr = hr_data[1]
                print(f"   Heart Rate: {hr} bpm")
        except Exception as e:
            print(f"   Error: {e}")
        
        # Subscribe to notifications
        print("\n5. Subscribing to heart rate notifications...")
        
        def notification_handler(characteristic: BleakGATTCharacteristic, data: bytearray):
            flags = data[0] if data else 0
            hr = data[1] if len(data) > 1 else 0
            print(f"   Notification: HR = {hr} bpm")
        
        try:
            await client.start_notify(HEART_RATE_MEASUREMENT, notification_handler)
            print("   Subscribed! Waiting for notifications (5 seconds)...")
            await asyncio.sleep(5)
            await client.stop_notify(HEART_RATE_MEASUREMENT)
        except Exception as e:
            print(f"   Subscribe error: {e}")
        
        print("\n6. Disconnecting...")
    
    print("\n=== Test Complete ===")


def test_with_bluepy():
    """Test using bluepy library"""
    print("=== Testing with bluepy ===\n")
    
    print(f"1. Connecting to {ESP32_ADDR}...")
    
    try:
        peri = Peripheral(ESP32_ADDR, addrType=ESP32_ADDR_TYPE, iface='hci0')
        print("   Connected!")
        
        print("\n2. Discovering services...")
        services = peri.getServices()
        
        for svc in services:
            print(f"\n   Service: {svc.uuid}")
            for char in svc.getCharacteristics():
                props = char.propertiesToString()
                print(f"      Characteristic: {char.uuid}")
                print(f"         Handle: {char.getHandle()}")
                print(f"         Properties: {props}")
                
                if "READ" in props:
                    try:
                        val = char.read()
                        print(f"         Value: {val.hex()}")
                    except:
                        pass
        
        print("\n3. Disconnecting...")
        peri.disconnect()
        print("\n=== Test Complete ===")
        
    except Exception as e:
        print(f"Error: {e}")


def test_with_socket():
    """Test using our CatSniffer socket interface"""
    print("=== Testing with CatSniffer socket ===\n")
    
    SOCK_PATH = '/tmp/catsniffer.sock'
    
    if not os.path.exists(SOCK_PATH):
        print(f"Socket not found: {SOCK_PATH}")
        print("Start the bridge first: sudo python3 modules/vhci_bridge.py -p /dev/ttyACM1")
        return
    
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCK_PATH)
    s.settimeout(15)
    
    def cmd(c, wait=0.5):
        s.send((c + '\n').encode())
        time.sleep(wait)
        try:
            return json.loads(s.recv(8192).decode())
        except:
            return {}
    
    print(f"1. Connecting to {ESP32_ADDR}...")
    result = cmd(f'connect {ESP32_ADDR} 0', 3)
    print(f"   Result: {result}")
    
    for i in range(10):
        st = cmd('status')
        if st.get('connected'):
            print(f"   [{i}] Connected! MTU={st.get('mtu')}")
            break
        time.sleep(0.5)
    
    print("\n2. Service Discovery...")
    svcs = cmd('services', 10)
    print(f"   Services: {json.dumps(svcs, indent=4)}")
    
    print("\n3. Characteristics...")
    chars = cmd('characteristics', 10)
    print(f"   Characteristics: {json.dumps(chars, indent=4)}")
    
    print("\n4. Disconnecting...")
    cmd('disconnect', 2)
    
    s.close()
    print("\n=== Test Complete ===")


if __name__ == "__main__":
    import os
    
    print("BLE Central Test Script")
    print("=" * 50)
    print(f"Target: {ESP32_ADDR}")
    print(f"Adapter: hci0")
    print("=" * 50)
    
    if HAS_BLEAK:
        asyncio.run(test_with_bleak())
    elif HAS_BLUEPY:
        test_with_bluepy()
    else:
        print("\nNo BLE library found!")
        print("Install one of:")
        print("  pip install bleak")
        print("  pip install bluepy")
        print("\nTrying socket interface...")
        test_with_socket()

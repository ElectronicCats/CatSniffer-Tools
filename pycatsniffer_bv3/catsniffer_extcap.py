#! /Library/Frameworks/Python.framework/Versions/3.11/bin/python3

import sys
import argparse
import time
import struct
import platform
import signal
from serial.tools import list_ports
from threading import Thread
from Modules import HexDumper, PcapDumper, Protocols, Fifo, Wireshark
import Modules.SnifferCollector as SCollector

# Constants
ERROR_INTERFACE = 2
ERROR_FIFO = 3
CTRL_ARG_MESSAGE = 0
CTRL_ARG_DELAY = 1

sniffer_collector = SCollector.SnifferCollector()
stop_capture = False

def stop_workers():
    global stop_capture
    stop_capture = True
    sniffer_collector.stop_workers()
    sniffer_collector.delete_all_workers()
    sys.exit(0)

def extcap_version():
    """Display the extcap version."""
    print("extcap {version=1.0}{help=https://github.com/ElectronicCats}{display=CatSniffer extcap}")

def extcap_interfaces():
    """List available interfaces for capture."""
    print("extcap {version=1.0}{help=https://github.com/ElectronicCats}{display=CatSniffer extcap LoRa}")
    print("interface {value=catsniffer_lora}{display=Sniffer LoRa Interface}")

def extcap_dlts(interface):
    """List available DLTs for the specified interface."""
    print("dlt {number=147}{name=USER0}{display=Catsniffer LoRa DLT}")

def list_serial_ports():
    """List all available serial ports."""
    ports = list_ports.comports()
    return [(port.device, port.description) for port in ports]

def extcap_config(interface, option):
    """Display configuration options for the interface."""
    args = [
        # Data for LoRa
        (0, '--serial-port', 'Serial Port', 'Serial port for the LoRa chip', 'selector', '{required=true}{default=COM1}'),
        (1, '--frequency', 'Frequency', 'Frequency for the LoRa chip', 'double', '{range=150,960}{default=915}'),
        (2, '--channel', 'Channel', 'Channel for the LoRa chip', 'integer', '{range=0,63}{default=0}'),
        (3, '--bandwidth', 'Bandwidth', 'Bandwidth for the LoRa chip', 'integer', '{range=0,9}{default=7}'),
        (4, '--spreading-factor', 'Spreading Factor', 'Spreading factor for the LoRa chip', 'integer', '{range=6,12}{default=7}'),
        (5, '--coding-rate', 'Coding Rate', 'Coding rate for the LoRa chip', 'integer', '{range=5,8}{default=5}'),
    ]

    for arg in args:
        print("arg {number=%d}{call=%s}{display=%s}{tooltip=%s}{type=%s}%s" % arg)
    
    for port in list_serial_ports():
        print("value {arg=0}{value=%s}{display=%s}" % (port[0], port[0]))

def display_serial_ports():
    """Display serial ports for user to select from."""
    ports = list_serial_ports()
    if not ports:
        print("No serial ports found.")
    else:
        print("Available serial ports:")
        for idx, (device, description) in enumerate(ports):
            print(f"{idx + 1}. {device} - {description}")

def validate_capture_filter(capture_filter):
    """Validate the capture filter."""
    if capture_filter not in ["filter", "something"]:
        print("ERROR: Invalid capture filter.")
        sys.exit(ERROR_INTERFACE)

def validate_output_file(output_file):
    """Validate the output file."""
    if not output_file.endswith(".pcapng"):
        print("ERROR: Invalid output file extension.")
        sys.exit(ERROR_FIFO)

def packet_control_thread(fifo):
    """Handle incoming control commands."""
    while True:
        time.sleep(1)
        try:
            with open(fifo, 'rb') as f:
                data = f.read()
                struct.unpack('!I', data[:4])
                print(f"Received control data: {data}")
        except Exception as e:
            print(f"Error reading control pipe: {e}")
            break

def main():
    """Main function to handle extcap arguments."""
    parser = argparse.ArgumentParser(description="Example extcap program")
    parser.add_argument('--capture', '-c', action='store_true', help="Start the capture")
    parser.add_argument('--extcap-interfaces', '-I', action='store_true', help="List available interfaces")
    parser.add_argument('--extcap-dlts', '-L', action='store_true', help="List DLTs for the given interface")
    parser.add_argument('--extcap-config', '-T', action='store_true', help="Display interface config options")
    parser.add_argument('--extcap-interface', '-i', help="Specify the interface to capture from")
    parser.add_argument('--extcap-control-in', help="Control channel for incoming commands")
    parser.add_argument('--extcap-control-out', help="Control channel for outgoing commands")
    parser.add_argument('--extcap-version', help="Display the extcap version")
    parser.add_argument('--fifo', '-F', help="Specify the FIFO for capture output")
    parser.add_argument('--capture-filter', '-f', help="Specify the capture filter")
    parser.add_argument('--serial-port', '-sp', help="Specify the serial port to use for the capture")
    # Data for LoRa
    parser.add_argument('--frequency', '-fr', help="Set the frequency for the LoRa chip")
    parser.add_argument('--channel', '-ch', help="Set the channel for the LoRa chip")
    parser.add_argument('--bandwidth', '-bw', help="Set the bandwidth for the LoRa chip")
    parser.add_argument('--spreading-factor', '-sf', help="Set the spreading factor for the LoRa chip")
    parser.add_argument('--coding-rate', '-cr', help="Set the coding rate for the LoRa chip")
    
    args = parser.parse_args()

    if args.extcap_interfaces:
        extcap_interfaces()
        sys.exit(0)

    if args.extcap_dlts:
        if not args.extcap_interface:
            sys.exit(ERROR_INTERFACE)
        extcap_dlts(args.extcap_interface)
        sys.exit(0)

    if args.extcap_config:
        if not args.extcap_interface:
            sys.exit(ERROR_INTERFACE)
        extcap_config(args.extcap_interface, args.extcap_control_in)
        sys.exit(0)

    if args.serial_port:
        print(f"Selected serial port: {args.serial_port}")
        print(args)
    else:
        print("No serial port specified. Listing available ports:")
        display_serial_ports()
        sys.exit(0)


    controlWriteStream = None
    controlReadStream = None
    if args.extcap_control_out is not None:
        controlWriteStream = open(args.extcap_control_out, 'wb', 0)
    if args.extcap_control_in is not None:
        controlReadStream = open(args.extcap_control_in, 'rb', 0)

    if args.capture:
        if not args.extcap_interface:
            sys.exit(ERROR_INTERFACE)
        if not args.fifo:
            sys.exit(ERROR_FIFO)

        signal.signal(signal.SIGINT, lambda sig, frame: stop_workers())
        signal.signal(signal.SIGTERM, lambda sig, frame: stop_workers())

        # Set parameters for sniffer
        sniffer_collector.set_board_uart(args.serial_port)
        sniffer_collector.set_is_catsniffer(2)
        sniffer_collector.set_lora_bandwidth(args.bandwidth)
        sniffer_collector.set_lora_channel(args.channel)
        sniffer_collector.set_lora_frequency(args.frequency)
        sniffer_collector.set_lora_spread_factor(args.spreading_factor)
        sniffer_collector.set_lora_coding_rate(args.coding_rate)

        output_workers = []

        print(args.fifo)

        if platform.system() == "Windows":
            output_workers.append(Fifo.FifoWindows(args.fifo))
        else:
            output_workers.append(Fifo.FifoLinux(args.fifo))

        sniffer_collector.set_output_workers(output_workers)
        sniffer_collector.run_workers()

        global stop_capture
        while not stop_capture:
            time.sleep(1)
            pass

if __name__ == "__main__":
    main()

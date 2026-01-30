#!/usr/bin/env python3
"""
CatSniffer LoRa Extcap Plugin for Wireshark

This plugin provides a Wireshark interface for capturing LoRa packets
using the CatSniffer hardware with the new multi-endpoint architecture.
"""
import os
import sys
import time
import struct
import signal
import logging
import argparse
import traceback
import threading
import platform
from serial.tools.list_ports import comports

from modules.catsniffer import (
    ShellConnection,
    LoRaConnection,
    catsniffer_get_devices,
    CATSNIFFER_VID,
    CATSNIFFER_PID,
)
from modules.pipes import UnixPipe, WindowsPipe, DEFAULT_UNIX_PATH
from protocol.sniffer_sx import SnifferSx
from protocol.common import START_OF_FRAME, get_global_header

scriptName = os.path.basename(sys.argv[0])

# Control numbers for Wireshark toolbar
CTRL_NUM_LOGGER = 0
CTRL_NUM_FREQUENCY = 1
CTRL_NUM_SPREADFACTOR = 2
CTRL_NUM_BANDWIDTH = 3
CTRL_NUM_CODINGRATE = 4
CTRL_NUM_TXPOWER = 5

# Control commands
CTRL_CMD_INITIALIZED = 0
CTRL_CMD_SET = 1
CTRL_CMD_ADD = 2
CTRL_CMD_REMOVE = 3
CTRL_CMD_ENABLE = 4
CTRL_CMD_DISABLE = 5
CTRL_CMD_STATUSBAR = 6
CTRL_CMD_INFORMATION = 7
CTRL_CMD_WARNING = 8
CTRL_CMD_ERROR = 9

# Board and protocol
CATSNIFFER_BOARD = 2
CATSNIFFER_DLT = 148

snifferSx = SnifferSx()
snifferSxCmd = snifferSx.Commands()


class UsageError(Exception):
    pass


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


class CatSnifferExtcapLogHandler(logging.Handler):
    def __init__(self, plugin):
        logging.Handler.__init__(self)
        self.plugin = plugin

    def emit(self, record):
        try:
            logMsg = self.format(record) + "\n"
        except:
            logMsg = traceback.format_exc() + "\n"
        try:
            self.plugin.writeControlMessage(CTRL_CMD_ADD, CTRL_NUM_LOGGER, logMsg)
        except:
            pass


class MinimalExtcap:
    def __init__(self):
        self.args = None
        self.logger = None
        self.captureStream = None
        self.controlReadStream = None
        self.controlWriteStream = None
        self.controlThread = None
        self.captureStopped = False
        self.controlsInitialized = False
        self.shell_connection = None
        self.lora_connection = None

    def main(self, args=None):
        log_handlers = [CatSnifferExtcapLogHandler(self)]
        log_files = os.environ.get("CATSNIFFER_LOG_FILE", None)
        if log_files:
            log_handlers.append(logging.FileHandler(log_files))
        log_levels = os.environ.get(
            "CATSNIFFER_LOG_LEVEL", "DEBUG" if log_files else "INFO"
        ).upper()
        logging.basicConfig(
            handlers=log_handlers,
            level=log_levels,
            format="%(asctime)s %(levelname)-8s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        self.logger = logging.getLogger(scriptName)
        try:
            self.loadArgs(args)
            # FIFO and control pipes must be opened, else Wireshark will freeze
            self.open_pipes()

            self.parseArgs()

            if self.args.op == "extcap-interfaces":
                print(self.extcap_interfaces())
            elif self.args.op == "extcap-dlts":
                print(self.extcap_dlts())
            elif self.args.op == "extcap-config":
                print(self.extcap_config())
            elif self.args.op == "capture":
                self.capture()
            else:
                raise UsageError("Operation not specified")

        except UsageError as ex:
            print(f"{ex}", file=sys.stderr)
            return 1

        self.close_pipes()
        return 0

    def loadArgs(self, args=None):
        parser = ArgumentParser(prog=scriptName)
        parser.add_argument(
            "--extcap-interfaces",
            dest="op",
            action="append_const",
            const="extcap-interfaces",
        )
        parser.add_argument(
            "--extcap-dlts", dest="op", action="append_const", const="extcap-dlts"
        )
        parser.add_argument(
            "--extcap-config", dest="op", action="append_const", const="extcap-config"
        )
        parser.add_argument(
            "--capture", dest="op", action="append_const", const="capture"
        )
        parser.add_argument("--extcap-interface")
        parser.add_argument("--extcap-version", help="Wireshark version")
        parser.add_argument("--fifo", help="Output fifo")
        parser.add_argument(
            "--extcap-control-in", help="Used to get control messages from toolbar"
        )
        parser.add_argument(
            "--extcap-control-out", help="Used to send control messages to toolbar"
        )
        parser.add_argument("--shell-port", help="Shell port for configuration")
        parser.add_argument("--lora-port", help="LoRa port for data")
        parser.add_argument(
            "--frequency",
            type=int,
            default=915000000,
            help="Frequency in Hz",
        )
        parser.add_argument(
            "--spread-factor",
            type=int,
            default=7,
            choices=[i for i in range(7, 13)],
            help="Spreading factor (7-12)",
        )
        parser.add_argument(
            "--bandwidth",
            type=int,
            default=125,
            choices=[125, 250, 500],
            help="Bandwidth in kHz",
        )
        parser.add_argument(
            "--coding-rate",
            type=int,
            default=5,
            choices=[i for i in range(5, 9)],
            help="Coding rate (5-8)",
        )
        parser.add_argument(
            "--tx-power",
            type=int,
            default=20,
            help="TX Power in dBm",
        )
        parser.add_argument(
            "--log-level",
            default="INFO",
            choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            help="Log level",
        )
        self.args = parser.parse_args(args)

    def parseArgs(self):
        if not self.args.op or len(self.args.op) != 1:
            raise UsageError("Please specify exactly one operation")
        self.args.op = self.args.op[0]
        self.args.frequency = int(self.args.frequency)
        self.args.spread_factor = int(self.args.spread_factor)
        self.args.bandwidth = int(self.args.bandwidth)
        self.args.coding_rate = int(self.args.coding_rate)
        self.args.tx_power = int(self.args.tx_power)

        self.logger.setLevel(self.args.log_level)

        if self.args.op == "capture" and not self.args.extcap_interface:
            raise UsageError(
                "Please specify the --extcap-interface option when capturing"
            )
        if self.args.op == "capture" and not self.args.fifo:
            raise UsageError("Please specify the --fifo option when capturing")
        if self.args.op == "capture" and not self.args.shell_port:
            raise UsageError("Please specify the --shell-port option when capturing")
        if self.args.op == "capture" and not self.args.lora_port:
            raise UsageError("Please specify the --lora-port option when capturing")

    def extcap_version(self):
        return "extcap {version=3.0}{display=CatSniffer LoRa Extcap}{help=https://github.com/ElectronicCats/CatSniffer}"

    def extcap_interfaces(self):
        lines = []
        lines.append(self.extcap_version())
        lines.append(
            "interface {value=catsniffer_lora}{display=CatSniffer LoRa Extcap}"
        )
        lines.append(
            "control {number=%d}{type=button}{role=logger}{display=Log}{tooltip=Show capture log}"
            % CTRL_NUM_LOGGER
        )
        lines.append(
            "control {number=%d}{type=string}{display=Frequency (Hz)}{tooltip=Frequency in Hz}"
            % CTRL_NUM_FREQUENCY
        )
        lines.append(
            "control {number=%d}{type=selector}{display=Bandwidth (kHz)}{tooltip=Bandwidth}"
            % CTRL_NUM_BANDWIDTH
        )
        lines.append(
            "control {number=%d}{type=selector}{display=Spreading Factor}{tooltip=Spreading Factor}"
            % CTRL_NUM_SPREADFACTOR
        )
        lines.append(
            "control {number=%d}{type=selector}{display=Coding Rate}{tooltip=Coding Rate}"
            % CTRL_NUM_CODINGRATE
        )
        lines.append(
            "control {number=%d}{type=string}{display=TX Power (dBm)}{tooltip=TX Power}"
            % CTRL_NUM_TXPOWER
        )

        # Default frequency
        lines.append(
            "value {control=%d}{value=%d}{display=%d Hz}"
            % (CTRL_NUM_FREQUENCY, 915000000, 915000000)
        )

        # Bandwidth options
        for bw in [125, 250, 500]:
            default = "{default=true}" if bw == 125 else ""
            lines.append(
                f"value {{control={CTRL_NUM_BANDWIDTH}}}{{value={bw}}}{{display={bw} kHz}}{default}"
            )

        # Spreading Factor
        for i in range(7, 13):
            default = "{default=true}" if i == 7 else ""
            lines.append(
                f"value {{control={CTRL_NUM_SPREADFACTOR}}}{{value={i}}}{{display=SF{i}}}{default}"
            )

        # Coding Rate
        for i in range(5, 9):
            default = "{default=true}" if i == 5 else ""
            lines.append(
                f"value {{control={CTRL_NUM_CODINGRATE}}}{{value={i}}}{{display=4/{i}}}{default}"
            )

        return "\n".join(lines)

    def extcap_dlts(self):
        return "dlt {number=%d}{name=catsniffer_lora_dlt}{display=CatSniffer LoRa DLT}" % (
            CATSNIFFER_DLT
        )

    def extcap_config(self):
        lines = []

        # Shell port selector
        lines.append(
            "arg {number=0}{call=--shell-port}{type=selector}{required=true}"
            "{display=Shell Port (Config)}"
            "{tooltip=CatSniffer Shell port for configuration}"
        )

        # LoRa port selector
        lines.append(
            "arg {number=1}{call=--lora-port}{type=selector}{required=true}"
            "{display=LoRa Port (Data)}"
            "{tooltip=CatSniffer LoRa port for data stream}"
        )

        # Frequency
        lines.append(
            "arg {number=2}{call=--frequency}{type=long}{default=915000000}"
            "{display=Frequency (Hz)}"
            "{tooltip=Frequency in Hz (e.g., 915000000 for 915 MHz)}"
        )

        # Spreading Factor
        lines.append(
            "arg {number=3}{call=--spread-factor}{type=selector}{default=7}"
            "{display=Spreading Factor}"
            "{tooltip=LoRa Spreading Factor (7-12)}"
        )

        # Bandwidth
        lines.append(
            "arg {number=4}{call=--bandwidth}{type=selector}{default=125}"
            "{display=Bandwidth (kHz)}"
            "{tooltip=LoRa Bandwidth in kHz}"
        )

        # Coding Rate
        lines.append(
            "arg {number=5}{call=--coding-rate}{type=selector}{default=5}"
            "{display=Coding Rate}"
            "{tooltip=LoRa Coding Rate (5-8)}"
        )

        # TX Power
        lines.append(
            "arg {number=6}{call=--tx-power}{type=integer}{default=20}"
            "{display=TX Power (dBm)}"
            "{tooltip=Transmit power in dBm}"
        )

        # Log Level
        lines.append(
            "arg {number=7}{call=--log-level}{type=selector}{display=Log Level}"
            "{tooltip=Set the log level}{default=INFO}{group=Logger}"
        )

        # Get available CatSniffer devices
        devices = catsniffer_get_devices()

        # Populate shell and lora port options from detected devices
        shell_ports = []
        lora_ports = []

        for dev in devices:
            if dev.shell_port:
                shell_ports.append((dev.shell_port, f"CatSniffer #{dev.device_id} Shell - {dev.shell_port}"))
            if dev.lora_port:
                lora_ports.append((dev.lora_port, f"CatSniffer #{dev.device_id} LoRa - {dev.lora_port}"))

        # Also add all serial ports as fallback
        for port in comports():
            if port.vid == CATSNIFFER_VID and port.pid == CATSNIFFER_PID:
                device = port.device
                if sys.platform == "win32":
                    device = f"//./{port.device}"
                if device not in [p[0] for p in shell_ports]:
                    shell_ports.append((device, f"{port.device}"))
                if device not in [p[0] for p in lora_ports]:
                    lora_ports.append((device, f"{port.device}"))

        # Add shell port values
        for device, displayName in shell_ports:
            lines.append(f"value {{arg=0}}{{value={device}}}{{display={displayName}}}")

        # Add lora port values
        for device, displayName in lora_ports:
            lines.append(f"value {{arg=1}}{{value={device}}}{{display={displayName}}}")

        # Spreading Factor values
        for i in range(7, 13):
            default = "{default=true}" if i == 7 else ""
            lines.append(f"value {{arg=3}}{{value={i}}}{{display=SF{i}}}{default}")

        # Bandwidth values
        for bw in [125, 250, 500]:
            default = "{default=true}" if bw == 125 else ""
            lines.append(f"value {{arg=4}}{{value={bw}}}{{display={bw} kHz}}{default}")

        # Coding Rate values
        for i in range(5, 9):
            default = "{default=true}" if i == 5 else ""
            lines.append(f"value {{arg=5}}{{value={i}}}{{display=4/{i}}}{default}")

        # Logger values
        lines.append("value {arg=7}{value=DEBUG}{display=DEBUG}")
        lines.append("value {arg=7}{value=INFO}{display=INFO}{default=true}")
        lines.append("value {arg=7}{value=WARNING}{display=WARNING}")
        lines.append("value {arg=7}{value=ERROR}{display=ERROR}")

        return "\n".join(lines)

    def capture(self):
        if self.controlReadStream:
            self.logger.info("Waiting for INITIALIZED message from Wireshark")
            while not self.controlsInitialized:
                time.sleep(0.1)

        self.logger.info("Initializing CatSniffer hardware interface")

        signal.signal(signal.SIGINT, lambda sig, frame: self.stopCapture())
        signal.signal(signal.SIGTERM, lambda sig, frame: self.stopCapture())

        fifo_path = DEFAULT_UNIX_PATH
        if self.args.fifo:
            fifo_path = self.args.fifo

        # Start the capture
        self.logger.info(f"Starting capture: {self.args.fifo}")
        if platform.system() == "Windows":
            pipe = WindowsPipe(fifo_path)
        else:
            pipe = UnixPipe(fifo_path)

        opening_worker = threading.Thread(target=pipe.open, daemon=True)
        opening_worker.start()

        # Connect to shell port for configuration
        self.shell_connection = ShellConnection(port=self.args.shell_port)
        if not self.shell_connection.connect():
            self.logger.error(f"Failed to connect to shell port: {self.args.shell_port}")
            return

        # Connect to lora port for data
        self.lora_connection = LoRaConnection(port=self.args.lora_port)
        if not self.lora_connection.connect():
            self.logger.error(f"Failed to connect to LoRa port: {self.args.lora_port}")
            self.shell_connection.disconnect()
            return

        # Send configuration via shell port
        self.logger.info("Configuring LoRa parameters...")
        self.shell_connection.send_command(snifferSxCmd.set_freq(self.args.frequency))
        self.shell_connection.send_command(snifferSxCmd.set_bw(self.args.bandwidth))
        self.shell_connection.send_command(snifferSxCmd.set_sf(self.args.spread_factor))
        self.shell_connection.send_command(snifferSxCmd.set_cr(self.args.coding_rate))
        self.shell_connection.send_command(snifferSxCmd.set_power(self.args.tx_power))

        # Apply configuration
        self.shell_connection.send_command(snifferSxCmd.apply())
        time.sleep(0.2)

        # Start streaming mode
        self.shell_connection.send_command(snifferSxCmd.start_streaming())
        self.logger.info("LoRa streaming started")

        header_flag = False
        self.writeControlMessage(
            CTRL_CMD_SET, CTRL_NUM_BANDWIDTH, str(self.args.bandwidth)
        )
        self.writeControlMessage(
            CTRL_CMD_SET, CTRL_NUM_FREQUENCY, str(self.args.frequency)
        )

        # Capture packets and write to the capture output until signaled to stop
        while not self.captureStopped:
            try:
                data = self.lora_connection.readline()
                if data:
                    self.logger.debug(f"Recv: {data}")
                    if data.startswith(START_OF_FRAME):
                        packet = snifferSx.Packet(
                            (START_OF_FRAME + data),
                            context={
                                "frequency": self.args.frequency,
                                "bandwidth": self.args.bandwidth,
                                "spread_factor": self.args.spread_factor,
                                "coding_rate": self.args.coding_rate,
                            },
                        )
                        if not header_flag:
                            header_flag = True
                            pipe.write_packet(get_global_header(148))
                        pipe.write_packet(packet.pcap)

                time.sleep(0.1)
            except KeyboardInterrupt:
                break

        # Cleanup
        self.logger.info("Stopping capture...")
        if self.shell_connection:
            self.shell_connection.send_command(snifferSxCmd.start_command())
            self.shell_connection.disconnect()
        if self.lora_connection:
            self.lora_connection.disconnect()
        if opening_worker.is_alive():
            opening_worker.join(timeout=1)
        pipe.remove()
        self.logger.info("Capture stopped")

    def stopCapture(self):
        self.captureStopped = True

    def open_pipes(self):
        if self.args.extcap_control_out is not None:
            self.controlWriteStream = open(self.args.extcap_control_out, "wb", 0)
            self.writeControlMessage(CTRL_CMD_SET, CTRL_NUM_LOGGER, "")

        if self.args.extcap_control_in is not None:
            self.controlReadStream = open(self.args.extcap_control_in, "rb", 0)

        if self.controlReadStream:
            self.controlThread = threading.Thread(
                target=self.controlThreadMain, daemon=True
            )
            self.controlThread.start()

    def close_pipes(self):
        if self.controlWriteStream is not None:
            self.controlWriteStream.close()

    def controlThreadMain(self):
        try:
            while True:
                (cmd, controlNum, payload) = self.readControlMessage()
                self.logger.info("Control message received: %d %d" % (cmd, controlNum))

                if cmd == CTRL_CMD_INITIALIZED:
                    self.controlsInitialized = True

                elif cmd == CTRL_CMD_SET and controlNum == CTRL_NUM_FREQUENCY:
                    self.logger.info("Changing Frequency: %s" % payload)
                    self.args.frequency = int(payload)
                    if self.shell_connection:
                        self.shell_connection.send_command(snifferSxCmd.set_freq(self.args.frequency))
                        self.shell_connection.send_command(snifferSxCmd.apply())
                        self.shell_connection.send_command(snifferSxCmd.start_streaming())
                    self.writeControlMessage(
                        CTRL_CMD_SET, CTRL_NUM_FREQUENCY, str(self.args.frequency)
                    )

                elif cmd == CTRL_CMD_SET and controlNum == CTRL_NUM_SPREADFACTOR:
                    self.logger.info("Changing Spread factor: %s" % payload)
                    self.args.spread_factor = int(payload)
                    if self.shell_connection:
                        self.shell_connection.send_command(snifferSxCmd.set_sf(self.args.spread_factor))
                        self.shell_connection.send_command(snifferSxCmd.apply())
                        self.shell_connection.send_command(snifferSxCmd.start_streaming())
                    self.writeControlMessage(
                        CTRL_CMD_SET, CTRL_NUM_SPREADFACTOR, str(self.args.spread_factor)
                    )

                elif cmd == CTRL_CMD_SET and controlNum == CTRL_NUM_BANDWIDTH:
                    self.logger.info("Changing bandwidth: %s" % payload)
                    self.args.bandwidth = int(payload)
                    if self.shell_connection:
                        self.shell_connection.send_command(snifferSxCmd.set_bw(self.args.bandwidth))
                        self.shell_connection.send_command(snifferSxCmd.apply())
                        self.shell_connection.send_command(snifferSxCmd.start_streaming())
                    self.writeControlMessage(
                        CTRL_CMD_SET, CTRL_NUM_BANDWIDTH, str(self.args.bandwidth)
                    )

                elif cmd == CTRL_CMD_SET and controlNum == CTRL_NUM_CODINGRATE:
                    self.logger.info("Changing coding rate: %s" % payload)
                    self.args.coding_rate = int(payload)
                    if self.shell_connection:
                        self.shell_connection.send_command(snifferSxCmd.set_cr(self.args.coding_rate))
                        self.shell_connection.send_command(snifferSxCmd.apply())
                        self.shell_connection.send_command(snifferSxCmd.start_streaming())
                    self.writeControlMessage(
                        CTRL_CMD_SET, CTRL_NUM_CODINGRATE, str(self.args.coding_rate)
                    )

                elif cmd == CTRL_CMD_SET and controlNum == CTRL_NUM_TXPOWER:
                    self.logger.info("Changing TX Power: %s" % payload)
                    self.args.tx_power = int(payload)
                    if self.shell_connection:
                        self.shell_connection.send_command(snifferSxCmd.set_power(self.args.tx_power))
                        self.shell_connection.send_command(snifferSxCmd.apply())
                        self.shell_connection.send_command(snifferSxCmd.start_streaming())
                    self.writeControlMessage(
                        CTRL_CMD_SET, CTRL_NUM_TXPOWER, str(self.args.tx_power)
                    )

        except EOFError:
            pass
        except:
            self.logger.exception("INTERNAL ERROR")
        finally:
            self.stopCapture()
            self.logger.info("Control thread exiting")

    def readControlMessage(self):
        try:
            header = self.controlReadStream.read(6)
        except IOError:
            raise EOFError()
        if len(header) < 6:
            raise EOFError()
        (sp, msgLenH, msgLenL, controlNum, cmd) = struct.unpack("!bBHBB", header)
        if sp != ord("T"):
            raise ValueError("Bad control message received")
        msgLen = (msgLenH << 16) | msgLenL
        payloadLen = msgLen - 2
        if payloadLen < 0 or payloadLen > 65535:
            raise ValueError("Bad control message received")
        if payloadLen > 0:
            payload = self.controlReadStream.read(payloadLen)
            if len(payload) < payloadLen:
                raise EOFError()
        else:
            payload = None
        return (cmd, controlNum, payload)

    def writeControlMessage(self, cmd, controlNum, payload):
        if not self.controlWriteStream:
            return
        if cmd < 0 or cmd > 255:
            raise ValueError("Invalid control message command")
        if controlNum < 0 or controlNum > 255:
            raise ValueError("Invalid control message control number")
        if payload is None:
            payload = b""
        elif isinstance(payload, str):
            payload = payload.encode("utf-8")
        if len(payload) > 65535:
            raise ValueError("Control message payload too long")
        msgLen = len(payload) + 2
        msg = bytearray()
        msg += struct.pack(
            "!bBHBB", ord("T"), msgLen >> 16, msgLen & 0xFFFF, controlNum, cmd
        )
        msg += payload
        self.controlWriteStream.write(msg)


if __name__ == "__main__":
    sys.exit(MinimalExtcap().main())

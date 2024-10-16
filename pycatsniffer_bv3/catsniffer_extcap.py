#! /Library/Frameworks/Python.framework/Versions/3.11/bin/python3
#
#   Copyright 2024, Kevin Leon
#
#
#  @file
#       A Wireshark extcap plug-in for real time packet capture using Sniffle.
#

import sys
import os
import os.path
import argparse
import re
import threading
import struct
import logging
import time
import signal
import traceback
import Modules.SnifferCollector as SCollector
from Modules import Fifo
from serial.tools.list_ports import comports

scriptName = os.path.basename(sys.argv[0])

CTRL_NUM_LOGGER      = 0
CTRL_NUM_ADVCHAN     = 1
CTRL_NUM_CHHOP       = 2
CTRL_BTN_CHANGECHAN  = 3
# Loggers
CTRL_CMD_INITIALIZED = 0
CTRL_CMD_SET         = 1
CTRL_CMD_ADD         = 2
CTRL_CMD_REMOVE      = 3
CTRL_CMD_ENABLE      = 4
CTRL_CMD_DISABLE     = 5
CTRL_CMD_STATUSBAR   = 6
CTRL_CMD_INFORMATION = 7
CTRL_CMD_WARNING     = 8
CTRL_CMD_ERROR       = 9
# Board and protocol
CATSNIFFER_BOARD     = 0
CATSNIFFER_MODE_IEEE = 1
CATSNIFFER_DLT       = 147
CATSNIFFER_VID       = 11914
CATSNIFFER_PID       = 192

class UsageError(Exception):
    pass

class SniffleExtcapPlugin:
    def __init__(self) -> None:
        self.args                = None
        self.logger              = None
        self.hw                  = SCollector.SnifferCollector(logger=logging.getLogger("sniffer_hw"))
        self.captureStream       = None
        self.controlReadStream   = None
        self.controlWriteStream  = None
        self.controlThread       = None
        self.captureStopped      = False
        self.controlsInitialized = False

    def main(self, args=None):
        # initialize logging
        #
        # add a log handler to pass internal log messages back to Wireshark
        # via the control-out FIFO
        #
        # if CATSNIFER_LOG_FILE env variable is set, also write log messages to
        # the named file
        #
        # if CATSNIFER_LOG_LEVEL is set, set the default log level accordingly
        #
        log_handlers = [SniffleExtcapLogHandler(self)]
        log_files = os.environ.get("CATSNIFER_LOG_FILE", None)
        if log_files:
            log_handlers.append(logging.FileHandler(log_files))
        log_levels = os.environ.get(
            "CATSNIFER_LOG_LEVEL", "DEBUG" if log_files else "INFO"
        ).upper()
        
        logging.basicConfig(
            handlers=log_handlers,
            level=log_levels,
            format="%(asctime)s %(levelname)-8s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        self.logger = logging.getLogger(scriptName)
        

        ret = 0

        try:
            # Load the given arguments
            self.loadArgs(args)

            # FIFO and control pipes must be opened, else Wireshark will freeze
            self.open_pipes()

            # Parse and validate the arguments
            self.parseArgs()

            # Perform the requested operation
            if self.args.op == "extcap-interfaces":
                print(self.extcap_interfaces())
            elif self.args.op == "extcap-dlts":
                print(self.extcap_dlts())
            elif self.args.op == "extcap-config":
                print(self.extcap_config())
            elif self.args.op == "extcap-reload-option":
                # No reloadable options, so simply return.
                pass
            elif self.args.op == "capture":
                self.capture()
            else:
                # Should not get here
                raise RuntimeError("Operation not specified")

        except UsageError as ex:
            print(f"{ex}", file=os.sys.stderr)
            ret = 1

        except KeyboardInterrupt:
            ret = 1

        except SystemExit as ex:
            ret = ex.code

        except:
            self.logger.exception("INTERNAL ERROR")
            ret = 1

        self.close_pipes()
        return ret

    def loadArgs(self, args=None):
        argParser = ArgumentParser(prog=scriptName)
        argParser.add_argument(
            "--extcap-interfaces",
            dest="op",
            action="append_const",
            const="extcap-interfaces",
            help="List available capture interfaces",
        )
        argParser.add_argument(
            "--extcap-dlts",
            dest="op",
            action="append_const",
            const="extcap-dlts",
            help="List DTLs for interface",
        )
        argParser.add_argument(
            "--extcap-config",
            dest="op",
            action="append_const",
            const="extcap-config",
            help="List configurations for interface",
        )
        argParser.add_argument(
            "--capture",
            dest="op",
            action="append_const",
            const="capture",
            help="Start capture",
        )
        argParser.add_argument("--extcap-interface", help="Target capture interface")
        argParser.add_argument("--extcap-version", help="Wireshark version")
        argParser.add_argument(
            "--extcap-reload-option", help="Reload elements for option"
        )
        argParser.add_argument("--fifo", help="Output fifo")
        argParser.add_argument("--extcap-capture-filter", help="Capture filter")
        argParser.add_argument(
            "--extcap-control-in", help="Used to get control messages from toolbar"
        )
        argParser.add_argument(
            "--extcap-control-out", help="Used to send control messages to toolbar"
        )
        argParser.add_argument("--serport", help="Sniffer serial port name")
        argParser.add_argument(
            "--advchan",
            type=int,
            default=11,
            choices=[i for i in range(11, 28)],
            help="Advertising channel to listen on",
        )
        argParser.add_argument(
            "--chhop",
            action="store_true",
            help="Channel Hop to recognize channels (Beta)",
        )
        argParser.add_argument(
            "--log-level",
            default="INFO",
            choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            help="Log level",
        )

        self.args = argParser.parse_args(args=args)

    def parseArgs(self):
        # Determine the operation being performed
        if not self.args.op or len(self.args.op) != 1:
            
            raise UsageError(
                "Please specify exactly one of --capture, --extcap-version, --extcap-interfaces, --extcap-dlts or --extcap-config"
            )
        self.args.op = self.args.op[0]

        # Parse --advchan argument
        self.args.advchan = int(self.args.advchan)
        
        self.logger.setLevel(self.args.log_level)
        
        if self.args.op == "capture" and not self.args.extcap_interface:
            raise UsageError(
                "Please specify the --extcap-interface option when capturing"
            )
        if self.args.op == "capture" and not self.args.fifo:
            raise UsageError("Please specify the --fifo option when capturing")
        if self.args.op == "capture" and not self.args.serport:
            raise UsageError("Please specify the --serport option when capturing")

    def extcap_version(self):
        return "extcap {version=1.0}{display=CatSniffer IEEE 802.15.4}{help=https://github.com/ElectronicCats/CatSniffer}"

    def extcap_interfaces(self):
        lines = []
        lines.append(self.extcap_version())
        lines.append("interface {value=catsniffer}{display=CatSniffer}")
        lines.append(
            "control {number=%d}{type=button}{role=logger}{display=Log}{tooltip=Show capture log}"
            % CTRL_NUM_LOGGER
        )
        lines.append(
            "control {number=%d}{type=selector}{display=Channel}{tooltip=Channel to listen on}"
            % CTRL_NUM_ADVCHAN
        )
        lines.append(
            "control {number=%d}{type=boolean}{display=Channel hopping}{default=false}{tooltip=Channel hopping to recognize channels (Beta)}"
            % CTRL_NUM_CHHOP
        )

        for i in range(11, 28):
            if i == int(self.args.advchan):
                lines.append(
                    "value {control=%d}{value=%d}{display=%d}{default=true}"
                    % (CTRL_NUM_ADVCHAN, i, i)
                )
            else:
                lines.append("value {control=%d}{value=%d}{display=%d}" % (CTRL_NUM_ADVCHAN, i, i))
        return "\n".join(lines)

    def extcap_dlts(self):
        return (
            "dlt {number=%d}{name=catsniffer_rpi}{display=CatSniffer IEEE 802.15.4 link-layer}"
            % (CATSNIFFER_DLT)
        )

    def extcap_config(self):
        lines = []
        lines.append(
            "arg {number=0}{call=--serport}{type=selector}{required=true}"
            "{display=Sniffer serial port}"
            "{tooltip=Sniffer device serial port}"
        )
        lines.append(
            "arg {number=1}{call=--advchan}{type=selector}{default=11}"
            "{display=Sniffer Channel}"
            "{tooltip=Channel to listen on}"
        )
        lines.append(
            "arg {number=2}{call=--chhop}{type=boolflag}{default=no}"
            "{display=Channel hopping}"
            "{tooltip=Channel hopping to recognize channels (Beta)}"
        )
        lines.append(
            "arg {number=3}{call=--log-level}{type=selector}{display=Log Level}{tooltip=Set the log level}{default=INFO}{group=Logger}"
        )
        lines.append(
            "value {arg=3}{value=DEBUG}{display=DEBUG}"
        )
        lines.append(
            "value {arg=3}{value=INFO}{display=INFO}"
        )
        lines.append(
            "value {arg=3}{value=WARNING}{display=WARNING}"
        )
        lines.append(
            "value {arg=3}{value=ERROR}{display=ERROR}"
        )
        other_ports = []
        for port in comports():
            if sys.platform == "win32":
                device = f"//./{port.device}"
            else:
                device = port.device
            if port.vid is not None and port.pid is not None:
                if port.vid == CATSNIFFER_VID and port.pid == CATSNIFFER_PID:
                    displayName = "%s - CatSniffer" % (port.device)
                    lines.append("value {arg=0}{value=%s}{display=%s}" % (device, displayName))
            else:
                if port.manufacturer is not None:
                    displayName = "%s - %s" % (port.device, port.manufacturer)
                else:
                    displayName = port.device
                other_ports.append((device, displayName))
        for device, displayName in other_ports:
            lines.append("value {arg=0}{value=%s}{display=%s}" % (device, displayName))
        for i in range(11, 28):
            lines.append("value {arg=1}{value=%d}{display=%d}" % (i, i))
        return "\n".join(lines)

    def capture(self):
        # Wait for the INITIALIZED message from Wireshark
        #    NOTE that Wireshark on Windows will delay sending the INITIALIZED message
        #    until after it receives the PCAP header.  Thus this loop must happen
        #    *after* the PcapBleWriter has been initialized to avoid a deadlock.
        if self.controlReadStream:
            self.logger.info("Waiting for INITIALIZED message from Wireshark")
            while not self.controlsInitialized:
                time.sleep(0.1)

        self.logger.info("Initializing Sniffle hardware interface")

        # initialize the Sniffle hardware interface
        self.hw.set_board_uart(self.args.serport)
        self.hw.set_is_catsniffer(CATSNIFFER_BOARD)
        self.hw.set_protocol_phy(CATSNIFFER_MODE_IEEE)
        self.hw.set_protocol_channel(self.args.advchan)
        self.hw.set_channel_hopping(self.args.chhop)

        self.logger.info("Starting capture")

        # Arrange to exit gracefully on a signal from Wireshark. NOTE that this
        # has no effect under Windows.
        signal.signal(signal.SIGINT, lambda sig, frame: self.stopCapture())
        signal.signal(signal.SIGTERM, lambda sig, frame: self.stopCapture())
        if self.args.fifo is not None:
            self.logger.info("Opening capture output FIFO")
            self.hw.set_output_workers([Fifo.FifoLinux(self.args.fifo)])
        # start the capture
        self.hw.run_workers()

        # capture packets and write to the capture output until signaled to stop
        while not self.captureStopped:
            # wait for a capture packet
            time.sleep(0.1)
            pass

        self.logger.info("Capture stopped")

    def open_pipes(self):
        # if a control-out FIFO has been given, open it for writing
        if self.args.extcap_control_out is not None:
            self.logger.info("Opening control-out FIFO")
            self.controlWriteStream = open(self.args.extcap_control_out, "wb", 0)

            # Clear the logger control in preparation for writing new messages
            self.writeControlMessage(CTRL_CMD_SET, CTRL_NUM_LOGGER, "")

        # if a control-in FIFO has been given, open it for reading
        if self.args.extcap_control_in is not None:
            self.logger.info("Opening control-in FIFO")
            self.controlReadStream = open(self.args.extcap_control_in, "rb", 0)

        # open the capture output FIFO and initialize the PCAP writer to write to it
        # if self.args.fifo is not None:
        #     self.logger.info("Opening capture output FIFO")
        #     self.hw.set_output_workers([Fifo.FifoLinux(self.args.fifo)])
            # self.captureStream = open(self.args.fifo, "wb", buffering=0)
            # self.pcapWriter = PcapBleWriter(self.captureStream)

        if self.controlReadStream:
            # start a thread to read control messages
            self.logger.info("Starting control thread")
            self.controlThread = threading.Thread(
                target=self.controlThreadMain, daemon=True
            )
            self.controlThread.start()

    def close_pipes(self):
        if self.hw.sniffer_recv_cancel:
            self.hw.stop_workers()
            self.hw.delete_all_workers()
        if self.controlWriteStream is not None:
            self.controlWriteStream.close()

    def controlThreadMain(self):
        self.logger.info("Control thread started")
        try:
            while True:
                (cmd, controlNum, payload) = self.readControlMessage()
                self.logger.info("Control message received: %d %d" % (cmd, controlNum))
                if cmd == CTRL_CMD_INITIALIZED:
                    self.controlsInitialized = True
                elif cmd == CTRL_CMD_SET and controlNum == CTRL_NUM_ADVCHAN:
                        self.logger.info("Changing channel: %s" % payload)
                        self.args.advchan = int(payload)
                        self.hw.set_protocol_channel(int(self.args.advchan))
                        self.hw.send_command_start()
                        self.writeControlMessage(CTRL_CMD_SET, CTRL_NUM_ADVCHAN, str(self.args.advchan))
                elif cmd == CTRL_CMD_SET and controlNum == CTRL_NUM_CHHOP:
                        self.logger.info("Changing channel hopping: %s" % payload)
                        self.args.chhop = payload == b"true"
                        self.hw.set_channel_hopping(self.args.chhop)
                        self.hw.send_command_start()
                        self.writeControlMessage(CTRL_CMD_SET, CTRL_NUM_CHHOP, str(self.args.chhop))

        except EOFError:
            # Wireshark closed the control FIFO, indicating it is done capturing
            pass
        except:
            self.logger.exception("INTERNAL ERROR")
        finally:
            self.stopCapture()
            self.logger.info("Control thread exiting")

    def readControlMessage(self):
        try:
            header = self.controlReadStream.read(6)
        except (
            IOError
        ):  # Windows will raise this when the other end of the FIFO is closed
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
        print(msg)
        self.controlWriteStream.write(msg)

    def stopCapture(self):
        # interrupt the main thread if it is in the middle of receiving data
        # from the capture hardware.
        if self.hw:
            self.hw.send_command_stop()

        # signal the main thread that capturing has been stopped
        self.captureStopped = True

class SniffleExtcapLogHandler(logging.Handler):
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


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


if __name__ == "__main__":
    sys.exit(SniffleExtcapPlugin().main())

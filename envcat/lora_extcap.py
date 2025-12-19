#!/opt/homebrew/bin/python3
import os
import sys
import time
import struct
import signal
import logging
import argparse
import traceback
import threading
from serial.tools.list_ports import comports

from modules.catsniffer import Catsniffer
from modules.pipes import UnixPipe, DEFAULT_UNIX_PATH
from protocol.sniffer_sx import SnifferSx
from protocol.common import START_OF_FRAME, get_global_header

scriptName = os.path.basename(sys.argv[0])

CTRL_NUM_LOGGER = 0
CTRL_NUM_FREQUENCY = 1
CTRL_NUM_CHANNEL = 2
CTRL_NUM_SPREADFACTOR = 3
CTRL_NUM_BANDWIDTH = 4
CTRL_NUM_CODINGRATE = 5
CTRL_NUM_PREAMBLE = 6
CTRL_NUM_SYNC_WORD = 7
# Loggers
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
CATSNIFFER_VID = 11914
CATSNIFFER_PID = 192

snifferSx = SnifferSx()
snifferSxCmd = snifferSx.Commands()


class UsageError(Exception):
    pass


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


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


# Worker API to handle the communications with the Modules
class Worker(threading.Thread):
    def __init__(self, module):
        threading.Thread.__init__(self)
        self.module = module
        self.running = False
        self.daemon = True
        self.worker = None

    def run(self):
        self.running = True
        self.worker = threading.Thread(target=self.module.start_module)
        self.worker.start()

    def stop(self):
        self.running = False
        self.module.stop_worker()
        self.worker.join(1)


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
        self.serial_worker = Catsniffer()

    def main(self, args=None):
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
        parser.add_argument("--serport", help="Sniffer serial port name")
        parser.add_argument(
            "--frequency",
            type=float,
            default=915,
            help="Regiion to listen on",
        )
        parser.add_argument(
            "--spread-factor",
            type=int,
            default=7,
            choices=[i for i in range(7, 13)],
            help="Spreading factor to listen on",
        )
        parser.add_argument(
            "--bandwidth",
            type=int,
            default=7,
            choices=[i for i in range(9)],
            help="Bandwidth to listen on",
        )
        parser.add_argument(
            "--coding-rate",
            type=int,
            default=5,
            choices=[i for i in range(5, 8)],
            help="Coding rate to listen on",
        )
        parser.add_argument(
            "--preamble",
            type=int,
            default=8,
            help="Preamble Length",
        )
        parser.add_argument(
            "--sync-word",
            type=str,
            default=0x12,
            help="Sync Word",
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
        self.args.frequency = float(self.args.frequency)
        self.args.spread_factor = int(self.args.spread_factor)
        self.args.bandwidth = int(self.args.bandwidth)
        self.args.coding_rate = int(self.args.coding_rate)

        self.logger.setLevel(self.args.log_level)

        if self.args.op == "capture" and not self.args.extcap_interface:
            raise UsageError(
                "Please specify the --extcap-interface option when capturing"
            )
        if self.args.op == "capture" and not self.args.fifo:
            raise UsageError("Please specify the --fifo option when capturing")
        if self.args.op == "capture" and not self.args.serport:
            raise UsageError("Please specify the --serport option when capturing")

    # ---------- Extcap mandatory methods ----------
    def extcap_version(self):
        return "extcap {version=1.0}{display=CatSniffer Extcap Lora}{help=https://github.com/ElectronicCats/CatSniffer}"

    def extcap_interfaces(self):
        lines = []
        self.logger.info(f"Frequency: {self.args.frequency}")
        lines.append(self.extcap_version())
        lines.append(
            "interface {value=catsniffer_lora}{display=CatSniffer Extcap Lora}"
        )
        lines.append(
            "control {number=%d}{type=button}{role=logger}{display=Log}{tooltip=Show capture log}"
            % CTRL_NUM_LOGGER
        )
        lines.append(
            "control {number=%d}{type=string}{display=Frequency in MHz}{tooltip=Frequency in MHz}"
            % CTRL_NUM_FREQUENCY
        )
        lines.append(
            "control {number=%d}{type=selector}{display=Bandwidth}{tooltip=Bandwidth to listen on}"
            % CTRL_NUM_BANDWIDTH
        )
        lines.append(
            "control {number=%d}{type=selector}{display=Spreading Factor}{tooltip=Spreading Factor to listen on}"
            % CTRL_NUM_SPREADFACTOR
        )
        lines.append(
            "control {number=%d}{type=selector}{display=Coding Rate}{tooltip=Coding Rate to listen on}"
            % CTRL_NUM_CODINGRATE
        )
        lines.append(
            "control {number=%d}{type=string}{display=Preamble}{tooltip=Preamble Length}"
            % CTRL_NUM_PREAMBLE
        )
        lines.append(
            "control {number=%d}{type=string}{display=Sync Word}{tooltip=Sync Word}"
            % CTRL_NUM_SYNC_WORD
        )
        lines.append(
            "value {control=%d}{value=%f}{display=%f MHz}"
            % (CTRL_NUM_FREQUENCY, 915, self.args.frequency)
        )
        # Bandwidth
        lines.append("value {control=%d}{value=0}{display=7.8}" % CTRL_NUM_BANDWIDTH)
        lines.append("value {control=%d}{value=1}{display=10.4}" % CTRL_NUM_BANDWIDTH)
        lines.append("value {control=%d}{value=2}{display=15.6}" % CTRL_NUM_BANDWIDTH)
        lines.append("value {control=%d}{value=3}{display=20.8}" % CTRL_NUM_BANDWIDTH)
        lines.append("value {control=%d}{value=4}{display=31.25}" % CTRL_NUM_BANDWIDTH)
        lines.append("value {control=%d}{value=5}{display=41.7}" % CTRL_NUM_BANDWIDTH)
        lines.append("value {control=%d}{value=6}{display=62.5}" % CTRL_NUM_BANDWIDTH)
        lines.append(
            "value {control=%d}{value=7}{display=125}{default=true}"
            % CTRL_NUM_BANDWIDTH
        )
        lines.append("value {control=%d}{value=8}{display=250}" % CTRL_NUM_BANDWIDTH)
        # Spreading Factor
        for i in range(7, 13):
            lines.append(
                "value {control=%d}{value=%d}{display=%d}"
                % (CTRL_NUM_SPREADFACTOR, i, i)
            )
        # Coding Rate
        for i in range(5, 9):
            lines.append(
                "value {control=%d}{value=%d}{display=4/%d}"
                % (CTRL_NUM_CODINGRATE, i, i)
            )

        return "\n".join(lines)

    def extcap_dlts(self):
        return "dlt {number=%d}{name=catsniffer_lora_dlt}{display=Catsniffer DLT}" % (
            CATSNIFFER_DLT
        )

    def extcap_config(self):
        lines = []
        lines.append(
            "arg {number=0}{call=--serport}{type=selector}{required=true}"
            "{display=Sniffer serial port}"
            "{tooltip=Sniffer device serial port}"
        )
        lines.append(
            "arg {number=1}{call=--frequency}{type=double}{default=915}"
            "{display=Frequency}"
            "{tooltip=Frequency to listen on}"
        )
        lines.append(
            "arg {number=3}{call=--spread-factor}{type=selector}{default=7}"
            "{display=Spreading Factor}"
            "{tooltip=Spreading Factor to listen on}"
        )
        lines.append(
            "arg {number=4}{call=--bandwidth}{type=selector}{default=7}"
            "{display=Bandwidth}"
            "{tooltip=Bandwidth to listen on}"
        )
        lines.append(
            "arg {number=5}{call=--coding-rate}{type=selector}{default=5}"
            "{display=Coding Rate}"
            "{tooltip=Coding Rate to listen on}"
        )
        lines.append(
            "arg {number=6}{call=--preamble}{type=double}{default=8}"
            "{display=Preamble}"
            "{tooltip=Preamble Length}"
        )
        lines.append(
            "arg {number=7}{call=--sync-word}{type=string}{default=0x12}"
            "{display=Sync Word}"
            "{tooltip=Sync Word}"
        )
        lines.append(
            "arg {number=6}{call=--log-level}{type=selector}{display=Log Level}{tooltip=Set the log level}{default=INFO}{group=Logger}"
        )
        other_ports = []
        for port in comports():
            if sys.platform == "win32":
                device = f"//./{port.device}"
            else:
                device = port.device
            if port.vid is not None and port.pid is not None:
                displayName = "%s" % (port.device)
                lines.append(
                    "value {arg=0}{value=%s}{display=%s}" % (device, displayName)
                )
            else:
                if port.manufacturer is not None:
                    displayName = "%s - %s" % (port.device, port.manufacturer)
                else:
                    displayName = port.device
                other_ports.append((device, displayName))
        for device, displayName in other_ports:
            lines.append("value {arg=0}{value=%s}{display=%s}" % (device, displayName))
        # Spreading Factor
        for i in range(7, 13):
            lines.append("value {arg=3}{value=%d}{display=%d}" % (i, i))
        # Bandwidth
        lines.append("value {arg=4}{value=0}{display=7.8}")
        lines.append("value {arg=4}{value=1}{display=10.4}")
        lines.append("value {arg=4}{value=2}{display=15.6}")
        lines.append("value {arg=4}{value=3}{display=20.8}")
        lines.append("value {arg=4}{value=4}{display=31.25}")
        lines.append("value {arg=4}{value=5}{display=41.7}")
        lines.append("value {arg=4}{value=6}{display=62.5}")
        lines.append("value {arg=4}{value=7}{display=125}{default=true}")
        lines.append("value {arg=4}{value=8}{display=250}")
        # Coding Rate
        for i in range(5, 9):
            lines.append("value {arg=5}{value=%d}{display=4/%d}" % (i, i))
        # Logger
        lines.append("value {arg=6}{value=DEBUG}{display=DEBUG}")
        lines.append("value {arg=6}{value=INFO}{display=INFO}")
        lines.append("value {arg=6}{value=WARNING}{display=WARNING}")
        lines.append("value {arg=6}{value=ERROR}{display=ERROR}")
        return "\n".join(lines)

    def capture(self):
        if self.controlReadStream:
            self.logger.info("Waiting for INITIALIZED message from Wireshark")
            while not self.controlsInitialized:
                time.sleep(0.1)

        self.logger.info("Initializing CatSniffer hardware interface")

        signal.signal(signal.SIGINT, lambda sig, frame: self.stopCapture())
        signal.signal(signal.SIGTERM, lambda sig, frame: self.stopCapture())

        self.serial_worker.set_port(self.args.serport)
        fifo_path = DEFAULT_UNIX_PATH
        if self.args.fifo:
            fifo_path = self.args.fifo

        # start the capture
        self.logger.info(f"Starting capture: {self.args.fifo}")
        pipe = UnixPipe(fifo_path)
        opening_worker = threading.Thread(target=pipe.open, daemon=True)
        opening_worker.start()

        self.serial_worker.connect()
        self.serial_worker.write(snifferSxCmd.set_freq(self.args.frequency))
        self.serial_worker.write(snifferSxCmd.set_bw(self.args.bandwidth))
        self.serial_worker.write(snifferSxCmd.set_sf(self.args.spread_factor))
        self.serial_worker.write(snifferSxCmd.set_cr(self.args.coding_rate))
        self.serial_worker.write(snifferSxCmd.set_pl(self.args.preamble))
        self.serial_worker.write(snifferSxCmd.set_sw(self.args.sync_word))
        self.serial_worker.write(snifferSxCmd.start())

        header_flag = False
        self.writeControlMessage(
            CTRL_CMD_SET, CTRL_NUM_BANDWIDTH, str(self.args.bandwidth)
        )

        # capture packets and write to the capture output until signaled to stop
        while not self.captureStopped:
            try:
                data = self.serial_worker.readline()
                if data:
                    self.logger.info(f"Recv: {data}")
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

                time.sleep(0.5)
            except KeyboardInterrupt:
                self.serial_worker.disconnect()
                if opening_worker.is_alive():
                    opening_worker.join()
                pipe.remove()
                break

        self.logger.info("Capture stopped")

    def stopCapture(self):
        # signal the main thread that capturing has been stopped
        self.captureStopped = True

    def open_pipes(self):
        # if a control-out FIFO has been given, open it for writing
        if self.args.extcap_control_out is not None:
            self.controlWriteStream = open(self.args.extcap_control_out, "wb", 0)

            # Clear the logger control in preparation for writing new messages
            self.writeControlMessage(CTRL_CMD_SET, CTRL_NUM_LOGGER, "")

        # if a control-in FIFO has been given, open it for reading
        if self.args.extcap_control_in is not None:
            self.controlReadStream = open(self.args.extcap_control_in, "rb", 0)

        if self.controlReadStream:
            # start a thread to read control messages
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
                    self.args.frequency = float(payload)
                    self.serial_worker.write(snifferSxCmd.set_freq(self.args.frequency))
                    self.serial_worker.write(snifferSxCmd.start())
                    self.writeControlMessage(
                        CTRL_CMD_SET,
                        CTRL_NUM_FREQUENCY,
                        str(self.args.frequency),
                    )
                elif cmd == CTRL_CMD_SET and controlNum == CTRL_NUM_SPREADFACTOR:
                    self.logger.info("Changing Spread factor: %s" % payload)
                    self.args.spread_factor = int(payload)
                    self.serial_worker.write(
                        snifferSxCmd.set_sf(self.args.spread_factor)
                    )
                    self.serial_worker.write(snifferSxCmd.start())
                    self.writeControlMessage(
                        CTRL_CMD_SET,
                        CTRL_NUM_SPREADFACTOR,
                        str(self.args.spread_factor),
                    )
                elif cmd == CTRL_CMD_SET and controlNum == CTRL_NUM_BANDWIDTH:
                    self.logger.info("Changing bandwidth: %s" % payload)
                    self.args.bandwidth = int(payload)
                    self.serial_worker.write(snifferSxCmd.set_bw(self.args.bandwidth))
                    self.serial_worker.write(snifferSxCmd.start())
                    self.writeControlMessage(
                        CTRL_CMD_SET, CTRL_NUM_BANDWIDTH, str(self.args.bandwidth)
                    )
                elif cmd == CTRL_CMD_SET and controlNum == CTRL_NUM_CODINGRATE:
                    self.logger.info("Changing coding rate: %s" % payload)
                    self.args.coding_rate = int(payload)
                    self.serial_worker.write(snifferSxCmd.set_cr(self.args.coding_rate))
                    self.serial_worker.write(snifferSxCmd.start())
                    self.writeControlMessage(
                        CTRL_CMD_SET, CTRL_NUM_CODINGRATE, str(self.args.coding_rate)
                    )
                elif cmd == CTRL_CMD_SET and controlNum == CTRL_NUM_PREAMBLE:
                    self.logger.info("Changing Preamble: %s" % payload)
                    self.args.preamble = int(payload)
                    self.serial_worker.write(snifferSxCmd.set_pl(self.args.preamble))
                    self.serial_worker.write(snifferSxCmd.start())
                    self.writeControlMessage(
                        CTRL_CMD_SET, CTRL_NUM_PREAMBLE, str(self.args.preamble)
                    )
                elif cmd == CTRL_CMD_SET and controlNum == CTRL_NUM_SYNC_WORD:
                    self.logger.info("Changing Sync word: %s" % payload)
                    self.args.sync_word = payload
                    self.serial_worker.write(snifferSxCmd.set_sw(self.args.sync_word))
                    self.serial_worker.write(snifferSxCmd.start())
                    self.writeControlMessage(
                        CTRL_CMD_SET, CTRL_NUM_SYNC_WORD, str(self.args.sync_word)
                    )

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
        self.controlWriteStream.write(msg)


if __name__ == "__main__":
    sys.exit(MinimalExtcap().main())

"""
CatSniffer TUI Testbench Device Management

CatSniffer device representation and serial endpoint handlers.
"""
import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable, Any, Pattern
from datetime import datetime

import serial

from .constants import (
    DEFAULT_BAUDRATE,
    COMMAND_TIMEOUT,
    ENDPOINT_BRIDGE,
    ENDPOINT_LORA,
    ENDPOINT_SHELL,
    ENDPOINT_LABELS,
    EndpointState,
    CommandStatus,
    DeviceHealth,
)
from .discovery import DiscoveredDevice, DeviceIdentity
from .logging import LogManager, log_manager


@dataclass
class CommandResult:
    """Result of a command execution."""
    command: str
    status: CommandStatus
    response: Optional[str]
    duration_ms: float
    retries: int
    error: Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.status == CommandStatus.PASS


@dataclass
class QueuedCommand:
    """A command waiting to be sent."""
    command: str
    future: asyncio.Future
    timeout: float
    expected_match: Optional[Pattern] = None
    sent_at: Optional[float] = None
    response_buffer: str = ""


class EndpointHandler:
    """
    Manages a single serial endpoint with async I/O.
    """

    def __init__(
        self,
        port: str,
        endpoint_type: str,
        device_id: int,
        log_manager: LogManager,
    ):
        self.port = port
        self.endpoint_type = endpoint_type  # "bridge", "lora", "shell"
        self.device_id = device_id
        self.log_manager = log_manager

        self.state = EndpointState.DISCONNECTED
        self._serial: Optional[serial.Serial] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._running = False

        # Command queue
        self._command_queue: asyncio.Queue[QueuedCommand] = asyncio.Queue()
        self._current_command: Optional[QueuedCommand] = None

        # Mode tracking (CDC1 specific)
        self.lora_mode: Optional[str] = None  # "stream" or "command"

        # Callbacks
        self._on_data_received: Optional[Callable[[str, Dict], None]] = None
        self._on_state_changed: Optional[Callable[[EndpointState], None]] = None

    @property
    def endpoint_label(self) -> str:
        return ENDPOINT_LABELS.get(self.endpoint_type, self.endpoint_type)

    def set_callbacks(
        self,
        on_data_received: Optional[Callable[[str, Dict], None]] = None,
        on_state_changed: Optional[Callable[[EndpointState], None]] = None,
    ):
        """Set event callbacks."""
        self._on_data_received = on_data_received
        self._on_state_changed = on_state_changed

    async def connect(self) -> bool:
        """Open serial port and start reader task."""
        if self.state == EndpointState.CONNECTED:
            return True

        try:
            self.state = EndpointState.CONNECTING
            if self._on_state_changed:
                self._on_state_changed(self.state)

            # Open serial port in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            self._serial = await loop.run_in_executor(
                None,
                lambda: serial.Serial(
                    self.port,
                    DEFAULT_BAUDRATE,
                    timeout=0.1,
                    write_timeout=1.0
                )
            )

            self._running = True
            self._reader_task = asyncio.create_task(self._reader_loop())
            self._command_queue = asyncio.Queue()

            self.state = EndpointState.CONNECTED
            if self._on_state_changed:
                self._on_state_changed(self.state)

            return True

        except Exception as e:
            self.state = EndpointState.ERROR
            if self._on_state_changed:
                self._on_state_changed(self.state)
            return False

    async def disconnect(self):
        """Close serial port and stop reader task."""
        self._running = False

        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        if self._serial and self._serial.is_open:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

        self.state = EndpointState.DISCONNECTED
        if self._on_state_changed:
            self._on_state_changed(self.state)

    async def send_command(
        self,
        command: str,
        timeout: float = COMMAND_TIMEOUT,
        retry: int = 1,
        expected_match: Optional[Pattern] = None
    ) -> CommandResult:
        """
        Send a command and wait for response.
        """
        if self.state != EndpointState.CONNECTED:
            return CommandResult(
                command=command,
                status=CommandStatus.ERROR,
                response=None,
                duration_ms=0,
                retries=0,
                error="Endpoint not connected"
            )

        # Check mode guard for CDC1
        if self.endpoint_type == ENDPOINT_LORA and self.lora_mode == "stream":
            return CommandResult(
                command=command,
                status=CommandStatus.ERROR,
                response=None,
                duration_ms=0,
                retries=0,
                error="CDC1 is in STREAM mode. Switch to command mode first."
            )

        for attempt in range(retry + 1):
            start_time = time.time()

            try:
                # Queue command
                future = asyncio.get_event_loop().create_future()
                queued_cmd = QueuedCommand(
                    command=command,
                    future=future,
                    timeout=timeout,
                    expected_match=expected_match
                )
                await self._command_queue.put(queued_cmd)

                # Wait for response
                response = await asyncio.wait_for(future, timeout=timeout + 1.0)

                duration_ms = (time.time() - start_time) * 1000

                # Log TX
                self.log_manager.log_tx(self.device_id, self.endpoint_label, command)

                if response:
                    self.log_manager.log_rx(self.device_id, self.endpoint_label, response)

                return CommandResult(
                    command=command,
                    status=CommandStatus.PASS if response else CommandStatus.FAIL,
                    response=response,
                    duration_ms=duration_ms,
                    retries=attempt
                )

            except asyncio.TimeoutError:
                duration_ms = (time.time() - start_time) * 1000
                if attempt < retry:
                    continue
                return CommandResult(
                    command=command,
                    status=CommandStatus.TIMEOUT,
                    response=None,
                    duration_ms=duration_ms,
                    retries=attempt,
                    error="Command timed out"
                )
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                return CommandResult(
                    command=command,
                    status=CommandStatus.ERROR,
                    response=None,
                    duration_ms=duration_ms,
                    retries=attempt,
                    error=str(e)
                )

    async def send_raw(self, data: bytes) -> bool:
        """Send raw bytes (for stream mode)."""
        if self.state != EndpointState.CONNECTED or not self._serial:
            return False

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._serial.write, data)
            await loop.run_in_executor(None, self._serial.flush)

            # Log TX
            self.log_manager.log_tx(self.device_id, self.endpoint_label, data.hex(), len(data))
            return True
        except Exception:
            return False

    async def send_line(self, line: str) -> bool:
        """Send a line with CRLF."""
        return await self.send_raw((line + "\r\n").encode('ascii'))

    async def _reader_loop(self):
        """Background task reading from serial port."""
        buffer = b""

        while self._running and self._serial:
            try:
                # Always attempt a small read; some macOS USB-serial drivers
                # don't reliably update in_waiting until after outbound traffic.
                loop = asyncio.get_event_loop()
                read_len = max(1, int(getattr(self._serial, "in_waiting", 0) or 0))
                chunk = await loop.run_in_executor(None, self._serial.read, read_len)

                # CDC0 is a raw stream endpoint; don't wait for line breaks.
                if self.endpoint_type == ENDPOINT_BRIDGE:
                    if chunk:
                        await self._process_raw_chunk(chunk)
                elif chunk:
                    buffer += chunk

                    # Process complete lines
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        line = line.strip()
                        if line:
                            await self._process_line(line)

                # Process command queue
                if self._current_command is None:
                    try:
                        queued_cmd = self._command_queue.get_nowait()
                        await self._send_queued_command(queued_cmd)
                    except asyncio.QueueEmpty:
                        pass

                await asyncio.sleep(0.005)  # Keep latency low without busy spinning

            except asyncio.CancelledError:
                break
            except Exception as e:
                await asyncio.sleep(0.1)

    async def _process_raw_chunk(self, chunk: bytes):
        """Process raw CDC0 stream chunks immediately."""
        try:
            # Prefer printable ASCII for readability; fall back to HEX for binary payloads.
            text = chunk.decode("ascii", errors="ignore")
            if text and any(ch.isprintable() and not ch.isspace() for ch in text):
                display = text.strip() or chunk.hex()
            else:
                display = chunk.hex()

            self.log_manager.log_rx(self.device_id, self.endpoint_label, display)

            if self._on_data_received:
                self._on_data_received(display, {})
        except Exception:
            pass

    async def _send_queued_command(self, queued_cmd: QueuedCommand):
        """Send a queued command and track response."""
        try:
            queued_cmd.sent_at = time.time()

            # Send command
            cmd_bytes = (queued_cmd.command + "\r\n").encode('ascii')
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._serial.write, cmd_bytes)
            await loop.run_in_executor(None, self._serial.flush)

            self._current_command = queued_cmd

            # Wait for response (handled in _process_line)
            # Start response timeout
            await asyncio.sleep(0.1)

        except Exception as e:
            if not queued_cmd.future.done():
                queued_cmd.future.set_exception(e)

    async def _process_line(self, line: bytes):
        """Process a received line."""
        try:
            line_str = line.decode('ascii', errors='ignore').strip()
            if not line_str:
                return

            # Parse for special formats (LoRa RX)
            parsed = self._parse_response(line_str)

            # Log RX
            self.log_manager.log_rx(self.device_id, self.endpoint_label, line_str, parsed)

            # Check if this matches current command expectation
            if self._current_command and not self._current_command.future.done():
                self._current_command.response_buffer += line_str + "\n"

                # Check for expected match or end of response
                if self._current_command.expected_match:
                    if self._current_command.expected_match.search(line_str):
                        self._current_command.future.set_result(
                            self._current_command.response_buffer.strip()
                        )
                        self._current_command = None
                else:
                    # Default: first non-empty line is response
                    if line_str and not self._current_command.future.done():
                        self._current_command.future.set_result(line_str)
                        self._current_command = None

            # Callback for data received
            if self._on_data_received:
                self._on_data_received(line_str, parsed or {})

        except Exception:
            pass

    def _parse_response(self, line: str) -> Optional[Dict]:
        """Parse response for special formats."""
        # LoRa RX format: "RX: <hex...> | RSSI: <int> | SNR: <int>"
        lora_match = re.match(
            r'RX:\s*([A-Fa-f0-9]+)\s*\|\s*RSSI:\s*(-?\d+)\s*\|\s*SNR:\s*(-?\d+)',
            line
        )
        if lora_match:
            return {
                "type": "lora_rx",
                "data": lora_match.group(1),
                "rssi": int(lora_match.group(2)),
                "snr": int(lora_match.group(3))
            }

        # FSK RX format: "FSK RX: <hex...> | RSSI: <int> | Len: <int>"
        fsk_match = re.match(
            r'FSK RX:\s*([A-Fa-f0-9]+)\s*\|\s*RSSI:\s*(-?\d+)\s*\|\s*Len:\s*(\d+)',
            line
        )
        if fsk_match:
            return {
                "type": "fsk_rx",
                "data": fsk_match.group(1),
                "rssi": int(fsk_match.group(2)),
                "len": int(fsk_match.group(3))
            }

        return None


class CatSnifferDevice:
    """
    Represents a single CatSniffer device with 3 endpoints.
    """

    def __init__(
        self,
        discovered: DiscoveredDevice,
        device_id: int,
        log_manager: LogManager,
    ):
        self.identity = discovered.identity
        self.device_id = device_id
        self.log_manager = log_manager

        # Create endpoint handlers
        self.bridge: Optional[EndpointHandler] = None
        self.lora: Optional[EndpointHandler] = None
        self.shell: Optional[EndpointHandler] = None

        if discovered.bridge_port:
            self.bridge = EndpointHandler(
                discovered.bridge_port,
                ENDPOINT_BRIDGE,
                device_id,
                log_manager
            )

        if discovered.lora_port:
            self.lora = EndpointHandler(
                discovered.lora_port,
                ENDPOINT_LORA,
                device_id,
                log_manager
            )

        if discovered.shell_port:
            self.shell = EndpointHandler(
                discovered.shell_port,
                ENDPOINT_SHELL,
                device_id,
                log_manager
            )

        # Device state cache
        self.current_band: Optional[str] = None
        self.current_modulation: Optional[str] = None  # "lora" or "fsk"
        self.last_status_time: Optional[float] = None
        self.last_rx_time: Optional[float] = None

        # Test state
        self.smoke_test_running = False
        self.smoke_test_results: Dict[str, CommandResult] = {}

    @property
    def health(self) -> DeviceHealth:
        if self.shell and self.lora and self.bridge:
            return DeviceHealth.HEALTHY
        elif self.shell:
            return DeviceHealth.PARTIAL
        else:
            return DeviceHealth.CRITICAL

    @property
    def is_complete(self) -> bool:
        return all([self.bridge, self.lora, self.shell])

    def __str__(self):
        return f"CatSniffer #{self.device_id}"

    async def connect_all(self) -> Dict[str, bool]:
        """Connect all available endpoints."""
        results = {}

        if self.shell:
            results["shell"] = await self.shell.connect()
        if self.lora:
            results["lora"] = await self.lora.connect()
        if self.bridge:
            results["bridge"] = await self.bridge.connect()

        return results

    async def disconnect_all(self):
        """Disconnect all endpoints."""
        if self.shell:
            await self.shell.disconnect()
        if self.lora:
            await self.lora.disconnect()
        if self.bridge:
            await self.bridge.disconnect()

    async def refresh_status(self) -> bool:
        """Send 'status' command and update cached state."""
        if not self.shell:
            return False

        result = await self.shell.send_command("status")
        if result.passed and result.response:
            # Parse status response
            resp_lower = result.response.lower()
            if "loraband" in resp_lower or "band3" in resp_lower:
                self.current_band = "lora"
            elif "sub-ghz" in resp_lower or "band2" in resp_lower:
                self.current_band = "subghz"
            elif "2.4ghz" in resp_lower or "band1" in resp_lower:
                self.current_band = "24ghz"

            if "lora" in resp_lower and "fsk" not in resp_lower:
                self.current_modulation = "lora"
            elif "fsk" in resp_lower:
                self.current_modulation = "fsk"

            self.last_status_time = time.time()
            return True
        return False

    # Convenience methods for CDC2 commands
    async def send_shell_command(self, command: str, **kwargs) -> CommandResult:
        """Send command via CDC2 (shell)."""
        if not self.shell:
            return CommandResult(
                command=command,
                status=CommandStatus.ERROR,
                response=None,
                duration_ms=0,
                retries=0,
                error="CDC2 (Shell) not available"
            )
        return await self.shell.send_command(command, **kwargs)

    async def send_lora_command(self, command: str, **kwargs) -> CommandResult:
        """Send command via CDC1 (LoRa port) with mode guard."""
        if not self.lora:
            return CommandResult(
                command=command,
                status=CommandStatus.ERROR,
                response=None,
                duration_ms=0,
                retries=0,
                error="CDC1 (LoRa) not available"
            )

        # Mode guard
        if self.lora.lora_mode == "stream":
            return CommandResult(
                command=command,
                status=CommandStatus.ERROR,
                response=None,
                duration_ms=0,
                retries=0,
                error="CDC1 is in STREAM mode. Switch to command mode first."
            )

        return await self.lora.send_command(command, **kwargs)

    async def set_band(self, band: str) -> CommandResult:
        """Set band: band1, band2, or band3."""
        result = await self.send_shell_command(band)
        if result.passed:
            if band == "band1":
                self.current_band = "24ghz"
            elif band == "band2":
                self.current_band = "subghz"
            elif band == "band3":
                self.current_band = "lora"
        return result

    async def set_modulation(self, mod: str) -> CommandResult:
        """Set modulation: lora or fsk."""
        result = await self.send_shell_command(f"modulation {mod}")
        if result.passed:
            self.current_modulation = mod.lower()
        return result

    async def set_lora_mode(self, mode: str) -> CommandResult:
        """Set LoRa mode: stream or command. Updates self.lora.lora_mode."""
        result = await self.send_shell_command(f"lora_mode {mode}")
        if result.passed and self.lora:
            self.lora.lora_mode = mode.lower()
        return result

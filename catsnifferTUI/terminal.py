"""
CatSniffer TUI Testbench - Interactive Serial Terminal

Modal screen for direct serial port interaction.
"""
import asyncio
import time
from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Header,
    Footer,
    Static,
    Input,
    Select,
    Log,
    Label,
)

from .constants import TerminalMode, DEFAULT_BAUDRATE, ENDPOINT_LABELS
from .device import EndpointHandler


class InteractiveSerialTerminal(ModalScreen):
    """Modal screen for interactive serial communication."""

    CSS = """
    InteractiveSerialTerminal {
        align: center middle;
    }

    #terminal-container {
        width: 90;
        height: 85%;
        border: thick $primary;
        background: $surface;
    }

    #terminal-header {
        dock: top;
        height: 3;
        padding: 1;
        background: $primary;
        color: $text;
    }

    #settings-row {
        height: 3;
        padding: 0 1;
        background: $surface-darken-1;
    }

    #terminal-log {
        height: 1fr;
        border: solid $primary-darken-2;
        margin: 1;
    }

    #input-row {
        height: 3;
        dock: bottom;
        padding: 0 1;
        background: $surface-darken-1;
    }

    #status-row {
        height: 2;
        dock: bottom;
        padding: 0 1;
        background: $primary-darken-1;
    }

    .setting-select {
        width: 15;
        margin-right: 2;
    }

    #input-field {
        width: 1fr;
        margin-right: 1;
    }

    #send-btn {
        width: 10;
    }

    .warning-label {
        color: $warning;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("enter", "send", "Send"),
        Binding("ctrl+l", "clear_log", "Clear"),
    ]

    device_id: reactive[int] = reactive(0)
    endpoint: reactive[str] = reactive("")
    endpoint_label: reactive[str] = reactive("")

    def __init__(
        self,
        endpoint_handler: EndpointHandler,
        device_id: int,
        endpoint_type: str,
        **kwargs
    ):
        super().__init__(**kwargs)
        self._endpoint = endpoint_handler
        self.device_id = device_id
        self.endpoint = endpoint_type
        self.endpoint_label = ENDPOINT_LABELS.get(endpoint_type, endpoint_type)

        self._mode = TerminalMode.LINE
        self._line_ending = "\r\n"
        self._baudrate = DEFAULT_BAUDRATE
        self._bytes_tx = 0
        self._bytes_rx = 0
        self._monitoring = False

    def compose(self) -> ComposeResult:
        yield Container(
            Header(),
            Container(
                Label(
                    f"Serial Terminal - CatSniffer #{self.device_id} {self.endpoint_label}",
                    id="terminal-title"
                ),
                Horizontal(
                    Select(
                        options=[
                            ("Line", TerminalMode.LINE),
                            ("Hex", TerminalMode.HEX),
                            ("Raw", TerminalMode.RAW),
                        ],
                        value=TerminalMode.LINE,
                        id="mode-select",
                        classes="setting-select"
                    ),
                    Select(
                        options=[
                            ("CRLF", "\r\n"),
                            ("LF", "\n"),
                            ("CR", "\r"),
                            ("None", ""),
                        ],
                        value="\r\n",
                        id="ending-select",
                        classes="setting-select"
                    ),
                    Label(
                        f"Port: {self._endpoint.port}",
                        id="port-label"
                    ),
                    id="settings-row"
                ),
                Log(id="terminal-log", highlight=True),
                Horizontal(
                    Input(placeholder="Enter command or hex data...", id="input-field"),
                    Button("Send", variant="primary", id="send-btn"),
                    id="input-row"
                ),
                Horizontal(
                    Label(f"TX: 0 bytes | RX: 0 bytes", id="status-label"),
                    Button("Clear", id="clear-btn"),
                    Button("Close", variant="error", id="close-btn"),
                    id="status-row"
                ),
                id="terminal-container"
            ),
            Footer()
        )

    async def on_mount(self):
        """Set up terminal on mount."""
        self._monitoring = True

        # Set up callback for incoming data
        self._endpoint.set_callbacks(on_data_received=self._on_data_received)

        # Start monitoring task
        self._monitor_task = asyncio.create_task(self._monitor_loop())

        # Log initial connection status
        log = self.query_one("#terminal-log", Log)
        log.write_line(f"[SYSTEM] Connected to {self._endpoint.port}")
        log.write_line(f"[SYSTEM] Mode: {self._mode.value}, Baud: {self._baudrate}")

    async def on_unmount(self):
        """Clean up on unmount."""
        self._monitoring = False
        if hasattr(self, '_monitor_task'):
            self._monitor_task.cancel()

    async def _monitor_loop(self):
        """Background monitoring for incoming data."""
        while self._monitoring:
            await asyncio.sleep(0.1)

    def _on_data_received(self, data: str, parsed: dict):
        """Handle incoming data from endpoint."""
        log = self.query_one("#terminal-log", Log)

        if self._mode == TerminalMode.HEX:
            # Display as hex
            log.write_line(f"< {data.encode().hex()}")
        else:
            # Display as text
            log.write_line(f"< {data}")

        self._bytes_rx += len(data)
        self._update_status()

    def _update_status(self):
        """Update status label."""
        status = self.query_one("#status-label", Label)
        status.update(f"TX: {self._bytes_tx} bytes | RX: {self._bytes_rx} bytes")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "send-btn":
            self.action_send()
        elif event.button.id == "clear-btn":
            self.action_clear_log()
        elif event.button.id == "close-btn":
            self.action_close()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        if event.input.id == "input-field":
            self.action_send()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle select changes."""
        if event.select.id == "mode-select":
            self._mode = event.value
        elif event.select.id == "ending-select":
            self._line_ending = event.value

    def action_send(self):
        """Send data from input field."""
        input_field = self.query_one("#input-field", Input)
        data = input_field.value.strip()

        if not data:
            return

        log = self.query_one("#terminal-log", Log)

        # Format data based on mode
        if self._mode == TerminalMode.HEX:
            # Parse hex input
            try:
                raw_bytes = bytes.fromhex(data.replace(" ", ""))
            except ValueError:
                log.write_line(f"[ERROR] Invalid hex: {data}")
                return

            # Send raw bytes
            asyncio.create_task(self._send_raw(raw_bytes))
            log.write_line(f"> {data}")

        elif self._mode == TerminalMode.RAW:
            # Send as raw bytes
            raw_bytes = data.encode('ascii', errors='replace')
            asyncio.create_task(self._send_raw(raw_bytes))
            log.write_line(f"> {data}")

        else:  # LINE mode
            # Send as line
            asyncio.create_task(self._send_line(data))
            log.write_line(f"> {data}")

        self._bytes_tx += len(data)
        self._update_status()
        input_field.value = ""

    async def _send_raw(self, data: bytes):
        """Send raw bytes."""
        if self._endpoint:
            await self._endpoint.send_raw(data)

    async def _send_line(self, line: str):
        """Send line with ending."""
        if self._endpoint:
            await self._endpoint.send_raw((line + self._line_ending).encode('ascii'))

    def action_clear_log(self):
        """Clear the terminal log."""
        log = self.query_one("#terminal-log", Log)
        log.clear()
        log.write_line("[SYSTEM] Log cleared")

    def action_close(self):
        """Close the terminal modal."""
        self._monitoring = False
        self.dismiss()

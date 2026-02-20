"""
CatSniffer TUI Testbench - Screen Definitions

Tab screens for All Devices and individual device views.
"""
import asyncio
from datetime import datetime
from typing import Dict, List, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.message import Message
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import (
    Button,
    Header,
    Footer,
    Static,
    Input,
    Label,
    DataTable,
    TabbedContent,
    TabPane,
)

from .constants import ENDPOINT_LABELS, DeviceHealth
from .device import CatSnifferDevice, CommandResult
from .widgets import (
    StatusIndicator,
    CommandButton,
    ConfigField,
    TestProgressPanel,
    LogViewer,
)
from .testbench import SmokeTestRunner, SmokeTestResult, TestStepResult


class AllDevicesScreen(Screen):
    """Screen showing all devices summary and fleet actions."""

    CSS = """
    AllDevicesScreen {
        layout: vertical;
    }

    #devices-table {
        height: 1fr;
        margin: 1;
    }

    #fleet-actions {
        height: auto;
        dock: bottom;
        padding: 1;
        background: $surface-darken-1;
    }

    .action-group {
        margin: 1 0;
    }

    .action-group Label {
        text-style: bold;
        margin-bottom: 1;
    }

    .action-buttons {
        height: auto;
    }

    .action-buttons Button {
        margin-right: 1;
    }
    """

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
    ]

    devices: reactive[Dict] = reactive({})

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._smoke_runner = SmokeTestRunner()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            DataTable(id="devices-table", zebra_stripes=True),
            Container(
                Horizontal(
                    Vertical(
                        Label("Fleet Band Actions:"),
                        Horizontal(
                            Button("All → 2.4GHz (band1)", id="fleet-band1"),
                            Button("All → Sub-GHz (band2)", id="fleet-band2"),
                            Button("All → LoRa (band3)", id="fleet-band3"),
                        ),
                        classes="action-group"
                    ),
                    Vertical(
                        Label("LoRa Frequency:"),
                        Horizontal(
                            Input(placeholder="915000000", id="fleet-freq"),
                            Button("Set All", id="fleet-set-freq"),
                        ),
                        classes="action-group"
                    ),
                    Vertical(
                        Label("Smoke Test:"),
                        Horizontal(
                            Button("Run All Smoke Tests", id="fleet-smoke", variant="warning"),
                            Button("Cancel All", id="fleet-cancel"),
                        ),
                        classes="action-group"
                    ),
                    classes="action-buttons"
                ),
                id="fleet-actions"
            ),
            id="main-container"
        )
        yield Footer()

    def on_mount(self):
        """Initialize table."""
        table = self.query_one("#devices-table", DataTable)
        table.add_columns("Device", "CDC0", "CDC1", "CDC2", "Health", "Status", "LoRa Mode", "Last RX")

    def update_devices(self, devices: Dict[int, CatSnifferDevice]):
        """Update device table."""
        self.devices = devices
        table = self.query_one("#devices-table", DataTable)
        table.clear()

        for device_id, device in devices.items():
            cdc0_status = "●" if device.bridge else "○"
            cdc1_status = "●" if device.lora else "○"
            cdc2_status = "●" if device.shell else "○"

            health = device.health.value
            test_status = "Testing..." if device.smoke_test_running else "Idle"
            lora_mode = device.lora.lora_mode if device.lora else "N/A"
            last_rx = datetime.fromtimestamp(device.last_rx_time).strftime("%H:%M:%S") if device.last_rx_time else "--"

            table.add_row(
                f"#{device_id}",
                f"[green]{cdc0_status}[/green]" if device.bridge else f"[dim]{cdc0_status}[/dim]",
                f"[green]{cdc1_status}[/green]" if device.lora else f"[dim]{cdc1_status}[/dim]",
                f"[green]{cdc2_status}[/green]" if device.shell else f"[dim]{cdc2_status}[/dim]",
                f"[green]{health}[/green]" if health == "healthy" else f"[yellow]{health}[/yellow]",
                test_status,
                lora_mode,
                last_rx
            )

    def on_button_pressed(self, event: Button.Pressed):
        """Handle fleet action buttons."""
        if event.button.id == "fleet-smoke":
            self._run_fleet_smoke()
        elif event.button.id == "fleet-band1":
            self.app.post_message(FleetAction("band1"))
        elif event.button.id == "fleet-band2":
            self.app.post_message(FleetAction("band2"))
        elif event.button.id == "fleet-band3":
            self.app.post_message(FleetAction("band3"))
        elif event.button.id == "fleet-set-freq":
            freq_input = self.query_one("#fleet-freq", Input)
            freq = freq_input.value.strip()
            if freq:
                self.app.post_message(FleetAction("lora_freq", freq))

    def _run_fleet_smoke(self):
        """Run smoke test on all devices."""
        self.app.post_message(FleetSmokeTest())


class FleetAction(Message):
    """Fleet action message."""
    def __init__(self, action: str, value: str = ""):
        super().__init__()
        self.action = action
        self.value = value


class FleetSmokeTest(Message):
    """Fleet smoke test request."""
    pass


class DeviceScreen(Screen):
    """Screen for a single device with 3 endpoint panels."""

    CSS = """
    DeviceScreen {
        layout: vertical;
    }

    #device-header {
        height: 3;
        padding: 1;
        background: $primary;
        color: $text;
    }

    #panels-container {
        layout: horizontal;
        height: 1fr;
    }

    .endpoint-panel {
        width: 1fr;
        padding: 1;
        border: solid $primary-darken-2;
        margin: 1;
    }

    .panel-title {
        text-style: bold;
        background: $primary-darken-1;
        padding: 0 1;
        margin-bottom: 1;
    }

    .button-row {
        height: auto;
        margin: 1 0;
    }

    .button-row Button {
        margin-right: 1;
        min-width: 10;
    }

    .config-section {
        margin: 1 0;
    }

    .config-section Label {
        text-style: bold;
        color: $accent;
    }

    .status-display {
        margin-top: 1;
        padding: 1;
        background: $surface-darken-1;
    }

    #test-panel {
        dock: bottom;
        height: 12;
    }
    """

    device_id: reactive[int] = reactive(0)

    def __init__(self, device: CatSnifferDevice, **kwargs):
        super().__init__(**kwargs)
        self._device = device
        self.device_id = device.device_id

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Horizontal(
                StatusIndicator(self._device.health.value),
                Label(f"CatSniffer #{self.device_id}", classes="device-title"),
                Label(self._device.identity.serial_number[:16], classes="serial-display"),
                classes="header-content"
            ),
            id="device-header"
        )
        yield Horizontal(
            # CDC2 Panel (Config)
            Container(
                Label("CDC2 - Shell Config", classes="panel-title"),
                ScrollableContainer(
                    Container(
                        Label("Mode/Band:", classes="config-section"),
                        Horizontal(
                            CommandButton("Boot", "boot", variant="warning"),
                            CommandButton("Exit", "exit"),
                            CommandButton("Reboot", "reboot", variant="error"),
                        ),
                        Horizontal(
                            CommandButton("2.4GHz", "band1"),
                            CommandButton("Sub-GHz", "band2"),
                            CommandButton("LoRa", "band3", variant="success"),
                        ),
                        Horizontal(
                            CommandButton("Status", "status", variant="primary"),
                        ),
                        classes="config-section"
                    ),
                    Container(
                        Label("LoRa Config:", classes="config-section"),
                        ConfigField("Freq (Hz)", "lora_freq", "915000000"),
                        Horizontal(
                            ConfigField("SF", "lora_sf", "7"),
                            ConfigField("BW (kHz)", "lora_bw", "125"),
                            ConfigField("CR", "lora_cr", "5"),
                        ),
                        Horizontal(
                            ConfigField("Power (dBm)", "lora_power", "14"),
                            ConfigField("Preamble", "lora_preamble", "8"),
                        ),
                        Horizontal(
                            CommandButton("Show Config", "lora_config"),
                            CommandButton("Apply", "lora_apply", variant="success"),
                        ),
                        classes="config-section"
                    ),
                    Container(
                        Label("FSK Config:", classes="config-section"),
                        ConfigField("Freq (Hz)", "fsk_freq", "915000000"),
                        Horizontal(
                            ConfigField("Bitrate", "fsk_bitrate", "50000"),
                            ConfigField("FDev (Hz)", "fsk_fdev", "25000"),
                        ),
                        Horizontal(
                            CommandButton("Show Config", "fsk_config"),
                            CommandButton("Apply", "fsk_apply", variant="success"),
                        ),
                        classes="config-section"
                    ),
                    Container(
                        Label("Modulation:", classes="config-section"),
                        Horizontal(
                            CommandButton("LoRa", "modulation lora", variant="primary"),
                            CommandButton("FSK", "modulation fsk"),
                        ),
                        classes="config-section"
                    ),
                    classes="scroll-content"
                ),
                classes="endpoint-panel"
            ),
            # CDC1 Panel (LoRa/FSK)
            Container(
                Label("CDC1 - LoRa/FSK", classes="panel-title"),
                Container(
                    Label("Mode:", classes="config-section"),
                    Horizontal(
                        CommandButton("Stream", "lora_mode stream"),
                        CommandButton("Command", "lora_mode command", variant="primary"),
                    ),
                    classes="config-section"
                ),
                Container(
                    Label("LoRa Commands:", classes="config-section"),
                    Horizontal(
                        CommandButton("TEST", "TEST", endpoint="CDC1"),
                        CommandButton("TXTEST", "TXTEST", endpoint="CDC1"),
                    ),
                    Horizontal(
                        Input(placeholder="TX hex data...", id="tx-hex-input"),
                        CommandButton("TX", "TX", endpoint="CDC1"),
                    ),
                    classes="config-section"
                ),
                Container(
                    Label("FSK Commands:", classes="config-section"),
                    Horizontal(
                        CommandButton("FSKTEST", "FSKTEST", endpoint="CDC1"),
                        CommandButton("FSKRX", "FSKRX", endpoint="CDC1"),
                    ),
                    Horizontal(
                        Input(placeholder="FSK TX hex...", id="fsk-tx-input"),
                        CommandButton("FSKTX", "FSKTX", endpoint="CDC1"),
                    ),
                    classes="config-section"
                ),
                Container(
                    Label("Last RX:", classes="config-section"),
                    Static("No data", id="last-rx-display"),
                    classes="config-section"
                ),
                classes="endpoint-panel"
            ),
            # CDC0 Panel (Bridge)
            Container(
                Label("CDC0 - CC1352 Bridge", classes="panel-title"),
                Container(
                    Label("Monitor:", classes="config-section"),
                    Horizontal(
                        Button("Start Monitor", id="start-monitor"),
                        Button("Stop Monitor", id="stop-monitor"),
                    ),
                    classes="config-section"
                ),
                Container(
                    Label("Bytes:", classes="config-section"),
                    Static("TX: 0 | RX: 0", id="bridge-counters"),
                    classes="config-section"
                ),
                Container(
                    Label("Test:", classes="config-section"),
                    Horizontal(
                        Input(placeholder="Hex bytes to send...", id="bridge-tx-input"),
                        Button("Send", id="bridge-send", variant="warning"),
                    ),
                    Static("[yellow]Warning: Binary passthrough[/yellow]", id="bridge-warning"),
                    classes="config-section"
                ),
                Container(
                    Button("Open Terminal", id="open-bridge-terminal"),
                    classes="config-section"
                ),
                classes="endpoint-panel"
            ),
            id="panels-container"
        )
        yield Container(
            TestProgressPanel(id="test-panel"),
            Horizontal(
                Button("Run Smoke Test", id="run-smoke", variant="primary"),
                Button("Clear Results", id="clear-results"),
                Static("Status: Idle", id="test-status"),
            ),
            id="test-controls"
        )
        yield Footer()

    def on_mount(self):
        """Set up device screen."""
        # Update health indicator
        health = self.query_one(StatusIndicator)
        health.state = self._device.health.value

    def on_command_button_command_requested(self, event: CommandButton.CommandRequested):
        """Handle command button clicks."""
        command = event.command
        endpoint = event.endpoint

        # Get hex input for TX commands
        if command == "TX":
            hex_input = self.query_one("#tx-hex-input", Input)
            if hex_input.value:
                command = f"TX {hex_input.value}"
        elif command == "FSKTX":
            hex_input = self.query_one("#fsk-tx-input", Input)
            if hex_input.value:
                command = f"FSKTX {hex_input.value}"

        # Post message to app
        self.app.post_message(DeviceCommand(
            self.device_id,
            command,
            endpoint
        ))

    def on_button_pressed(self, event: Button.Pressed):
        """Handle button presses."""
        if event.button.id == "run-smoke":
            self.app.post_message(DeviceSmokeTest(self.device_id))
        elif event.button.id == "clear-results":
            panel = self.query_one("#test-panel", TestProgressPanel)
            panel.clear_results()
        elif event.button.id == "open-bridge-terminal":
            if self._device.bridge:
                self.app.open_terminal(self._device.bridge, self.device_id, "Cat-Bridge")

    def update_test_progress(self, step_result: TestStepResult):
        """Update smoke test progress."""
        panel = self.query_one("#test-panel", TestProgressPanel)
        panel.add_step_result(
            int(step_result.step.name),
            step_result.step.endpoint,
            step_result.step.command,
            step_result.passed,
            step_result.response_snippet
        )

    def update_test_complete(self, result: SmokeTestResult):
        """Update when smoke test completes."""
        status = self.query_one("#test-status", Static)
        if result.passed:
            status.update(f"[green]PASS: {result.passed_count}/{result.total_count}[/green]")
        else:
            status.update(f"[red]FAIL: {result.passed_count}/{result.total_count}[/red]")

    def update_last_rx(self, data: str, parsed: dict):
        """Update last RX display."""
        display = self.query_one("#last-rx-display", Static)
        if parsed:
            if parsed.get("type") == "lora_rx":
                display.update(f"LoRa: {parsed['data'][:20]} | RSSI: {parsed['rssi']} | SNR: {parsed['snr']}")
            elif parsed.get("type") == "fsk_rx":
                display.update(f"FSK: {parsed['data'][:20]} | RSSI: {parsed['rssi']} | Len: {parsed['len']}")
        else:
            display.update(data[:60])


class DeviceCommand(Message):
    """Device command message."""
    def __init__(self, device_id: int, command: str, endpoint: str):
        super().__init__()
        self.device_id = device_id
        self.command = command
        self.endpoint = endpoint


class DeviceSmokeTest(Message):
    """Device smoke test request."""
    def __init__(self, device_id: int):
        super().__init__()
        self.device_id = device_id

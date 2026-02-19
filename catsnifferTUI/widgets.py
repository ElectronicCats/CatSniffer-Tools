"""
CatSniffer TUI Testbench - Custom Widgets

Custom TUI widgets for the testbench interface.
"""
from typing import Optional
from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static, Button, Input, Label, DataTable

from .constants import DeviceHealth, EndpointState, ENDPOINT_LABELS


class StatusIndicator(Static):
    """Visual indicator for health/state."""

    state: reactive[str] = reactive("unknown")

    def __init__(self, state: str = "unknown", **kwargs):
        super().__init__(**kwargs)
        self.state = state

    def watch_state(self, state: str):
        """Update indicator when state changes."""
        self.update(self._get_indicator())

    def _get_indicator(self) -> str:
        indicators = {
            "healthy": "[green]●[/green]",
            "partial": "[yellow]●[/yellow]",
            "critical": "[red]●[/red]",
            "connected": "[green]●[/green]",
            "connecting": "[yellow]◐[/yellow]",
            "disconnected": "[dim]○[/dim]",
            "error": "[red]●[/red]",
            "unknown": "[dim]?[/dim]",
        }
        return indicators.get(self.state, "[dim]?[/dim]")

    def render(self) -> str:
        return self._get_indicator()


class EndpointHealthIndicator(Horizontal):
    """Health indicator for a single endpoint."""

    def __init__(self, endpoint_name: str, state: str = "unknown", **kwargs):
        super().__init__(**kwargs)
        self.endpoint_name = endpoint_name
        self._state = state

    def compose(self) -> ComposeResult:
        yield StatusIndicator(self._state, id=f"indicator-{self.endpoint_name}")
        yield Label(self.endpoint_name, classes="endpoint-label")

    def update_state(self, state: str):
        self._state = state
        indicator = self.query_one(StatusIndicator)
        indicator.state = state


class DeviceListItem(Container):
    """A single device entry in the sidebar."""

    class Selected(Message):
        """Device selected message."""
        def __init__(self, device_id: int):
            super().__init__()
            self.device_id = device_id

    class TerminalRequested(Message):
        """Terminal requested for endpoint."""
        def __init__(self, device_id: int, endpoint: str):
            super().__init__()
            self.device_id = device_id
            self.endpoint = endpoint

    device_id: reactive[int] = reactive(0)
    device_name: reactive[str] = reactive("")
    health: reactive[str] = reactive("unknown")

    def __init__(
        self,
        device_id: int,
        device_name: str,
        health: DeviceHealth,
        endpoints: dict,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.device_id = device_id
        self.device_name = device_name
        self.health = health.value
        self._endpoints = endpoints

    def compose(self) -> ComposeResult:
        yield Horizontal(
            StatusIndicator(self.health, classes="device-health"),
            Label(self.device_name, classes="device-name"),
            classes="device-header"
        )
        yield Container(
            *[
                EndpointHealthIndicator(
                    ENDPOINT_LABELS.get(ep, ep),
                    "connected" if port else "disconnected"
                )
                for ep, port in self._endpoints.items()
            ],
            classes="endpoints-list"
        )

    def on_click(self):
        """Handle click to select device."""
        self.post_message(self.Selected(self.device_id))


class LogViewer(Container):
    """Unified log viewer with filtering."""

    class MarkRequested(Message):
        """Mark button pressed."""
        pass

    class ExportRequested(Message):
        """Export button pressed."""
        pass

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._entries = []
        self._device_filter = None
        self._endpoint_filter = "ALL"
        self._search_filter = ""

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Label("Device:", classes="filter-label"),
            Static("All", id="device-filter-display", classes="filter-display"),
            Label("Endpoint:", classes="filter-label"),
            Static("ALL", id="endpoint-filter-display", classes="filter-display"),
            Input(placeholder="Search...", id="search-input", classes="search-input"),
            Button("MARK", id="mark-btn", variant="primary"),
            Button("Export", id="export-btn"),
            classes="log-controls"
        )
        yield DataTable(id="log-table", zebra_stripes=True)

    def on_mount(self):
        """Initialize log table."""
        table = self.query_one("#log-table", DataTable)
        table.add_columns("Time", "Device", "Endpoint", "Dir", "Data")

    def on_button_pressed(self, event: Button.Pressed):
        """Handle button presses."""
        if event.button.id == "mark-btn":
            self.post_message(self.MarkRequested())
        elif event.button.id == "export-btn":
            self.post_message(self.ExportRequested())

    def add_entry(self, timestamp: float, device_id: int, endpoint: str,
                  direction: str, data: str):
        """Add a log entry."""
        table = self.query_one("#log-table", DataTable)
        ts = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S.%f")[:-3]
        table.add_row(ts, f"#{device_id}", endpoint, direction, data[:80])

        # Limit rows
        if table.row_count > 500:
            table.remove_row(0)

    def add_mark(self):
        """Add a mark separator."""
        table = self.query_one("#log-table", DataTable)
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        table.add_row(ts, "", "", "", "─" * 40 + " MARK " + "─" * 40)

    def clear(self):
        """Clear all entries."""
        table = self.query_one("#log-table", DataTable)
        table.clear()


class TestProgressPanel(Container):
    """Shows smoke test progress and results."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._results = []

    def compose(self) -> ComposeResult:
        yield Label("Smoke Test Progress", classes="panel-title")
        yield DataTable(id="test-results", zebra_stripes=True)
        yield Horizontal(
            Label("Status:", classes="status-label"),
            Static("Idle", id="test-status"),
            classes="status-row"
        )

    def on_mount(self):
        """Initialize test results table."""
        table = self.query_one("#test-results", DataTable)
        table.add_columns("Step", "Endpoint", "Command", "Status", "Response")

    def clear_results(self):
        """Clear test results."""
        table = self.query_one("#test-results", DataTable)
        table.clear()

    def add_step_result(self, step_num: int, endpoint: str, command: str,
                        passed: bool, response: str):
        """Add a step result."""
        table = self.query_one("#test-results", DataTable)
        status = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
        table.add_row(str(step_num), endpoint, command, status, response[:40])

    def set_status(self, status: str, running: bool = False):
        """Set test status."""
        status_widget = self.query_one("#test-status", Static)
        if running:
            status_widget.update(f"[yellow]Running: {status}[/yellow]")
        else:
            status_widget.update(status)


class CommandButton(Button):
    """A button that sends a specific command."""

    class CommandRequested(Message):
        """Command button pressed."""
        def __init__(self, command: str, endpoint: str):
            super().__init__()
            self.command = command
            self.endpoint = endpoint

    def __init__(self, label: str, command: str, endpoint: str = "CDC2",
                 variant: str = "default", **kwargs):
        super().__init__(label, variant=variant, **kwargs)
        self._command = command
        self._endpoint = endpoint

    def on_click(self):
        """Handle click."""
        self.post_message(self.CommandRequested(self._command, self._endpoint))


class ConfigField(Horizontal):
    """A labeled input field for configuration values."""

    class ValueChanged(Message):
        """Value changed in field."""
        def __init__(self, field_name: str, value: str):
            super().__init__()
            self.field_name = field_name
            self.value = value

    def __init__(self, label: str, field_name: str, default: str = "",
                 placeholder: str = "", **kwargs):
        super().__init__(**kwargs)
        self._label = label
        self._field_name = field_name
        self._default = default
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        yield Label(f"{self._label}:", classes="config-label")
        yield Input(
            value=self._default,
            placeholder=self._placeholder,
            id=f"field-{self._field_name}",
            classes="config-input"
        )

    def on_input_changed(self, event: Input.Changed):
        """Handle input change."""
        if event.input.id == f"field-{self._field_name}":
            self.post_message(self.ValueChanged(self._field_name, event.value))

    def get_value(self) -> str:
        """Get current value."""
        input_widget = self.query_one(Input)
        return input_widget.value

    def set_value(self, value: str):
        """Set value."""
        input_widget = self.query_one(Input)
        input_widget.value = value

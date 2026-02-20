#!/usr/bin/env python3
"""
CatSniffer TUI Testbench - Main Entry Point

Version-tolerant Textual shell with discovery, hotplug, and per-device views.
"""
import asyncio
import os
import traceback
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Button, Checkbox, DataTable, Footer, Input, Label, Static
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from rich.markup import escape

from .discovery import DeviceIdentity, discover_devices
from .device import CatSnifferDevice
from .hotplug import HotplugWatcher, create_hotplug_watcher
from .logging import log_manager
from .testbench import SmokeTestRunner


class CatSnifferTestbenchApp(App):
    """Main TUI application for CatSniffer testbench."""

    CSS = """
    App {
        layout: vertical;
    }

    #title {
        height: 1;
        content-align: left middle;
        padding: 0 1;
        background: #1e2a36;
        color: white;
        text-style: bold;
    }

    #tabs {
        height: auto;
        padding: 0 1;
        background: #1b1f24;
    }

    #tabs Button {
        margin-right: 1;
    }

    .tab-active {
        background: #0d6eb8;
        color: white;
        text-style: bold;
    }

    .tab-inactive {
        background: #1b1f24;
        color: #c7c7c7;
    }

    #main-content {
        height: 1fr;
        layout: vertical;
    }

    #all-pane {
        height: 1fr;
        layout: vertical;
    }

    #devices-table {
        height: 1fr;
    }

    #fleet-actions {
        height: auto;
        padding: 1;
        background: #1e2a36;
    }

    .action-group {
        height: auto;
        margin: 0 0 1 0;
    }

    .action-label {
        width: auto;
        margin-right: 1;
    }

    .action-group Button {
        width: auto;
        margin-right: 1;
    }

    .device-pane {
        height: 1fr;
        layout: vertical;
        padding: 0 1;
    }

    #all-io-pane {
        height: 1fr;
        layout: horizontal;
        padding: 0 1;
    }

    .io-column {
        width: 1fr;
        height: 1fr;
        layout: vertical;
        padding: 0 1 0 0;
    }

    .panel {
        border: solid #2c3e50;
        padding: 0 1;
        margin: 0 0 0 0;
    }

    .quick-panel {
        height: auto;
        max-height: 8;
        margin-bottom: 1;
    }

    .terminal-panel {
        border: solid #3d566e;
        padding: 0 1;
        margin: 0 1 0 0;
        width: 1fr;
        height: 1fr;
        layout: vertical;
    }

    .terminal-log-scroll {
        height: 1fr;
        border: solid #2c3e50;
        margin: 0 0 0 0;
    }

    .terminal-log {
        width: 100%;
        height: auto;
        padding: 0 1;
    }

    .button-row {
        height: auto;
        margin: 0;
    }

    .button-row Button {
        min-width: 12;
        color: white;
        text-style: bold;
        content-align: center middle;
        margin-right: 1;
    }

    .quick-panel .button-row Button {
        min-width: 1;
        width: auto;
        margin-right: 1;
    }

    .term-input-row {
        height: auto;
    }

    .term-input-row Input {
        width: 1fr;
        margin-right: 1;
    }

    .term-input-row Button {
        width: auto;
        min-width: 0;
        padding: 0;
        text-style: none;
    }

    .term-header-row {
        height: auto;
        margin-bottom: 0;
    }

    .term-title {
        width: 1fr;
    }

    .term-clear-btn {
        width: auto;
        min-width: 0;
        padding: 0;
        text-style: none;
    }

    .term-mode-btn {
        width: auto;
        min-width: 0;
        padding: 0;
        text-style: none;
        margin-right: 1;
    }

    .target-checkbox {
        margin-right: 1;
    }

    .flex-spacer {
        width: 1fr;
    }

    .terminal-grid {
        layout: horizontal;
        height: 1fr;
        margin-top: 0;
    }

    #status-line {
        height: 1;
        content-align: left middle;
        padding: 0 1;
        background: #243240;
        color: white;
    }

    .device-summary {
        height: auto;
        margin: 0 0 1 0;
        color: #8fb1d1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "rescan", "Rescan"),
        Binding("0", "tab_all", "All Devices"),
        Binding("5", "tab_all_io", "All Devices I/O"),
        Binding("6", "tab_all_io", "All Devices I/O"),
        Binding("1", "tab_device_1", "Device 1"),
        Binding("2", "tab_device_2", "Device 2"),
        Binding("3", "tab_device_3", "Device 3"),
        Binding("4", "tab_device_4", "Device 4"),
        Binding("ctrl+1", "focus_term_1", "Focus CC1352"),
        Binding("ctrl+2", "focus_term_2", "Focus LoRa"),
        Binding("ctrl+3", "focus_term_3", "Focus Shell"),
    ]
    ENDPOINT_DISPLAY = {
        "CDC0": "CC1352",
        "CDC1": "LoRa",
        "CDC2": "Shell",
    }
    DEVICE_COLORS = {
        1: "#5cc8ff",
        2: "#8bd450",
        3: "#f4b942",
        4: "#ff7aa2",
    }

    def __init__(self):
        super().__init__()
        self.devices: Dict[int, CatSnifferDevice] = {}
        self.selected_tab = "all"

        self._identity_map: Dict[DeviceIdentity, int] = {}
        self._miss_count: Dict[DeviceIdentity, int] = {}
        self._smoke_runners: Dict[int, SmokeTestRunner] = {}

        self._hotplug_watcher: Optional[HotplugWatcher] = None
        self._rescan_pending = False
        self._rescan_lock = asyncio.Lock()
        self._poll_timer = None
        self._device_view_state: Dict[int, str] = {}
        self._all_table_state: str = ""
        self._terminal_buffers: Dict[int, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
        self._pending_shell_echo: Dict[int, List[str]] = defaultdict(list)
        self._terminal_mode: Dict[int, Dict[str, str]] = defaultdict(lambda: defaultdict(lambda: "text"))
        self._fleet_shell_buffer: List[str] = []
        self._fleet_shell_mode: str = "text"
        self._fleet_lora_buffer: List[str] = []
        self._fleet_lora_mode: str = "text"
        self._session_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    def compose(self) -> ComposeResult:
        yield Label("CatSniffer TUI Testbench", id="title")

        with Horizontal(id="tabs"):
            yield Button("All Devices", id="tab-all")
            yield Button("All Devices I/O", id="tab-io-all")
            yield Button("Device 1", id="tab-device-1")
            yield Button("Device 2", id="tab-device-2")
            yield Button("Device 3", id="tab-device-3")
            yield Button("Device 4", id="tab-device-4")

        with Vertical(id="main-content"):
            with Vertical(id="all-pane"):
                yield DataTable(id="devices-table")
                with Vertical(id="fleet-actions"):
                    with Horizontal(classes="action-group"):
                        yield Label("Fleet Band Actions:", classes="action-label")
                        yield Button("All -> 2.4GHz", id="fleet-band1")
                        yield Button("All -> Sub-GHz", id="fleet-band2")
                        yield Button("All -> LoRa", id="fleet-band3")
                    with Horizontal(classes="action-group"):
                        yield Label("Fleet Quick Actions:", classes="action-label")
                        yield Button("Status", id="fleet-status")
                        yield Button("LoRa Mode", id="fleet-lora-mode-shell")
                        yield Button("FSK Mode", id="fleet-fsk-mode-shell")
                        yield Button("Stream", id="fleet-stream")
                        yield Button("Command", id="fleet-command")
                        yield Button("Run Smoke Test", id="fleet-smoke", variant="warning")
                        yield Button("Save Logs", id="fleet-save-logs")
                    with Horizontal(classes="action-group"):
                        yield Label("Tip:", classes="action-label")
                        yield Static("Use tab 5 for all CDC2 shell and tab 6 for all CDC1 LoRa")

            for i in range(1, 5):
                yield ScrollableContainer(id=f"device-{i}-pane", classes="device-pane")
            with Horizontal(id="all-io-pane"):
                with Vertical(id="all-shell-pane", classes="io-column"):
                    yield Static("Broadcast shell (CDC2) to all connected devices", classes="device-summary")
                    yield Container(
                        Horizontal(
                            Static("All Devices Shell Terminal (CDC2)", classes="term-title"),
                            Button("ASCII", id="fleet-shell-mode", classes="term-mode-btn"),
                            Button("Clear", id="fleet-shell-clear", classes="term-clear-btn"),
                            classes="term-header-row",
                        ),
                        ScrollableContainer(
                            Static("(no data yet)", id="fleet-shell-log", classes="terminal-log"),
                            id="fleet-shell-log-scroll",
                            classes="terminal-log-scroll",
                        ),
                        Horizontal(
                            Input(placeholder="Broadcast command to all CDC2...", id="fleet-shell-input"),
                            Button("Send", id="fleet-shell-send"),
                            classes="term-input-row",
                        ),
                        classes="terminal-panel",
                    )
                with Vertical(id="all-lora-pane", classes="io-column"):
                    yield Static("Broadcast LoRa endpoint (CDC1) to all connected devices", classes="device-summary")
                    yield Container(
                        Horizontal(
                            Static("All Devices LoRa Terminal (CDC1)", classes="term-title"),
                            Checkbox("D1", value=True, id="fleet-lora-dev-1", classes="target-checkbox"),
                            Checkbox("D2", value=True, id="fleet-lora-dev-2", classes="target-checkbox"),
                            Checkbox("D3", value=True, id="fleet-lora-dev-3", classes="target-checkbox"),
                            Checkbox("D4", value=True, id="fleet-lora-dev-4", classes="target-checkbox"),
                            Button("ASCII", id="fleet-lora-mode", classes="term-mode-btn"),
                            Button("Clear", id="fleet-lora-clear", classes="term-clear-btn"),
                            classes="term-header-row",
                        ),
                        ScrollableContainer(
                            Static("(no data yet)", id="fleet-lora-log", classes="terminal-log"),
                            id="fleet-lora-log-scroll",
                            classes="terminal-log-scroll",
                        ),
                        Horizontal(
                            Input(placeholder="Broadcast payload to all CDC1...", id="fleet-lora-input"),
                            Button("Send", id="fleet-lora-send"),
                            classes="term-input-row",
                        ),
                        classes="terminal-panel",
                    )

        yield Static("Starting...", id="status-line")
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#devices-table", DataTable)
        try:
            table.add_columns("Slot", "Serial", "CDC0", "CDC1", "CDC2", "Health", "Status")
        except Exception:
            pass

        self._update_all_tab()
        for device_id in range(1, 5):
            self._update_device_pane(device_id)

        self._switch_tab("all")
        self._set_status("UI ready | Press R to rescan")
        self._poll_timer = self.set_interval(1.0, self._schedule_rescan)
        self.set_timer(0.05, self._start_async_init)

    def _start_async_init(self) -> None:
        asyncio.create_task(self._initialize_background())

    async def _initialize_background(self) -> None:
        try:
            await self._rescan_devices()
            self._hotplug_watcher = create_hotplug_watcher(self._on_usb_event)
            await self._hotplug_watcher.start()
            self._set_status(f"Ready | Devices: {len(self.devices)}")
        except Exception as error:
            self._log_error("Background init failed", error)
            self._set_status(f"Init error: {error}")

    async def on_unmount(self) -> None:
        if self._poll_timer:
            self._poll_timer.stop()
            self._poll_timer = None
        if self._hotplug_watcher:
            try:
                await self._hotplug_watcher.stop()
            except BaseException:
                pass
        if self.devices:
            tasks = [device.disconnect_all() for device in self.devices.values()]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    self._log_error("Device disconnect error during shutdown", result)

    def _schedule_rescan(self) -> None:
        if not self._rescan_pending:
            self._rescan_pending = True
            asyncio.create_task(self._debounced_rescan())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""

        if button_id == "tab-all":
            self._switch_tab("all")
            return
        if button_id == "tab-io-all":
            self._switch_tab("io-all")
            return
        if button_id.startswith("tab-device-"):
            self._switch_tab(button_id.replace("tab-", ""))
            return

        if button_id == "fleet-shell-send":
            try:
                input_widget = self.query_one("#fleet-shell-input", Input)
                text = input_widget.value
                input_widget.value = ""
                asyncio.create_task(self._send_fleet_shell_line(text))
            except Exception as error:
                self._set_status(f"Fleet shell send error: {error}")
            return

        if button_id == "fleet-shell-clear":
            self._fleet_shell_buffer.clear()
            self._append_fleet_shell_line("(cleared)")
            self._set_status("Cleared All Devices Shell log")
            return

        if button_id == "fleet-shell-mode":
            self._fleet_shell_mode = "hex" if self._fleet_shell_mode == "text" else "text"
            try:
                mode_btn = self.query_one("#fleet-shell-mode", Button)
                mode_btn.label = "HEX" if self._fleet_shell_mode == "hex" else "ASCII"
            except Exception:
                pass
            self._set_status(f"All Devices Shell mode: {self._fleet_shell_mode.upper()}")
            return

        if button_id == "fleet-lora-send":
            try:
                input_widget = self.query_one("#fleet-lora-input", Input)
                text = input_widget.value
                input_widget.value = ""
                asyncio.create_task(self._send_fleet_lora_line(text))
            except Exception as error:
                self._set_status(f"Fleet LoRa send error: {error}")
            return

        if button_id == "fleet-lora-clear":
            self._fleet_lora_buffer.clear()
            self._append_fleet_lora_line("(cleared)")
            self._set_status("Cleared All Devices LoRa log")
            return

        if button_id == "fleet-lora-mode":
            self._fleet_lora_mode = "hex" if self._fleet_lora_mode == "text" else "text"
            try:
                mode_btn = self.query_one("#fleet-lora-mode", Button)
                mode_btn.label = "HEX" if self._fleet_lora_mode == "hex" else "ASCII"
            except Exception:
                pass
            self._set_status(f"All Devices LoRa mode: {self._fleet_lora_mode.upper()}")
            return

        # Fleet actions
        if button_id == "fleet-band1":
            asyncio.create_task(self._fleet_action("band1"))
            return
        if button_id == "fleet-band2":
            asyncio.create_task(self._fleet_action("band2"))
            return
        if button_id == "fleet-band3":
            asyncio.create_task(self._fleet_action("band3"))
            return
        if button_id == "fleet-status":
            asyncio.create_task(self._fleet_action("status"))
            return
        if button_id == "fleet-lora-mode-shell":
            asyncio.create_task(self._fleet_action("modulation lora"))
            return
        if button_id == "fleet-fsk-mode-shell":
            asyncio.create_task(self._fleet_action("modulation fsk"))
            return
        if button_id == "fleet-stream":
            asyncio.create_task(self._fleet_action("lora_mode stream"))
            return
        if button_id == "fleet-command":
            asyncio.create_task(self._fleet_action("lora_mode command"))
            return
        if button_id == "fleet-smoke":
            asyncio.create_task(self._fleet_smoke())
            return
        if button_id == "fleet-save-logs":
            self._save_all_terminal_logs()
            return

        if button_id.startswith("term-send-"):
            # term-send-<device_id>-CDCx
            try:
                _, _, device_s, endpoint = button_id.split("-", 3)
                device_id = int(device_s)
                input_widget = self.query_one(f"#term-input-{device_id}-{endpoint}", Input)
                text = input_widget.value
                input_widget.value = ""
                asyncio.create_task(self._send_terminal_line(device_id, endpoint, text))
            except Exception as error:
                self._set_status(f"Terminal send parse error: {error}")
            return

        if button_id.startswith("term-clear-"):
            # term-clear-<device_id>-CDCx
            try:
                _, _, device_s, endpoint = button_id.split("-", 3)
                device_id = int(device_s)
                self._terminal_buffers[device_id][endpoint].clear()
                self._append_terminal_line(device_id, endpoint, "(cleared)")
                self._set_status(f"Cleared {self.ENDPOINT_DISPLAY.get(endpoint, endpoint)} log on #{device_id}")
            except Exception as error:
                self._set_status(f"Terminal clear parse error: {error}")
            return

        if button_id.startswith("term-mode-"):
            # term-mode-<device_id>-CDCx
            try:
                _, _, device_s, endpoint = button_id.split("-", 3)
                device_id = int(device_s)
                current = self._terminal_mode[device_id][endpoint]
                self._terminal_mode[device_id][endpoint] = "hex" if current == "text" else "text"
                mode_btn = self.query_one(f"#term-mode-{device_id}-{endpoint}", Button)
                mode_btn.label = "HEX" if self._terminal_mode[device_id][endpoint] == "hex" else "ASCII"
                self._set_status(
                    f"{self.ENDPOINT_DISPLAY.get(endpoint, endpoint)} mode: {self._terminal_mode[device_id][endpoint].upper()}"
                )
            except Exception as error:
                self._set_status(f"Terminal mode parse error: {error}")
            return

        # Device quick actions
        for device_id in range(1, 5):
            prefix = f"dev{device_id}-"
            if button_id.startswith(prefix):
                if device_id not in self.devices:
                    self._set_status(f"No device in slot {device_id}")
                    return
                device = self.devices[device_id]
                action = button_id[len(prefix):]

                if action == "status":
                    asyncio.create_task(self._execute_command(device, "status"))
                elif action == "band1":
                    asyncio.create_task(self._execute_command(device, "band1"))
                elif action == "band2":
                    asyncio.create_task(self._execute_command(device, "band2"))
                elif action == "band3":
                    asyncio.create_task(self._execute_command(device, "band3"))
                elif action == "lora":
                    asyncio.create_task(self._execute_command(device, "modulation lora"))
                elif action == "fsk":
                    asyncio.create_task(self._execute_command(device, "modulation fsk"))
                elif action == "stream":
                    asyncio.create_task(self._execute_command(device, "lora_mode stream"))
                elif action == "command":
                    asyncio.create_task(self._execute_command(device, "lora_mode command"))
                elif action == "smoke" and device_id in self._smoke_runners:
                    asyncio.create_task(self._smoke_runners[device_id].run_single(device))
                elif action == "save-logs":
                    self._save_terminal_logs(device_id)
                return

    def on_input_submitted(self, event: Input.Submitted) -> None:
        input_id = event.input.id or ""
        if input_id == "fleet-shell-input":
            text = event.input.value
            event.input.value = ""
            asyncio.create_task(self._send_fleet_shell_line(text))
            return
        if input_id == "fleet-lora-input":
            text = event.input.value
            event.input.value = ""
            asyncio.create_task(self._send_fleet_lora_line(text))
            return
        if not input_id.startswith("term-input-"):
            return
        # term-input-<device_id>-CDCx
        try:
            _, _, device_s, endpoint = input_id.split("-", 3)
            device_id = int(device_s)
            text = event.input.value
            event.input.value = ""
            asyncio.create_task(self._send_terminal_line(device_id, endpoint, text))
        except Exception as error:
            self._set_status(f"Terminal input parse error: {error}")

    def action_tab_all(self) -> None:
        self._switch_tab("all")

    def action_tab_all_io(self) -> None:
        self._switch_tab("io-all")

    def action_tab_all_lora(self) -> None:
        self._switch_tab("io-all")

    def action_tab_all_shell(self) -> None:
        self._switch_tab("io-all")

    def action_tab_device_1(self) -> None:
        self._switch_tab("device-1")

    def action_tab_device_2(self) -> None:
        self._switch_tab("device-2")

    def action_tab_device_3(self) -> None:
        self._switch_tab("device-3")

    def action_tab_device_4(self) -> None:
        self._switch_tab("device-4")

    def action_focus_term_1(self) -> None:
        self._focus_terminal_input("CDC0")

    def action_focus_term_2(self) -> None:
        self._focus_terminal_input("CDC1")

    def action_focus_term_3(self) -> None:
        self._focus_terminal_input("CDC2")

    def _switch_tab(self, tab_id: str) -> None:
        self.selected_tab = tab_id

        all_pane = self.query_one("#all-pane", Vertical)
        all_pane.display = (tab_id == "all")
        io_pane = self.query_one("#all-io-pane", Horizontal)
        io_pane.display = (tab_id == "io-all")
        shell_pane = self.query_one("#all-shell-pane", Vertical)
        shell_pane.display = (tab_id == "io-all")
        lora_pane = self.query_one("#all-lora-pane", Vertical)
        lora_pane.display = (tab_id == "io-all")

        for device_id in range(1, 5):
            pane = self.query_one(f"#device-{device_id}-pane", ScrollableContainer)
            pane.display = (tab_id == f"device-{device_id}")

        self._update_tab_styles(tab_id)
        self._set_status(f"Selected: {tab_id} | Devices: {len(self.devices)}")

    def _update_tab_styles(self, tab_id: str) -> None:
        tab_map = {
            "tab-all": "all",
            "tab-io-all": "io-all",
            "tab-device-1": "device-1",
            "tab-device-2": "device-2",
            "tab-device-3": "device-3",
            "tab-device-4": "device-4",
        }
        for button_id, mapped_tab in tab_map.items():
            try:
                button = self.query_one(f"#{button_id}", Button)
            except Exception:
                continue
            button.remove_class("tab-active")
            button.remove_class("tab-inactive")
            if mapped_tab == tab_id:
                button.add_class("tab-active")
            else:
                button.add_class("tab-inactive")

    def action_rescan(self) -> None:
        self._set_status("Manual rescan requested")
        asyncio.create_task(self._rescan_devices())

    def _on_usb_event(self) -> None:
        if not self._rescan_pending:
            self._rescan_pending = True
            asyncio.create_task(self._debounced_rescan())

    async def _debounced_rescan(self) -> None:
        await asyncio.sleep(0.3)
        self._rescan_pending = False
        await self._rescan_devices()

    async def _rescan_devices(self) -> None:
        async with self._rescan_lock:
            try:
                discovered = discover_devices()
                current_identities = set()

                for disc in discovered:
                    current_identities.add(disc.identity)

                    if disc.identity not in self._identity_map:
                        used_slots = set(self._identity_map.values())
                        available_slot = next((slot for slot in range(1, 5) if slot not in used_slots), None)
                        if available_slot is None:
                            continue

                        device_id = available_slot
                        self._identity_map[disc.identity] = device_id
                        device = CatSnifferDevice(disc, device_id, log_manager)
                        self.devices[device_id] = device

                        runner = SmokeTestRunner()
                        self._smoke_runners[device_id] = runner

                        await device.connect_all()
                        self._wire_terminal_callbacks(device)
                    else:
                        self._miss_count[disc.identity] = 0
                        device_id = self._identity_map[disc.identity]
                        device = self.devices.get(device_id)
                        if device:
                            # Keep callbacks/live readers healthy across rescan cycles.
                            self._wire_terminal_callbacks(device)
                            await device.connect_all()

                for identity, device_id in list(self._identity_map.items()):
                    if identity not in current_identities:
                        self._miss_count[identity] = self._miss_count.get(identity, 0) + 1
                        if self._miss_count[identity] >= 2:
                            if device_id in self.devices:
                                await self.devices[device_id].disconnect_all()
                                log_manager.remove_device(device_id)
                                del self.devices[device_id]
                            self._smoke_runners.pop(device_id, None)
                            del self._identity_map[identity]
                            del self._miss_count[identity]

                self._update_all_tab()
                if self.selected_tab.startswith("device-"):
                    try:
                        active_device = int(self.selected_tab.split("-")[1])
                        self._update_device_pane(active_device)
                    except Exception:
                        pass

                self._set_status(f"Rescanned | Devices: {len(self.devices)}")

            except Exception as error:
                self._log_error("Rescan failed", error)
                self._set_status(f"Rescan error: {error}")
            finally:
                self._rescan_pending = False

    def _update_all_tab(self) -> None:
        try:
            snapshot_rows = []
            for slot in range(1, 5):
                if slot in self.devices:
                    device = self.devices[slot]
                    snapshot_rows.append(
                        (
                            slot,
                            device.identity.serial_number[:12],
                            bool(device.bridge),
                            bool(device.lora),
                            bool(device.shell),
                            device.health.value,
                            device.smoke_test_running,
                        )
                    )
                else:
                    snapshot_rows.append((slot, "empty"))
            snapshot = repr(snapshot_rows)
            if snapshot == self._all_table_state:
                return
            self._all_table_state = snapshot

            table = self.query_one("#devices-table", DataTable)
            table.clear()

            for slot in range(1, 5):
                if slot in self.devices:
                    device = self.devices[slot]
                    cdc0 = "OK" if device.bridge else "--"
                    cdc1 = "OK" if device.lora else "--"
                    cdc2 = "OK" if device.shell else "--"
                    health = device.health.value
                    status = "Testing" if device.smoke_test_running else "Idle"
                    serial = device.identity.serial_number[:12]
                    table.add_row(f"#{slot}", serial, cdc0, cdc1, cdc2, health, status)
                else:
                    table.add_row(f"#{slot}", "Empty", "--", "--", "--", "--", "--")
        except Exception as error:
            self._log_error("Table update failed", error)

    def _update_device_pane(self, device_id: int) -> None:
        try:
            snapshot = self._device_snapshot(device_id)
            if self._device_view_state.get(device_id) == snapshot:
                return
            self._device_view_state[device_id] = snapshot

            pane = self.query_one(f"#device-{device_id}-pane", ScrollableContainer)
            pane.remove_children()

            if device_id not in self.devices:
                pane.mount(Static(f"No device in slot {device_id}"))
                return

            device = self.devices[device_id]
            pane.mount(
                Static(
                    f"CatSniffer #{device_id} | Serial: {device.identity.serial_number[:12]} | Health: {device.health.value}"
                )
            )
            pane.mount(
                Static(
                    " | ".join(
                        [
                            f"CC1352: {device.bridge.port if device.bridge else '--'}",
                            f"LoRa: {device.lora.port if device.lora else '--'}",
                            f"Shell: {device.shell.port if device.shell else '--'}",
                        ]
                    ),
                    classes="device-summary",
                )
            )

            actions = Container(
                Static("Quick Actions"),
                Horizontal(
                    Button("Status", id=f"dev{device_id}-status", variant="primary"),
                    Button("band1", id=f"dev{device_id}-band1"),
                    Button("band2", id=f"dev{device_id}-band2"),
                    Button("band3", id=f"dev{device_id}-band3"),
                    Button("LoRa Mode", id=f"dev{device_id}-lora"),
                    Button("FSK Mode", id=f"dev{device_id}-fsk"),
                    Button("Stream", id=f"dev{device_id}-stream"),
                    Button("Command", id=f"dev{device_id}-command"),
                    Button("Run Smoke Test", id=f"dev{device_id}-smoke", variant="warning"),
                    Static("", classes="flex-spacer"),
                    Button("Save Logs", id=f"dev{device_id}-save-logs"),
                    classes="button-row",
                ),
                Static(f"Smoke: {'Running...' if device.smoke_test_running else 'Idle'} | r=Rescan"),
                classes="panel quick-panel",
            )

            term_cdc0 = self._terminal_widget(device_id, "CDC0", bool(device.bridge))
            term_cdc1 = self._terminal_widget(device_id, "CDC1", bool(device.lora))
            term_cdc2 = self._terminal_widget(device_id, "CDC2", bool(device.shell))

            terminal_row = Horizontal(term_cdc0, term_cdc1, term_cdc2, classes="terminal-grid")
            pane.mount(actions, terminal_row)

        except Exception as error:
            self._log_error(f"Device pane update failed ({device_id})", error)

    def _terminal_widget(self, device_id: int, endpoint: str, available: bool) -> Container:
        log_text = "\n".join(self._terminal_buffers[device_id][endpoint]) or "(no data yet)"
        endpoint_name = self.ENDPOINT_DISPLAY.get(endpoint, endpoint)
        mode_label = "HEX" if self._terminal_mode[device_id][endpoint] == "hex" else "ASCII"
        return Container(
            Horizontal(
                Static(
                    f"{endpoint_name} Terminal {'(connected)' if available else '(not available)'}",
                    classes="term-title",
                ),
                Button(mode_label, id=f"term-mode-{device_id}-{endpoint}", disabled=not available, classes="term-mode-btn"),
                Button(
                    "Clear",
                    id=f"term-clear-{device_id}-{endpoint}",
                    disabled=not available,
                    classes="term-clear-btn",
                ),
                classes="term-header-row",
            ),
            ScrollableContainer(
                Static(log_text, id=f"term-log-{device_id}-{endpoint}", classes="terminal-log"),
                id=f"term-log-scroll-{device_id}-{endpoint}",
                classes="terminal-log-scroll",
            ),
            Horizontal(
                Input(placeholder=f"{endpoint_name} input...", id=f"term-input-{device_id}-{endpoint}"),
                Button("Send", id=f"term-send-{device_id}-{endpoint}", disabled=not available),
                classes="term-input-row",
            ),
            classes="terminal-panel",
        )

    def _device_snapshot(self, device_id: int) -> str:
        if device_id not in self.devices:
            return f"{device_id}:empty"
        device = self.devices[device_id]
        return repr(
            (
                device_id,
                device.identity.serial_number[:12],
                device.health.value,
                device.bridge.port if device.bridge else None,
                device.lora.port if device.lora else None,
                device.shell.port if device.shell else None,
                device.smoke_test_running,
            )
        )

    async def _execute_command(self, device: CatSnifferDevice, command: str) -> None:
        self._set_status(f"Running on #{device.device_id}: {command}")
        self._append_terminal_line(device.device_id, "CDC2", f"> {command}")
        self._append_fleet_shell_line(f"[#{device.device_id}] > {command}", device.device_id)
        self._pending_shell_echo[device.device_id].append(command)
        result = await device.send_shell_command(command)
        # Avoid full device-pane rebuild on every command press; keep terminal UX stable.
        self._all_table_state = ""
        self._update_all_tab()
        if result.passed:
            self._set_status(f"OK #{device.device_id}: {command}")
        else:
            detail = result.error or result.response or result.status.value
            self._set_status(f"FAIL #{device.device_id}: {command} | {detail}")

    def _wire_terminal_callbacks(self, device: CatSnifferDevice) -> None:
        def make_cb(endpoint_label: str):
            def _cb(data: str, parsed: Dict) -> None:
                incoming_lines = data.splitlines() or [data]

                if endpoint_label == "CDC2":
                    pending = self._pending_shell_echo[device.device_id]
                    for raw in incoming_lines:
                        line_raw = raw.strip()
                        if not line_raw:
                            continue

                        line = line_raw.lower()
                        if pending:
                            cmd = pending[0].strip()
                            cmd_l = cmd.lower()
                            # Some firmware echoes command inline with response:
                            # e.g. "band12.4GHz Band"
                            if line.startswith(cmd_l):
                                self._append_terminal_line(device.device_id, endpoint_label, f"< (echo) {cmd}")
                                self._append_fleet_shell_line(f"[#{device.device_id}] < (echo) {cmd}", device.device_id)
                                pending.pop(0)
                                remainder = line_raw[len(cmd):].strip()
                                if remainder:
                                    self._append_terminal_line(device.device_id, endpoint_label, f"< {remainder}")
                                    self._append_fleet_shell_line(f"[#{device.device_id}] < {remainder}", device.device_id)
                                continue

                        self._append_terminal_line(device.device_id, endpoint_label, f"< {line_raw}")
                        self._append_fleet_shell_line(f"[#{device.device_id}] < {line_raw}", device.device_id)
                    return

                for raw in incoming_lines:
                    line_raw = raw.rstrip("\r")
                    if line_raw:
                        self._append_terminal_line(device.device_id, endpoint_label, f"< {line_raw}")
                        if endpoint_label == "CDC1":
                            self._append_fleet_lora_line(f"[#{device.device_id}] < {line_raw}", device.device_id)
            return _cb

        if device.bridge:
            device.bridge.set_callbacks(on_data_received=make_cb("CDC0"))
        if device.lora:
            device.lora.set_callbacks(on_data_received=make_cb("CDC1"))
        if device.shell:
            device.shell.set_callbacks(on_data_received=make_cb("CDC2"))

    def _append_terminal_line(self, device_id: int, endpoint: str, line: str) -> None:
        buf = self._terminal_buffers[device_id][endpoint]
        buf.append(line)
        if len(buf) > 200:
            del buf[: len(buf) - 200]
        try:
            widget = self.query_one(f"#term-log-{device_id}-{endpoint}", Static)
            widget.update("\n".join(buf))
            scroller = self.query_one(f"#term-log-scroll-{device_id}-{endpoint}", ScrollableContainer)
            scroller.scroll_end(animate=False)
        except Exception:
            pass

    async def _fleet_action(self, command: str) -> None:
        tasks = [self._execute_command(device, command) for device in self.devices.values()]
        if tasks:
            await asyncio.gather(*tasks)

    async def _fleet_smoke(self) -> None:
        tasks = []
        for device_id, device in self.devices.items():
            runner = self._smoke_runners.get(device_id)
            if runner:
                tasks.append(runner.run_single(device))
        if tasks:
            await asyncio.gather(*tasks)
            self._all_table_state = ""
            self._device_view_state.clear()
            self._update_all_tab()
            for device_id in range(1, 5):
                self._update_device_pane(device_id)

    async def _send_terminal_line(self, device_id: int, endpoint: str, text: str) -> None:
        device = self.devices.get(device_id)
        if not device:
            self._set_status(f"No device in slot {device_id}")
            return

        handler = None
        if endpoint == "CDC0":
            handler = device.bridge
        elif endpoint == "CDC1":
            handler = device.lora
        elif endpoint == "CDC2":
            handler = device.shell

        if not handler:
            self._set_status(f"{endpoint} not available on #{device_id}")
            return

        payload = text.strip()
        if not payload:
            return

        # Prefix TX and RX in the log so shell echo is clearly distinguishable.
        self._append_terminal_line(device_id, endpoint, f"> {payload}")
        if endpoint == "CDC2":
            self._pending_shell_echo[device_id].append(payload)
            self._append_fleet_shell_line(f"[#{device_id}] > {payload}", device_id)
        elif endpoint == "CDC1":
            self._append_fleet_lora_line(f"[#{device_id}] > {payload}", device_id)
        mode = self._terminal_mode[device_id][endpoint]
        if mode == "hex":
            try:
                raw = bytes.fromhex(payload.replace(" ", ""))
            except ValueError:
                self._set_status(f"Invalid HEX input for {self.ENDPOINT_DISPLAY.get(endpoint, endpoint)}")
                return
            ok = await handler.send_raw(raw)
        else:
            ok = await handler.send_line(payload)
        if endpoint == "CDC2":
            self._append_terminal_line(device_id, endpoint, "")
        if ok:
            self._set_status(f"Sent to #{device_id} {self.ENDPOINT_DISPLAY.get(endpoint, endpoint)}")
        else:
            self._set_status(f"Send failed on #{device_id} {self.ENDPOINT_DISPLAY.get(endpoint, endpoint)}")

    async def _send_fleet_shell_line(self, text: str) -> None:
        payload = text.strip()
        if not payload:
            return

        targets = [(device_id, device.shell) for device_id, device in sorted(self.devices.items()) if device.shell]
        if not targets:
            self._set_status("No Shell (CDC2) endpoints available")
            return

        self._append_fleet_shell_line(f"[ALL] > {payload}")
        sent_count = 0

        if self._fleet_shell_mode == "hex":
            try:
                raw = bytes.fromhex(payload.replace(" ", ""))
            except ValueError:
                self._set_status("Invalid HEX input for All Devices Shell")
                return
            for device_id, handler in targets:
                if handler and await handler.send_raw(raw):
                    self._pending_shell_echo[device_id].append(payload)
                    sent_count += 1
                else:
                    self._append_fleet_shell_line(f"[#{device_id}] ! send failed", device_id)
        else:
            for device_id, handler in targets:
                if handler and await handler.send_line(payload):
                    self._pending_shell_echo[device_id].append(payload)
                    sent_count += 1
                else:
                    self._append_fleet_shell_line(f"[#{device_id}] ! send failed", device_id)

        self._set_status(f"Broadcast to {sent_count}/{len(targets)} device(s) on CDC2")

    def _append_fleet_shell_line(self, line: str, device_id: Optional[int] = None) -> None:
        styled = escape(line)
        if device_id in self.DEVICE_COLORS:
            styled = f"[{self.DEVICE_COLORS[device_id]}]{styled}[/]"
        self._fleet_shell_buffer.append(styled)
        if len(self._fleet_shell_buffer) > 400:
            del self._fleet_shell_buffer[: len(self._fleet_shell_buffer) - 400]
        try:
            widget = self.query_one("#fleet-shell-log", Static)
            widget.update("\n".join(self._fleet_shell_buffer))
            scroller = self.query_one("#fleet-shell-log-scroll", ScrollableContainer)
            scroller.scroll_end(animate=False)
        except Exception:
            pass

    async def _send_fleet_lora_line(self, text: str) -> None:
        payload = text.strip()
        if not payload:
            return

        selected = self._selected_fleet_lora_targets()
        targets = [
            (device_id, device.lora)
            for device_id, device in sorted(self.devices.items())
            if device_id in selected and device.lora
        ]
        if not selected:
            self._set_status("Select at least one device checkbox (D1..D4) for CDC1 send")
            return
        if not targets:
            self._set_status("No selected LoRa (CDC1) endpoints available")
            return

        self._append_fleet_lora_line(f"[ALL] > {payload}")
        sent_count = 0

        if self._fleet_lora_mode == "hex":
            try:
                raw = bytes.fromhex(payload.replace(" ", ""))
            except ValueError:
                self._set_status("Invalid HEX input for All Devices LoRa")
                return
            for device_id, handler in targets:
                if handler and await handler.send_raw(raw):
                    sent_count += 1
                    self._append_fleet_lora_line(f"[#{device_id}] > {payload}", device_id)
                else:
                    self._append_fleet_lora_line(f"[#{device_id}] ! send failed", device_id)
        else:
            for device_id, handler in targets:
                if handler and await handler.send_line(payload):
                    sent_count += 1
                    self._append_fleet_lora_line(f"[#{device_id}] > {payload}", device_id)
                else:
                    self._append_fleet_lora_line(f"[#{device_id}] ! send failed", device_id)

        self._set_status(f"Broadcast to {sent_count}/{len(targets)} device(s) on CDC1")

    def _selected_fleet_lora_targets(self) -> List[int]:
        selected: List[int] = []
        for device_id in range(1, 5):
            try:
                cb = self.query_one(f"#fleet-lora-dev-{device_id}", Checkbox)
                if cb.value:
                    selected.append(device_id)
            except Exception:
                pass
        return selected

    def _append_fleet_lora_line(self, line: str, device_id: Optional[int] = None) -> None:
        styled = escape(line)
        if device_id in self.DEVICE_COLORS:
            styled = f"[{self.DEVICE_COLORS[device_id]}]{styled}[/]"
        self._fleet_lora_buffer.append(styled)
        if len(self._fleet_lora_buffer) > 400:
            del self._fleet_lora_buffer[: len(self._fleet_lora_buffer) - 400]
        try:
            widget = self.query_one("#fleet-lora-log", Static)
            widget.update("\n".join(self._fleet_lora_buffer))
            scroller = self.query_one("#fleet-lora-log-scroll", ScrollableContainer)
            scroller.scroll_end(animate=False)
        except Exception:
            pass

    def _focus_terminal_input(self, endpoint: str) -> None:
        if not self.selected_tab.startswith("device-"):
            self._set_status("Open a device tab first for terminal focus shortcuts")
            return
        try:
            device_id = int(self.selected_tab.split("-")[1])
            input_widget = self.query_one(f"#term-input-{device_id}-{endpoint}", Input)
            input_widget.focus()
            self._set_status(f"Focused {self.ENDPOINT_DISPLAY.get(endpoint, endpoint)} input on #{device_id}")
        except Exception:
            self._set_status("Terminal input not available")

    def _save_terminal_logs(self, device_id: int) -> None:
        base_dir = os.path.join(os.getcwd(), "logs", "terminal", f"device-{device_id}")
        try:
            os.makedirs(base_dir, exist_ok=True)
            count = 0
            for endpoint in ("CDC0", "CDC1", "CDC2"):
                lines = self._terminal_buffers[device_id][endpoint]
                if not lines:
                    continue
                endpoint_name = self.ENDPOINT_DISPLAY.get(endpoint, endpoint).lower().replace(" ", "-")
                path = os.path.join(base_dir, f"{self._session_stamp}-{endpoint_name}.log")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(lines) + "\n")
                count += 1
            if count:
                self._set_status(f"Saved {count} terminal log(s) to {base_dir}")
            else:
                self._set_status(f"No terminal data to save for device #{device_id}")
        except Exception as error:
            self._set_status(f"Save logs failed: {error}")

    def _save_all_terminal_logs(self) -> None:
        if not self.devices:
            self._set_status("No devices available for log export")
            return
        for device_id in sorted(self.devices):
            self._save_terminal_logs(device_id)
        self._set_status(f"Saved terminal logs for {len(self.devices)} device(s)")

    def _set_status(self, text: str) -> None:
        try:
            self.query_one("#status-line", Static).update(text)
        except Exception:
            pass

    def _log_error(self, prefix: str, error: Exception) -> None:
        message = f"{prefix}: {error}\n{traceback.format_exc()}"
        self.log(message)
        try:
            with open("/tmp/catsniffer_tui_error.log", "a", encoding="utf-8") as fh:
                fh.write(message + "\n")
        except Exception:
            pass


def main() -> None:
    app = CatSnifferTestbenchApp()
    app.run()


if __name__ == "__main__":
    main()

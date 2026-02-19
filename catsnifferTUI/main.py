#!/usr/bin/env python3
"""
CatSniffer TUI Testbench - Main Entry Point

Production-quality multi-device testbench for CatSniffer hardware validation.

Usage:
    python main.py

Requirements:
    textual>=0.47.0
    pyserial>=3.5
    pyusb>=1.2.1
"""
import asyncio
import sys
from datetime import datetime
from typing import Dict, List, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import (
    Header,
    Footer,
    Static,
    Label,
    TabbedContent,
    TabPane,
    Button,
)

from .constants import (
    CATSNIFFER_VID,
    CATSNIFFER_PID,
    HOTPLUG_SCAN_INTERVAL,
    ENDPOINT_BRIDGE,
    ENDPOINT_LORA,
    ENDPOINT_SHELL,
)
from .discovery import discover_devices, DiscoveredDevice, DeviceIdentity
from .device import CatSnifferDevice, CommandResult
from .logging import LogManager, log_manager
from .testbench import (
    SmokeTestRunner,
    FleetActions,
    SmokeTestResult,
    TestStepResult,
    SMOKE_TEST_STEPS,
)
from .screens import (
    AllDevicesScreen,
    DeviceScreen,
    FleetAction,
    FleetSmokeTest,
    DeviceCommand,
    DeviceSmokeTest,
)
from .terminal import InteractiveSerialTerminal


class CatSnifferTestbenchApp(App):
    """Main TUI application for CatSniffer testbench."""

    CSS = """
    CatSnifferTestbenchApp {
        layout: vertical;
    }

    #main-container {
        layout: horizontal;
        height: 1fr;
    }

    #sidebar {
        width: 25;
        dock: left;
        background: $surface-darken-1;
        border-right: solid $primary;
    }

    #sidebar-header {
        background: $primary;
        color: $text;
        padding: 1;
        text-style: bold;
    }

    #device-list {
        height: 1fr;
        overflow: auto;
    }

    #hotplug-status {
        dock: bottom;
        height: 2;
        padding: 0 1;
        background: $primary-darken-1;
    }

    #content-area {
        width: 1fr;
        height: 1fr;
    }

    #log-bar {
        height: 10;
        dock: bottom;
        border-top: solid $primary;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "rescan", "Rescan"),
        Binding("l", "focus_logs", "Logs"),
        Binding("0", "show_all_devices", "All Devices"),
        Binding("1", "show_device_1", "Device #1"),
        Binding("2", "show_device_2", "Device #2"),
        Binding("3", "show_device_3", "Device #3"),
        Binding("4", "show_device_4", "Device #4"),
    ]

    # Reactive state
    devices: reactive[Dict[int, CatSnifferDevice]] = reactive({})
    scanning: reactive[bool] = reactive(False)
    device_count: reactive[int] = reactive(0)

    def __init__(self):
        super().__init__()
        self._device_manager = DeviceManager()
        self._smoke_runner = SmokeTestRunner()
        self._fleet_actions = FleetActions()
        self._log_manager = log_manager
        self._scan_task: Optional[asyncio.Task] = None
        self._device_screens: Dict[int, DeviceScreen] = {}

        # Set up callbacks
        self._smoke_runner.set_callbacks(
            on_progress=self._on_smoke_progress,
            on_complete=self._on_smoke_complete,
        )

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Container(
                Label("Connected Devices", id="sidebar-header"),
                Container(id="device-list"),
                Horizontal(
                    Static("Scanning...", id="scan-status"),
                    Static("0 devices", id="device-count"),
                    id="hotplug-status"
                ),
                id="sidebar"
            ),
            Container(
                TabbedContent(id="main-tabs", initial="all-devices"),
                id="content-area"
            ),
            id="main-container"
        )
        yield Footer()

    async def on_mount(self):
        """Initialize application on mount."""
        # Install tabs
        tabs = self.query_one("#main-tabs", TabbedContent)
        await tabs.add_pane(TabPane("All Devices", AllDevicesScreen(id="all-devices")))

        # Start hotplug scanning
        self._scan_task = asyncio.create_task(self._hotplug_loop())

        # Initial scan
        await self._rescan_devices()

    async def on_unmount(self):
        """Clean up on unmount."""
        if self._scan_task:
            self._scan_task.cancel()

        # Disconnect all devices
        for device in self.devices.values():
            await device.disconnect_all()

    async def _hotplug_loop(self):
        """Background hotplug scanning loop."""
        while True:
            await asyncio.sleep(HOTPLUG_SCAN_INTERVAL)
            await self._rescan_devices()

    async def _rescan_devices(self):
        """Rescan for devices and update state."""
        self.scanning = True
        self._update_scan_status()

        try:
            # Discover devices
            discovered = discover_devices()

            # Build identity map for current devices
            current_identities = {
                dev.identity: dev_id for dev_id, dev in self.devices.items()
            }

            # Build new device map
            new_devices: Dict[int, CatSnifferDevice] = {}
            device_id = 1

            for disc in discovered:
                # Check if we already know this device
                if disc.identity in current_identities:
                    old_id = current_identities[disc.identity]
                    new_devices[old_id] = self.devices[old_id]
                else:
                    # New device
                    device = CatSnifferDevice(disc, device_id, self._log_manager)
                    new_devices[device_id] = device
                    device_id += 1

                    # Connect and install screen
                    await device.connect_all()

            # Handle removed devices
            for dev_id, device in self.devices.items():
                if dev_id not in new_devices:
                    await device.disconnect_all()
                    self._log_manager.remove_device(dev_id)

            # Update reactive state
            self.devices = new_devices
            self.device_count = len(new_devices)

            # Update UI
            self._update_device_list()
            self._update_tabs()
            self._update_all_devices_screen()

        except Exception as e:
            self.log(f"Scan error: {e}")

        finally:
            self.scanning = False
            self._update_scan_status()

    def _update_scan_status(self):
        """Update scan status display."""
        try:
            status = self.query_one("#scan-status", Static)
            count = self.query_one("#device-count", Static)

            if self.scanning:
                status.update("[yellow]Scanning...[/yellow]")
            else:
                status.update("[green]Ready[/green]")

            count.update(f"{self.device_count} device(s)")
        except Exception:
            pass

    def _update_device_list(self):
        """Update device list in sidebar."""
        try:
            device_list = self.query_one("#device-list", Container)
            device_list.remove_children()

            for device_id, device in self.devices.items():
                health_color = "green" if device.health.value == "healthy" else "yellow"
                btn = Button(
                    f"[{health_color}]#{device_id}[/{health_color}] {device.identity.serial_number[:8]}",
                    id=f"device-btn-{device_id}"
                )
                device_list.mount(btn)
        except Exception:
            pass

    def _update_tabs(self):
        """Update device tabs."""
        try:
            tabs = self.query_one("#main-tabs", TabbedContent)

            # Remove old device tabs
            for dev_id in list(self._device_screens.keys()):
                if dev_id not in self.devices:
                    tabs.remove_pane(f"device-{dev_id}")
                    del self._device_screens[dev_id]

            # Add new device tabs
            for dev_id, device in self.devices.items():
                if dev_id not in self._device_screens:
                    screen = DeviceScreen(device, id=f"device-{dev_id}")
                    self._device_screens[dev_id] = screen
                    tabs.add_pane(TabPane(f"#{dev_id}", screen))
        except Exception:
            pass

    def _update_all_devices_screen(self):
        """Update all devices screen."""
        try:
            screen = self.query_one("#all-devices", AllDevicesScreen)
            screen.update_devices(self.devices)
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed):
        """Handle button presses."""
        if event.button.id and event.button.id.startswith("device-btn-"):
            device_id = int(event.button.id.split("-")[-1])
            self._show_device_tab(device_id)

    def _show_device_tab(self, device_id: int):
        """Switch to device tab."""
        tabs = self.query_one("#main-tabs", TabbedContent)
        tabs.active = f"device-{device_id}"

    # Fleet actions
    def on_fleet_action(self, event: FleetAction):
        """Handle fleet action."""
        asyncio.create_task(self._execute_fleet_action(event.action, event.value))

    async def _execute_fleet_action(self, action: str, value: str):
        """Execute a fleet action."""
        devices = list(self.devices.values())

        if action in ("band1", "band2", "band3"):
            await self._fleet_actions.set_all_band(devices, action)
        elif action == "lora_freq" and value:
            try:
                freq = int(value)
                await self._fleet_actions.set_all_lora_freq(devices, freq)
            except ValueError:
                pass

    def on_fleet_smoke_test(self, event: FleetSmokeTest):
        """Handle fleet smoke test."""
        asyncio.create_task(self._run_fleet_smoke())

    async def _run_fleet_smoke(self):
        """Run smoke test on all devices."""
        devices = list(self.devices.values())
        await self._smoke_runner.run_multiple(devices)

    # Device commands
    def on_device_command(self, event: DeviceCommand):
        """Handle device command."""
        asyncio.create_task(self._execute_device_command(event))

    async def _execute_device_command(self, event: DeviceCommand):
        """Execute a device command."""
        device = self.devices.get(event.device_id)
        if not device:
            return

        if event.endpoint == "CDC2":
            result = await device.send_shell_command(event.command)
        elif event.endpoint == "CDC1":
            result = await device.send_lora_command(event.command)
        else:
            return

        # Log result
        self._log_manager.log_tx(
            event.device_id,
            event.endpoint,
            event.command
        )
        if result.response:
            self._log_manager.log_rx(
                event.device_id,
                event.endpoint,
                result.response
            )

    def on_device_smoke_test(self, event: DeviceSmokeTest):
        """Handle device smoke test."""
        device = self.devices.get(event.device_id)
        if device:
            asyncio.create_task(self._smoke_runner.run_single(device))

    def _on_smoke_progress(self, device_id: int, step_result: TestStepResult):
        """Handle smoke test progress."""
        screen = self._device_screens.get(device_id)
        if screen:
            self.call_from_thread(screen.update_test_progress, step_result)

    def _on_smoke_complete(self, device_id: int, result: SmokeTestResult):
        """Handle smoke test completion."""
        screen = self._device_screens.get(device_id)
        if screen:
            self.call_from_thread(screen.update_test_complete, result)

    # Terminal
    def open_terminal(self, endpoint_handler, device_id: int, endpoint_type: str):
        """Open interactive terminal for endpoint."""
        self.push_screen(
            InteractiveSerialTerminal(endpoint_handler, device_id, endpoint_type)
        )

    # Actions
    def action_rescan(self):
        """Force rescan."""
        asyncio.create_task(self._rescan_devices())

    def action_show_all_devices(self):
        """Show all devices tab."""
        tabs = self.query_one("#main-tabs", TabbedContent)
        tabs.active = "all-devices"

    def action_show_device_1(self):
        self._show_device_tab(1)

    def action_show_device_2(self):
        self._show_device_tab(2)

    def action_show_device_3(self):
        self._show_device_tab(3)

    def action_show_device_4(self):
        self._show_device_tab(4)


class DeviceManager:
    """Manages device state and identity."""

    def __init__(self):
        self._identities: Dict[DeviceIdentity, int] = {}
        self._next_id = 1

    def get_or_assign_id(self, identity: DeviceIdentity) -> int:
        """Get existing ID or assign new one."""
        if identity not in self._identities:
            self._identities[identity] = self._next_id
            self._next_id += 1
        return self._identities[identity]

    def remove_identity(self, identity: DeviceIdentity):
        """Remove identity."""
        if identity in self._identities:
            del self._identities[identity]


def main():
    """Main entry point."""
    app = CatSnifferTestbenchApp()
    app.run()


if __name__ == "__main__":
    main()

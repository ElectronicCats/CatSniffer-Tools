"""
CatSniffer TUI Testbench - Event-Based Hotplug Detection

Platform-specific USB hotplug detection using native APIs.
NO POLLING - only event-based or manual rescan.
"""
import asyncio
import platform
from typing import Callable, Optional
from abc import ABC, abstractmethod

from .constants import CATSNIFFER_VID, CATSNIFFER_PID


class HotplugWatcher(ABC):
    """Abstract base class for platform-specific hotplug watchers."""

    def __init__(self, on_devices_changed: Callable[[], None]):
        self.on_devices_changed = on_devices_changed
        self._running = False

    @abstractmethod
    async def start(self):
        """Start watching for USB events."""
        pass

    @abstractmethod
    async def stop(self):
        """Stop watching."""
        pass

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return platform name for logging."""
        pass


class MacOSHotplugWatcher(HotplugWatcher):
    """
    macOS hotplug using IOKit notifications via pyobjc.

    Requires: pip install pyobjc-framework-IOKit
    """

    def __init__(self, on_devices_changed: Callable[[], None]):
        super().__init__(on_devices_changed)
        self._observer = None

    @property
    def platform_name(self) -> str:
        return "macOS IOKit"

    async def start(self):
        """Start IOKit notification listener."""
        try:
            import asyncio
            loop = asyncio.get_event_loop()

            # Try to use IOKit
            self._running = True
            await loop.run_in_executor(None, self._setup_iokit)
        except ImportError:
            # No pyobjc - manual rescan only
            self._running = True

    def _setup_iokit(self):
        """Set up IOKit notifications."""
        try:
            from PyObjCTools import AppHelper
            from Foundation import NSObject, NSRunLoop, NSDate
            import objc

            # Load IOKit
            IOKit = objc.loadBundle(
                "IOKit",
                globals(),
                "/System/Library/Frameworks/IOKit.framework"
            )

            # Create callback object
            class USBObserver(NSObject):
                def __init__(self, callback):
                    self.callback = callback

                def deviceAdded_(self, sender):
                    if self.callback:
                        self.callback()

                def deviceRemoved_(self, sender):
                    if self.callback:
                        self.callback()

            # Create notification port
            IONotificationPortRef = IOKit.IONotificationPortCreate(0)
            run_loop_source = IOKit.IONotificationPortGetRunLoopSource(
                IONotificationPortRef, None
            )
            CFRunLoopRef = IOKit.CFRunLoopGetCurrent()
            IOKit.CFRunLoopAddSource(CFRunLoopRef, run_loop_source, IOKit.kCFRunLoopDefaultMode)

            # Create observer
            self._observer = USBObserver.alloc().initWithCallback_(
                lambda: asyncio.get_event_loop().call_soon_threadsafe(self.on_devices_changed)
            )

            # Register for USB device notifications
            matching_dict = IOKit.IOServiceMatching(kIOUSBDeviceClassName)
            IOKit.IOServiceAddMatchingNotification(
                IONotificationPortRef,
                kIOFirstMatchNotification,
                matching_dict,
                self._observer.deviceAdded_,
                self._observer,
                None
            )
            IOKit.IOServiceAddMatchingNotification(
                IONotificationPortRef,
                kIOTerminatedNotification,
                matching_dict,
                self._observer.deviceRemoved_,
                self._observer,
                None
            )

        except Exception:
            # IOKit setup failed - manual rescan only
            self._observer = None

    async def stop(self):
        """Stop watching."""
        self._running = False
        self._observer = None


class LinuxHotplugWatcher(HotplugWatcher):
    """
    Linux hotplug using pyudev.

    Requires: pip install pyudev
    """

    def __init__(self, on_devices_changed: Callable[[], None]):
        super().__init__(on_devices_changed)
        self._monitor = None
        self._observer = None

    @property
    def platform_name(self) -> str:
        return "Linux udev"

    async def start(self):
        """Start udev monitor."""
        try:
            import pyudev

            context = pyudev.Context()
            monitor = pyudev.Monitor.from_netlink(context)
            monitor.filter_by(subsystem='tty')

            self._running = True
            loop = asyncio.get_event_loop()

            def monitor_callback(device):
                if not self._running:
                    return
                # Only trigger for USB serial devices with our VID or any add/remove
                props = device.properties
                if 'ID_VENDOR_ID' in props:
                    try:
                        vid = int(props.get('ID_VENDOR_ID', '0'), 16)
                        if vid == CATSNIFFER_VID:
                            loop.call_soon_threadsafe(self.on_devices_changed)
                    except ValueError:
                        pass

            self._observer = pyudev.MonitorObserver(monitor, callback=monitor_callback)
            self._observer.start()

        except ImportError:
            # No pyudev - manual rescan only
            self._running = True

    async def stop(self):
        """Stop watching."""
        self._running = False
        if self._observer:
            self._observer.stop()
            self._observer = None


class ManualOnlyWatcher(HotplugWatcher):
    """
    Fallback for platforms without native hotplug support.
    Manual rescan only (press 'R' key).
    """

    @property
    def platform_name(self) -> str:
        return "Manual Rescan Only"

    async def start(self):
        """Nothing to start - manual rescan only."""
        self._running = True

    async def stop(self):
        """Nothing to stop."""
        self._running = False


def create_hotplug_watcher(on_devices_changed: Callable[[], None]) -> HotplugWatcher:
    """Factory function to create platform-appropriate watcher."""
    system = platform.system()

    if system == "Darwin":
        return MacOSHotplugWatcher(on_devices_changed)
    elif system == "Linux":
        return LinuxHotplugWatcher(on_devices_changed)
    else:
        return ManualOnlyWatcher(on_devices_changed)

"""
CatSniffer TUI Testbench Logging

Ring buffer log management and export functionality.
"""
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

from .constants import LOG_BUFFER_SIZE, LOG_EXPORT_DIR


@dataclass
class LogEntry:
    """Single log entry."""
    timestamp: float
    device_id: int
    endpoint: str  # "CDC0", "CDC1", "CDC2"
    direction: str  # "TX" or "RX"
    data: str
    parsed: Optional[Dict] = None  # Parsed RX data (RSSI, SNR, etc.)
    is_mark: bool = False  # MARK separator

    def format(self) -> str:
        """Format entry for display."""
        ts = datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S.%f")[:-3]
        if self.is_mark:
            return f"{ts} {'─' * 60} MARK {'─' * 60}"
        prefix = f"{ts} [#{self.device_id}][{self.endpoint}]"
        if self.direction == "TX":
            return f"{prefix} > {self.data}"
        else:
            return f"{prefix} < {self.data}"


class RingBufferLog:
    """Thread-safe ring buffer for log entries."""

    def __init__(self, max_entries: int = LOG_BUFFER_SIZE):
        self.max_entries = max_entries
        self.entries: deque = deque(maxlen=max_entries)
        self._marks: List[float] = []  # Timestamps of marks

    def add_tx(self, device_id: int, endpoint: str, data: str):
        """Add TX entry."""
        entry = LogEntry(
            timestamp=datetime.now().timestamp(),
            device_id=device_id,
            endpoint=endpoint,
            direction="TX",
            data=data
        )
        self.entries.append(entry)

    def add_rx(self, device_id: int, endpoint: str, data: str, parsed: Optional[Dict] = None):
        """Add RX entry with optional parsed data."""
        entry = LogEntry(
            timestamp=datetime.now().timestamp(),
            device_id=device_id,
            endpoint=endpoint,
            direction="RX",
            data=data,
            parsed=parsed
        )
        self.entries.append(entry)

    def add_mark(self):
        """Add MARK separator."""
        entry = LogEntry(
            timestamp=datetime.now().timestamp(),
            device_id=0,
            endpoint="",
            direction="",
            data="",
            is_mark=True
        )
        self.entries.append(entry)
        self._marks.append(entry.timestamp)

    def filter(
        self,
        device_id: Optional[int] = None,
        endpoint: Optional[str] = None,
        search: Optional[str] = None
    ) -> List[LogEntry]:
        """Filter entries by device, endpoint, and search string."""
        result = list(self.entries)

        if device_id is not None:
            result = [e for e in result if e.device_id == device_id or e.is_mark]

        if endpoint and endpoint != "ALL":
            result = [e for e in result if e.endpoint == endpoint or e.is_mark]

        if search:
            search_lower = search.lower()
            result = [e for e in result if search_lower in e.data.lower() or e.is_mark]

        return result

    def export_to_file(self, path: Optional[str] = None, device_id: Optional[int] = None) -> str:
        """Export logs to file. Returns file path."""
        if path is None:
            os.makedirs(LOG_EXPORT_DIR, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            suffix = f"_device{device_id}" if device_id else "_all"
            path = os.path.join(LOG_EXPORT_DIR, f"catsniffer_log_{ts}{suffix}.txt")

        entries = self.filter(device_id=device_id)

        with open(path, "w") as f:
            f.write(f"CatSniffer TUI Testbench Log Export\n")
            f.write(f"Exported: {datetime.now().isoformat()}\n")
            f.write(f"Entries: {len(entries)}\n")
            f.write("=" * 80 + "\n\n")

            for entry in entries:
                f.write(entry.format() + "\n")

        return path

    def clear(self):
        """Clear all entries."""
        self.entries.clear()
        self._marks.clear()

    def get_entry_count(self) -> int:
        """Get total entry count."""
        return len(self.entries)


class LogManager:
    """Manages logs for all devices."""

    def __init__(self):
        self.global_log = RingBufferLog()
        self._device_logs: Dict[int, RingBufferLog] = {}
        self._byte_counters: Dict[int, Dict[str, Dict[str, int]]] = {}

    def get_device_log(self, device_id: int) -> RingBufferLog:
        """Get or create log buffer for device."""
        if device_id not in self._device_logs:
            self._device_logs[device_id] = RingBufferLog()
            self._byte_counters[device_id] = {
                "CDC0": {"tx": 0, "rx": 0},
                "CDC1": {"tx": 0, "rx": 0},
                "CDC2": {"tx": 0, "rx": 0},
            }
        return self._device_logs[device_id]

    def log_tx(self, device_id: int, endpoint: str, data: str, bytes_count: int = 0):
        """Log TX to both global and device logs."""
        self.global_log.add_tx(device_id, endpoint, data)
        self.get_device_log(device_id).add_tx(device_id, endpoint, data)
        self._add_bytes(device_id, endpoint, "tx", bytes_count or len(data))

    def log_rx(self, device_id: int, endpoint: str, data: str, parsed: Optional[Dict] = None):
        """Log RX to both global and device logs."""
        self.global_log.add_rx(device_id, endpoint, data, parsed)
        self.get_device_log(device_id).add_rx(device_id, endpoint, data, parsed)
        self._add_bytes(device_id, endpoint, "rx", len(data))

    def add_mark(self):
        """Add MARK to all logs."""
        self.global_log.add_mark()
        for device_log in self._device_logs.values():
            device_log.add_mark()

    def _add_bytes(self, device_id: int, endpoint: str, direction: str, count: int):
        """Update byte counter."""
        if device_id in self._byte_counters:
            if endpoint in self._byte_counters[device_id]:
                self._byte_counters[device_id][endpoint][direction] += count

    def get_byte_counters(self, device_id: int) -> Dict[str, Dict[str, int]]:
        """Get byte counters for device."""
        return self._device_logs.get(device_id, {})

    def get_counters(self, device_id: int) -> Dict[str, Dict[str, int]]:
        """Get byte counters for device."""
        return self._byte_counters.get(device_id, {
            "CDC0": {"tx": 0, "rx": 0},
            "CDC1": {"tx": 0, "rx": 0},
            "CDC2": {"tx": 0, "rx": 0},
        })

    def reset_counters(self, device_id: int):
        """Reset byte counters for device."""
        if device_id in self._byte_counters:
            for ep in self._byte_counters[device_id]:
                self._byte_counters[device_id][ep] = {"tx": 0, "rx": 0}

    def remove_device(self, device_id: int):
        """Remove device logs (on disconnect)."""
        if device_id in self._device_logs:
            del self._device_logs[device_id]
        if device_id in self._byte_counters:
            del self._byte_counters[device_id]


# Global log manager instance
log_manager = LogManager()

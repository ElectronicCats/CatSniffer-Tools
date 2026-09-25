"""
BLE Spam — live view of the advertising cycle.

``catnip spam run`` starts a cycle and then leaves it running; the raw stream is
a fast scroll of ``SPAM: <model> (i/n)`` lines that says little at a glance. This
turns that stream into a fixed panel — active mode, elapsed time, the model being
advertised right now, ads emitted and the last rotated address — so the operator
can watch the session rather than read a firehose.

The hardened firmware adds resource telemetry (``STATS: … stack=…/… heap=…/…``),
a low-stack ``WARN:`` and, when scan is enabled, ``SCAN:`` reports. The view folds
those too: extra rows for power/interval/stack/heap, a red Stack row on a warning,
and a secondary table listing the most recent scan reports (Fase 4).

The rendering is pure: :class:`SpamLiveView` folds each parsed :class:`SpamLine`
into counters and paints a Rich renderable from them. :func:`run_live` drives the
controller's event generator against it. The generator blocks per read timeout
and skips idle reads, so ``Ctrl+C`` is delivered promptly; the caller
(``cli/ble_spam.py``) owns the ``stop``/``close`` on exit (R5).
"""

from __future__ import annotations

import time
from collections import deque

from rich.console import Group
from rich.live import Live
from rich.table import Table

from .core import LineKind, SpamLine, SpamMode

REFRESH_PER_SECOND = 8
# Newest-first ring of scan reports shown in the secondary feed table.
SCAN_FEED_MAX = 8


class SpamLiveView:
    """Fold the parsed event stream into a repaintable status panel."""

    def __init__(self, mode: SpamMode) -> None:
        self.mode = mode
        self.models: int | None = None
        self.cycles = 0
        self.adverts = 0
        self.current_model: str | None = None
        self.index: int | None = None
        self.total: int | None = None
        self.addr: str | None = None
        self.last_error: str | None = None
        self.started = time.monotonic()
        # Hardened-firmware telemetry (None until a STATS/STATUS line carries it).
        self.power = None  # PowerProfile
        self.int_min: int | None = None
        self.int_max: int | None = None
        self.stack_used: int | None = None
        self.stack_size: int | None = None
        self.heap_free: int | None = None
        self.heap_total: int | None = None
        self.stack_warn = False  # a WARN: low-stack line was seen
        # Scan feed (only fills when the build has SPAM_WITH_SCAN and it is on).
        self.scan_reports = 0
        self.scan_recent: deque[tuple[str | None, int | None, int | None]] = deque(
            maxlen=SCAN_FEED_MAX
        )

    def update(self, line: SpamLine) -> None:
        """Fold one parsed device line into the view's counters."""
        if line.kind is LineKind.CYCLE:
            self.adverts += 1
            self.current_model = line.model
            self.index = line.index
            self.total = line.total
            # The per-cycle index carries the model count (i/n) even between the
            # every-100 ``cycles=`` reports, so keep it current from here too.
            if line.total is not None:
                self.models = line.total
        elif line.kind is LineKind.STATUS and line.status is not None:
            self.mode = line.status.mode
            self.models = line.status.models
            self._absorb_profile(
                line.status.power, line.status.int_min, line.status.int_max
            )
        elif line.kind is LineKind.STATS:
            if line.cycles is not None:
                self.cycles = line.cycles
            if line.addr is not None:
                self.addr = line.addr
            if line.stats is not None:
                s = line.stats
                self.stack_used = s.stack_used
                self.stack_size = s.stack_size
                self.heap_free = s.heap_free
                self.heap_total = s.heap_total
                self._absorb_profile(s.power, s.int_min, s.int_max)
        elif line.kind is LineKind.WARN:
            # Low-stack warning: flag the Stack row (rendered red, like last_error).
            self.stack_warn = True
        elif line.kind is LineKind.SCAN:
            # Only reports (mac/rssi/len) feed the table; state lines are ignored.
            if line.rssi is not None:
                self.scan_reports += 1
                self.scan_recent.appendleft((line.addr, line.rssi, line.data_len))
        elif line.kind is LineKind.ERROR:
            self.last_error = line.message

    def _absorb_profile(self, power, int_min, int_max) -> None:
        """Latch power/interval from a STATUS or STATS line when present."""
        if power is not None:
            self.power = power
        if int_min is not None and int_max is not None:
            self.int_min = int_min
            self.int_max = int_max

    def _elapsed(self) -> str:
        seconds = int(time.monotonic() - self.started)
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    @staticmethod
    def _pair(a: int | None, b: int | None) -> str:
        return "—" if a is None or b is None else f"{a}/{b}"

    def render(self):
        """Build the current status renderable (status table, plus a scan feed)."""
        model = self.current_model or "—"
        if self.index is not None and self.total is not None:
            model = f"{model} ({self.index}/{self.total})"

        table = Table(
            title=f"BLE spam — mode {self.mode.token}",
            title_justify="center",
            caption="Ctrl+C to stop",
            caption_justify="center",
        )
        table.add_column("Field", style="cyan", no_wrap=True)
        table.add_column("Value", style="magenta")

        table.add_row("Elapsed", self._elapsed())
        table.add_row("Models", "—" if self.models is None else str(self.models))
        table.add_row("Cycles", str(self.cycles))
        table.add_row("Ads sent", str(self.adverts))
        table.add_row("Current model", model)
        table.add_row("Last address", self.addr or "—")
        table.add_row("Power", "—" if self.power is None else self.power.value)
        if self.int_min is None or self.int_max is None:
            interval = "—"
        else:
            interval = f"{self.int_min}-{self.int_max}"
        table.add_row("Interval", interval)
        stack = self._pair(self.stack_used, self.stack_size)
        table.add_row("Stack", f"[red]{stack}[/red]" if self.stack_warn else stack)
        table.add_row("Heap", self._pair(self.heap_free, self.heap_total))
        if self.last_error:
            table.add_row("Last error", f"[red]{self.last_error}[/red]")

        if self.scan_reports == 0:
            return table
        return Group(table, self._render_scan())

    def _render_scan(self) -> Table:
        """Secondary table: the most recent scan reports, newest first."""
        table = Table(
            title=f"Scan feed — {self.scan_reports} reports",
            title_justify="center",
        )
        table.add_column("MAC", style="green", no_wrap=True)
        table.add_column("RSSI", style="yellow", justify="right")
        table.add_column("Len", style="magenta", justify="right")
        for mac, rssi, length in self.scan_recent:
            table.add_row(
                mac or "—",
                "—" if rssi is None else str(rssi),
                "—" if length is None else str(length),
            )
        return table


def run_live(controller, mode: SpamMode, console=None) -> SpamLiveView:
    """Render the controller's live event stream until it ends or Ctrl+C.

    Returns the final :class:`SpamLiveView` (useful for tests). Does not stop or
    close the controller — the caller owns lifecycle so the hardware is halted on
    every exit path (R5).
    """
    view = SpamLiveView(mode)
    with Live(
        view.render(),
        refresh_per_second=REFRESH_PER_SECOND,
        console=console,
    ) as live:
        for line in controller.read_events():
            view.update(line)
            live.update(view.render())
    return view

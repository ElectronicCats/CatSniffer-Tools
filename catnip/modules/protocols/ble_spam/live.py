"""
BLE Spam — live view of the advertising cycle.

``catnip spam run`` starts a cycle and then leaves it running; the raw stream is
a fast scroll of ``SPAM: <model> (i/n)`` lines that says little at a glance. This
turns that stream into a fixed panel — active mode, elapsed time, the model being
advertised right now, ads emitted and the last rotated address — so the operator
can watch the session rather than read a firehose.

The rendering is pure: :class:`SpamLiveView` folds each parsed :class:`SpamLine`
into counters and paints a Rich table from them. :func:`run_live` drives the
controller's event generator against it. The generator blocks per read timeout
and skips idle reads, so ``Ctrl+C`` is delivered promptly; the caller
(``cli/ble_spam.py``) owns the ``stop``/``close`` on exit (R5).
"""

from __future__ import annotations

import time

from rich.live import Live
from rich.table import Table

from .core import LineKind, SpamLine, SpamMode

REFRESH_PER_SECOND = 8


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
        elif line.kind is LineKind.STATS:
            if line.cycles is not None:
                self.cycles = line.cycles
            if line.addr is not None:
                self.addr = line.addr
        elif line.kind is LineKind.ERROR:
            self.last_error = line.message

    def _elapsed(self) -> str:
        seconds = int(time.monotonic() - self.started)
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def render(self) -> Table:
        """Build the current status table."""
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
        if self.last_error:
            table.add_row("Last error", f"[red]{self.last_error}[/red]")
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

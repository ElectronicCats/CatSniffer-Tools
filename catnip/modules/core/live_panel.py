"""Live capture panel — a running ``sniff lora``/``sniff fsk`` seen as rates and
signal quality instead of as a hex dump.

``-v`` prints every frame as hex and ASCII, which is what a reader wants when
the payload is the object of interest and the wrong thing entirely while a
capture is left running: the numbers that say whether the capture is working —
how fast frames arrive, how strong they are, whether the rate just collapsed —
are spread over a screenful of scrollback and gone by the time they are read.

So this is the loop :class:`~modules.protocols.sx1262.scan.ScanGraph` and
cativity's ``Graphs`` already run: the capture thread only touches counters, a
daemon thread repaints a Rich ``Live`` region four times a second, and the panel
stays in place rather than scrolling.  What it shows is what a fixed-height
panel can keep current — the rate over the last few seconds, the last and best
link quality, an RSSI histogram and the handful of most recent frames, cut
short.  Nothing is lost by not printing the rest: the full payloads go to
``--write``/``--raw``/``--ascii`` and to Wireshark, and the session totals to
the report printed when the capture stops.
"""

import time
from collections import deque

from rich.console import Group
from rich.live import Live
from rich.table import Table

REFRESH_PER_SECOND = 4

# Seconds of arrivals the pkt/s figure averages over.  Long enough that one
# frame does not read as a burst, short enough that the number falls back to
# zero while the user is still looking at the panel that showed the traffic.
RATE_WINDOW = 10.0

# The RSSI histogram: dBm per row, and the range the rows cover.  The SX1262
# reports around -150 dBm on noise and never much above -10, and anything
# outside that is clamped into the end rows rather than given one of its own.
RSSI_BUCKET_DB = 10
RSSI_FLOOR = -150
RSSI_CEILING = -10

# Bar width of the busiest histogram row; the rest are scaled against it.
MAX_BAR = 40

# Frames kept for the "last frames" table, and how much of each payload is
# shown.  A preview answers "is this the traffic I am after?"; the bytes
# themselves are already in the capture file.
RECENT_FRAMES = 6
HEX_PREVIEW_BYTES = 14


def _quality(value, unit: str) -> str:
    """``-42.0`` → ``"-42 dBm"``; nothing heard yet → ``"—"``."""
    return "—" if value is None else f"{value:.0f}{unit}"


class CaptureGraph:
    """Counters the capture updates, and the panel a Live thread paints from them.

    Thread safety is by construction rather than by lock, as in ``ScanGraph``:
    the capture thread only increments its own counters, every histogram bucket
    exists from the start so no key can appear mid-iteration, and the
    recent-frames list is replaced rather than mutated, so the render thread
    always reads a complete one.
    """

    def __init__(self, modulation: str = "LoRa", summary=None):
        self.running = True
        self.modulation = modulation
        # ``_run_sx_capture`` already builds a (label, value) summary of the
        # radio settings to echo before configuring; the caption reuses it so
        # the panel says which settings these packets arrived on.
        self.summary = list(summary or [])
        # An FSK frame is reported without an SNR, so the column would be a
        # line of em dashes for the whole session.
        self.show_snr = modulation.upper() != "FSK"

        self.packets = 0
        self.errors = 0
        self.noise = 0
        self.last_rssi = None
        self.last_snr = None
        self.best_rssi = None
        self.peak_rate = 0.0
        self.started = time.monotonic()
        self.arrivals = deque()
        self.buckets = {
            floor: 0 for floor in range(RSSI_FLOOR, RSSI_CEILING, RSSI_BUCKET_DB)
        }
        self.recent = []

    # ── updates, called from the capture thread ──────────────────────────────

    @staticmethod
    def _bucket(rssi) -> int:
        """The histogram row ``rssi`` belongs to, clamped to the table's range."""
        floor = int(rssi // RSSI_BUCKET_DB) * RSSI_BUCKET_DB
        return max(RSSI_FLOOR, min(RSSI_CEILING - RSSI_BUCKET_DB, floor))

    def record(self, rssi, snr=None, payload: bytes = b"") -> None:
        """Count one received frame.  ``snr`` is None for FSK, which has none."""
        self.packets += 1
        self.arrivals.append(time.monotonic())
        self.last_rssi = rssi
        self.last_snr = snr
        if self.best_rssi is None or rssi > self.best_rssi:
            self.best_rssi = rssi
        self.buckets[self._bucket(rssi)] += 1

        preview = payload[:HEX_PREVIEW_BYTES].hex()
        if len(payload) > HEX_PREVIEW_BYTES:
            preview += "…"
        row = (time.strftime("%H:%M:%S"), len(payload), rssi, preview)
        # Rebound, not appended to: the render thread reads this list without a
        # lock, and a new list is seen either whole or not at all.
        self.recent = (self.recent + [row])[-RECENT_FRAMES:]

    def note_error(self) -> None:
        """A line that looked like a frame and would not parse."""
        self.errors += 1

    def note_noise(self) -> None:
        """A line from the device that was neither a frame nor a known banner."""
        self.noise += 1

    def stop(self) -> None:
        self.running = False

    # ── rendering ────────────────────────────────────────────────────────────

    def rate(self) -> float:
        """Frames per second over the last :data:`RATE_WINDOW` seconds.

        Called from the render thread, which is also the only one that drops
        arrivals off the front of the deque — the capture thread only appends.
        """
        now = time.monotonic()
        cutoff = now - RATE_WINDOW
        while self.arrivals and self.arrivals[0] < cutoff:
            self.arrivals.popleft()

        # The first second of a capture would otherwise divide by almost
        # nothing and report a rate of hundreds from a single frame.
        window = min(RATE_WINDOW, max(now - self.started, 1.0))
        rate = len(self.arrivals) / window
        self.peak_rate = max(self.peak_rate, rate)
        return rate

    def draw_bar(self, count: int, scale: int, char: str = "❚") -> str:
        """A bar for ``count`` frames, ``scale`` being the busiest bucket."""
        if count <= 0 or scale <= 0:
            return ""
        return char * max(1, round(MAX_BAR * count / scale))

    def elapsed(self) -> str:
        seconds = int(time.monotonic() - self.started)
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _caption(self) -> str:
        settings = " · ".join(
            f"{label.rstrip(':')} {value}" for label, value in self.summary
        )
        return (f"{settings}\n" if settings else "") + "Ctrl+C to stop"

    def _stats_table(self) -> Table:
        table = Table(
            title=f"{self.modulation} capture",
            title_justify="center",
            caption=self._caption(),
            caption_justify="center",
        )
        table.add_column("Elapsed", style="cyan", no_wrap=True, justify="right")
        table.add_column("Packets", style="magenta", no_wrap=True, justify="right")
        table.add_column("pkt/s", style="magenta", no_wrap=True, justify="right")
        table.add_column("Peak", style="magenta", no_wrap=True, justify="right")
        table.add_column("Last RSSI", style="yellow", no_wrap=True, justify="right")
        if self.show_snr:
            table.add_column("Last SNR", style="yellow", no_wrap=True, justify="right")
        table.add_column("Best RSSI", style="yellow", no_wrap=True, justify="right")
        table.add_column("Errors", style="red", no_wrap=True, justify="right")
        table.add_column("Noise", style="red", no_wrap=True, justify="right")

        rate = self.rate()
        row = [
            self.elapsed(),
            str(self.packets),
            f"{rate:.2f}",
            f"{self.peak_rate:.2f}",
            _quality(self.last_rssi, " dBm"),
        ]
        if self.show_snr:
            row.append(_quality(self.last_snr, " dB"))
        row += [_quality(self.best_rssi, " dBm"), str(self.errors), str(self.noise)]
        table.add_row(*row)
        return table

    def _histogram_table(self) -> Table:
        filled = [floor for floor, count in self.buckets.items() if count]
        table = Table(
            title="RSSI distribution",
            title_justify="center",
            caption=None if filled else "waiting for the first frame",
            caption_justify="center",
        )
        table.add_column("dBm", style="cyan", no_wrap=True, justify="right")
        table.add_column("Packets", style="magenta", no_wrap=True, justify="right")
        table.add_column("", style="green", no_wrap=True)

        if not filled:
            return table

        scale = max(self.buckets.values())
        # Strongest row first, and contiguous down to the weakest one heard, so
        # a bucket nothing landed in reads as a gap rather than disappearing
        # and leaving two distant rows looking adjacent.
        for floor in range(max(filled), min(filled) - RSSI_BUCKET_DB, -RSSI_BUCKET_DB):
            count = self.buckets[floor]
            table.add_row(
                f"{floor} to {floor + RSSI_BUCKET_DB}",
                str(count),
                self.draw_bar(count, scale),
            )
        return table

    def _recent_table(self) -> Table:
        table = Table(title="Last frames", title_justify="center")
        table.add_column("Time", style="cyan", no_wrap=True)
        table.add_column("Len", style="cyan", no_wrap=True, justify="right")
        table.add_column("RSSI", style="yellow", no_wrap=True, justify="right")
        table.add_column("Payload", style="green", no_wrap=True)

        for when, length, rssi, preview in reversed(self.recent):
            table.add_row(when, f"{length}B", f"{rssi:.0f}", preview)
        return table

    def generate(self) -> Group:
        return Group(self._stats_table(), self._histogram_table(), self._recent_table())

    def create_live(self, console=None) -> None:
        with Live(
            self.generate(),
            refresh_per_second=REFRESH_PER_SECOND,
            console=console,
        ) as live:
            while self.running:
                time.sleep(0.4)
                live.update(self.generate(), refresh=True)

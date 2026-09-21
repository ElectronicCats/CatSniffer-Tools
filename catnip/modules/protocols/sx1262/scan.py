"""``catnip lora scan`` — host-driven sweep of LoRa SF/BW/frequency combinations.

Identifying the settings of an unknown LoRa transmitter is a search, not a
measurement: the SX1262 only demodulates a frame when the spreading factor,
the bandwidth, the frequency *and* the sync word already match what the
transmitter used, so "did anything arrive?" is the only signal available and
it has to be asked once per combination.  Done by hand — one ``catnip sniff
lora`` per guess — the default 18 combinations are the better part of an hour.

The sweep needs nothing from the firmware that is not already there.  The
RP2040 keeps taking ``lora_freq``/``lora_bw``/``lora_sf``/``lora_apply`` on
Cat-Shell while it streams received frames on Cat-LoRa, and ``apply_lora_config``
re-arms reception with the new settings, so the hop is orchestrated from the
host exactly as :class:`CativityRunner` hops 802.15.4 channels for ``cativity``.

Threading mirrors that runner:

  * a reader thread drains Cat-LoRa into a queue, so a frame is never missed
    while the sweep is busy talking to the shell;
  * the main thread retunes, waits out the dwell and attributes what arrived;
  * a third thread renders the live table.

The sweep runs on the main thread rather than in a worker so Ctrl+C lands in
the loop that owns the radio, and the session stops between two combinations
instead of halfway through a retune.
"""

import queue
import threading
import time

from rich.live import Live
from rich.table import Table

# Internal
from ...core.catnip import (
    CatSnifferDevice,
    LoRaConnection,
    ShellConnection,
    DEFAULT_READLINE_MAX_BYTES,
)

# The LoRa setup sequence, the Cat-Shell echo handling and the line prefix the
# firmware marks received frames with are the sniffer's, not the scanner's:
# importing them keeps a retune here and a capture there talking to the same
# firmware in the same way, instead of a second copy that drifts.
from ...core.bridge import (
    _configure_lora,
    _shell_error,
    _shell_reply,
    _LORA_LINE_PREFIX,
    _SHELL_CMD_DELAY,
)
from ...utils.output import (
    console as default_console,
    print_dim,
    print_empty_line,
    print_error,
    print_info,
    print_success,
    print_warning,
)

# External
from protocol.sniffer_sx import SnifferSx

snifferSx = SnifferSx()
snifferSxCmd = snifferSx.Commands()


# The three bandwidths the firmware's ``lora_bw`` accepts, and the six
# spreading factors the SX1262 offers — the whole LoRa search space bar the
# frequency, which only the user knows anything about.
BANDWIDTHS = (125, 250, 500)
SPREAD_FACTORS = (7, 8, 9, 10, 11, 12)
DEFAULT_FREQUENCY_MHZ = 915.0

# The radio's tuning range, the same window ``sniff lora`` enforces.
MIN_FREQ_HZ = 150_000_000
MAX_FREQ_HZ = 960_000_000

# A frequency written as a bare number is MHz below this and Hz above it.  The
# radio stops at 960 MHz, so no value is ambiguous: 915 can only be megahertz
# and 915000000 can only be hertz.
_HZ_THRESHOLD = 1000

DEFAULT_DWELL = 3.0

# How often the dwell is interrupted to attribute what has arrived so far.
# Short enough that the live table moves while a combination is being listened
# to, rather than jumping only when the sweep leaves it.
COUNT_SLICE = 0.2

REFRESH_PER_SECOND = 4

# Rows the live table shows before it starts hiding the silent combinations.
# A sweep over several frequencies is longer than a terminal, and the rows
# worth watching are the ones that heard something plus the one being listened
# to right now.
MAX_LIVE_ROWS = 24

# Bar width at which the activity column stops growing and prints the count.
MAX_BAR = 40


# ──────────────────────────────────────────────────────────────────────────────
# Parsing the search space
# ──────────────────────────────────────────────────────────────────────────────


def _parse_list(value, convert, label):
    """Split a comma-separated option into a de-duplicated list, order kept."""
    items = []
    for chunk in str(value).split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            item = convert(chunk)
        except ValueError:
            raise ValueError(f"{chunk!r} is not a valid {label}")
        if item not in items:
            items.append(item)

    if not items:
        raise ValueError(f"No {label} given")
    return items


def parse_frequencies(value) -> list:
    """``"868.1,915"`` → ``[868100000, 915000000]``.

    Accepts MHz (``915``, ``868.1``) or Hz (``915000000``); see
    :data:`_HZ_THRESHOLD` for why both read unambiguously.
    """

    def to_hz(chunk):
        number = float(chunk)
        return int(round(number if number >= _HZ_THRESHOLD else number * 1e6))

    frequencies = _parse_list(value, to_hz, "frequency")

    for freq in frequencies:
        if not MIN_FREQ_HZ <= freq <= MAX_FREQ_HZ:
            raise ValueError(
                f"Frequency {freq / 1e6:.3f} MHz is out of range "
                f"({MIN_FREQ_HZ // 1_000_000}-{MAX_FREQ_HZ // 1_000_000} MHz)"
            )
    return frequencies


def parse_spread_factors(value) -> list:
    """``"7,9,12"`` → ``[7, 9, 12]``."""
    factors = _parse_list(value, int, "spreading factor")

    for sf in factors:
        if sf not in SPREAD_FACTORS:
            raise ValueError(f"Spreading factor {sf} is out of range (7-12)")
    return factors


def parse_bandwidths(value) -> list:
    """``"125,500"`` → ``[125, 500]``."""
    bandwidths = _parse_list(value, int, "bandwidth")

    for bw in bandwidths:
        if bw not in BANDWIDTHS:
            raise ValueError(
                f"Bandwidth {bw} kHz is not one of "
                f"{', '.join(str(b) for b in BANDWIDTHS)}"
            )
    return bandwidths


def build_combos(frequencies, bandwidths, spread_factors) -> list:
    """Every ``(frequency_hz, bandwidth_khz, spread_factor)`` to be tried.

    Ordered frequency-major and spreading-factor-minor, which is the order that
    changes the fewest settings between two consecutive retunes and the order
    a reader scanning the live table expects.
    """
    return [
        (freq, bw, sf)
        for freq in frequencies
        for bw in bandwidths
        for sf in spread_factors
    ]


def sweep_duration(combos, dwell: float, passes: int) -> float:
    """Seconds one run takes, retune overhead included, or 0 when unbounded.

    Four shell commands per combination, each paced by ``_SHELL_CMD_DELAY``;
    the estimate exists so the user can tell before starting whether a sweep
    is a coffee break or a lunch break.
    """
    if not passes:
        return 0.0
    return passes * len(combos) * (dwell + 4 * _SHELL_CMD_DELAY)


def format_combo(combo) -> str:
    """``(915000000, 125, 7)`` → ``"915.000 MHz  BW125  SF7"``."""
    freq, bw, sf = combo
    return f"{freq / 1e6:.3f} MHz  BW{bw}  SF{sf}"


def sniff_command(combo, sync_word: str) -> str:
    """The ``catnip sniff lora`` invocation that captures on ``combo``."""
    freq, bw, sf = combo
    return f"catnip sniff lora -freq {freq} -bw {bw} -sf {sf} -sw {sync_word}"


# ──────────────────────────────────────────────────────────────────────────────
# Live table
# ──────────────────────────────────────────────────────────────────────────────


class ScanGraph:
    """Live packets-per-combination table, in the shape of ``cativity``'s Graphs."""

    def __init__(self, combos, dwell: float = DEFAULT_DWELL, passes: int = 1):
        self.running = True
        self.combos = list(combos)
        self.dwell = dwell
        self.passes = passes
        self.current = None
        self.pass_number = 0
        self.stats = {
            combo: {"packets": 0, "rssi": None, "snr": None, "error": ""}
            for combo in self.combos
        }

    # ── updates, called from the sweep thread ────────────────────────────────

    def set_current(self, combo):
        self.current = combo

    def set_pass(self, pass_number: int):
        self.pass_number = pass_number

    def record(self, combo, samples):
        """Attribute ``[(rssi, snr), ...]`` to ``combo``.

        Link quality is kept for the strongest frame rather than averaged: on a
        combination that heard two transmitters the average describes neither,
        and the question a scan answers is whether *something* came through.
        """
        if not samples:
            return
        stat = self.stats[combo]
        stat["packets"] += len(samples)
        for rssi, snr in samples:
            if stat["rssi"] is None or rssi > stat["rssi"]:
                stat["rssi"] = rssi
                stat["snr"] = snr

    def mark_error(self, combo, message: str):
        """Record a setting the firmware refused, so a blank row reads as one."""
        self.stats[combo]["error"] = message

    def stop(self):
        self.running = False

    # ── rendering ────────────────────────────────────────────────────────────

    def draw_bar(self, packets: int, char: str = "❚") -> str:
        if packets <= 0:
            return ""
        if packets > MAX_BAR:
            return f"{char * MAX_BAR} ({packets})"
        return char * packets

    def visible_rows(self) -> tuple:
        """``(rows, hidden)`` — the combinations worth a line right now.

        Everything, until the sweep is wider than a terminal; from there on the
        combinations that heard something, plus the one being listened to.
        """
        if len(self.combos) <= MAX_LIVE_ROWS:
            return self.combos, 0

        rows = [
            combo
            for combo in self.combos
            if self.stats[combo]["packets"]
            or self.stats[combo]["error"]
            or combo == self.current
        ]
        return rows, len(self.combos) - len(rows)

    def _caption(self, hidden: int) -> str:
        heard = sum(1 for s in self.stats.values() if s["packets"])
        total = "∞" if not self.passes else str(self.passes)
        caption = (
            f"pass {self.pass_number}/{total} · "
            f"{len(self.combos)} combinations · {self.dwell:g}s dwell · "
            f"{heard} with traffic"
        )
        if hidden:
            caption += f" · {hidden} silent row(s) hidden"
        return caption + " · Ctrl+C to stop"

    def generate_table(self) -> Table:
        rows, hidden = self.visible_rows()

        table = Table(
            title="LoRa Parameter Sweep",
            title_justify="center",
            caption=self._caption(hidden),
            caption_justify="center",
        )
        table.add_column("", style="red", no_wrap=True)
        table.add_column("Freq (MHz)", style="cyan", no_wrap=True, justify="right")
        table.add_column("BW", style="cyan", no_wrap=True, justify="right")
        table.add_column("SF", style="cyan", no_wrap=True, justify="right")
        table.add_column("Packets", style="magenta", no_wrap=True, justify="right")
        table.add_column("Best RSSI", style="yellow", no_wrap=True, justify="right")
        table.add_column("SNR", style="yellow", no_wrap=True, justify="right")
        table.add_column("Activity", style="green", no_wrap=True)

        for combo in rows:
            freq, bw, sf = combo
            stat = self.stats[combo]
            activity = stat["error"] or self.draw_bar(stat["packets"])
            table.add_row(
                "---->" if combo == self.current else "",
                f"{freq / 1e6:.3f}",
                str(bw),
                str(sf),
                str(stat["packets"]),
                "" if stat["rssi"] is None else f"{stat['rssi']:.0f} dBm",
                "" if stat["snr"] is None else f"{stat['snr']:.0f} dB",
                activity,
            )

        return table

    def create_live(self, console=None):
        with Live(
            self.generate_table(),
            refresh_per_second=REFRESH_PER_SECOND,
            console=console,
        ) as live:
            while self.running:
                time.sleep(0.4)
                live.update(self.generate_table(), refresh=True)

    # ── results ──────────────────────────────────────────────────────────────

    def ranked(self) -> list:
        """``(combo, stat)`` pairs that heard something, busiest first."""
        heard = [(c, s) for c, s in self.stats.items() if s["packets"]]
        return sorted(
            heard,
            key=lambda item: (item[1]["packets"], item[1]["rssi"] or -999),
            reverse=True,
        )


# ──────────────────────────────────────────────────────────────────────────────
# The sweep
# ──────────────────────────────────────────────────────────────────────────────


class LoraScanner:
    """Retunes the SX1262 across ``combos`` and counts what each one receives."""

    def __init__(
        self,
        device: CatSnifferDevice,
        combos,
        dwell: float = DEFAULT_DWELL,
        passes: int = 1,
        sync_word: str = "private",
        console=None,
    ):
        self.device = device
        self.combos = list(combos)
        self.dwell = dwell
        self.passes = passes
        self.sync_word = sync_word
        self.console = console or default_console
        self.graph = ScanGraph(self.combos, dwell=dwell, passes=passes)
        self.packets = queue.Queue()
        self.running = False
        self.shell = None
        self.lora = None

    # ── plumbing ─────────────────────────────────────────────────────────────

    def _reader(self):
        """Drain Cat-LoRa into the queue for as long as the sweep runs."""
        while self.running:
            connection = self.lora.connection
            if not connection or not connection.is_open:
                break
            try:
                raw = connection.readline(DEFAULT_READLINE_MAX_BYTES)
            except Exception:
                break

            if not raw or _LORA_LINE_PREFIX not in raw.strip():
                continue

            try:
                # SnifferSx.Packet is the sniffer's own line parser; the
                # LoRaTap record it also builds is discarded here, which costs
                # one struct.pack on a path that sees a handful of frames per
                # dwell and buys the parsing the capture path is tested on.
                packet = snifferSx.Packet(raw)
            except ValueError:
                continue

            self.packets.put((packet.rssi, packet.snr))

    def _drain(self) -> list:
        """Everything received since the last call, as ``[(rssi, snr), ...]``."""
        samples = []
        while True:
            try:
                samples.append(self.packets.get_nowait())
            except queue.Empty:
                return samples

    def _retune(self, combo) -> None:
        """Point the radio at ``combo`` without printing over the live table."""
        freq, bw, sf = combo
        commands = (
            snifferSxCmd.set_freq(freq),
            snifferSxCmd.set_bw(bw),
            snifferSxCmd.set_sf(sf),
            snifferSxCmd.apply_config(),
        )

        for command in commands:
            reply = _shell_reply(self.shell.send_command(command, timeout=1.5), command)
            error = _shell_error(reply)
            if error:
                # A refused setting makes the next dwell meaningless — say so
                # in the row rather than reporting a silent combination the
                # radio was never actually tuned to.
                self.graph.mark_error(combo, error[:40])
            elif not reply:
                self.graph.mark_error(combo, "no reply")
            time.sleep(_SHELL_CMD_DELAY)

    def _sweep(self) -> None:
        pass_number = 0
        while self.running:
            pass_number += 1
            self.graph.set_pass(pass_number)

            for combo in self.combos:
                if not self.running:
                    return

                self._retune(combo)
                # Frames demodulated with the previous settings can still be
                # in the USB pipe; counting them here would credit this
                # combination with the last one's traffic.
                self._drain()
                self.graph.set_current(combo)

                deadline = time.monotonic() + self.dwell
                while self.running and time.monotonic() < deadline:
                    time.sleep(min(COUNT_SLICE, max(0.0, deadline - time.monotonic())))
                    self.graph.record(combo, self._drain())

            if self.passes and pass_number >= self.passes:
                return

    # ── entry point ──────────────────────────────────────────────────────────

    def run(self) -> bool:
        """Configure, sweep, report.  Returns False when the sweep never ran."""
        if not self.device.shell_port:
            print_error("No shell_port on device — cannot configure the radio")
            return False
        if not self.device.lora_port:
            print_error("No lora_port on device — cannot receive the LoRa stream")
            return False

        self.shell = ShellConnection(port=self.device.shell_port)
        if not self.shell.connect():
            print_error(f"Cannot open shell port: {self.device.shell_port}")
            return False

        # The first combination doubles as the initial configuration, so the
        # full setup sequence — RF switch, modulation, sync word and the rest —
        # runs exactly once and the sweep only ever changes the three settings
        # it is sweeping.
        first_freq, first_bw, first_sf = self.combos[0]
        print_info(f"Configuring LoRa via {self.device.shell_port}...")
        if not _configure_lora(
            self.shell,
            first_freq,
            first_bw,
            first_sf,
            coding_rate=5,
            tx_power=20,
            sync_word=self.sync_word,
            preamble=12,
            iq="normal",
        ):
            print_warning(
                "Some settings were not confirmed by the firmware — continuing"
            )

        self.lora = LoRaConnection(port=self.device.lora_port)
        if not self.lora.connect():
            print_error(f"Cannot open LoRa port: {self.device.lora_port}")
            self.shell.disconnect()
            return False

        time.sleep(0.3)
        try:
            self.lora.connection.reset_input_buffer()
        except Exception:
            pass

        print_info("Switching RP2040 to stream mode...")
        stream_cmd = snifferSxCmd.start_streaming()
        reply = _shell_reply(
            self.shell.send_command(stream_cmd, timeout=2.0), stream_cmd
        )
        if "STREAM" in reply.upper() and not _shell_error(reply):
            print_success("Stream mode active")
        else:
            print_warning(f"Unexpected stream response: {reply!r} — continuing")

        self.running = True
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(
            target=self.graph.create_live, args=(self.console,), daemon=True
        ).start()

        try:
            self._sweep()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

        self.print_results()
        return True

    def stop(self) -> None:
        self.running = False
        self.graph.stop()
        # Let the live table paint its final state before anything is printed
        # under it, or the results land inside the table's last frame.
        time.sleep(0.5)

        try:
            if self.shell:
                stop_cmd = snifferSxCmd.start_command()
                self.shell.send_command(stop_cmd, timeout=2.0)
        except Exception as exc:
            print_warning(f"Could not restore command mode: {exc}")

        for connection in (self.shell, self.lora):
            try:
                if connection:
                    connection.disconnect()
            except Exception:
                pass

    # ── report ───────────────────────────────────────────────────────────────

    def print_results(self) -> None:
        # Live leaves the cursor at the end of the table's caption, so the
        # first result would otherwise be printed onto that same line.
        print_empty_line()
        ranked = self.graph.ranked()

        if not ranked:
            print_warning("No LoRa frames on any of the combinations swept")
            print_dim(
                "The sync word has to match too: try -sw public for LoRaWAN or "
                "-sw 0x2B for Meshtastic."
            )
            print_dim(
                "A slow combination needs a longer look: one SF12/BW125 frame "
                "is over a second on air, so raise --dwell."
            )
            print_dim("Widen --freq if the transmitter may be on another band.")
            return

        best, best_stat = ranked[0]
        print_success(
            f"{len(ranked)} combination(s) received traffic — "
            f"best: {format_combo(best)} ({best_stat['packets']} packet(s))"
        )
        for combo, stat in ranked[:5]:
            quality = "" if stat["rssi"] is None else f"  RSSI {stat['rssi']:.0f} dBm"
            print_dim(f"{format_combo(combo)}  →  {stat['packets']} packet(s){quality}")

        print_info("Capture it with:")
        print_dim(sniff_command(best, self.sync_word))

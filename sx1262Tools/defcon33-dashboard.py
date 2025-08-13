#!/usr/bin/env python3
"""
Meshtastic Chat TUI — a beautiful, scrollable terminal app

Features
- Live packet capture via catsniffer
- Decrypts text messages using provided DEFAULT_KEYS
- Left sidebar: Channels (auto-detected) with unread counts
- Main area: Scrollable table (time, channel, name, message)
- Top bar: status (port, preset, freq, RX state)
- Node name resolution from NODEINFO frames (long/short name)
- Smooth, buffered UI updates; safe handling of special characters
- Keyboard: [A]ll channels, [0-7] to filter, [F]ind (filter text), [C]lear filter, [Q]uit

Dependencies: textual>=0.62, rich, meshtastic, cryptography, catsniffer

Run:
  python meshtastic_chat_tui.py -p /dev/ttyUSB0 -baud 921600 -f 902 -ps LongFast

Notes:
- This app focuses on portnum==1 (TEXT) messages for the chat view.
- NODEINFO (portnum==4) updates the name registry.
- Other ports are ignored for the main chat but can be logged to stderr if desired.
"""

from __future__ import annotations
import argparse
import asyncio
import base64
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Third-party
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from rich.markup import escape as rich_escape
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import DataTable, Static, Input, Footer

# Hardware / protobufs
import catsniffer
from meshtastic import mesh_pb2, admin_pb2, telemetry_pb2

# -------------------------- Radio / decoding helpers -------------------------
DEFAULT_KEYS = [
    "OEu8wB3AItGBvza4YSHh+5a3LlW/dCJ+nWr7SNZMsaE=",
    "6IzsaoVhx1ETWeWuu0dUWMLqItvYJLbRzwgTAKCfvtY=",
    "TiIdi8MJG+IRnIkS8iUZXRU+MHuGtuzEasOWXp4QndU=",
]

SYNC_WORLD = 0x2B

CHANNELS_PRESET = {
    "defcon33": {"sf": 7, "bw": 9, "cr": 5, "pl": 16},
    "ShortTurbo": {"sf": 7, "bw": 9, "cr": 5, "pl": 8},
    "ShortSlow": {"sf": 8, "bw": 8, "cr": 5, "pl": 8},
    "ShortFast": {"sf": 7, "bw": 8, "cr": 5, "pl": 8},
    "MediumSlow": {"sf": 10, "bw": 8, "cr": 5, "pl": 8},
    "MediumFast": {"sf": 9, "bw": 8, "cr": 5, "pl": 8},
    "LongSlow": {"sf": 12, "bw": 7, "cr": 5, "pl": 8},
    "LongFast": {"sf": 11, "bw": 8, "cr": 5, "pl": 8},
    "LongMod": {"sf": 11, "bw": 7, "cr": 8, "pl": 8},
    "VLongSlow": {"sf": 11, "bw": 7, "cr": 8, "pl": 8},
}


def msb2lsb(hexstr: str) -> str:
    return hexstr[6:8] + hexstr[4:6] + hexstr[2:4] + hexstr[0:2]


def extract_frame(raw: bytes) -> bytes:
    if not raw.startswith(b"@S") or not raw.endswith(b"@E\r\n"):
        raise ValueError("Invalid frame")
    length = int.from_bytes(raw[2:4], byteorder="big")
    return raw[4 : 4 + length]


def extract_fields(data: bytes) -> Dict[str, bytes]:
    return {
        "dest": data[0:4],
        "sender": data[4:8],
        "packet_id": data[8:12],
        "flags": data[12:13],
        "payload": data[16:],
    }


def decrypt(payload: bytes, key: bytes, sender: bytes, packet_id: bytes) -> bytes:
    nonce = packet_id + b"\x00\x00\x00\x00" + sender + b"\x00\x00\x00\x00"
    cipher = Cipher(algorithms.AES(key), modes.CTR(nonce), backend=default_backend())
    return cipher.decryptor().update(payload)


# ------------------------------- Data models --------------------------------
@dataclass
class ChatMessage:
    ts: float
    channel: int
    sender_id_hex: str
    sender_name: str
    text: str

    def as_row(self) -> Tuple[str, str, str, str]:
        t = datetime.fromtimestamp(self.ts).strftime("%H:%M:%S")
        return (t, str(self.channel), self.sender_name or self.sender_id_hex, self.text)


class NodeRegistry:
    def __init__(self) -> None:
        self._by_id: Dict[str, str] = {}

    def set_from_user_pb(self, user: mesh_pb2.User) -> None:
        node_id = user.id or ""
        if not node_id:
            return
        name = user.long_name or user.short_name or node_id
        # Sanitize for terminal
        self._by_id[node_id] = sanitize_text(name)

    def resolve(self, node_id_hex: str) -> str:
        # node_id in protobuf is typically a string; sender bytes are numeric. We map by hex as fallback.
        return self._by_id.get(node_id_hex, node_id_hex)


# --------------------------- Text sanitation ---------------------------------
CONTROL_REPLACEMENT = "�"


def sanitize_text(s: str) -> str:
    """Escape Rich markup and replace control chars except newlines and tabs."""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = "".join(
        (ch if (ch == "\n" or ch == "\t" or (31 < ord(ch) < 127) or ord(ch) >= 0xA0) else CONTROL_REPLACEMENT)
        for ch in s
    )
    return rich_escape(s)


# --------------------------- Radio monitor thread ----------------------------
class Monitor(catsniffer.Catsniffer):
    def __init__(self, port: str, baudrate: int, rx_queue: queue.Queue) -> None:
        super().__init__(port, baudrate)
        self.port = port          # <-- add this
        self.baudrate = baudrate  # <-- and this
        self.rx_queue = rx_queue
        self.running = True
        self.thread = None

    def start(self) -> None:
        self.open()
        self.thread = threading.Thread(target=self._recv_worker, daemon=True)
        self.thread.start()

    def _recv_worker(self) -> None:
        while self.running:
            try:
                data = self.recv()
                if data:
                    self.rx_queue.put(data)
            except Exception as e:
                if self.running:
                    print(f"[ERROR] {e}", file=sys.stderr)

    def stop(self) -> None:
        self.running = False
        try:
            super().close()
        except Exception:
            pass
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1)


# ------------------------------ UI Components --------------------------------
class HeaderBar(Static):
    def __init__(self, *, port: str, preset: str, freq: str) -> None:
        self._port = port
        self._preset = preset
        self._freq = freq
        super().__init__(expand=True)

    def on_mount(self) -> None:
        self.update(self.render())  # was: self._render()

    def set_status(self, *, port: Optional[str] = None, preset: Optional[str] = None, freq: Optional[str] = None) -> None:
        if port:
            self._port = port
        if preset:
            self._preset = preset
        if freq:
            self._freq = freq
        self.update(self.render())  # was: self._render()

    def render(self) -> Text:  # was: _render
        t = Text(justify="left")
        t.append(" Meshtastic Chat TUI ", style="bold reverse")
        t.append(f"  Port: {self._port}  ")
        t.append(f"Preset: {self._preset}  ")
        t.append(f"Freq: {self._freq} MHz  ")
        t.append(" — Press Q to quit, A for All, 0-7 for channel, F to filter, C to clear", style="dim")
        return t


class ChannelSidebar(Static):
    active_channel: reactive[Optional[int]] = reactive(None)

    def __init__(self) -> None:
        super().__init__(expand=True)
        self._counts: Dict[Optional[int], int] = {None: 0}

    def increment(self, ch: int) -> None:
        self._counts[ch] = self._counts.get(ch, 0) + 1
        self._counts[None] = self._counts.get(None, 0) + 1
        self.update(self.render())  # was: self._render()

    def set_active(self, ch: Optional[int]) -> None:
        self.active_channel = ch
        self.update(self.render())  # was: self._render()

    def render(self) -> Text:  # was: _render
        t = Text()
        t.append(" Channels\n", style="bold underline")
        def line(label: str, ch_key: Optional[int]) -> None:
            count = self._counts.get(ch_key, 0)
            is_active = self.active_channel == ch_key
            style = "bold white on blue" if is_active else ""
            t.append(f"{label:<10} ", style=style)
            t.append(f"{count:>5}\n", style="dim")
        line("All", None)
        for ch in sorted(k for k in self._counts.keys() if isinstance(k, int)) or list(range(0, 8)):
            if ch not in self._counts:
                self._counts[ch] = 0
            line(f"Ch {ch}", ch)
        return t


class ChatTable(DataTable):
    def on_mount(self) -> None:
        self.add_columns("Time", "Ch", "From", "Message")
        self.cursor_type = "row"
        self.zebra_stripes = True
        self.fixed_columns = 1
        self.show_header = True
        #self.styles.border = ("heavy",)
        self.styles.height = "100%"

    def add_message(self, msg: ChatMessage) -> None:
        self.add_row(*msg.as_row())
        # Auto-scroll to bottom if currently at bottom
        if self.row_count > 0 and self.cursor_row == self.row_count - 2:
            self.move_cursor(row=self.row_count - 1)
        # Keep selection at latest
        self.cursor_type = "row"


class StatusBar(Static):
    def set_text(self, text: str) -> None:
        self.update(Text(text))


# ------------------------------ Main App -------------------------------------
class MeshtasticChatApp(App):
    CSS = """
    Screen {
        layout: vertical;
    }
    # Top status bar
    .header { height: 3; }
    # Body split: sidebar + table
    .body { height: 1fr; }
    .sidebar {
        width: 22;
        border: heavy $surface;
        padding: 1 1;
    }
    .main {
        border: heavy $surface;
    }
    .footer { height: 1; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("a", "filter_all", "All"),
        Binding("f", "filter_text", "Find"),
        Binding("c", "clear_filter", "Clear"),
        # numeric channels 0-7
        *[Binding(str(d), f"filter_channel({d})", f"Ch {d}") for d in range(0, 8)],
    ]

    def __init__(self, *, monitor: Monitor, preset: str, freq: str) -> None:
        super().__init__()
        self.monitor = monitor
        self.rx_queue = monitor.rx_queue  # type: ignore[attr-defined]
        self.async_rx_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.keys = [base64.b64decode(k) for k in DEFAULT_KEYS]
        self.node_registry = NodeRegistry()
        self.header = HeaderBar(port=self.monitor.port, preset=preset, freq=str(freq))  # type: ignore[arg-type]
        self.sidebar = ChannelSidebar()
        self.table = ChatTable()
        self.footer = Footer()
        self.status = StatusBar()
        self.filter_text: Optional[str] = None
        self.active_channel: Optional[int] = None

    # ---------------------- Compose UI ----------------------
    def compose(self) -> ComposeResult:
        yield Container(self.header, classes="header")
        with Horizontal(classes="body"):
            yield Container(self.sidebar, classes="sidebar")
            yield Container(self.table, classes="main")
        yield self.footer

    # ---------------------- Lifecycle -----------------------
    async def on_mount(self) -> None:
        # Start a background task to ferry data from thread queue -> asyncio queue
        self.set_interval(0.05, self._pump_thread_queue)
        # periodic status refresh
        self.set_interval(1.0, lambda: self.header.set_status())


    def _pump_thread_queue(self) -> None:
        moved = 0
        while True:
            try:
                frame = self.rx_queue.get_nowait()
            except queue.Empty:
                break
            else:
                # we're already on the app's thread; use put_nowait
                self.async_rx_queue.put_nowait(frame)
                moved += 1
        if moved:
            # schedule the coroutine to handle the frames
            asyncio.create_task(self._process_available())

    async def _process_frame(self, frame: bytes) -> None:
        try:
            raw = extract_frame(frame)
            fields = extract_fields(raw)
        except Exception:
            return
        # try keys
        for key in self.keys:
            try:
                decrypted = decrypt(fields["payload"], key, fields["sender"], fields["packet_id"])
            except Exception:
                continue
            msg = self._decode_any(decrypted, fields)
            if msg is not None:
                await self._handle_decoded(msg)
                break

    def _decode_any(self, decrypted: bytes, fields: Dict[str, bytes]) -> Optional[Tuple[str, Dict]]:
        # return (type, data)
        pb = mesh_pb2.Data()
        try:
            pb.ParseFromString(decrypted)
        except Exception:
            return None
        # Common meta
        src_hex = fields["sender"].hex().upper()
        dst_hex = fields["dest"].hex().upper()
        channel = getattr(pb, "channel", 0)  # default 0 if missing

        if pb.portnum == 1:  # TEXT
            try:
                text = pb.payload.decode(errors="replace")
            except Exception:
                text = "(decode error)"
            return (
                "text",
                {
                    "channel": int(channel),
                    "src_hex": src_hex,
                    "dst_hex": dst_hex,
                    "text": sanitize_text(text),
                },
            )
        elif pb.portnum == 4:  # NODEINFO
            try:
                user = mesh_pb2.User()
                user.ParseFromString(pb.payload)
                return ("nodeinfo", {"user": user})
            except Exception:
                return None
        else:
            return None

    async def _handle_decoded(self, item: Tuple[str, Dict]) -> None:
        kind, data = item
        if kind == "nodeinfo":
            user: mesh_pb2.User = data["user"]
            self.node_registry.set_from_user_pb(user)
            return
        if kind == "text":
            ch = data["channel"]
            src_hex = data["src_hex"]
            text = data["text"]
            name = self.node_registry.resolve(src_hex)
            msg = ChatMessage(ts=time.time(), channel=ch, sender_id_hex=src_hex, sender_name=name, text=text)
            # Filter logic
            if self._passes_filter(msg):
                self.table.add_message(msg)
            # Always increment counts
            self.sidebar.increment(ch)

    def _passes_filter(self, msg: ChatMessage) -> bool:
        if self.active_channel is not None and msg.channel != self.active_channel:
            return False
        if self.filter_text:
            ft = self.filter_text.lower()
            if ft not in msg.sender_name.lower() and ft not in msg.text.lower():
                return False
        return True

    # Process frames queued for asyncio
    async def _process_available(self) -> None:
        while not self.async_rx_queue.empty():
            frame = await self.async_rx_queue.get()
            await self._process_frame(frame)

    # ------------------------- Actions / Keys -------------------------
    def action_quit(self) -> None:
        self.exit()

    def action_filter_all(self) -> None:
        self.active_channel = None
        self.sidebar.set_active(None)
        self._refresh_table()

    def action_clear_filter(self) -> None:
        self.filter_text = None
        self._refresh_table()

    def action_filter_channel(self, channel: int) -> None:
        self.active_channel = int(channel)
        self.sidebar.set_active(self.active_channel)
        self._refresh_table()

    def action_filter_text(self) -> None:
        def on_submit(value: str) -> None:
            self.filter_text = value.strip() or None
            self._refresh_table()
            self.pop_screen()

        # lightweight inline prompt
        prompt = InlinePrompt("Filter (name/message): ", on_submit)
        self.push_screen(prompt)

    def _refresh_table(self) -> None:
        # Rebuild table with current filters — we don't persist all rows locally for memory reasons.
        # In a longer-running app, you may store a ring buffer of recent messages and re-render from that.
        self.table.clear(columns=False)
        # No backlog available; future messages will respect filters.
        status = "All channels" if self.active_channel is None else f"Channel {self.active_channel}"
        if self.filter_text:
            status += f" — filter: {self.filter_text!r}"
        self.status.set_text(status)


class InlinePrompt(App):
    """Minimal inline prompt screen to capture a single line of input."""

    CSS = """
    Screen { align: center middle; }
    #panel { width: 80%; border: round green; padding: 1 2; }
    """

    def __init__(self, label: str, on_submit) -> None:
        super().__init__()
        self.label = label
        self.on_submit = on_submit
        self.input = Input(placeholder="type and press Enter…")

    def compose(self) -> ComposeResult:
        yield Container(self.sidebar, classes="sidebar")
        yield self.input

    async def on_mount(self) -> None:
        await self.input.focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:  # type: ignore[override]
        self.on_submit(event.value)


# ------------------------------- Entrypoint ----------------------------------
async def run_app(args) -> None:
    rx_queue: queue.Queue = queue.Queue()
    mon = Monitor(args.port, args.baudrate, rx_queue)
    mon.start()

    # Configure radio
    mon.transmit(f"set_bw {CHANNELS_PRESET[args.preset]['bw']}")
    mon.transmit(f"set_sf {CHANNELS_PRESET[args.preset]['sf']}")
    mon.transmit(f"set_cr {CHANNELS_PRESET[args.preset]['cr']}")
    mon.transmit(f"set_pl {CHANNELS_PRESET[args.preset]['pl']}")
    mon.transmit(f"set_sw {SYNC_WORLD}")
    mon.transmit(f"set_freq {args.frequency}")
    mon.transmit("set_rx")

    try:
        app = MeshtasticChatApp(monitor=mon, preset=args.preset, freq=str(args.frequency))
        await app.run_async()

    finally:
        mon.stop()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", default=catsniffer.find_catsniffer_serial_port())
    parser.add_argument("-baud", "--baudrate", type=int, default=catsniffer.DEFAULT_BAUDRATE)
    parser.add_argument("-f", "--frequency", default=902)
    parser.add_argument("-ps", "--preset", choices=CHANNELS_PRESET.keys(), default="LongFast")
    args = parser.parse_args()

    try:
        asyncio.run(run_app(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

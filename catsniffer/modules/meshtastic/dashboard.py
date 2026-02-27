#!/usr/bin/env python3
"""
Meshtastic Chat TUI Dashboard
Updated for Catsniffer FW with FSK support
"""

from __future__ import annotations
import argparse
import asyncio
import base64
import os
import queue
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .core import (
    DEFAULT_KEYS,
    SYNC_WORD_MESHTASTIC,
    CHANNELS_PRESET,
    msb2lsb,
    extract_frame,
    extract_fields,
    decrypt
)

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
from modules.catsniffer import LoRaConnection
from protocol.sniffer_sx import SnifferSx
from meshtastic import mesh_pb2, admin_pb2, telemetry_pb2
from meshtastic import mesh_pb2, admin_pb2, telemetry_pb2

# -------------------------- Radio / decoding helpers -------------------------
from .core import (
    DEFAULT_KEYS,
    SYNC_WORD_MESHTASTIC,
    CHANNELS_PRESET,
    msb2lsb,
    extract_frame,
    extract_fields,
    decrypt
)


# ------------------------------- Data models --------------------------------


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
        # Try to map by full ID
        for node_id, name in self._by_id.items():
            if node_id.endswith(node_id_hex) or node_id_hex in node_id:
                return name
        return node_id_hex


# --------------------------- Text sanitation ---------------------------------
CONTROL_REPLACEMENT = "�"


def sanitize_text(s: str) -> str:
    """Cleans the text for display in terminal"""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = "".join(
        (
            ch
            if (ch == "\n" or ch == "\t" or (31 < ord(ch) < 127) or ord(ch) >= 0xA0)
            else CONTROL_REPLACEMENT
        )
        for ch in s
    )
    return rich_escape(s)


# --------------------------- Radio monitor thread ----------------------------
class Monitor(LoRaConnection):
    def __init__(self, port: str, baudrate: int, rx_queue: queue.Queue) -> None:
        super().__init__(port)
        self.baudrate = baudrate
        self.rx_queue = rx_queue
        self.running = True
        self.thread = None
        self.last_keepalive = 0

    def start(self) -> None:
        self.connect()
        self.thread = threading.Thread(target=self._recv_worker, daemon=True)
        self.thread.start()

    def _recv_worker(self) -> None:
        while self.running:
            try:
                # Keepalive to keep the firmware semaphore active
                now = time.time()
                if now - self.last_keepalive > 2.0:
                    try:
                        self.connection.write(b"\x00")
                        self.connection.flush()
                        self.last_keepalive = now
                    except Exception:
                        pass

                # Read line from serial port
                data = self.readline()
                if data:
                    self.rx_queue.put(data)
            except Exception as e:
                if self.running:
                    print(f"[ERROR] {e}", file=sys.stderr)

    def stop(self) -> None:
        self.running = False
        try:
            self.disconnect()
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
        self.update(self.render())

    def set_status(
        self,
        *,
        port: Optional[str] = None,
        preset: Optional[str] = None,
        freq: Optional[str] = None,
    ) -> None:
        if port:
            self._port = port
        if preset:
            self._preset = preset
        if freq:
            self._freq = freq
        self.update(self.render())

    def render(self) -> Text:
        t = Text(justify="left")
        t.append(" Meshtastic Chat TUI ", style="bold reverse")
        t.append(f"  Port: {self._port}  ")
        t.append(f"Preset: {self._preset}  ")
        t.append(f"Freq: {self._freq} MHz  ")
        t.append(
            " — Press Q to quit, A for All, 0-7 for channel, F to filter, C to clear",
            style="dim",
        )
        return t


class ChannelSidebar(Static):
    active_channel: reactive[Optional[int]] = reactive(None)

    def __init__(self) -> None:
        super().__init__(expand=True)
        self._counts: Dict[Optional[int], int] = {None: 0}

    def increment(self, ch: int) -> None:
        self._counts[ch] = self._counts.get(ch, 0) + 1
        self._counts[None] = self._counts.get(None, 0) + 1
        self.update(self.render())

    def set_active(self, ch: Optional[int]) -> None:
        self.active_channel = ch
        self.update(self.render())

    def render(self) -> Text:
        t = Text()
        t.append(" Channels\n", style="bold underline")

        def line(label: str, ch_key: Optional[int]) -> None:
            count = self._counts.get(ch_key, 0)
            is_active = self.active_channel == ch_key
            style = "bold white on blue" if is_active else ""
            t.append(f"{label:<10} ", style=style)
            t.append(f"{count:>5}\n", style="dim")

        line("All", None)
        for ch in range(8):
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
        self.styles.height = "100%"

    def add_message(self, msg: ChatMessage) -> None:
        self.add_row(*msg.as_row())
        # Auto-scroll to bottom if currently at bottom
        if self.row_count > 0 and self.cursor_row == self.row_count - 2:
            self.move_cursor(row=self.row_count - 1)


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
        *[Binding(str(d), f"filter_channel({d})", f"Ch {d}") for d in range(0, 8)],
    ]

    def __init__(self, *, monitor: Monitor, preset: str, freq: str) -> None:
        super().__init__()
        self.monitor = monitor
        self.rx_queue = monitor.rx_queue
        self.async_rx_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.keys = [base64.b64decode(k) for k in DEFAULT_KEYS]
        self.node_registry = NodeRegistry()
        self.header = HeaderBar(port=monitor.port, preset=preset, freq=str(freq))
        self.sidebar = ChannelSidebar()
        self.table = ChatTable()
        self.footer = Footer()
        self.status = StatusBar()
        self.filter_text: Optional[str] = None
        self.active_channel: Optional[int] = None
        self.packet_count = 0

    # ---------------------- Compose UI ----------------------
    def compose(self) -> ComposeResult:
        yield Container(self.header, classes="header")
        with Horizontal(classes="body"):
            yield Container(self.sidebar, classes="sidebar")
            yield Container(self.table, classes="main")
        yield self.footer

    # ---------------------- Lifecycle -----------------------
    async def on_mount(self) -> None:
        self.set_interval(0.05, self._pump_thread_queue)
        self.set_interval(1.0, lambda: self.header.set_status())

    def _pump_thread_queue(self) -> None:
        moved = 0
        while True:
            try:
                frame = self.rx_queue.get_nowait()
            except queue.Empty:
                break
            else:
                self.async_rx_queue.put_nowait(frame)
                moved += 1
        if moved:
            asyncio.create_task(self._process_available())

    async def _process_frame(self, frame: bytes) -> None:
        try:
            raw = extract_frame(frame)
            if not raw or len(raw) < 16:
                return
                
            fields = extract_fields(raw)
            if not fields or len(fields.get("payload", b"")) == 0:
                return
                
        except Exception as e:
            return
            
        # Try with all keys
        decrypted_success = False
        for key in self.keys:
            try:
                decrypted = decrypt(
                    fields["payload"], key, fields["sender"], fields["packet_id"]
                )
                msg = self._decode_any(decrypted, fields)
                if msg is not None:
                    await self._handle_decoded(msg)
                    decrypted_success = True
                    break
            except Exception:
                continue

        if not decrypted_success:
            # Intentar interpretar como texto plano (canales abiertos)
            try:
                raw_payload = fields["payload"]
                plain_text = raw_payload.decode('utf-8', errors='ignore')
                if plain_text.isprintable() and len(plain_text) > 0:
                    # Crear mensaje emulado
                    ch = fields.get("channel", b"\x00")[0]
                    src_hex = fields["sender"].hex().upper()
                    name = self.node_registry.resolve(src_hex)
                    msg_obj = ChatMessage(
                        ts=time.time(),
                        channel=ch,
                        sender_id_hex=src_hex,
                        sender_name=name,
                        text=f"[PLAIN] {plain_text}",
                    )
                    self.packet_count += 1
                    if self._passes_filter(msg_obj):
                        self.table.add_message(msg_obj)
                    self.sidebar.increment(ch)
            except:
                pass

    def _decode_any(
        self, decrypted: bytes, fields: Dict[str, bytes]
    ) -> Optional[Tuple[str, Dict]]:
        pb = mesh_pb2.Data()
        try:
            pb.ParseFromString(decrypted)
        except Exception:
            return None
            
        src_hex = fields["sender"].hex().upper()
        dst_hex = fields["dest"].hex().upper()
        channel = fields.get("channel", b"\x00")[0]

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
            
            msg = ChatMessage(
                ts=time.time(),
                channel=ch,
                sender_id_hex=src_hex,
                sender_name=name,
                text=text,
            )
            
            self.packet_count += 1
            
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

        # Use Input directly
        input_widget = Input(placeholder="Enter filter text...")
        input_widget.on_submit = on_submit
        self.push_screen(input_widget)

    def _refresh_table(self) -> None:
        self.table.clear(columns=False)
        status = (
            "All channels"
            if self.active_channel is None
            else f"Channel {self.active_channel}"
        )
        if self.filter_text:
            status += f" — filter: {self.filter_text!r}"
        self.status.set_text(status)


# ------------------------------- Entrypoint ----------------------------------
async def run_app(args) -> None:
    rx_queue: queue.Queue = queue.Queue()
    mon = Monitor(args.port, args.baudrate, rx_queue)
    mon.start()

    # Configure radio using commands from the new firmware
    print(f"[*] Configuring radio on {args.port}...")
    # Use specific commands from the updated firmware
    commands = [
        f"lora_freq {int(args.frequency * 1_000_000)}",
        f"lora_sf {CHANNELS_PRESET[args.preset]['sf']}",
        f"lora_bw {CHANNELS_PRESET[args.preset]['bw']}",  # Note: uses index, not kHz
        f"lora_cr {CHANNELS_PRESET[args.preset]['cr']}",
        f"lora_preamble {CHANNELS_PRESET[args.preset]['pl']}",
        f"lora_syncword 0x{SYNC_WORD_MESHTASTIC:02X}",  # CORRECTED: 0x2B
        "lora_apply",
        "lora_mode stream"
    ]
    
    for cmd in commands:
        print(f"  > {cmd}")
        mon.write(f"{cmd}\r\n".encode())
        await asyncio.sleep(0.1)

    try:
        app = MeshtasticChatApp(
            monitor=mon, preset=args.preset, freq=str(args.frequency)
        )
        await app.run_async()

    finally:
        mon.stop()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Meshtastic Chat TUI - Updated for Catsniffer FW",
        epilog="""
Examples:
  python dashboard.py -p /dev/ttyUSB1
  python dashboard.py -p COM3 -f 902 -ps LongFast
        """,
    )
    parser.add_argument(
        "-p",
        "--port",
        required=True,
        help="Serial port for CatSniffer LoRa device",
    )
    parser.add_argument(
        "-baud",
        "--baudrate",
        type=int,
        default=115200,
        help="Baudrate (default: 115200)",
    )
    parser.add_argument(
        "-f",
        "--frequency",
        type=float,
        default=906.875,
        help="Frequency in MHz (default: 906.875)",
    )
    parser.add_argument(
        "-ps",
        "--preset",
        choices=list(CHANNELS_PRESET.keys()),
        default="LongFast",
        help="Channel preset (default: LongFast)",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run_app(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
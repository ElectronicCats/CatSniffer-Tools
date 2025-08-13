# Meshtastic Chat TUI

A **beautiful, scrollable, interactive terminal dashboard** for monitoring Meshtastic traffic in real time for defcon33
It uses [`textual`](https://github.com/Textualize/textual) for a responsive terminal interface, `catsniffer` for packet capture, and Meshtastic protobufs to decode and display chat messages with sender names and channels.

---

## ✨ Features

### 📡 Real-time packet capture
- Reads LoRa frames from a `catsniffer` device over serial.
- Supports **any baud rate**, preset, and frequency supported by the radio.

### 🔑 Automatic decryption
- Tries multiple default AES keys (`DEFAULT_KEYS` list) for each packet.
- Automatically detects the correct key and decodes messages.

### 🗨 Chat-focused display
- **Left sidebar**: Lists all detected channels (`0–7`), plus an `All` view.
- Shows **unread counts** for each channel.
- Highlights the **active channel**.

- **Main table**: Scrollable chat history with:
  1. **Time** (HH:MM:SS)
  2. **Channel**
  3. **From** (resolved name or node ID)
  4. **Message** (safe rendering of special characters)

### 📇 Name resolution
- Learns node names from **NODEINFO** packets.
- Displays human-readable names instead of raw IDs.

### 🔍 Live filtering
- **Filter by channel**: Press `0`–`7` to see only messages from that channel.
- **Show all**: Press `A` to reset to all channels.
- **Search filter**: Press `F` and type to filter by **name or message content**.
- **Clear filter**: Press `C`.

### 🎨 Theming
- Fully compatible with `textual` themes.
- Switch to **dark mode** or **light mode** using `--theme` or Textual’s built-in theme toggle (see below).

### 🖥 Maximization
- Terminal-based full-screen mode.
- **On Linux/macOS**: use `F11` in most terminals to maximize.
- **On Windows Terminal**: `Alt + Enter` for true full-screen.
- For smaller windows, the UI auto-adjusts.

### 🔄 Auto-refresh
- New messages appear instantly.
- Scrollback buffer keeps recent history visible.
- Unread counts update in the sidebar in real time.

### 🛡 Safe text handling
- Escapes Rich markup to prevent style injection.
- Replaces control characters with `�`.

---

## 📦 Requirements

```bash
pip install textual rich cryptography meshtastic catsniffer
```
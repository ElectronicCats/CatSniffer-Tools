# CatSniffer TUI Testbench

Production-quality multi-device testbench for CatSniffer hardware validation, manufacturing testing, and debugging.

## Features

- **Multi-device discovery**: Auto-detects and groups USB CDC endpoints (CDC0/CDC1/CDC2) per physical device
- **Hotplug support**: Continuous background scanning without UI blocking
- **Button-driven UX**: No manual command typing required
- **Smoke test suite**: Automated 11-step validation sequence
- **Fleet actions**: Batch operations across all devices
- **Interactive terminals**: Direct serial port access for debugging
- **Comprehensive logging**: Ring buffer with export capability

## Quick Start

```bash
cd catsnifferTUI
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or: .venv\Scripts\activate  # Windows
pip install -r requirements.txt
python -m catsnifferTUI
```

## Linux Permissions

```bash
sudo usermod -a -G dialout $USER
# Log out and back in for changes to take effect
```

## Keybindings

| Key | Action |
|-----|--------|
| `Q` | Quit |
| `R` | Rescan devices |
| `0` | All Devices tab |
| `1-4` | Device tabs |
| `L` | Focus logs |

## Device Endpoints

Each CatSniffer has 3 USB CDC endpoints:

| Port | Name | Purpose |
|------|------|---------|
| CDC0 | Cat-Bridge | CC1352 HCI UART (binary passthrough) |
| CDC1 | Cat-LoRa | SX1262 LoRa/FSK control |
| CDC2 | Cat-Shell | Configuration shell |

## Smoke Test Sequence

1. CDC2: `status`
2. CDC2: `band3`
3. CDC2: `modulation lora`
4. CDC2: `lora_mode command`
5. CDC2: `lora_config`
6. CDC2: `lora_apply`
7. CDC1: `TEST`
8. CDC1: `TXTEST`
9. CDC2: `modulation fsk`
10. CDC2: `fsk_apply`
11. CDC1: `FSKTEST`

## Architecture

```
catsnifferTUI/
├── main.py              # Entry point, Textual app
├── discovery.py         # USB/serial discovery
├── device.py            # Device and endpoint handlers
├── terminal.py          # Interactive terminal modal
├── widgets.py           # Custom TUI widgets
├── screens.py           # Tab screens
├── testbench.py         # Smoke test logic
├── logging.py           # Ring buffer logs
└── constants.py         # Configuration constants
```

## Adding New Commands

1. Add command to `constants.py` in `CDC2_COMMANDS` or `CDC1_LORA_COMMANDS`
2. Add button in `screens.py` DeviceScreen
3. Update smoke test in `testbench.py` if needed

## Requirements

- Python 3.11+
- textual >= 0.47.0
- pyserial >= 3.5
- pyusb >= 1.2.1

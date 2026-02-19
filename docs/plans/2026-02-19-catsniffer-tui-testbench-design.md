# CatSniffer Multi-Device TUI Testbench - Design Document

**Date:** 2026-02-19
**Status:** Approved
**Location:** `catsnifferTUI/`

## 1. Overview

Production-quality TUI testbench for CatSniffer hardware validation, manufacturing testing, and debugging. Targets macOS + Linux with zero configuration.

### Goals
- Multi-device auto-discovery with reliable endpoint grouping
- Hotplug support without UI blocking
- Button-driven "bench instrument" UX (no manual command typing)
- Comprehensive smoke test suite
- Full logging with export capability
- Interactive serial terminal for debugging

### Non-Goals
- End-user tool (this is for validation/manufacturing/debug)
- Windows-specific optimizations (works, but not primary target)

---

## 2. Architecture

### 2.1 Package Structure

```
catsnifferTUI/
├── main.py              # Entry point, Textual app, hotplug timer
├── discovery.py         # USB/serial discovery, device grouping
├── device.py            # CatSnifferDevice, EndpointHandler, command queues
├── terminal.py          # InteractiveSerialTerminal modal screen
├── widgets.py           # Custom TUI widgets
├── screens.py           # Tab screens (AllDevices, DeviceScreen)
├── testbench.py         # SmokeTestRunner, test sequences
├── logging.py           # RingBufferLog, LogEntry, export
├── constants.py         # VID/PID, timeouts, command definitions
└── requirements.txt
```

### 2.2 Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        main.py (App)                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Hotplug Task │  │  Tab Router  │  │   Log Aggregator     │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                      │              │
│         ▼                 ▼                      ▼              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              DeviceManager (singleton)                    │  │
│  │   - Dict[DeviceIdentity, CatSnifferDevice]               │  │
│  │   - discover_devices() on 1s interval                    │  │
│  │   - Emits: DeviceAdded, DeviceRemoved, DeviceChanged     │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
       ┌──────────┐    ┌──────────┐    ┌──────────┐
       │ Device 1 │    │ Device 2 │    │ Device N │
       │ ┌──────┐ │    │ ┌──────┐ │    │ ┌──────┐ │
       │ │CDC0  │ │    │ │CDC0  │ │    │ │CDC0  │ │
       │ ├──────┤ │    │ ├──────┤ │    │ ├──────┤ │
       │ │CDC1  │ │    │ │CDC1  │ │    │ │CDC1  │ │
       │ ├──────┤ │    │ ├──────┤ │    │ ├──────┤ │
       │ │CDC2  │ │    │ │CDC2  │ │    │ │CDC2  │ │
       │ └──────┘ │    │ └──────┘ │    │ └──────┘ │
       └──────────┘    └──────────┘    └──────────┘
              │
              ▼ (on click)
       ┌─────────────────────────────────────┐
       │   InteractiveSerialTerminal         │
       │   (modal screen for raw I/O)        │
       └─────────────────────────────────────┘
```

---

## 3. Device Discovery & Grouping

### 3.1 Constants

```python
CATSNIFFER_VID = 0x1209
CATSNIFFER_PID = 0xBABB
DEFAULT_BAUDRATE = 115200

ENDPOINT_BRIDGE = "Cat-Bridge"  # CDC0 - CC1352 HCI UART
ENDPOINT_LORA = "Cat-LoRa"      # CDC1 - SX1262 LoRa/FSK
ENDPOINT_SHELL = "Cat-Shell"    # CDC2 - Config/Debug shell
```

### 3.2 Discovery Algorithm

1. Get all serial ports from `serial.tools.list_ports.comports()`
2. Filter by VID/PID match (0x1209:0xBABB)
3. Sort by device name for cross-platform consistency
4. Group by serial number extracted from `hwid` field:
   - Regex: `SER=([A-Fa-f0-9]+)`
   - Fallback: `location` field
5. For each group of 3+ ports:
   - Map endpoints by description keywords (shell/lora/bridge)
   - Fallback to positional ordering (0=Bridge, 1=LoRa, 2=Shell)
6. Create `CatSnifferDevice` if mapping successful
7. Mark as partial if endpoints missing

### 3.3 Endpoint Mapping Priority

| Priority | Method | Pattern |
|----------|--------|---------|
| 1 | Description | "shell" → CDC2, "lora" → CDC1, "bridge" → CDC0 |
| 2 | Positional | ports[0]→Bridge, ports[1]→LoRa, ports[2]→Shell |

### 3.4 Device Identity

```python
@dataclass(frozen=True)
class DeviceIdentity:
    """Stable identity for tab ordering across rescans."""
    serial_number: str
    usb_bus: Optional[int]
    usb_address: Optional[int]
```

### 3.5 Device Health States

| State | Condition |
|-------|-----------|
| HEALTHY | All 3 endpoints present |
| PARTIAL | Missing endpoints but has CDC2 |
| CRITICAL | Missing CDC2 (cannot configure) |

---

## 4. Serial Communication Model

### 4.1 EndpointHandler

Manages single serial port with:
- Async background reader task
- Command queue with timeout/retry
- Ring buffer for all I/O
- Mode tracking (CDC1 stream vs command)

```python
class EndpointHandler:
    async def connect(self) -> bool
    async def disconnect(self)
    async def send_command(command, timeout=2.0, retry=1, expected_match=None) -> CommandResult
    async def send_raw(data: bytes) -> bool
```

### 4.2 Command Result

```python
@dataclass
class CommandResult:
    command: str
    status: Literal["PASS", "FAIL", "TIMEOUT", "ERROR"]
    response: Optional[str]
    duration_ms: float
    retries: int
    error: Optional[str]
```

### 4.3 Mode Guardrails

- CDC1 stream mode: Block command-mode commands, show warning
- Modulation change: Block TX attempts during transition
- Missing endpoint: Disable related UI controls

---

## 5. UI Layout

### 5.1 Overall Structure

```
┌─────────────────────────────────────────────────────────────────────┐
│ [All Devices] [CatSniffer #1] [CatSniffer #2] ...     🔌 3 devices │ ← Tab bar
├─────────────────────────────────────────────────────────────────────┤
│ ┌─────────────┐ ┌─────────────────────────────────────────────────┐│
│ │ Device List │ │                                                 ││
│ │ ● #1 Bridge │ │              MAIN CONTENT AREA                  ││
│ │ ● #1 LoRa   │ │         (varies by selected tab)               ││
│ │ ● #1 Shell  │ │                                                 ││
│ │             │ │                                                 ││
│ │ ● #2 Bridge │ │                                                 ││
│ │ ● #2 LoRa   │ │                                                 ││
│ │ ● #2 Shell  │ │                                                 ││
│ └─────────────┘ └─────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────────────┤
│ Device: [All ▼] Endpoint: [ALL ▼] Search: [____] [MARK] [Export]  │ ← Log bar
│ ┌─────────────────────────────────────────────────────────────────┐│
│ │ 10:23:45.123 [#1][CDC2] > status                               ││
│ │ 10:23:45.125 [#1][CDC2] < Mode: Passthrough | Band: LoRa       ││
│ │ 10:23:46.000 [#2][CDC1] < RX: A1B2C3 | RSSI: -45 | SNR: 8     ││
│ └─────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────┘
```

### 5.2 All Devices Tab

Summary grid:
| Device | CDC0 | CDC1 | CDC2 | Last Status | LoRa Mode | Modulation | Last RX |
|--------|------|------|------|-------------|-----------|------------|---------|
| #1 | ● | ● | ● | 10:23:45 | command | lora | 10:23:46 |
| #2 | ● | ◐ | ● | 10:22:10 | stream | fsk | -- |

Fleet Actions Panel:
- Set all band1/band2/band3 (with confirm)
- Set all LoRa freq (input + confirm)
- Run Smoke Test on All (parallel, rate-limited to 3)

### 5.3 Device Tab (3 columns)

**Column A: CDC2 Config Panel**
- Mode/Band buttons: boot, exit, band1, band2, band3, reboot, status
- LoRa config: freq, sf, bw, cr, power, preamble, syncword, iq, lora_mode
  - Buttons: "Show Config" (lora_config), "Apply" (lora_apply)
- FSK config: freq, bitrate, fdev, bw, power, preamble, syncword, crc
  - Buttons: "Show Config" (fsk_config), "Apply" (fsk_apply)
- Modulation toggle: lora | fsk
- CC1352 FW ID: input + set/get/clear/list
- Status: last command, last response, last error

**Column B: CDC1 LoRa/FSK Panel**
- Mode toggle: stream | command (sends CDC2 lora_mode)
- LoRa buttons: TEST, TXTEST, TX (hex input)
- FSK buttons: FSKTEST, FSKTX (hex input), FSKRX
- RX Monitor toggle: Start/Stop
- Live RX view: parsed packets with RSSI/SNR

**Column C: CDC0 CC1352 Panel**
- Monitor toggle (off by default)
- Byte counters (TX/RX)
- "Send bytes" test (hex input) with warning label
- Click to open interactive terminal

### 5.4 Interactive Serial Terminal Modal

Opens when clicking an endpoint in sidebar.

```
┌─────────────────────────────────────────────────────────────────┐
│  Serial Terminal - #1 CDC2 (Shell)                     [X]     │
├─────────────────────────────────────────────────────────────────┤
│  Mode: [Line ▼]  Ending: [CRLF ▼]  Baud: [115200 ▼]            │
├─────────────────────────────────────────────────────────────────┤
│  > help                                                         │
│  Commands: boot, exit, band1, band2, band3, status...          │
│  > status                                                       │
│  Mode: Passthrough | Band: LoRa                                 │
│  > _                                                            │
├─────────────────────────────────────────────────────────────────┤
│  Input: [________________________________] [Send]               │
│  TX: 156 bytes | RX: 2,341 bytes      [Clear] [Close]          │
└─────────────────────────────────────────────────────────────────┘
```

Terminal Modes:
- **Line Mode** (CDC1/CDC2 default): Text lines with CRLF
- **Hex Mode**: Hex input/output display
- **Raw Mode** (CDC0 default): Binary, hex display only

---

## 6. Smoke Test Sequence

### 6.1 Standard Smoke Test (per device)

| Step | Endpoint | Command | Expected Response Contains |
|------|----------|---------|---------------------------|
| 1 | CDC2 | status | "Mode:", "Band:" |
| 2 | CDC2 | band3 | "LoRa" or "band3" |
| 3 | CDC2 | modulation lora | "lora" or "LoRa" |
| 4 | CDC2 | lora_mode command | "COMMAND" |
| 5 | CDC2 | lora_config | "LoRa Configuration:", "Frequency:" |
| 6 | CDC2 | lora_apply | "applied" or "success" |
| 7 | CDC1 | TEST | "TEST" or "ready" |
| 8 | CDC1 | TXTEST | "TX Result" or "Success" |
| 9 | CDC2 | modulation fsk | "fsk" or "FSK" |
| 10 | CDC2 | fsk_apply | "applied" or "success" |
| 11 | CDC1 | FSKTEST | "FSK" or "Success" |

### 6.2 Test Execution

- Sequential steps per device
- Each step shows: timestamp, command, response snippet, PASS/FAIL
- 2 second timeout per command
- 1 retry on failure
- Overall result: PASS if >= 9/11 steps pass

### 6.3 Fleet Smoke Test

- Run on all devices in parallel
- Rate-limit: max 3 concurrent devices
- Aggregate results in summary table

---

## 7. Logging System

### 7.1 Ring Buffer

```python
class RingBufferLog:
    def __init__(self, max_entries: int = 10000):
        self.entries: deque[LogEntry] = deque(maxlen=max_entries)

    def add(self, entry: LogEntry)
    def filter(device_id, endpoint, search: str) -> List[LogEntry]
    def export_to_file(path: str)
```

### 7.2 Log Entry

```python
@dataclass
class LogEntry:
    timestamp: float
    device_id: int
    endpoint: str  # "CDC0", "CDC1", "CDC2"
    direction: str  # "TX" or "RX"
    data: str
    parsed: Optional[Dict]  # For parsed RX lines (RSSI, SNR, etc.)
```

### 7.3 Log Viewer Features

- Device selector dropdown (All + each device)
- Endpoint filter (ALL/CDC0/CDC1/CDC2)
- Search box (filters in real-time)
- MARK button (inserts `--- MARK ---` separator)
- Export button (writes timestamped .log file)

### 7.4 Byte Counters

Per endpoint, per device:
- `bytes_tx: int`
- `bytes_rx: int`
- Reset on device disconnect

---

## 8. Keybindings

| Key | Action |
|-----|--------|
| `Tab` | Cycle through tabs |
| `1-9` | Jump to device tab N |
| `0` | Jump to All Devices tab |
| `R` | Rescan devices |
| `L` | Focus log viewer |
| `Q` | Quit |
| `Escape` | Close modal / unfocus |
| `Enter` | Send in terminal modal |

---

## 9. Error Handling

### 9.1 Connection Errors
- Show red banner with error message
- Disable controls for failed endpoint
- Auto-retry on next rescan

### 9.2 Command Errors
- Display in status widget
- Log with ERROR level
- Include in smoke test results

### 9.3 Device Disconnect During Test
- Mark test as FAILED with reason "Device disconnected"
- Continue UI operation
- Show disconnected banner

### 9.4 Partial Device
- Yellow health indicator
- Disable controls for missing endpoints
- Show warning in device panel

---

## 10. Dependencies

```
textual>=0.47.0
pyserial>=3.5
pyusb>=1.2.1
```

---

## 11. Run Instructions

```bash
cd catsnifferTUI
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
python main.py
```

**Linux Note:** User must be in `dialout` group for serial access:
```bash
sudo usermod -a -G dialout $USER
# Log out and back in
```

---

## 12. Extension Points

### Adding New CDC2 Commands
1. Add to `constants.py` CDC2_COMMANDS list
2. Add button/widget in `screens.py` DeviceScreen
3. Add handler in `testbench.py` if part of smoke test

### Adding New Test Sequences
1. Create new test class in `testbench.py` extending `TestSequence`
2. Define steps as list of (endpoint, command, expected_match)
3. Register in `SmokeTestRunner.available_tests`

### Adding New Parsers
1. Add parser function in `device.py` (e.g., `parse_lora_rx_line`)
2. Register in `EndpointHandler._parse_response` based on endpoint type
3. Parsed data stored in `LogEntry.parsed` dict

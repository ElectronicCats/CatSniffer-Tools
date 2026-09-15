# CatSniffer Tool Analysis & Feature Assessment

**Date**: 2026-09-11
**Analyzed Files**:
- `modules/core/cli.py` — Root CLI architecture
- `modules/device/cli.py` — Device discovery, identification, status
- `modules/sniff/cli.py` — Sniffing commands (BLE, Zigbee, Thread, LoRa, FSK, AirTag)
- `modules/firmware/cli.py` — Flash, verify, update, restore
- `modules/protocols/cli/sx1262.py` — LoRa/FSK tools (spectrum, scan)
- `modules/protocols/cli/meshtastic.py` — Meshtastic protocol tools
- `CatSniffer-Firmware/RP2040/catsniffer/src/main.c` — RP2040 firmware

---

## Architecture Summary

### CLI Structure (Click-based)
```
catnip
├── devices          # List connected CatSniffers
├── identify         # Send identify command
├── status           # Board/firmware/capabilities + diagnostics
├── flash            # Flash CC1352 firmware
├── verify           # Device functionality tests
├── update           # RP2040 firmware update
├── restore          # CC1352 JTAG restore (v3 only)
├── sniff            # Sniffing subcommands
│   ├── ble          # Sniffle BLE
│   ├── zigbee       # TI 15.4
│   ├── thread       # TI 15.4
│   ├── lora         # SX1262 LoRa
│   ├── fsk          # SX1262 FSK/GFSK
│   └── airtag_scanner
├── lora             # LoRa/FSK tools
│   ├── spectrum     # Live spectrum analyzer (via CDC2 shell)
│   └── scan         # SF/BW/freq sweep (via CDC1 stream)
├── meshtastic       # Meshtastic tools
│   ├── decode       # Offline packet decryption
│   ├── live         # Real-time decoder
│   ├── dashboard    # TUI chat interface
│   └── config       # Config file extraction
└── cativity         # (Protocol plugin)
```

### Firmware Capabilities (RP2040 + CC1352 + SX1262)

**USB CDC-ACM Interfaces (3 endpoints)**:
| Port | Firmware Name | Purpose | Baud |
|------|---------------|---------|------|
| CDC0 | Cat-Bridge | CC1352 UART bridge (TI sniffer data) | 921600 |
| CDC1 | Cat-LoRa | SX1262 data stream + command channel | 115200 |
| CDC2 | Cat-Shell | Text shell for config/debug | 115200 |

**Radio Subsystems**:
1. **CC1352** (via UART) — 2.4 GHz (BLE, Zigbee, Thread, 802.15.4) + Sub-GHz (TI 15.4)
2. **SX1262** (via SPI + DIO1 IRQ) — LoRa (150-960 MHz) + FSK/GFSK (137-1020 MHz)

**Firmware Shell Commands (CDC2)**:
```
identify                 # Device identification
help                     # Command list
status                   # Firmware diagnostics (counters, stacks, faults)
lora_config              # Show/set LoRa parameters
lora_mode stream|command # Switch CDC1 mode
fsk_apply                # Apply FSK config
fsk_config               # Show FSK parameters
TEST                     # Radio self-test
TX <hex>                 # LoRa transmit
FSKTEST                  # FSK test packet
FSKTX <hex>              # FSK transmit
FSKRX                    # Start FSK async RX
FSKRXSTOP                # Stop FSK RX
set_start_freq <MHz>     # Spectrum scan start
set_end_freq <MHz>       # Spectrum scan end
start                    # Start spectrum scan
```

**Key Firmware Features**:
- Dual modulation (LoRa/FSK) with automatic RX re-arm
- Ring buffers with overflow/overrun counters
- RF band switching via GPIOs (CTF1/2/3): 2.4 GHz, Sub-GHz 1, Sub-GHz 2
- LED status/animation
- Boot mode detection (BOOTSEL pin)
- LoRa async RX with DIO1 IRQ callback
- FSK async RX with CRC/whitening options

---

## 1. New Features (No Firmware Changes Required)

### A. LoRa/FSK Configuration Profiles & Presets ⭐⭐⭐ **High Impact**
**What**: Save/load named radio configurations as JSON/YAML files.
```bash
catnip lora config save meshtastic-eu --freq 868.1 --sf 7 --bw 125 --sw 0x2B
catnip lora config load meshtastic-eu
catnip lora config list
```
**Why no FW change**: All parameters accepted via existing shell commands (`lora_config`, `fsk_apply`) on CDC2.
**Integration**: New `config` subcommand under `lora` group in `sx1262.py`; uses `ShellConnection` + `queue_radio_command()` pattern from `meshtastic_live`.

---

### B. Multi-Channel LoRa Scanning / Channel Hopping ⭐⭐⭐ **High Impact**
**What**: Rapidly retune SX1262 across frequencies, logging activity per channel.
```bash
catnip lora hop --channels 868.1,868.3,868.5 --dwell 2 --log hop_log.csv
```
**Why no FW change**: Firmware supports `set_frequency` via shell; `lora_scan` already does SF/BW combos.
**Integration**: Extend `LoraScanner` in `protocols/sx1262/scan.py` to support frequency-only sweeps; reuse `build_combos`/`sweep_duration`.

---

### C. LoRaWAN Frame Decoder & Analysis ⭐⭐⭐ **High Impact**
**What**: Real-time LoRaWAN PHY/MAC decoding (join requests, data frames, MIC verification) with device profiling.
```bash
catnip lorawan decode --input capture.pcapng --key <AppKey>
catnip lorawan live --freq 868.1 --sw public
```
**Why no FW change**: Sync word `0x34` (LoRaWAN) already supported in `sniff lora`. Raw frames + RSSI/SNR come through CDC1.
**Integration**: New `protocols/cli/lorawan.py` or subcommand under `meshtastic`; uses existing `run_sx_bridge` output pipe.

---

### D. Continuous Capture with Rotating Files ⭐⭐ **Medium Impact**
**What**: Auto-rotate captures by size/time.
```bash
catnip sniff lora -w capture_%Y%m%d_%H%M.pcapng --rotate-size 100MB --rotate-time 1h
```
**Why no FW change**: Bridge layer already writes pcapng; rotation is host-side file management.
**Integration**: Modify `run_sx_bridge`/`run_fsk_bridge` in `core/bridge.py` to accept rotation params.

---

### E. Real-Time Signal Quality Dashboard ⭐⭐ **Medium Impact**
**What**: Terminal UI showing RSSI/SNR histograms, packet rate, frequency offset estimation, link budget.
```bash
catnip lora monitor --freq 915 --duration 60
```
**Why no FW change**: Every packet includes RSSI/SNR (see `lora_rx_cb`, `fsk_rx_cb`). Statistics computed on host.
**Integration**: New `lora monitor` command; reuse `MeshtasticChatApp` TUI pattern from `meshtastic_dashboard`.

---

### F. Scheduled / Triggered Captures ⭐⭐ **Medium Impact**
**What**: Start captures at specific time or on signal trigger.
```bash
catnip sniff lora -w capture.pcapng --start-at "2026-09-12 02:00" --duration 3600
catnip sniff lora -w capture.pcapng --trigger-rssi -80
```
**Why no FW change**: CLI controls start/stop; firmware streams continuously once configured.
**Integration**: Wrap `run_sx_bridge` with scheduler; use existing `device_session` context manager.

---

### G. Capture Replay & Packet Injection ⭐⭐ **Medium Impact**
**What**: Re-transmit captured packets via `TX <hex>` shell command.
```bash
catnip lora replay capture.pcapng --port /dev/ttyACM1 --rate 10
```
**Why no FW change**: Firmware supports `TX <hex>` and `FSKTX <hex>` commands on CDC2 (see `process_lora_command`).
**Integration**: New `lora replay` command; parse pcapng, extract raw frames, send via `ShellConnection.send_command("TX " + hex)`.

---

### H. Spectrum Waterfall / History View ⭐⭐ **Medium Impact**
**What**: Scrolling historical view of spectrum scans over time.
```bash
catnip lora spectrum --waterfall --start-freq 860 --end-freq 930
```
**Why no FW change**: `lora spectrum` already scans via shell commands on CDC2. Waterfall is host-side rendering.
**Integration**: Extend `SpectrumScan` in `protocols/sx1262/spectrum.py` with curses/rich live table.

---

### I. Protocol-Specific Decoders (Host-Side) ⭐⭐ **Medium Impact**
**What**: Pluggable decoders for 802.15.4g/Wi-SUN, M-Bus, Sigfox, Z-Wave, etc.
```bash
catnip decode --protocol wisun --input capture.pcapng
catnip decode --protocol mbus --input capture.pcapng
```
**Why no FW change**: Firmware outputs raw bytes; decoding entirely host-side (like `MeshtasticDecoder`).
**Integration**: New `decode` subcommand with `--protocol` flag; registry pattern like `fw_aliases.py`.

---

### J. Remote / Headless Operation API ⭐ **Lower Impact**
**What**: REST/gRPC server exposing device control, capture start/stop, file download.
```bash
catnip serve --port 8080 --auth token
# POST /api/v1/devices/1/sniff/lora {freq: 915e6, sf: 7, ...}
# GET  /api/v1/captures/123/download
```
**Why no FW change**: All device interaction via USB serial; server wraps existing CLI commands.
**Integration**: New `serve` command; FastAPI/Flask wrapping `device_session` and bridge functions.

---

## 2. Refinements to Existing Features

### A. Smarter Auto-Band Selection for Sniff Commands ⭐⭐⭐ **High Impact**
**Problem**: `sniff lora`/`sniff fsk` don't auto-switch RF band (CTF GPIOs) — user must know 2.4GHz vs Sub-GHz.
**Fix**: In `sniff_lora`/`sniff_fsk`, infer band from frequency and call `select_rf_band()` (already used in `sniff_ble`).
```python
# In sniff_lora/sniff_fsk before run_sx_bridge:
select_rf_band(dev.shell_port, cc1352_band_command(), "Sub-GHz" if frequency < 500e6 else "2.4 GHz")
```
**Integration**: Add `select_rf_band` call in `sniff_lora`/`sniff_fsk` in `sniff/cli.py`.

---

### B. Capture Loss Reporting for LoRa/FSK ⭐⭐⭐ **High Impact**
**Problem**: `sniff zigbee`/`sniff ble` report ring buffer drops via `report_capture_loss`; `sniff lora`/`sniff fsk` don't.
**Fix**: Call `reset_loss_counters` before capture and `report_capture_loss` after in `run_sx_bridge`/`run_fsk_bridge`.
```python
# In run_sx_bridge / run_fsk_bridge:
loss_armed = reset_loss_counters(dev.shell_port)
try:
    # ... capture ...
    return packet_count
finally:
    report_capture_loss(dev.shell_port, loss_armed)
```
**Integration**: Modify `core/bridge.py`; firmware already tracks `ring_overflow_count` and `uart_overrun_count`.

---

### C. Live Packet Count & Rate in Sniff Commands ⭐⭐⭐ **High Impact**
**Problem**: No real-time packet counter during `sniff lora`/`sniff fsk` (only at end).
**Fix**: Bridge functions return `packet_count`; add periodic status line (every 5s) to console.
**Integration**: Update `run_sx_bridge`/`run_fsk_bridge` to print rolling count; reuse `verbose` flag.

---

### D. Unified Output Format Options ⭐⭐ **Medium Impact**
**Problem**: `sniff zigbee` has `--raw-file`, `--ascii-file`, `--pcap-file`; `sniff lora`/`sniff fsk` same but inconsistent help text.
**Fix**: Standardize via shared option decorators (already exist in `cli_options.py`). Add `--format json|csv|kismet`.
**Integration**: Extend bridge writers; add formatters in `core/bridge.py`.

---

### E. Better Error Messages for Sync Word Mismatches ⭐⭐ **Medium Impact**
**Problem**: Silent capture (no packets) when sync word wrong — no hint.
**Fix**: After capture, if `packet_count == 0` and `--verbose`, suggest alternatives.
```python
if packet_count == 0 and verbose:
    if sync_word == "private":
        print_warning("No packets received. Try --sync-word public (LoRaWAN) or --sync-word 0x2B (Meshtastic)")
```
**Integration**: Post-capture check in `sniff_lora`/`sniff_fsk`.

---

### F. Device Status: Show Active Radio Config ⭐⭐ **Medium Impact**
**Problem**: `catnip status` shows firmware/capabilities but not *current* radio settings (freq, SF, BW).
**Fix**: Query `lora_config` and `fsk_config` via shell on CDC2; display in status table.
**Integration**: Extend `read_status` in `firmware/fw_status.py` to parse `lora_config`/`fsk_config` responses.

---

### G. FSK Bandwidth Auto-Correction Warning in CLI ⭐⭐ **Medium Impact**
**Problem**: Firmware silently widens FSK BW if too narrow (see `apply_fsk_config`); CLI warns pre-capture only.
**Fix**: After `fsk_apply`, read back actual BW from firmware and confirm.
**Integration**: In `sniff_fsk`, after config, send `fsk_config` query via shell and compare.

---

### H. Shell Command Completion for `catnip lora` ⭐ **Lower Impact**
**Problem**: No tab-completion for `catnip lora scan --freq`, `--sf`, `--bw` values.
**Fix**: Add `shell_complete` callbacks returning common values (EU/US channels, all SFs, all BWs).
**Integration**: Use Click's `shell_complete` on options in `sx1262.py`.

---

### I. Consistent Verbose Logging Across Sniff Commands ⭐ **Lower Impact**
**Problem**: `sniff ble` uses `-v` flag on group; `sniff lora`/`sniff fsk` have their own `-v`; inconsistent.
**Fix**: Move `-v` to parent `sniff` group (like `ble`); pass verbosity to bridge functions.
**Integration**: Refactor `sniff` group in `sniff/cli.py`; update all subcommands.

---

### J. Progress Indicator for Long Firmware Flashes ⭐ **Lower Impact**
**Problem**: `catnip flash zigbee` shows no progress during multi-MB flash.
**Fix**: Flasher already has progress callbacks; wire to Rich progress bar.
**Integration**: Update `Flasher.flash_firmware` in `firmware/flasher.py` to accept progress callback.

---

## Priority Matrix

| Priority | Feature | Est. Effort | User Impact | Firmware Change |
|----------|---------|-------------|-------------|-----------------|
| **P0** | LoRa/FSK Config Profiles | Low | ⭐⭐⭐ | No |
| **P0** | Capture Loss Reporting (LoRa/FSK) | Low | ⭐⭐⭐ | No |
| **P0** | Auto Band Selection | Low | ⭐⭐⭐ | No |
| **P1** | LoRaWAN Decoder | Medium | ⭐⭐⭐ | No |
| **P1** | Live Packet Counter | Low | ⭐⭐ | No |
| **P1** | Channel Hopping Scanner | Medium | ⭐⭐ | No |
| **P2** | Capture Rotation | Medium | ⭐⭐ | No |
| **P2** | Packet Replay/Injection | Medium | ⭐⭐ | No |
| **P2** | Signal Quality Dashboard | Medium | ⭐⭐ | No |
| **P3** | Scheduled/Triggered Captures | Medium | ⭐ | No |
| **P3** | Protocol Decoders Registry | Medium | ⭐ | No |
| **P3** | Spectrum Waterfall | Medium | ⭐ | No |
| **P4** | Remote API Server | High | ⭐ | No |
| **P4** | Unified Output Formats | Low | ⭐ | No |
| **P4** | Better Sync Word Hints | Low | ⭐ | No |
| **P4** | Status Shows Radio Config | Low | ⭐ | No |
| **P4** | FSK BW Readback Verify | Low | ⭐ | No |
| **P5** | Shell Completion | Low | ⭐ | No |
| **P5** | Consistent Verbose Flags | Low | ⭐ | No |
| **P5** | Flash Progress Bar | Low | ⭐ | No |

---

## Implementation Notes

### Reusable Patterns in Codebase
1. **`ShellConnection`** (`core/usb_connection.py`) — Context manager for CDC2 shell commands
2. **`queue_radio_command()`** (firmware `main.c:439`) — Thread-safe command queue to LoRa thread
3. **`device_session`** (`core/device_session.py`) — Handles firmware flashing, port detection, cleanup
4. **`run_sx_bridge` / `run_fsk_bridge`** (`core/bridge.py`) — Stream CDC1 to pcapng/Wireshark
5. **`Flasher`** (`firmware/flasher.py`) — Firmware download, verification, flashing
6. **Rich Console/TUI** — `console`, `print_info`, `print_success`, `Table`, `Progress` patterns throughout

### Key Integration Points
- **CDC2 (Shell)**: Configuration, status queries, spectrum scan control
- **CDC1 (LoRa/FSK Stream)**: Raw packet data + metadata (RSSI, SNR) for sniffing
- **CDC0 (Bridge)**: CC1352 TI sniffer data (Zigbee/Thread/BLE)
- **Ring Buffers**: Firmware tracks `ring_overflow_count`, `uart_overrun_count` — exposed via `status` command

### Testing Strategy
- Unit tests for new CLI commands (mock `ShellConnection`, `Serial`)
- Integration tests with physical device (CI hardware-in-loop)
- Capture file format validation (pcapng, LoRaTap)
- Regression tests for existing sniff/flash commands

---

## Conclusion

The CatSniffer tool has a **solid, modular architecture** with clear separation between:
- **Transport layer** (USB CDC-ACM, ring buffers)
- **Radio control** (shell commands on CDC2)
- **Data plane** (streaming on CDC1/CDC0)
- **Host-side processing** (bridge, decoders, CLI)

**All proposed features leverage existing firmware capabilities** — no firmware modifications required. The highest-impact, lowest-effort items are:
1. **Config profiles** (eliminates repetitive flags)
2. **Capture loss reporting** (data integrity)
3. **Auto band selection** (prevents silent failures)
4. **LoRaWAN decoder** (major protocol support)

These four alone would significantly improve usability for both casual and power users.

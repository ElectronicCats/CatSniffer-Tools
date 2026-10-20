# Protocol

The wire level: what travels over each of the three serial ports, how frames
become pcap records, and how those records reach Wireshark. This page is for
people changing catnip or writing something that talks to the same firmware.

- [The three ports](#ports)
- [The shell protocol](#shell)
- [The antenna switch](#antenna)
- [CC1352 framing](#ti-framing)
- [SX1262 framing](#sx-framing)
- [pcap output](#pcap)
- [Pipes](#pipes)
- [The CC1352 bootloader](#bootloader)

---

<a id="ports"></a>
## The three ports

One USB composite device (`1209:babb`) exposing three CDC-ACM interfaces.
Each CDC-ACM instance takes two USB interfaces — communication plus data — so
the interface numbers are 0, 2 and 4, not 0, 1, 2:

| Interface | Role | Carries | Wrapper |
|---|---|---|---|
| 0 | `Cat-Bridge` | raw binary to and from the CC1352 | `BridgeConnection` |
| 2 | `Cat-LoRa` | the SX1262 data stream, as **text lines** | `LoRaConnection` |
| 4 | `Cat-Shell` | the host MCU's text command shell | `ShellConnection` |

All three default to **115200 baud**, no hardware flow control. Two details
matter when opening them by hand:

- **DTR polarity differs by role.** `Cat-Bridge` is opened with `DTR=False`
  and `RTS=False`, because asserting them resets the CC1352 — the bootloader
  code toggles them deliberately, and nothing else should. `Cat-LoRa` and
  `Cat-Shell` assert `DTR=True`, which is how Zephyr's CDC-ACM stack learns a
  host is attached (without it, Windows sees no output).
- **Timeouts are centralised**: 2 s read and write, `readline()` capped at
  4096 bytes so a firmware that stops emitting `\n` cannot grow a buffer
  without bound. The LoRa stream uses a shorter 0.5 s read timeout, which is
  what keeps the capture loop responsive to `Ctrl-C` and lets it see natural
  inter-frame gaps.

Role assignment is described in
[Reference](reference.md#device-selection); the three strategies live in
[`usb_connection.py`](../modules/core/usb_connection.py).

---

<a id="shell"></a>
## The shell protocol

Line-oriented text on `Cat-Shell`: write a command, read the reply. It is the
only port that answers questions about the board itself.

| Family | Commands | Used by |
|---|---|---|
| Identity | `fw_version`, `status`, `help`, `identify` | [`status`](commands/status.md), [`devices`](commands/devices.md), [`verify`](commands/verify.md) |
| Firmware id | `cc1352_fw_id get` / `set <id>` / `clear` / `list` | [`status`](commands/status.md), [`flash`](commands/flash.md) |
| Bootloader | `boot`, `exit` | [`flash`](commands/flash.md) |
| LoRa radio | `lora_freq`, `lora_bw`, `lora_sf`, `lora_cr`, `lora_power`, `lora_syncword`, `lora_apply`, `lora_config`, `lora_mode stream\|command` | [`sniff lora`](commands/sniff.md#sniff-lora) |
| FSK radio | `fsk_freq`, `fsk_bitrate`, `fsk_fdev`, `fsk_bw`, `fsk_syncword`, `fsk_preamble`, `fsk_crc`, `fsk_whitening`, `fsk_payload`, `fsk_apply`, `fsk_config` | [`sniff fsk`](commands/sniff.md#sniff-fsk) |
| Antenna | `band1`, `band3` | every capture path |

Two conventions worth knowing:

- **`lora_mode`** switches the `Cat-LoRa` port between `command` (the radio
  accepts configuration) and `stream` (it emits received frames). Capture
  paths set `stream` at the start and `command` on the way out — a session
  killed halfway can leave the board in `stream`.
- **Errors come back as `ERR …` lines**, not as silence. Two of them are
  answers rather than failures: `ERR not supported on this board` (a v2 asked
  for the firmware id) and `ERR storage unavailable` (NVS did not mount). Both
  mean *stop asking*, and catnip does.

The `Board:` line of `fw_version` is what establishes the board generation —
see [Firmware](firmware.md#generations).

---

<a id="antenna"></a>
## The antenna switch

The board has **one antenna path shared between the two radios**, switched by
pins the host MCU drives. `band1` points it at the CC1352's 2.4 GHz leg;
`band3` points it at the SX1262's sub-GHz leg.

**The position survives across sessions.** The firmware's `change_band`
returns early when the requested band is already selected, and nothing resets
it between runs — so a Zigbee capture started after `sniff lora` would listen
through the LoRa leg, and hear nothing, unless it asks for its own band. Every
capture path therefore sets the band explicitly rather than assuming the
boot-time default, which is itself a no-op for the same reason.

If you write code that touches the radio, send the band command. A silent
capture with correct settings is almost always this.

---

<a id="ti-framing"></a>
## CC1352 framing

Binary, framed, on `Cat-Bridge` — the TI sniffer protocol implemented in
[`protocol/sniffer_ti.py`](../protocol/sniffer_ti.py):

```
┌──────────┬──────────┬────────┬─────────┬─────┬──────────┐
│   SOF    │ category │ length │ payload │ FCS │   EOF    │
│  40 53   │  + type  │   LE   │         │     │  40 45   │
└──────────┴──────────┴────────┴─────────┴─────┴──────────┘
```

`0x4053` opens a frame and `0x4045` closes it (`@S` and `@E`). The info byte
splits into a **category** — reserved, command, command response, or data
streaming/error — and a type within it. Commands the host sends are built the
same way: `ping`, `start`, `stop`, `pause`, `resume`, `config_freq`,
`config_phy`.

Channels are configured as a frequency: 802.15.4 channel *n* is
`2405 + 5(n − 11)` MHz, packed as two 16-bit little-endian halves (integer
MHz and fraction in 1/65536 units).

---

<a id="sx-framing"></a>
## SX1262 framing

Not binary at all. The SX1262 firmware emits **text lines** on `Cat-LoRa`,
one per received frame, and catnip parses them with a regex:

```
RX: 48656c6c6f | RSSI: -42 | SNR: 9
FSK RX: 4142 | RSSI: -55 | Len: 2
```

LoRa lines carry SNR; FSK lines carry a length instead, because the SX1262
measures no SNR for FSK. A firmware that truncates its own hex dump reports
the true length, which is preserved as the on-wire length in the pcap record
even though fewer bytes were captured.

Each parsed frame is wrapped in a **LoRaTap** header
([DLT 270](glossary.md#loratap)) built in
[`protocol/sniffer_sx.py`](../protocol/sniffer_sx.py) — 15 bytes, big-endian:

| Field | Bytes | Note |
|---|---|---|
| version, padding, header length | 4 | version 0, length 15 |
| frequency | 4 | Hz |
| bandwidth | 1 | enum: 125 → 1, 250 → 2, 500 → 4 |
| spreading factor | 1 | 7–12 |
| RSSI ×3, SNR | 4 | packet, max, current, then SNR |
| sync word | 1 | `0x12` private, `0x34` LoRaWAN, `0x2B` Meshtastic |

That header is why LoRa captures need no plugin and why the packet list can
show link quality per frame: Wireshark's own LoRaTap dissector resolves those
fields. See [Wireshark](wireshark.md).

---

<a id="pcap"></a>
## pcap output

Both drivers converge on [`protocol/common.py`](../protocol/common.py), which
writes classic pcap:

- **Global header** — magic `0xa1b2c3d4`, version 2.4, snaplen `0xffff`, and
  the link type. **147** (USER0) for the CC1352 paths, **270** (LoRaTap) for
  the SX1262 ones.
- **Record header** — timestamp seconds, microseconds, captured length, on-wire
  length. The two lengths differ only when the source truncated the frame
  before catnip saw it.

The file sink ([`bridge.py`](../modules/core/bridge.py)) picks the format from
the extension: `.pcapng` writes a section header block and an interface
description block, tagged with the catnip version; anything else writes flat
pcap. An existing file is **truncated, never appended to** — a second pcap
header mid-file yields something no dissector reads past — which is why `-w`
refuses to overwrite without `-f`.

---

<a id="pipes"></a>
## Pipes

Live capture goes through a pipe rather than a file:

| Platform | Object | Path |
|---|---|---|
| Linux, macOS | FIFO (`os.mkfifo`) | `/tmp/fcatnip` |
| Windows | named pipe (`win32pipe`, needs **pywin32**) | `\\.\pipe\fcatnip` |

catnip writes the pcap global header and then each record as it arrives.
Wireshark is launched as `wireshark -k -i <pipe>`, optionally with `-C
<profile>` and whatever display arguments the protocol needs.

Opening a FIFO for writing **blocks until a reader attaches**, so the open
happens on its own thread and the capture waits on an event with a timeout —
that is where *"Timed out waiting for Wireshark"* comes from. An existing FIFO
is reused rather than treated as an error.

BLE takes a longer route, because the Sniffle extcap plugin owns the radio: it
gets **two** pipes. catnip runs the plugin, reads its output from an internal
pipe (`sniffle_plugin_<pid>`), and re-emits it into the pipe Wireshark reads,
launching Wireshark only once the sniffer header has arrived.

---

<a id="bootloader"></a>
## The CC1352 bootloader

Flashing is the one path that departs from the rules above. It runs on
`Cat-Bridge` at **500000 baud**, not 115200, and it deliberately toggles the
control lines every other path leaves alone.

The sequence, implemented in
[`cc2538.py`](../modules/firmware/cc2538.py) and driven by
[`flasher.py`](../modules/firmware/flasher.py):

1. `boot` over `Cat-Shell` puts the CC1352 into its serial bootloader.
2. The bootloader is synchronised and reports the chip id, the package, the
   flash size and the IEEE address.
3. **The safety gate**, immediately before the erase. The flash size the
   bootloader reports identifies the board — measured, so it outranks both the
   shell's answer and a `--board` override — and the image is refused unless
   its file name names the matching CC1352 variant *and* it fits in the flash:

   ```
   [X] Refusing to flash: 'sniffle_cc1352p7_1M.hex' is a CC1352P7 image but this v2 board has a CC1352P1; flashing it would disable the CC1352 bootloader
   ```

   An image whose name says nothing about the variant is accepted only on a
   v3, where every bundled image is a P7 build. An unknown board is never
   allowed.
4. Mass erase, then write.
5. **Verify by CRC32**, comparing the bootloader's own calculation against the
   image's. A mismatch aborts.
6. `exit` over `Cat-Shell`, then a wait for the board to re-enumerate.
7. On a v3, `cc1352_fw_id set <id>` records what was written — retried a few
   times while the shell comes back up.

When the bootloader itself no longer answers,
[`restore`](commands/restore.md) loads a CMSIS-DAP probe onto the RP2040 and
reprograms the chip through OpenOCD over cJTAG. That route does not exist on a
v2.

---

## See also

- Where these modules live: [Architecture](architecture.md).
- What reaches Wireshark, and how it is dissected: [Wireshark](wireshark.md).
- Images, ids and generations: [Firmware](firmware.md).

# `catnip sniff`

> Sniffer protocol control

The capture commands. Seven subcommands across **two different radios**, and
which radio a subcommand uses decides almost everything else about it — which
port carries the packets, which firmware has to be loaded, and which flags
exist.

| Subcommand | Radio | Port | Firmware |
|---|---|---|---|
| [`ble`](#sniff-ble) | CC1352 | Cat-Bridge | Sniffle |
| [`zigbee`](#sniff-zigbee) | CC1352 | Cat-Bridge | TI sniffer |
| [`thread`](#sniff-thread) | CC1352 | Cat-Bridge | TI sniffer |
| [`airtag_scanner`](#sniff-airtag_scanner) | CC1352 | Cat-Bridge | AirTag scanner |
| [`lora`](#sniff-lora) | SX1262 | Cat-LoRa | SX1262 sniffer |
| [`fsk`](#sniff-fsk) | SX1262 | Cat-LoRa | SX1262 sniffer |
| [`profiles`](#sniff-profiles) | — | — | — (lists saved radio settings) |

**The firmware must match the protocol.** Each subcommand checks for the image
it needs and flashes it if it is missing, so you normally do not call
[`flash`](flash.md) yourself. Switching between BLE and Zigbee reflashes the
CC1352 each time.

## Quick Start

```sh
# 1. Sniff BLE advertising traffic — flashes Sniffle if it is not there
catnip sniff ble

# 2. The same, opening Wireshark live
catnip sniff ble --wireshark

# 3. Zigbee needs a channel; the TI firmware gets flashed on the way
catnip sniff zigbee -c 15 -ws

# 4. Sub-GHz: LoRa, with the radio settings named instead of typed
catnip sniff lora --profile us915-meshtastic-longfast -l
```

---

## How it works

```
  radio ──► firmware ──► Cat-Bridge / Cat-LoRa ──► catnip ──┬──► terminal dump
                                                            ├──► FIFO ──► Wireshark   (-ws)
                                                            ├──► .pcap / .pcapng      (-w)
                                                            └──► hex / ASCII log      (-r / -ascii)
```

1. The subcommand resolves the firmware id it requires.
2. It asks the board what is running. Missing or wrong → it flashes, then waits
   for the board to come back.
3. Packets stream over the port that radio owns.
4. Output goes wherever the flags say. These are not exclusive: `-ws` and `-w`
   work together, so you can watch live *and* keep the capture.

---

## Subcommands

All subcommands take `-d, --device INTEGER` — *Device ID (for multiple
CatSniffers)*. It is omitted from the tables below.

<a id="sniff-ble"></a>
### `sniff ble`

> Sniffing BLE with Sniffle firmware.

| Option | Description |
|---|---|
| `-ws, --wireshark` | Open Wireshark with Sniffle extcap plugin |
| `-c, --channel INTEGER RANGE` | BLE advertising channel (37, 38, 39) `[37<=x<=39]` |
| `-m, --mode [conn_follow\|passive_scan\|active_scan]` | Sniffle mode |

```sh
catnip sniff ble                    # ready for manual Wireshark setup
catnip sniff ble --wireshark        # auto-open Wireshark
catnip sniff ble -c 39 -m passive_scan
```

BLE advertises on three channels only — **37** (2402 MHz), **38** (2426 MHz)
and **39** (2480 MHz). A sniffer listens to one at a time.

| Mode | What it does | Detectable? |
|---|---|---|
| `passive_scan` | Listens only. | No — it transmits nothing. |
| `active_scan` | Sends `SCAN_REQ` to pull extended data from advertisers. | **Yes.** |
| `conn_follow` | Follows an already-established connection and captures its data traffic. | No. |

> [!Note]
> `active_scan` transmits. Use `passive_scan` when the capture has to stay
> invisible to the devices around you.

<a id="sniff-zigbee"></a>
### `sniff zigbee`

> Sniffing Zigbee with Sniffer TI firmware.

| Option | Description |
|---|---|
| `-ws` | Open Wireshark |
| `-c, --channel INTEGER RANGE` | Zigbee channel `[11<=x<=26; required]` |
| `-r, --raw FILE` | Save captured packets as raw hex to FILE (`RX: <hex> \| RSSI: <rssi>`) |
| `-ascii, --ascii FILE` | Save captured packets as decoded ASCII to FILE (`RX: <ascii> \| RSSI: <rssi>`) |
| `-w, --write FILE` | Write the capture to FILE for offline analysis (`.pcap`, or `.pcapng` if the name ends in `.pcapng`). Works with or without `--wireshark` |
| `-f, --force` | Overwrite the `--write` file if it already exists |

```sh
catnip sniff zigbee -c 15
catnip sniff zigbee -c 15 -ws              # open Wireshark
catnip sniff zigbee -c 15 -r capture.raw   # save raw log to file
catnip sniff zigbee -c 15 -w capture.pcap  # save a capture for tshark
```

**`--channel` is required.** 802.15.4 has no scan mode here: the radio sits on
one channel and hears only that one. Use [`cativity`](cativity.md) first if you
do not know which channel the network is on.

<a id="sniff-thread"></a>
### `sniff thread`

> Sniffing Thread with Sniffer TI firmware.

Same firmware, same ports and the same flags as `sniff zigbee` — Thread and
Zigbee are both 802.15.4 and the TI sniffer covers both.

| Option | Description |
|---|---|
| `-ws` | Open Wireshark |
| `-c, --channel INTEGER RANGE` | Thread channel `[11<=x<=26; required]` |
| `-r, --raw FILE` | Save captured packets as raw hex to FILE |
| `-ascii, --ascii FILE` | Save captured packets as decoded ASCII to FILE |
| `-w, --write FILE` | Write the capture to FILE for offline analysis |
| `-f, --force` | Overwrite the `--write` file if it already exists |

```sh
catnip sniff thread -c 15
catnip sniff thread -c 15 -ws              # open Wireshark
catnip sniff thread -c 15 -w capture.pcap  # save a capture for tshark
```

> [!Note]
> `zigbee` and `thread` take **`-ws`** with no long form. `lora` and `fsk` take
> **`-ws, --wireshark`**. Same short flag, and `--wireshark` is not accepted by
> the 802.15.4 subcommands.

<a id="sniff-lora"></a>
### `sniff lora`

> Sniffing LoRa with Sniffer SX1262 firmware.

| Option | Description |
|---|---|
| `-ws, --wireshark` | Open Wireshark live while the capture runs (LoRaTap over a local pipe) |
| `-oc, --open-capture` | Open the capture in Wireshark when the sniffer stops. Without `--write` the packets are saved to a temporary `.pcapng` file first |
| `-v, --verbose` | Show verbose output in terminal |
| `-l, --live` | Show a live panel while capturing — packets/s, last and best link quality, an RSSI histogram and the last frames — instead of the scrolling packet dump |
| `-P, --profile TEXT` | Fill in radio defaults from a named profile — built-in region/protocol presets (see `catnip sniff profiles`), or your own in `~/.config/catnip/profiles.toml`. Flags you pass explicitly still override it. |
| `--save-profile NAME` | Save this command's radio settings (after `--profile` and any explicit flags are merged) as NAME in `~/.config/catnip/profiles.toml`, for later use as `--profile NAME`. |
| `-freq, --frequency INTEGER RANGE` | Frequency in Hz, 150-960 MHz (e.g., 915000000 for 915 MHz) |
| `-bw, --bandwidth [125\|250\|500]` | Bandwidth in kHz |
| `-sf, --spread_factor INTEGER RANGE` | Spreading Factor (7-12) |
| `-cr, --coding_rate INTEGER RANGE` | Coding Rate (5-8) |
| `-pw, --tx_power INTEGER RANGE` | TX Power in dBm (-9 to 22, SX1262 hardware range) |
| `-sw, --sync-word TEXT` | LoRa sync word: `public` (0x34, LoRaWAN), `private` (0x12) or any raw byte as 0xNN (e.g. 0x2B for Meshtastic). Default: private. |
| `-pre, --preamble INTEGER RANGE` | Preamble length in **symbols** (6-65535). Default: 12. |
| `--iq [normal\|inverted]` | IQ polarity. LoRaWAN downlinks need `inverted`. Default: normal. |
| `-r, --raw FILE` | Save captured packets as raw hex to FILE (`RX: <hex> \| RSSI: <rssi> \| SNR: <snr>`) |
| `-ascii, --ascii FILE` | Save captured packets as decoded ASCII to FILE |
| `-w, --write FILE` | Write the capture to FILE for offline analysis |
| `-f, --force` | Overwrite the `--write` file if it already exists |

```sh
catnip sniff lora                          # defaults: 915MHz, SF7, BW125
catnip sniff lora -freq 868000000 -sf 9
catnip sniff lora -ws                      # live Wireshark while sniffing
catnip sniff lora -l                       # live panel instead of hex
catnip sniff lora -oc                      # sniff, then open Wireshark
catnip sniff lora -w capture.pcapng        # save it, offer to open it
catnip sniff lora -sw public               # LoRaWAN sync word (0x34)
catnip sniff lora -sw 0x2B -pre 16         # Meshtastic sync word
catnip sniff lora -sw public --iq inverted # LoRaWAN downlinks
catnip sniff lora --profile eu868-meshtastic-longfast
```

**A LoRa receiver only demodulates a frame whose spreading factor, bandwidth,
frequency and sync word it already matches.** Get one of them wrong and the
capture is silent, with nothing in the output to say which one. That is what
[`--profile`](#radio-profiles) and [`lora scan`](lora.md) exist for.

A frequency far from 433/470/868/915 MHz gets a warning: the antenna matching
network is fixed in hardware, so a stray digit in `--frequency` produces zero
packets with nothing to blame.

<a id="sniff-fsk"></a>
### `sniff fsk`

> Sniffing (G)FSK with Sniffer SX1262 firmware.

Same radio and same ports as `sniff lora`, with the SX1262 in FSK mode — where
it hears the sub-GHz traffic LoRa cannot: 802.15.4g/Wi-SUN, smart meters, alarm
and sensor links, and anything else on a plain (G)FSK ISM channel.

The output flags (`-ws`, `-oc`, `-v`, `-l`, `-P`, `--save-profile`, `-r`,
`-ascii`, `-w`, `-f`) are identical to `sniff lora`. The radio flags are not:

| Option | Description |
|---|---|
| `-freq, --frequency INTEGER RANGE` | Frequency in Hz, 137-1020 MHz (e.g., 915000000 for 915 MHz) |
| `-br, --bitrate INTEGER RANGE` | Bitrate in bps (600-300000). Default: 50000. |
| `-fd, --fdev INTEGER RANGE` | Frequency deviation in Hz (600-200000). Default: 25000. |
| `-bw, --bandwidth [4.8 … 467.0]` | RX bandwidth in kHz. Must cover bitrate + 2x deviation or the firmware widens it to 187.2. Default: 187.2. |
| `-pw, --tx_power INTEGER RANGE` | TX Power in dBm (-9 to 22, SX1262 hardware range) |
| `-pre, --preamble INTEGER RANGE` | Preamble length in **bytes** (FSK counts bytes, not symbols). Default: 8. |
| `-sw, --sync-word TEXT` | FSK sync word: 1-8 bytes of hex (e.g. 2DD4 for 802.15.4g/Meshtastic). Default: 12AD. |
| `--bt [off\|0.3\|0.5\|0.7\|1.0]` | Gaussian filter BT: `off` is plain FSK, a value is GFSK. Default: 0.5. |
| `--crc / --no-crc` | Let the modem verify the CRC and drop failing frames. Default: `--no-crc`. |
| `--whitening / --no-whitening` | Undo the transmitter's data whitening. Default: `--no-whitening`. |
| `--pktlen [variable\|fixed]` | `variable` reads each frame's length from its header, `fixed` assumes `--payload` bytes. Default: variable. |
| `--payload INTEGER RANGE` | Payload length for `--pktlen fixed`, maximum length otherwise. Default: 255. |

```sh
catnip sniff fsk                             # defaults: 915MHz, 50kbps
catnip sniff fsk -freq 868000000 -br 100000 -fd 50000
catnip sniff fsk -sw 2DD4 --whitening        # 802.15.4g-style framing
catnip sniff fsk -ws                         # live Wireshark
catnip sniff fsk -l                          # live panel instead of hex
catnip sniff fsk -w capture.pcapng           # save it, offer to open it
catnip sniff fsk --bt off                    # plain FSK, no shaping
```

**FSK is stricter than LoRa**: it only demodulates what matches the bitrate,
deviation and sync word it was told to expect, so those have to be right.

> [!Important]
> `-pre/--preamble` means **symbols** under `sniff lora` and **bytes** under
> `sniff fsk`. The same number is a different length of air time in each.

<a id="sniff-airtag_scanner"></a>
### `sniff airtag_scanner`

> Sniffing Airtag Scanner firmware.

Prints each detected AirTag directly in the terminal, with its RSSI and an
approximate distance estimate.

| Option | Description |
|---|---|
| `--putty` | Open PuTTY with serial configuration instead |

```sh
catnip sniff airtag_scanner
catnip sniff airtag_scanner --putty    # auto-open PuTTY at 9600 baud instead
```

The port is read at **9600 baud** — much slower than the other captures,
because this firmware emits text, not packets. Lines that do not parse as a
detection are still printed, dimmed, rather than dropped. `Ctrl+C` stops it and
reports how many detections were seen.

`--putty` hands the port to PuTTY **instead** of streaming here, configured at
9600 8N1, no flow control. PuTTY comes from `apt install putty`,
`brew install putty` or [putty.org](https://www.putty.org/) depending on the
platform.

> [!Important]
> This is the one capture subcommand that produces **no pcap and no Wireshark
> integration**. It has no `-w`, `-ws` or `-r`. To log it, redirect the
> terminal output.

<!-- TODO: paste a real detection stream with hardware and an AirTag in range.
     See the progress log in plan-implementacion-documentacion.md. -->

<a id="sniff-profiles"></a>
### `sniff profiles`

> List radio profiles available to `--profile` (built-in and user-defined).

| Option | Description |
|---|---|
| `-c, --command [lora\|fsk]` | Only list profiles for this radio mode |

```sh
catnip sniff profiles
```

```
  eu868-meshtastic-defcon33 (lora): 869.525 MHz, BW500, SF7, CR4/5, sync 0x2B
  eu868-meshtastic-longfast (lora): 869.525 MHz, BW250, SF11, CR4/5, sync 0x2B
  eu868-meshtastic-longmod (lora): 869.525 MHz, BW250, SF11, CR4/6, sync 0x2B
  eu868-meshtastic-longslow (lora): 869.525 MHz, BW250, SF12, CR4/5, sync 0x2B
  eu868-meshtastic-mediumfast (lora): 869.525 MHz, BW250, SF9, CR4/5, sync 0x2B
  eu868-meshtastic-mediumslow (lora): 869.525 MHz, BW250, SF10, CR4/5, sync 0x2B
  eu868-meshtastic-shortfast (lora): 869.525 MHz, BW250, SF8, CR4/5, sync 0x2B
  eu868-meshtastic-shortslow (lora): 869.525 MHz, BW250, SF9, CR4/5, sync 0x2B
  eu868-meshtastic-shortturbo (lora): 869.525 MHz, BW500, SF7, CR4/5, sync 0x2B
  eu868-meshtastic-vlongslow (lora): 869.525 MHz, BW125, SF12, CR4/5, sync 0x2B
  stm32 (lora): 915.000 MHz, BW250, SF11, CR4/5, sync public
  us915-meshtastic-defcon33 (lora): 906.875 MHz, BW500, SF7, CR4/5, sync 0x2B
  us915-meshtastic-longfast (lora): 906.875 MHz, BW250, SF11, CR4/5, sync 0x2B
  us915-meshtastic-longmod (lora): 906.875 MHz, BW250, SF11, CR4/6, sync 0x2B
  us915-meshtastic-longslow (lora): 906.875 MHz, BW250, SF12, CR4/5, sync 0x2B
  us915-meshtastic-mediumfast (lora): 906.875 MHz, BW250, SF9, CR4/5, sync 0x2B
  us915-meshtastic-mediumslow (lora): 906.875 MHz, BW250, SF10, CR4/5, sync 0x2B
  us915-meshtastic-shortfast (lora): 906.875 MHz, BW250, SF9, CR4/5, sync 0x2B
  us915-meshtastic-shortturbo (lora): 906.875 MHz, BW500, SF7, CR4/5, sync 0x2B
  us915-meshtastic-vlongslow (lora): 906.875 MHz, BW125, SF12, CR4/5, sync 0x2B
```

> [!Note]
> **All built-in profiles are LoRa.** `catnip sniff profiles -c fsk` prints
> nothing on a stock install — FSK profiles have to be written by hand in
> `profiles.toml`.

---

<a id="radio-profiles"></a>
## Radio profiles

`sniff lora` and `sniff fsk` each take 8–14 radio flags, and a wrong sync word
or band gives zero packets with no error pointing at the mistake. `--profile`
(`-P`) fills in the whole set from a name; **any flag typed explicitly still
overrides it**:

```sh
catnip sniff lora --profile eu868-meshtastic-longfast
catnip sniff lora -P us915-meshtastic-shortfast -pw 10   # override tx_power only
```

Built-in profiles cover every Meshtastic channel preset crossed with the US915
and EU868 default frequencies.

### Saving your own

`--save-profile NAME` writes the settings this command ended up with — after
`--profile` and every explicit flag are merged — to
`~/.config/catnip/profiles.toml`:

```sh
catnip sniff lora -freq 868000000 -sf 9 --save-profile mi-perfil
catnip sniff fsk -freq 868000000 --save-profile mi-fsk
```

Or write the file yourself, as `[profiles.NAME]` tables. A user profile whose
name matches a built-in replaces it. The file location can be overridden with
the `CATNIP_PROFILES_FILE` environment variable.

```toml
[profiles.home-lora]
frequency = 915000000
bandwidth = "125"        # one of "125", "250", "500"
spread_factor = 7
coding_rate = 5
sync_word = "private"    # "private", "public" or "0xNN"
preamble = 12
tx_power = 20
iq = "normal"

[profiles.home-fsk]
command = "fsk"          # defaults to "lora" when omitted
frequency = 868000000
bitrate = 50000
fdev = 25000
bandwidth = "187.2"
sync_word = "2DD4"
```

A profile only needs the fields it overrides; the rest keep the command's own
defaults. **A profile written for `lora` is rejected under `sniff fsk` and vice
versa** — the same field name means something different in each mode
(`preamble` is symbols in LoRa, bytes in FSK), and that mismatch is exactly the
silent misconfiguration `--profile` exists to prevent.

---

### Notes

- **Switching protocols reflashes the CC1352.** Going from `sniff ble` to
  `sniff zigbee` and back costs a flash cycle each way. The SX1262 subcommands
  (`lora`, `fsk`) use a different chip and do not disturb the CC1352 image.
- `-ws` and `-w` are not exclusive: watch live and keep the file.
- `-oc/--open-capture` differs from `-ws`: it opens Wireshark **after** the
  sniffer stops, on the finished file. Without `-w` it writes a temporary
  `.pcapng` first.
- `-r/--raw` and `-ascii` are plain text logs, not pcap. They are the easiest
  thing to grep, and the only option for a quick look without Wireshark.
- `catnip sniff -v` (on the group) and `-v` on `lora`/`fsk` are different flags
  with the same spelling. For log verbosity across the whole tool, use the
  global `catnip -v` / `-vv`.

---

## See also

- [`lora`](lora.md) — `lora scan` finds the settings to pass here; `lora spectrum` shows where to look.
- [`cativity`](cativity.md) — which 802.15.4 channel to give `-c` before capturing.
- [`meshtastic`](meshtastic.md) — decodes what `sniff lora` captures on the Meshtastic presets.
- [`flash`](flash.md) — what the automatic firmware step does under the hood.
- Extcap, FIFOs and dissectors: [Wireshark](../wireshark.md).

# `catnip meshtastic`

> Meshtastic protocol tools

Meshtastic is long-range off-grid messaging over LoRa: kilometres, no cellular,
AES-256 encrypted, in the 868/915 MHz ISM bands. These four subcommands cover
the whole path — get the key, watch the mesh, decode one packet, or sit in a
chat view.

They split by what they need:

| Subcommand | Needs hardware? | What it does |
|---|---|---|
| [`decode`](#meshtastic-decode) | no | Decrypts one hex packet you already captured |
| [`config`](#meshtastic-config) | no | Pulls PSKs and settings out of a Meshtastic config file |
| [`live`](#meshtastic-live) | yes | Tunes the radio and decodes packets as they arrive |
| [`dashboard`](#meshtastic-dashboard) | yes | The same capture, as a chat TUI |

## Quick Start

```sh
# 1. Get the channel PSK out of your Meshtastic config export
catnip meshtastic config userPrefs.jsonc

# 2. Watch the mesh live on the US default channel
catnip meshtastic live -f 906.875 -ps LongFast

# 3. Or decode a single packet you captured earlier
catnip meshtastic decode -i fffffffff449ca27440287026300000048656c6c6f2065766572796f6e65
```

---

## Packet structure

```
┌──────────┬──────────┬────────────┬───────┬─────────┬──────────┬─────────────┐
│ Dest     │ Sender   │ Packet ID  │ Flags │ Channel │ Reserved │ Payload     │
│ (4 bytes)│ (4 bytes)│ (4 bytes)  │ (1)   │ (1)     │ (2)      │ (Variable)  │
└──────────┴──────────┴────────────┴───────┴─────────┴──────────┴─────────────┘
```

| Field | Meaning |
|---|---|
| **Dest** | Destination node ID. `ffffffff` is broadcast. |
| **Sender** | Source node ID. |
| **Packet ID** | Unique per packet. |
| **Flags** | Hop limit, ACK request, routing bits. |
| **Channel** | Mesh channel number (0–7). |
| **Payload** | Encrypted protobuf. This is what `decode` decrypts. |

The header is **not** encrypted — sender, destination and channel are readable
without any key. Only the payload needs the PSK.

---

## Channel presets

A Meshtastic preset is a named LoRa configuration. Both `live` and `dashboard`
take one with `-ps/--preset`, and it has to match the mesh you are listening to
or you will hear nothing.

| Preset | SF | BW | CR | Notes |
|---|---|---|---|---|
| `defcon33` | SF7 | 500 kHz | 4/5 | Short range, fastest, long preamble |
| `ShortTurbo` | SF7 | 500 kHz | 4/5 | Short range, fastest |
| `ShortFast` | SF7 | 250 kHz | 4/5 | Short range, fast |
| `ShortSlow` | SF8 | 250 kHz | 4/5 | Short range, lower speed |
| `MediumFast` | SF9 | 250 kHz | 4/5 | Medium range |
| `MediumSlow` | SF10 | 250 kHz | 4/5 | Medium range, slower |
| `LongFast` | SF11 | 250 kHz | 4/5 | **Default.** Best range/speed balance |
| `LongSlow` | SF12 | 125 kHz | 4/5 | Maximum range, slowest |
| `LongMod` | SF11 | 125 kHz | 4/8 | Long range, robust coding |
| `VLongSlow` | SF11 | 125 kHz | 4/8 | Very long range, robust coding |

The same presets exist as profiles for [`sniff lora`](sniff.md#radio-profiles)
(`us915-meshtastic-longfast` and friends), crossed with the regional
frequencies.

---

## Subcommands

<a id="meshtastic-decode"></a>
### `meshtastic decode`

> Decrypt and decode a hex-encoded Meshtastic packet

| Option | Description |
|---|---|
| `-i, --input TEXT` | Hex-encoded payload (raw packet data starting with dest, sender, etc.) **[required]** |
| `-k, --key TEXT` | Base64-encoded AES key. Use `ham` or `nokey` for open channels |

Offline and hardware-free: paste in the hex of a captured packet and get the
plaintext back.

```sh
catnip meshtastic decode \
  --input "fffffffff449ca27440287026300000048656c6c6f2065766572796f6e65"
```

```
Decrypted raw (hex): 48656c6c6f2065766572796f6e65
[TEXT - UNENCRYPTED] f449ca27 -> ffffffff: Hello everyone
```

With a channel key:

```sh
catnip meshtastic decode \
  --input "fffffffff449ca27440287026300000041406aa0a81ef722d3a4598dc66326ace68cc3" \
  --key "1PG7OiApB1nwvP+rz05pAQ=="
```

```
Decrypted raw (hex): 0801120f48656c6c6f20656e63727970746564
[TEXT] f449ca27 -> ffffffff: Hello encrypted
```

Non-text payloads are decoded by type — a position report comes back as
coordinates:

```
Decrypted raw (hex): 0803120a0d44ee4d161500c63bb7
[POSITION] f449ca27 -> ffffffff: 37.420601999999995, -122.0819456
```

The decoder tries the well-known default keys automatically, so traffic on the
public default channel decodes without `--key`. Use `--key ham` or
`--key nokey` for channels that carry no encryption at all.

<a id="meshtastic-config"></a>
### `meshtastic config`

> Extract PSKs and config info from a Meshtastic JSONC config file

Takes a `userPrefs.jsonc` — the config file a Meshtastic firmware build is
customised with — and prints what is in it, including the channel keys in both
hex and the base64 form `decode` wants.

```sh
catnip meshtastic config userPrefs.jsonc
```

```
=== CHANNELS ===
Channel 0: MyMesh
  PSK (hex):     0102030405060708090a0b0c0d0e0f10
  PSK (base64):  AQIDBAUGBwgJCgsMDQ4PEA==

=== GENERAL CONFIG ===
LoRa Channel: 20
LoRa Modem Preset: meshtastic_Config_LoRaConfig_ModemPreset_LONG_FAST
MQTT Address: mqtt.example.org
Timezone: CET-1CEST,M3.5.0,M10.5.0/3

=== OEM BRANDING ===

=== ADMIN KEYS ===
No admin keys found.
```

Four sections, always printed even when empty: **CHANNELS** (name and PSK),
**GENERAL CONFIG** (LoRa channel and preset, MQTT server and credentials,
timezone, ringtone), **OEM BRANDING**, and **ADMIN KEYS** (hex and base64).

> [!Important]
> The output contains **channel PSKs, admin keys and MQTT passwords in
> plaintext**. Treat it like any other secret: it is exactly what someone needs
> to read the mesh's traffic. Do not paste it into a bug report.

The `PSK (base64)` value is the one to hand to `decode --key`.

<a id="meshtastic-live"></a>
### `meshtastic live`

> Live Meshtastic decoder - Capture and decode packets in real-time

| Option | Description |
|---|---|
| `-d, --device INTEGER` | Device ID (for multiple CatSniffers) |
| `-baud, --baudrate INTEGER` | Baudrate (default: 115200) |
| `-f, --frequency FLOAT` | Frequency in MHz (default: 906.875) |
| `-ps, --preset [defcon33\|ShortTurbo\|…\|VLongSlow]` | Channel preset (default: LongFast) |

Configures the SX1262 over the Cat-Shell port, then reads and decodes packets
from the Cat-LoRa port as they arrive. The radio setup is printed as it
happens — the individual `lora_freq` / `lora_sf` / `lora_bw` / `lora_syncword`
commands are visible, which makes a misconfiguration easy to spot.

```sh
catnip meshtastic live --device 1 --frequency 906.875 --preset LongFast
```

<!-- TODO: paste a real capture with hardware and mesh traffic in range.
     See the progress log in plan-implementacion-documentacion.md. -->

<a id="meshtastic-dashboard"></a>
### `meshtastic dashboard`

> Meshtastic Chat TUI - Beautiful terminal dashboard for Meshtastic

Same flags as `live`, same capture, different presentation: a terminal chat
view of the mesh rather than a scrolling decoder log.

| Option | Description |
|---|---|
| `-d, --device INTEGER` | Device ID (for multiple CatSniffers) |
| `-baud, --baudrate INTEGER` | Baudrate (default: 115200) |
| `-f, --frequency FLOAT` | Frequency in MHz (default: 906.875) |
| `-ps, --preset [defcon33\|ShortTurbo\|…\|VLongSlow]` | Channel preset (default: LongFast) |

```sh
catnip meshtastic dashboard -f 869.525 -ps LongFast
```

<!-- TODO: paste a real dashboard screenshot/capture with hardware.
     See the progress log in plan-implementacion-documentacion.md. -->

---

### Notes

- **`-f/--frequency` is in MHz here** (`906.875`), while
  [`sniff lora`](sniff.md#sniff-lora) takes `-freq` in **Hz** (`906875000`).
  Different units, similar-looking flags.
- The default frequency, `906.875` MHz, is the US915 Meshtastic default. In
  Europe use `869.525`.
- `live` and `dashboard` reconfigure the radio and leave it that way. Run
  [`catnip status`](status.md) if a later LoRa capture behaves unexpectedly.
- `decode` and `config` need no CatSniffer at all — they are useful on a
  capture file from someone else's hardware.
- These commands need the bundled `meshtastic` Python library. If it is
  missing, the command says so and suggests
  `pip install meshtastic protobuf pyyaml`.

---

## See also

- [`sniff lora`](sniff.md#sniff-lora) — raw LoRa capture with the same presets, written to pcap.
- [`lora scan`](lora.md) — find the frequency and SF when you do not know the mesh's settings.
- Terms: [Glossary](../glossary.md).

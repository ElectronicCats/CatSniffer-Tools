# `catnip lora`

> LoRa SX1262 tools

Two tools for the problem that comes *before* a LoRa capture: **you cannot
receive what you cannot describe.** A LoRa receiver only demodulates a frame
whose spreading factor, bandwidth, frequency and sync word it already matches,
so an unknown transmitter gives you silence rather than an error.

- [`spectrum`](#lora-spectrum) — *where* is there energy? Sweeps 150–960 MHz by RSSI.
- [`scan`](#lora-scan) — *what settings decode it?* Sweeps SF/BW/frequency and counts packets.

Neither replaces the other: `spectrum` sees any RF energy but decodes nothing;
`scan` decodes real LoRa frames but only on the combinations it tries.

## Quick Start

```sh
# 1. Find where the energy is across the sub-GHz range
catnip lora spectrum

# 2. Around that frequency, find the settings that actually decode
catnip lora scan -f 868.1,868.3,868.5

# 3. Capture with what you found
catnip sniff lora -freq 868300000 -sf 9 -bw 125
```

---

## Subcommands

<a id="lora-spectrum"></a>
### `lora spectrum`

> Live Spectrum Scanner for SX1262 - Real-time frequency spectrum analyzer

| Option | Description |
|---|---|
| `-d, --device INTEGER` | Device ID (for multiple CatSniffers) |
| `-b, --baudrate INTEGER` | Baudrate (default: 115200) |
| `--start-freq FLOAT RANGE` | Starting frequency in MHz, 150-960 (default: 150) |
| `--end-freq FLOAT RANGE` | End frequency in MHz, 150-960 (default: 960) |
| `--offset INTEGER RANGE` | RSSI offset in dBm (default: -15) `[-100<=x<=100]` |

```sh
catnip lora spectrum                                # the whole 150-960 MHz range
catnip lora spectrum --start-freq 863 --end-freq 870  # the EU868 band
```

This is an **RSSI sweep**, not a demodulator. It shows where there is energy —
a transmitter, a jammer, a noisy switching supply — without caring what
modulation it is. Narrow the range to get finer resolution over the band you
care about.

`--offset` shifts the reported RSSI to calibrate against a known reference; it
does not change what the radio hears.

<!-- TODO: paste a real sweep with hardware attached. See the progress log in
     plan-implementacion-documentacion.md. -->

<a id="lora-scan"></a>
### `lora scan`

> Sweep SF/BW/frequency combinations and count packets on each.

| Option | Description |
|---|---|
| `-d, --device INTEGER` | Device ID (for multiple CatSniffers) |
| `-f, --freq TEXT` | Frequencies to sweep, comma separated, in MHz (`868.1,915`) or Hz (`915000000`). Default: 915 |
| `--sf TEXT` | Spreading factors to sweep, comma separated (7-12). Default: all |
| `--bw TEXT` | Bandwidths to sweep in kHz, comma separated (`125,250,500`). Default: all |
| `--dwell FLOAT RANGE` | Seconds to listen on each combination (default: 3). A single SF12/BW125 frame is over a second on air — give the slow end more `[0.2<=x<=120]` |
| `--passes INTEGER RANGE` | Number of full sweeps; 0 repeats until Ctrl+C (default: 1) `[0<=x<=1000]` |
| `-sw, --sync-word TEXT` | LoRa sync word: `private` (0x12), `public` (0x34, LoRaWAN) or any raw byte as 0xNN (e.g. 0x2B for Meshtastic). Default: private. |

```sh
catnip lora scan                          # 915 MHz, every SF and BW
catnip lora scan --dwell 8                # slow traffic, longer look
catnip lora scan -f 868.1,868.3,868.5     # the EU channels
catnip lora scan --sf 7,9 --bw 125        # narrow the search
catnip lora scan -sw 0x2B -f 906.875      # look for Meshtastic
catnip lora scan --passes 0               # keep sweeping until Ctrl+C
```

The host retunes the SX1262 between combinations while the firmware keeps
streaming, and a live table shows which combination is hearing anything.

<!-- TODO: paste a real scan with hardware and LoRa traffic in range.
     See the progress log in plan-implementacion-documentacion.md. -->

---

## How to pick the sweep

The default sweep is 6 spreading factors × 3 bandwidths = **18 combinations**
per frequency, at 3 s each — about a minute per frequency, per pass. Two things
change that:

- **`--dwell` is a time budget per combination, and it has a floor.** A single
  SF12/BW125 frame takes over a second of air time. At the default 3 s the slow
  end can easily miss an infrequent transmitter. If you suspect SF11/SF12,
  raise `--dwell` rather than adding passes.
- **`--sync-word` is not part of the sweep.** It is a single value for the
  whole run, and a mismatch makes every combination silent. `private` (0x12)
  is the default; use `public` for LoRaWAN and `0x2B` for Meshtastic. If a scan
  comes back empty everywhere, the sync word is the first thing to change.

`--passes 0` keeps cycling until `Ctrl+C` — the right choice for traffic that
only appears occasionally.

---

### Notes

- Both subcommands use the **SX1262** over the Cat-LoRa port, so they neither
  need nor disturb whatever CC1352 image is loaded.
- `scan` only finds **LoRa**. For (G)FSK traffic the equivalent knobs are
  bitrate, deviation and sync word — see [`sniff fsk`](sniff.md#sniff-fsk).
- Once you know the settings, save them:
  `catnip sniff lora -freq … -sf … --save-profile mi-perfil`. See
  [radio profiles](sniff.md#radio-profiles).
- A frequency far from 433/470/868/915 MHz is a likely typo: the board's
  antenna matching network is fixed in hardware and will not hear it.

---

## See also

- [`sniff lora`](sniff.md#sniff-lora) / [`sniff fsk`](sniff.md#sniff-fsk) — capture once you know the settings.
- [`sniff profiles`](sniff.md#sniff-profiles) — named settings, so this search happens once.
- [`meshtastic live`](meshtastic.md#meshtastic-live) — if what you found is a Meshtastic mesh.
- [`cativity`](cativity.md) — the 2.4 GHz 802.15.4 equivalent of this reconnaissance step.

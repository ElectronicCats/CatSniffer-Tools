# `catnip cativity`

> IQ Activity Monitor

The reconnaissance step for 802.15.4. [`sniff zigbee`](sniff.md#sniff-zigbee)
and [`sniff thread`](sniff.md#sniff-thread) both **require** a channel, and the
radio hears only the channel it is parked on — so unless you already know which
of the sixteen a network uses, you have to find it first. `cativity` hops
through all of them and shows where the traffic is.

It uses the same TI sniffer firmware as the 802.15.4 capture commands, and
flashes it if it is missing.

## Quick Start

```sh
# 1. Hop every channel and watch where packets appear
catnip cativity

# 2. Park on the busy one for a closer look
catnip cativity --channel 25

# 3. Capture it properly, now that you know the channel
catnip sniff zigbee -c 25 -ws
```

---

## 802.15.4 channels

The standard defines **16 channels in the 2.4 GHz band**, numbered 11 to 26,
each 2 MHz wide and 5 MHz apart:

| Channel | Center frequency |
|---|---|
| 11 | 2405 MHz |
| 12 | 2410 MHz |
| … | … (5 MHz steps) |
| 26 | 2480 MHz |

Both **Zigbee** (mesh IoT: smart home, industrial automation) and **Thread**
(IPv6 mesh: Nest, Matter) sit on this same PHY, which is why one firmware and
one channel map serve both. See [Glossary](../glossary.md) for the terms.

---

## Options

| Option | Description |
|---|---|
| `-d, --device INTEGER` | Device ID (for multiple CatSniffers) |
| `-c, --channel INTEGER RANGE` | Fixed channel (11-26) `[11<=x<=26]` |
| `-t, --topology` | Show network topology |
| `-p, --protocol [all\|zigbee\|thread]` | Protocol filter |

---

## Modes

### Channel hopping (default)

With no `--channel`, it cycles through 11–26 and keeps a running count per
channel. The `Current` column marks where the radio is right now, `Activity`
draws the traffic as a bar, and `Packets` is cumulative:

```
                    Channel Activity
┏━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┓
┃ Current ┃ Channel ┃ Activity                ┃ Packets ┃
┡━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━┩
│         │ 11      │                         │ 0       │
│         │ 15      │ ❚❚                      │ 2       │
│         │ 19      │ ❚                       │ 1       │
│         │ 25      │ ❚❚❚❚❚❚❚❚❚❚❚❚❚❚❚❚❚❚❚❚❚❚❚ │ 23      │
│ ---->   │ 26      │ ❚                       │ 1       │
└─────────┴─────────┴─────────────────────────┴─────────┘
                Channel Hopping Activity
```

Read that as: channel 25 has an active network, 15 has something occasional,
19 and 26 are noise, everything else is quiet.

> [!Note]
> Hopping means the radio is off every other channel while it listens to one.
> **Counts are a sample, not a census** — a quiet channel may simply not have
> transmitted while the radio was there. Let it run for a few cycles before
> concluding anything.

### Fixed channel

`--channel N` disables hopping and stays put. Use it once you know the channel:
it stops missing packets that land while the radio is elsewhere, which matters
both for accurate counts and for topology discovery.

```sh
catnip cativity --channel 15
```

### Topology

`--topology` builds a map of the devices seen and how they relate, rather than
only counting packets. Combine it with a protocol filter to cut the noise:

```sh
catnip cativity --topology --protocol zigbee
```

Topology needs **traffic**, and enough of it. Give it several minutes on a
fixed channel, and generate activity on the network if you can (switch a light,
trip a sensor). A mesh that is idle, or one whose devices only wake
periodically, will show very little.

<!-- TODO: paste real hopping, fixed-channel and topology runs with hardware
     and 802.15.4 traffic in range. See the progress log in
     plan-implementacion-documentacion.md. -->

---

### Notes

- **Running two boards in parallel works**: point each at a different channel
  with `--device` and watch both in separate terminals.
- Nothing at all on any channel usually means range, not a fault — 802.15.4
  radios are low power. Move closer to a known device and wake it up.
- Dropped packets under hopping point at CPU load or another program holding
  the serial port. A fixed channel costs far less.
- Encrypted payloads still count and still appear in the activity view: this
  command works at the PHY/MAC level and never needs to decrypt anything.

---

## See also

- [`sniff zigbee` / `sniff thread`](sniff.md) — capture the channel this command found.
- [`flash`](flash.md) — `catnip flash zigbee` installs the TI firmware by hand if the automatic step fails.
- [`lora spectrum`](lora.md) — the sub-GHz equivalent, for the SX1262 radio.
- Terms: [Glossary](../glossary.md) · Symptoms: [Troubleshooting](../troubleshooting.md).

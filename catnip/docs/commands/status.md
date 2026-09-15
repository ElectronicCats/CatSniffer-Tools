# `catnip status`

> Show board, firmware and capabilities detected on a CatSniffer.

**Honest by design.** Unlike [`sniff`](sniff.md) and [`flash`](flash.md), which
look for *one specific* firmware and flash it when it is missing, `status` only
reports what it can confirm on the device right now. Where it cannot confirm
something it prints `unknown` rather than guessing.

That makes it the right command to run *before* you believe anything else, and
the right output to paste into a bug report.

## Quick Start

```sh
# 1. What is on the first connected board?
catnip status

# 2. A specific board, when several are plugged in
catnip status --device 1

# 3. Add the firmware's own per-thread health dump (v2 boards)
catnip status --diagnostics
```

---

## How it works

`status` assembles its picture from three independent sources, and keeps them
visually separate:

```
  Cat-Shell port ──► board generation ("Board:" line of fw_version)
                 ──► firmware diagnostics (counters, stacks, last fault)
                 ──► cached SX1262 radio config (LoRa + FSK)

  Cat-Bridge port ─► firmware identity ──► capabilities
```

Firmware identity is resolved in confidence order, most reliable first, and
the answer is labelled with the method that produced it:

| `Detected via` | How it was established |
|---|---|
| `metadata` | Read from the firmware id stored on the board. Definitive. |
| `direct communication` | The board answered a protocol probe that only `ti_sniffer` or `sniffle` can answer. Reliable, but only these two can be identified this way. |
| *(row absent, `Firmware: unknown`)* | Neither worked. Nothing is inferred from what happens to be installed. |

**A v2 board keeps no CC1352 firmware id**, so on v2 the `metadata` path is
never available and identification falls back to direct communication — which
is why a v2 running anything other than Sniffle or the TI sniffer reports
`unknown` even when it is working perfectly.

---

## Options

| Option | Description |
|---|---|
| `-d, --device INTEGER` | Device ID (for multiple CatSniffers) |
| `-D, --diagnostics` | Also dump the per-thread stack report and the trace ring (only v2 boards report them) |

```sh
catnip status
```

<!-- TODO: paste a real run with hardware attached. Every table below needs a
     connected CatSniffer. See the progress log in
     plan-implementacion-documentacion.md. -->

With no board connected it fails cleanly and exits 1:

```
✗ No CatSniffer device found!
  Make sure your CatSniffer is connected.
```

---

## What the tables mean

### Status table

One row per fact: `Board`, the three ports, and — when identification
succeeded — `Firmware`, `Detected via` and `Capabilities`.

`Board can` lists what this *generation* is physically able to do, stated up
front instead of only when a command refuses:

| Row | Meaning when `no` |
|---|---|
| Stores the CC1352 firmware id | Firmware identification falls back to direct probing; `unknown` is common. |
| Can self-program the CC1352 (`catnip restore`) | [`restore`](restore.md) is unavailable — no RP2040 to load the CMSIS-DAP probe onto. An external cJTAG programmer is the only route. |
| Its releases ship CC1352 `.hex` assets | Fewer images are offered by [`flash --list`](flash.md); some protocols have no image for this board at all. |

### Firmware diagnostics

Printed whenever the shell port answers. Which rows appear depends on the
board: the SAMD21 (v2) build reports stack headroom, the last fault and a
per-thread dump; the RP2040 (v3) build reports only the two loss counters.

- `loss: ring_dropped` is counted in **bytes**; `loss: uart_overrun` and
  `loss: dma_regress` are **event counts**. A non-zero value is highlighted —
  it means captured data was lost, not that the board is broken.
- `stack unused: <thread>` under **96 bytes** is printed in red and triggers a
  separate warning: that board is close to a stack overflow.

### Radio configuration (SX1262)

The LoRa and FSK cached parameters, shown **side by side regardless of which
modulation is active**. This is deliberate: a capture that comes up silent is
very often a previous session of the *other* modulation that never switched
back.

---

### Notes

- `--diagnostics` only adds output on boards that report it. On a v3 the extra
  thread and trace dump simply does not exist; when it does exist and you did
  not ask, `status` tells you the flag is available.
- Firmware lines the installed version does not recognise are printed
  **verbatim** rather than dropped, so a newer firmware never silently hides
  information from an older catnip.
- The command ends with suggested next steps, derived from the firmware it
  found — or `catnip flash --list` when it found none.

---

## See also

- [`devices`](devices.md) — the port table and how boards are numbered.
- [`verify`](verify.md) — active testing rather than passive reporting.
- [`flash`](flash.md) — what to run when `Firmware` is `unknown` or wrong.
- Generations, images and NVS metadata: [Firmware](../firmware.md).

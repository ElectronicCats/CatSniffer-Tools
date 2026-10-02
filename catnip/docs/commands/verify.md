# `catnip verify`

> Verify CatSniffer device functionality

Where [`status`](status.md) *reports* what the board says about itself, `verify`
*exercises* it: it sends real commands over the Cat-Shell port, reconfigures the
SX1262, and makes the radio transmit. Run it when a board behaves oddly and you
need to know whether the hardware or the firmware is at fault.

It tests **every connected device** unless you name one.

## Quick Start

```sh
# 1. Quick check of all connected devices
catnip verify

# 2. The full run: shell + LoRa configuration + LoRa transmission
catnip verify --test-all

# 3. Just the verdict, for a script
catnip verify --quiet
```

---

## Options

| Option | Description |
|---|---|
| `--test-all` | Run all tests including LoRa configuration and communication |
| `-d, --device INTEGER` | Test only a specific device (by ID) |
| `-q, --quiet` | Show only summary results |

---

## The three test suites

`verify` runs the first suite always, the other two only with `--test-all`.

### 1. Basic Commands — Cat-Shell port

Five shell commands, each checked for an expected substring in the reply:

| Step | Command sent | Passes when the reply contains |
|---|---|---|
| `help` | `help` | `Commands:` |
| `status` | `status` | `Mode:` |
| `lora_config` | `lora_config` | `LoRa Configuration:` |
| `lora_mode` | `lora_mode stream` | `STREAM` |
| `identify` | `identify` | `identify` |

Afterwards it sends `lora_mode command` to put the board back the way it found
it. **All five must pass** for the suite to pass.

### 2. LoRa Configuration — Cat-Shell port

Six configuration commands against the SX1262:

| Step | Command sent |
|---|---|
| `freq` | `lora_freq 915000000` |
| `sf` | `lora_sf 7` |
| `bw` | `lora_bw 125` |
| `cr` | `lora_cr 5` |
| `power` | `lora_power 14` |
| `apply` | `lora_apply` |

> [!Note]
> This suite passes at **4 of 6**, not 6 of 6. The tolerance is deliberate —
> firmware versions differ in which of these commands they acknowledge — but it
> does mean a green `Config` column can hide two failed steps. Read the
> per-step output, not only the summary table, when you are chasing a radio
> problem.

### 3. LoRa Communication — Cat-LoRa **and** Cat-Shell ports

The only suite that uses two ports at once: commands go **out** over the
Cat-LoRa port and the answer is read **back** on Cat-Shell.

| Step | Sent to Cat-LoRa | Passes when Cat-Shell reports |
|---|---|---|
| `TEST` | `TEST` | `TEST`, `LoRa ready` or `initialized` |
| `TEST2` | `TEST` | `TEST` or `LoRa ready` |
| `TXTEST` | `TXTEST` | `TX Result`, `DEBUG: Sending` or `Success` |
| `TX` | `TX 50494E47` | `TX Result` or `Success` |
| `CHECK` | — | reads the LoRa port; **no data is the expected result** |

It switches the board to command mode first and back to stream mode at the end.

> [!Important]
> `TXTEST` and `TX` **transmit**. This is not a passive test — the board emits
> on 915 MHz at 14 dBm with the settings suite 2 just applied. Make sure that is
> legal and appropriate where you are before running `--test-all`.

---

## Reading the summary

Plain `verify` prints one column:

```
  Device      Basic
 ───────────────────
  Device #1    ✅
```

`--test-all` prints four, where `Overall` is the **AND** of the other three —
a single failed suite fails the device:

```
  Device      Basic   Config   Comm   Overall
 ─────────────────────────────────────────────
  Device #1    ✅       ✅      ✅      ✅
```

A device missing the ports a suite needs scores `❌` for that suite rather than
skipping it: no Cat-Shell port fails `Config`, and missing either Cat-LoRa or
Cat-Shell fails `Comm`.

<!-- TODO: paste real runs (plain, --test-all, --quiet) with hardware attached.
     The per-step output above is described from the implementation, not from a
     capture. See the progress log in plan-implementacion-documentacion.md. -->

---

### Notes

- **`verify` changes radio settings and does not put them all back.** Suite 2
  leaves the SX1262 on 915 MHz / SF7 / BW125 / CR4-5 / 14 dBm. If a later
  capture comes up silent, this is a likely reason — pass the settings you want
  explicitly, or check them with `catnip status`.
- `--quiet` still prints each suite header and the per-device `PASS`/`FAIL`
  line; it suppresses the per-step detail and the summary table.
- With no `-d`, every connected device is tested in turn.

---

## See also

- [`status`](status.md) — the passive equivalent; start there.
- [`devices`](devices.md) — confirms the three ports each suite depends on.
- [`flash`](flash.md) — reflashing the CC1352 is the usual next step when `Basic` fails.
- Symptom-by-symptom fixes: [Troubleshooting](../troubleshooting.md).

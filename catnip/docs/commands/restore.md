# `catnip restore`

> Restore CC1352 when bootloader is broken.

The recovery path for the one failure [`flash`](flash.md) cannot fix itself:
a CC1352 whose **serial bootloader no longer answers**. That happens when an
image built for the wrong chip variant is written — a CC1352P7 image on a
CC1352P1 disables the bootloader — or when a flash is interrupted partway.

Instead of the serial bootloader, `restore` goes in over **JTAG**, using the
board's own RP2040 as the programmer.

> [!Important]
> **v3 boards only.** A v2 (SAMD21) has no RP2040 to load the probe onto and
> needs an external cJTAG programmer instead. [`status`](status.md) reports this
> as `Can self-program the CC1352 (catnip restore): no`.

## Quick Start

```sh
# 1. Confirm this is really a dead bootloader and not a dead port
catnip status

# 2. Recover with the default CatSniffer firmware
catnip restore

# 3. Verify the chip answers again
catnip status
```

---

## Prerequisites

**OpenOCD** must be installed:

| Platform | Command |
|---|---|
| Linux | `sudo apt install openocd` |
| macOS | `brew install openocd` |
| Windows | `choco install openocd` |

> [!Note]
> The catnip installer offers to install OpenOCD as part of the setup flow, so
> on a machine set up that way it is usually already present.

---

## How it works

The RP2040 is repurposed twice: first as a CMSIS-DAP JTAG probe to reach the
CC1352, then put back the way it was.

```
  1. RP2040 ──BOOTSEL──► load free_dap (CMSIS-DAP probe firmware)
  2. OpenOCD ──JTAG──► erase CC1352 flash   (bootloader sector preserved)
  3. RP2040 ──BOOTSEL──► reload the official bridge firmware
  4. host ──serial bootloader──► flash the CC1352 image   (now working again)
```

1. **Prerequisite check** — OpenOCD present, required firmware assets available.
2. **JTAG programmer mode** — RP2040 into BOOTSEL, `free_dap` loaded.
3. **CC1352 erase over JTAG** — the bootloader sector is deliberately preserved;
   erasing it is what broke the board in the first place.
4. **Bridge restoration** — RP2040 into BOOTSEL again, official bridge firmware
   put back. The board is a normal CatSniffer again after this step.
5. **Serial flash** — the CC1352 image is written through the bootloader that
   step 3 brought back.

> [!Caution]
> If catnip cannot put the board into BOOTSEL automatically, it stops and asks
> you to do it by hand with the **BOOT** and **RESET** buttons. This is normal
> on a board whose shell port is also unresponsive — it is a prompt, not a
> failure.

---

## Options

| Argument / Option | Description |
|---|---|
| `[FIRMWARE]` | Path to a `.hex` file. If omitted, uses the default CatSniffer firmware from the catnip release. |
| `-d, --device INTEGER` | Device ID (for shell access to trigger BOOTSEL) |
| `--tapid TEXT` | CC1352 JTAG TAPID (default: CC1352P7) |
| `--board [v2\|v3]` | Board generation override (v2 = SAMD21 + CC1352P1, v3 = RP2040 + CC1352P7). Only needed when the Cat-Shell port cannot answer; the wrong value disables the CC1352 bootloader |

The `--tapid` default is `0x1BB7702F`, the CC1352P7 JTAG TAP id. Change it only
for a different CC1352 variant.

```sh
catnip restore                    # default CatSniffer firmware
catnip restore firmware.hex       # custom firmware
catnip restore firmware.hex -d 1  # specific device
catnip restore --board v3         # name the board when its shell is dead
```

With no board connected:

```
✗ No CatSniffer devices found!
  Make sure your CatSniffer is connected.
```

<!-- TODO: paste a real recovery run with hardware attached. See the progress
     log in plan-implementacion-documentacion.md. -->

---

### Notes

- **`-d/--device` here means something narrower than elsewhere**: it selects the
  board whose shell port is used to trigger BOOTSEL. With no `-d`, the first
  device is used and the command warns that it picked for you.
- A board in this state often has a working Cat-Shell port and a silent
  Cat-Bridge. If the *shell* port is also gone, pass `--board v3` so catnip does
  not have to ask the board what it is.
- `restore` is not a faster `flash`. It erases over JTAG and reloads the RP2040
  twice; use [`flash`](flash.md) whenever the serial bootloader still answers.

---

## See also

- [`flash`](flash.md) — the normal path, and the `--board` mismatch that makes this command necessary.
- [`status`](status.md) — tells you whether this board can self-program at all.
- [`update`](flash.md#catnip-update) — updates the host MCU, not the CC1352.

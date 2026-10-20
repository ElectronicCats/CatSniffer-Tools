# Troubleshooting

Symptom first, then the checks in the order worth doing them. Every handled
error is a clean one-line message with a leading `✗` and a non-zero exit code —
**if you get a Python traceback instead, that is a bug**, and the traceback is
what the report needs (see [Traceback instead of an error](#traceback)).

Credentials are redacted from error messages before they are printed, so the
output on this page is safe to paste into an issue.

## Symptoms

**Device and ports**

- [No CatSniffer devices found](#no-devices)
- [Permission denied on the serial port](#permission-denied)
- [A board the OS sees but catnip does not list](#not-all-ports)
- [A command fails while a serial monitor is open](#port-busy)

**Firmware**

- [Flashing fails, or verification mismatches](#flash-failed)
- [Firmware name or alias not found](#firmware-not-found)
- [Not supported on this board generation](#unsupported-board)
- [The board generation comes up unknown](#board-unknown)
- [The board stopped answering after a flash](#bricked)

**Capture**

- [The capture runs but no packets arrive](#no-packets)
- [`cativity` shows zero packets on every channel](#cativity-silent)
- [Packets are being dropped](#dropped-packets)
- [Meshtastic live or dashboard shows nothing](#meshtastic-silent)
- [The AirTag scanner prints nothing](#airtag-silent)
- [Refusing to overwrite the capture file](#capture-file-exists)

**Wireshark**

- [Wireshark not found on this system](#wireshark-missing)
- [Sniffle extcap plugin not found](#extcap-missing)
- [Wireshark opens but stays empty](#wireshark-empty)
- [Timed out waiting for Wireshark](#wireshark-timeout)
- [A stale FIFO is left behind](#stale-pipe)

**Everything else**

- [`vhci start` will not come up](#vhci-down)
- [Tab completion does nothing](#completion-missing)
- [`flash --list` is cut off at the right edge](#narrow-terminal)
- [Traceback instead of an error](#traceback)

---

<a id="no-devices"></a>
## No CatSniffer devices found

**Symptom**

```
⚠ No CatSniffer devices found.
```

or, from any command that needs a board:

```
✗ No CatSniffer device found!
  Make sure your CatSniffer is connected.
```

**Check, in order:**

1. **Is the board on the USB bus at all?** catnip matches VID/PID
   `1209:babb`:

   ```sh
   lsusb | grep 1209                       # Linux
   system_profiler SPUSBDataType           # macOS
   ```

   Nothing here means it is a cable, a port or a power problem, not catnip.
   Try a different cable — charge-only USB cables are the classic cause — and a
   port on the machine rather than a hub.

2. **Does the OS expose the ports?**

   ```sh
   ls -l /dev/ttyACM*                      # Linux
   ls -l /dev/tty.usbmodem*                # macOS
   ```

   On Windows, look under *Ports (COM & LPT)* in Device Manager, and install
   the CH340 / CP210x USB-serial drivers if the entries carry a warning icon.

3. **Are all three interfaces there?** A board whose ports do not all resolve
   is skipped and never gets an ID. `--debug` prints what pyserial actually
   sees, interface by interface:

   ```sh
   catnip devices --debug
   ```

4. **Permissions.** On Linux a port you cannot open can still be listed — see
   [Permission denied](#permission-denied).

`catnip devices` **exits 0** when it finds nothing: an empty list is an answer,
not a failure. Commands that need a board exit 1.

---

<a id="permission-denied"></a>
## Permission denied on the serial port

**Symptom** — on Linux, any command that opens a port fails with the port named
and `[Errno 13] Permission denied` in the message. The board is listed by
`catnip devices`; it just cannot be opened.

**Check, in order:**

1. **Who owns the port?**

   ```sh
   ls -l /dev/ttyACM0     # crw-rw---- 1 root dialout ...
   groups                 # are you in that group?
   ```

2. **Install the rules and join the groups.** This is exactly what
   [`setup-env`](commands/setup-env.md) is for:

   ```sh
   sudo catnip setup-env
   ```

   It writes `/etc/udev/rules.d/99-catsniffer.rules` and adds you to `dialout`
   and `bluetooth`.

3. **Log out and back in.** Group membership is read at login: `groups` will
   keep showing the old list in an existing session. `newgrp dialout` works for
   one shell if you cannot log out yet.

4. **If the rule was installed but nothing changed**, reload udev and re-trigger
   it for the board already plugged in:

   ```sh
   sudo udevadm control --reload-rules
   sudo udevadm trigger
   ls -l /dev/ttyACM*
   ```

   `setup-env` does this itself; it is worth running by hand when the rules file
   was edited some other way.

`sudo chmod 666 /dev/ttyACM*` gets you moving in the next thirty seconds and is
undone by the next replug. Use it to confirm the diagnosis, not as the fix.

---

<a id="not-all-ports"></a>
## A board the OS sees but catnip does not list

**Symptom** — `lsusb` shows the CatSniffer, `/dev/ttyACM*` entries exist, and
`catnip devices` still reports `⚠ No CatSniffer devices found.`

**Why it happens** — catnip keeps a board only when it can assign **all three**
roles (Cat-Bridge, Cat-LoRa, Cat-Shell) to its interfaces. A board where one
role cannot be resolved is skipped whole rather than listed with a gap, so a
partial detection looks exactly like no detection.

Role assignment tries three strategies in order: the USB interface description
string, the USB interface index from the port's location field, and finally
position in sorted port order. The first two need the OS to expose descriptor
data; the third is the Windows fallback.

**Check, in order:**

1. **Count the interfaces catnip can see:**

   ```sh
   catnip devices --debug
   ```

   The raw table lists port, description, HWID, location, interface and serial
   number for every matching USB interface. Fewer than three rows per board is
   the whole answer: the board is not exposing them.

2. **Three rows but still no device** means role mapping failed — the
   `description`, `interface` and `location` columns are all empty or
   identical. This is worth an issue, with that table attached.

3. **Host MCU firmware** is what creates the three CDC interfaces. If one never
   appears, reflashing it with [`update`](commands/flash.md#catnip-update) is
   the fix.

While the shell port is the one missing, commands that need the board
generation can be told explicitly with `--board v2|v3`.

---

<a id="port-busy"></a>
## A command fails while a serial monitor is open

**Symptom** — a `ConnectionError` naming the operation and, underneath it, the
OS reason: `[Errno 16] Device or resource busy`. `identify` renders it as a
panel whose first fix step is *"Check that no other program (e.g. a serial
monitor) has the port open."*

**Check, in order:**

1. **Close anything else holding the port**: `screen`, `minicom`, PuTTY, the
   Arduino IDE serial monitor, another catnip in a second terminal.

   ```sh
   fuser -v /dev/ttyACM2          # Linux: who has it open
   lsof | grep ttyACM             # same question, more output
   ```

2. A `screen` session that was closed with the window rather than `Ctrl-A K`
   is still attached. `screen -ls` then `screen -X -S <id> quit`.

3. Only one process can own a serial port. Two catnip commands against the same
   board at the same time will not work either.

---

<a id="flash-failed"></a>
## Flashing fails, or verification mismatches

**Symptom** — the transfer aborts partway, or the written image does not read
back the same.

**Check, in order:**

1. **The cable.** A marginal USB cable corrupts the transfer and nothing else
   in the chain will tell you so. Swap it before anything else.
2. **Both ports.** Flashing needs Cat-Bridge *and* Cat-Shell: bootloader entry
   is a shell command, the image transfer is a bridge transfer. Confirm with
   `catnip devices`.
3. **Replug and retry.** The CC1352 bootloader can be left in a state a power
   cycle clears.
4. **Check the image is for this board.** A v2 takes CC1352P1 images, a v3
   takes CC1352P7 images:

   ```sh
   catnip flash --list             # what this board can take
   catnip flash --list --all       # the whole catalogue
   ```

5. **Re-download.** Delete the cached release directory and let catnip fetch
   the image again.
6. If the board no longer enumerates at all afterwards, go to
   [The board stopped answering](#bricked).

---

<a id="firmware-not-found"></a>
## Firmware name or alias not found

**Symptom**

```
✗ No firmware specified!

ℹ Use 'catnip flash --list' to see available firmware images and aliases.
ℹ Or specify a firmware name: catnip flash <firmware_name_or_alias>
```

or a name that matched nothing.

**Check, in order:**

1. `catnip flash --list` and copy an alias from the first column. Aliases are
   `sniffle`, `ti_sniffer`, `airtag_scanner_cc1352p7`, `rp2040_boot` and
   friends — **not** the hyphenated spellings some older documentation used.
2. Partial names work as long as they are unambiguous; full file names always
   work.
3. The alias list `--list` prints is filtered by board generation. If the name
   you want is missing, it is not built for this board — see
   [Not supported on this board generation](#unsupported-board).

---

<a id="unsupported-board"></a>
## Not supported on this board generation

**Symptom**

```
╭─ ✗ UnsupportedOnBoardError ──────────────────────────────────────────────────╮
│                                                                              │
│  Problem: Zigbee sniffing needs the 'ti_sniffer' firmware, which is not      │
│  built for a CatSniffer v2 (SAMD21 + CC1352P1).                              │
│                                                                              │
│  Fix:                                                                        │
│    1. Images available for v2: catnip_v2, sniffle.                           │
│    2. This needs a CatSniffer v3 (RP2040 + CC1352P7).                        │
│                                                                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

Exit code **5**, and it is deliberately not a firmware error: nothing went
wrong, and retrying will not help. A v2 has no NVS, no CMSIS-DAP probe, and no
CC1352P7 images.

**Check, in order:**

1. Confirm the generation: `catnip status`.
2. Read what the message offers — it lists the images that *do* exist for that
   generation.
3. If you believe the detection is wrong, force it with `--board v3` on
   `flash`, `update` or `restore` and confirm with `catnip status`.

See [Firmware](firmware.md) for what each generation carries.

---

<a id="board-unknown"></a>
## The board generation comes up unknown

**Symptom**

```
Board generation unknown — showing every image. Connect the Cat-Shell port or pass --board v2/--board v3 to filter.
```

The generation is answered over Cat-Shell. No shell port, no answer.

**Check, in order:**

1. `catnip devices` — is Cat-Shell listed? If not, see
   [the section above](#not-all-ports).
2. Is something else holding the shell port? See [Port busy](#port-busy).
3. Pass `--board v2` or `--board v3` explicitly to get past it for now.

---

<a id="bricked"></a>
## The board stopped answering after a flash

**Symptom** — the USB ports are gone, `catnip devices` finds nothing, and
`catnip update` prints the manual recovery steps:

```
⚠ No CatSniffer device detected

═══════════════════════════════════════════════════
  ⚠  DEVICE NOT DETECTED — Manual Action Required
═══════════════════════════════════════════════════

⚠ The CatSniffer USB endpoints were not found.
⚠ This may indicate corrupted or missing firmware.


To recover the device, follow these steps:

  1. Hold down the button RESET1 on the CatSniffer
  2. Press SW1 button on the CatSniffer
  3. While holding SW1, release RESET1 on the CatSniffer
  4. Release the SW1 button
  5. The CatSniffer should appear as a USB drive named RPI-RP2
```

**Which chip stopped answering decides the fix:**

- **Host MCU (RP2040 / SAMD21)** — no USB ports at all. Follow the button
  sequence above; the board mounts as a USB volume (`RPI-RP2` on v3, `SNIFFER`
  on v2) and [`update`](commands/flash.md#catnip-update) writes the UF2.
- **CC1352 only** — the ports are there, the radio is not answering.
  [`restore`](commands/restore.md) reflashes it through the host MCU's
  debug probe.

---

<a id="no-packets"></a>
## The capture runs but no packets arrive

**Check, in order:**

1. **Is the firmware the one this protocol needs?**

   ```sh
   catnip status
   ```

   BLE needs Sniffle, Zigbee and Thread need the TI sniffer, AirTag needs the
   scanner image. `sniff` flashes the right one on the way in, so a mismatch
   here usually means the flash was skipped or failed.

2. **The channel.** 802.15.4 has no scan mode: the radio hears one channel and
   nothing else. Find the busy one with [`cativity`](commands/cativity.md)
   before capturing. BLE advertises only on 37, 38 and 39.

3. **For LoRa and FSK, every radio parameter has to match** — frequency,
   spreading factor, bandwidth and sync word. One wrong value produces a silent
   capture with nothing in the output to say which. Use a
   [profile](commands/sniff.md#radio-profiles) instead of typing them, or sweep
   with [`lora scan`](commands/lora.md#lora-scan).

4. **Did `verify --test-all` run recently?** It leaves the SX1262 on
   915 MHz / SF7 / BW125 / CR4-5 / 14 dBm. Re-apply your settings.

5. **Is there traffic to catch?** Turn a Zigbee bulb on and off, trigger a
   sensor, send a Meshtastic message. A quiet network looks exactly like a
   broken capture.

6. **The antenna.** 2.4 GHz and sub-GHz use different antennas and a different
   RF path. A frequency far from 433/470/868/915 MHz gets a warning because the
   matching network is fixed in hardware.

---

<a id="cativity-silent"></a>
## `cativity` shows zero packets on every channel

**Check, in order:**

1. **Firmware** — `cativity` needs the TI sniffer image: `catnip status`, then
   `catnip flash ti_sniffer` if it is not there.
2. **Range** — 802.15.4 devices are low-power. Move within a few metres of a
   known Zigbee or Thread device.
3. **Make traffic happen.** Idle mesh networks transmit very little. Switch a
   bulb, open a sensor, re-pair a device.
4. **Try a channel known to be busy** before concluding nothing is there:

   ```sh
   catnip cativity --channel 15     # common Zigbee
   catnip cativity --channel 25     # common Thread
   ```

5. **Topology needs time.** It is built from observed traffic: give it two to
   five minutes on the network's real channel before believing an empty map.

---

<a id="dropped-packets"></a>
## Packets are being dropped

**Symptom** — gaps in the capture, sequence numbers jumping, or fewer packets
than a second sniffer sees.

**Check, in order:**

1. **Stop channel hopping.** Hopping spends most of its time elsewhere: on a
   known channel, `catnip cativity --channel 15` sees everything that channel
   carries. The same applies to capture — `sniff` is single-channel by design.
2. **One reader per port.** A serial monitor or a second catnip competing for
   the same port loses bytes for both. See [Port busy](#port-busy).
3. **Take work off the host.** Dissecting live in Wireshark costs more than
   writing to a file. If the machine is loaded, capture with `-w` and open the
   file afterwards.
4. **Check the USB path.** A hub shared with a busy device, or a long cable,
   shows up as dropped bytes rather than as an error.

---

<a id="meshtastic-silent"></a>
## Meshtastic live or dashboard shows nothing

**Check, in order:**

1. **Preset and frequency must match the mesh.** The defaults are a starting
   point, not a guess that fits every region:

   ```sh
   catnip meshtastic live -f 906.875 -ps LongFast
   ```

2. **Sync word.** Meshtastic uses `0x2B`, not the LoRa default. The
   `meshtastic` commands set it themselves; a raw `sniff lora` does not.
3. **Prove the radio works at all** with `catnip verify --test-all`: if the
   LoRa communication suite fails, the problem is below Meshtastic.
4. **Range and traffic** — a mesh with no chatter produces no packets. Send a
   message from a node you control.

---

<a id="airtag-silent"></a>
## The AirTag scanner prints nothing

**Check, in order:**

1. The scanner needs a **Find My device in range** — an AirTag, or an Apple
   device advertising on the Find My network. Beacons are periodic, not
   continuous: give it a minute.
2. Confirm the firmware landed: `catnip status`.
3. If you asked for `--putty` and got `PuTTY not found!`, install it
   (`sudo apt install putty`, `brew install putty`, or the Windows installer
   from putty.org) or drop the flag and read the output in the terminal.
4. A serial terminal of your own works just as well, at **9600 baud, 8N1**:

   ```sh
   screen /dev/ttyACM0 9600
   minicom -D /dev/ttyACM0 -b 9600
   ```

   Only one process at a time, though — see [Port busy](#port-busy).

---

<a id="capture-file-exists"></a>
## Refusing to overwrite the capture file

**Symptom** — `sniff` stops before touching the radio because the `--write`
target already exists.

This is deliberate: a second PCAP header written into an existing file produces
a capture no dissector reads past. Either write somewhere else, or say so:

```sh
catnip sniff zigbee -c 15 -w capture.pcap -f
```

---

<a id="wireshark-missing"></a>
## Wireshark not found on this system

**Symptom**

```
✗ Wireshark not found on this system
ℹ Install Wireshark, then run the command again:
  sudo apt install wireshark      # Debian / Ubuntu
  sudo pacman -S wireshark-qt     # Arch
  https://www.wireshark.org/download.html
```

The check runs **before** the radio is configured, so nothing was half-started.

**Check, in order:**

1. Install it, or capture to a file now and analyse later:

   ```sh
   catnip sniff lora -w capture.pcapng
   ```

2. Already installed? catnip looks in the standard locations per platform and
   then on `PATH`. A Snap, Homebrew or custom-prefix install is found only if
   `wireshark` is on your `PATH`:

   ```sh
   which wireshark
   ```

---

<a id="extcap-missing"></a>
## Sniffle extcap plugin not found

**Symptom**

```
✗ Sniffle extcap plugin not found!
  Install it from: https://github.com/nccgroup/Sniffle
  Place sniffle_extcap.py (or .exe) in your Wireshark extcap directory.
```

BLE capture into Wireshark goes through NCC Group's Sniffle extcap plugin,
which is not bundled.

**Check, in order:**

1. Find your extcap directory — *Help → About Wireshark → Folders → Extcap
   path* names it. The usual places:

   | Platform | Directory |
   |---|---|
   | Linux | `~/.local/lib/wireshark/extcap/` or `/usr/lib/wireshark/extcap/` |
   | macOS | `~/.local/lib/wireshark/extcap/` |
   | Windows | `%APPDATA%\Wireshark\extcap\` or `C:\Program Files\Wireshark\extcap\` |

2. Drop `sniffle_extcap.py` there and make it executable.
3. On Linux and macOS the plugin is a `.py` file, so a Python interpreter has
   to be reachable. From a PyInstaller build catnip resolves a real interpreter
   rather than the frozen binary; if it cannot, it says so.

Details in [Wireshark](wireshark.md).

---

<a id="wireshark-empty"></a>
## Wireshark opens but stays empty

**Check, in order:**

1. **Is catnip still running?** The capture ends when the command does.
2. **Is the FIFO there?**

   ```sh
   ls -l /tmp/fcatnip        # expect a 'p' in the first column
   ```

3. **Is the dissector right for the link type?** LoRa arrives as LoRaTap and
   needs the LoRaTap dissector; BLE needs Sniffle's. A capture that is arriving
   but not dissected looks like *Malformed Packet*, not like an empty window —
   that distinction tells you which half to fix.
4. **Test the stream without Wireshark in the way:**

   ```sh
   catnip sniff zigbee -c 15 -w /tmp/test.pcap
   tshark -r /tmp/test.pcap | head
   ```

   Packets in the file and nothing in Wireshark means the problem is the plugin
   or the pipe, not the radio.

---

<a id="wireshark-timeout"></a>
## Timed out waiting for Wireshark

**Symptom**

```
✗ Timed out waiting for Wireshark — aborting
```

catnip created the pipe, started Wireshark and nobody opened the other end.

**Check, in order:**

1. Did the Wireshark window actually appear? A missing or broken install is
   the usual cause — see [Wireshark not found](#wireshark-missing).
2. Is an older Wireshark still running and holding the interface list? Close
   every window and retry.
3. Left-over FIFO from a previous run: [stale pipe](#stale-pipe).

---

<a id="stale-pipe"></a>
## A stale FIFO is left behind

A session killed with `SIGKILL`, or a machine that lost power mid-capture,
leaves `/tmp/fcatnip` on disk.

catnip handles this on its own — it reuses an existing FIFO and logs
`Pipeline already exists` at INFO level (visible with `-v`). **It is not an
error**, despite what older documentation said. Remove it only if you suspect
the file is not a FIFO any more:

```sh
ls -l /tmp/fcatnip        # 'p' = FIFO, '-' = a regular file, which is wrong
rm /tmp/fcatnip
```

End captures with `Ctrl-C` and let the process finish its cleanup.

---

<a id="vhci-down"></a>
## `vhci start` will not come up

**Check, in order:**

1. **Run the built-in check first.** It tests each prerequisite separately:

   ```sh
   catnip vhci check
   ```

2. **Kernel module:** `sudo modprobe hci_vhci`, and `/dev/vhci` must exist.
3. **Root:** `/dev/vhci` needs it — `sudo catnip vhci start`.
4. **Firmware:** the bridge speaks to Sniffle. `catnip flash sniffle`.
5. **Board generation:** only the v3 is validated for VHCI.

Full requirement table in [`vhci`](commands/vhci.md).

---

<a id="completion-missing"></a>
## Tab completion does nothing

**Check, in order:**

1. Did you reload the shell after installing? `exec $SHELL`, or source your rc
   file.
2. zsh needs its rc-file entry (`fpath` + `compinit`), which the installer
   appends to `~/.zshrc`. If your `~/.zshrc` is generated from a dotfiles
   manager, the change may have been overwritten.
3. The generated script calls catnip by **absolute path**. Moving or
   reinstalling the venv breaks it: rerun `catnip completion install`.
4. Windows is not supported — the command exits 1 saying so.

---

<a id="narrow-terminal"></a>
## `flash --list` is cut off at the right edge

The `Description` column asks for a minimum width that does not fit in a
terminal narrower than about 140 columns, and `rich` clips the table rather
than wrapping it. Widen the window, or read the same catalogue in
[Firmware](firmware.md). This is a display bug, not a catalogue problem.

---

<a id="traceback"></a>
## Traceback instead of an error

A Python traceback means catnip failed somewhere it did not expect to. **That
is a bug — please report it**, with the full traceback:

```sh
CATNIP_DEBUG=1 catnip <the command that failed>
```

Include the output of `catnip devices` and `catnip status`, and the board
generation. Credentials are redacted from the one-line errors, so paste those
as they come; skim a full traceback before posting it.

---

## See also

- Exit codes and what raises them: [Reference](reference.md#exit-codes).
- What is not supported on your platform at all: [Limitations](limitations.md).
- Terms used above: [Glossary](glossary.md).

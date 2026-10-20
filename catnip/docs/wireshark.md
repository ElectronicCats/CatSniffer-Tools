# Wireshark

Where the packets end up. catnip can hand a live capture to Wireshark while it
runs, or write a file you open afterwards — and which of the two works without
extra setup depends on the protocol, because each radio speaks a different
link-layer format.

- [Two ways in](#two-ways-in)
- [What each protocol needs](#per-protocol)
- [Installing the Sniffle extcap plugin](#sniffle-extcap)
- [The catnip LoRa extcap plugin](#lora-extcap)
- [The LoRa column layout](#columns)
- [Decode As and the LoRaWAN sync word](#decode-as)
- [Limits](#limits)

---

<a id="two-ways-in"></a>
## Two ways in

**Live**, with `-ws/--wireshark`: catnip creates a
[FIFO](glossary.md#fifo) — `/tmp/fcatnip`, or `\\.\pipe\fcatnip` on Windows —
writes [pcap](glossary.md#pcap) frames into it and launches
`wireshark -k -i <fifo>`. The capture ends when catnip does.

**Afterwards**, with `-w/--write FILE`, or `-oc/--open-capture` to write a
temporary file and open it when the sniffer stops. Nothing is lost by choosing
this route: the same bytes reach the same dissectors, just not while they
arrive.

```sh
catnip sniff zigbee -c 15 -ws               # live
catnip sniff zigbee -c 15 -w capture.pcap   # file
catnip sniff zigbee -c 15 -ws -w capture.pcap  # both, one run
catnip sniff lora -oc                       # sniff now, open when it stops
```

Wireshark is looked for in the standard location for your platform and then on
`PATH`, **before** the radio is configured — so a missing install is one line
of output, not a capture that mysteriously times out. See
[Troubleshooting](troubleshooting.md#wireshark-missing).

---

<a id="per-protocol"></a>
## What each protocol needs

| Capture | Link type | Dissected by | Extra setup |
|---|---|---|---|
| `sniff ble` | Sniffle's own | NCC Group's `sniffle_extcap` | **the plugin, installed separately** |
| `sniff zigbee` | DLT 147 (USER0) | Wireshark's 802.15.4 dissector | a Wireshark profile named `Zigbee` |
| `sniff thread` | DLT 147 (USER0) | Wireshark's 802.15.4 dissector | a Wireshark profile named `Thread` |
| `sniff lora` | DLT 270 ([LoRaTap](glossary.md#loratap)) | built into Wireshark | none |
| `sniff fsk` | DLT 270 (LoRaTap) | built into Wireshark | none |

**LoRa and FSK need nothing installed.** LoRaTap is a link type Wireshark
dissects natively, and catnip writes the radio metadata — RSSI, SNR, sync word,
bandwidth — into the LoRaTap header, so the packet list can show link quality
per frame.

**Zigbee and Thread are launched with `wireshark -C Zigbee` / `-C Thread`**,
naming a Wireshark *configuration profile*. Create those profiles once (*Edit →
Configuration Profiles*, `+`, name it exactly `Zigbee` or `Thread`) and set the
USER0 (DLT 147) mapping to the 802.15.4 dissector inside them. Without the
profile Wireshark falls back to the default one, where USER0 is unmapped and
frames show as raw data.

**BLE goes through a plugin and a second pipe.** catnip runs `sniffle_extcap`
itself, reads its output through an internal pipe, and re-emits it into the
pipe Wireshark reads — which is why the sequence is *wait for the sniffer
header → launch Wireshark → wait for it to connect*, each step with its own
timeout and its own error line.

---

<a id="sniffle-extcap"></a>
## Installing the Sniffle extcap plugin

Not bundled with catnip: it belongs to
[NCC Group's Sniffle](https://github.com/nccgroup/Sniffle), the same project as
the BLE firmware.

1. Find your extcap directory — *Help → About Wireshark → Folders → Extcap
   path*:

   | Platform | Directory |
   |---|---|
   | Linux | `~/.local/lib/wireshark/extcap/`, `/usr/lib/wireshark/extcap/`, `/usr/local/lib/wireshark/extcap/` |
   | macOS | `~/.local/lib/wireshark/extcap/` |
   | Windows | `%APPDATA%\Wireshark\extcap\`, `C:\Program Files\Wireshark\extcap\` |

2. Put `sniffle_extcap.py` (or the `.exe` on Windows) there and make it
   executable.

3. Restart Wireshark. catnip finds the plugin in those same directories.

On Linux and macOS the plugin is a Python script, so an interpreter has to be
reachable. Running catnip from a PyInstaller build, `sys.executable` is the
frozen binary rather than Python, so catnip resolves a real interpreter before
launching the plugin — and says so plainly if it cannot find one.

---

<a id="lora-extcap"></a>
## The catnip LoRa extcap plugin

catnip also ships an extcap plugin of its own,
[`lora_extcap.py`](../lora_extcap.py), which makes the CatSniffer appear in
Wireshark's interface list as **CatSniffer LoRa Extcap**. It is for starting a
LoRa capture *from Wireshark* rather than from the CLI, and it adds a toolbar
where frequency, spreading factor, bandwidth, coding rate and TX power can be
changed mid-capture.

Install it by linking it into the extcap directory:

```sh
ln -s "$PWD/lora_extcap.py" ~/.local/lib/wireshark/extcap/lora_extcap.py
chmod +x ~/.local/lib/wireshark/extcap/lora_extcap.py
```

> [!Note]
> **The plugin and `catnip sniff lora` do not produce the same link type.** The
> plugin emits DLT 148 (USER1) under the name `catnip_lora_dlt`, which needs a
> USER1 mapping configured in Wireshark; `sniff lora` emits LoRaTap (270),
> which needs nothing. Unless you specifically want the in-Wireshark toolbar,
> the CLI path is the one that works out of the box.

---

<a id="columns"></a>
## The LoRa column layout

Wireshark's default columns assume an addressed link layer. A LoRa radio
reports no addresses, so *Source*, *Destination* and *Info* arrive empty and
the payload is only visible after clicking into a packet.

For LoRa and FSK captures catnip overrides the column set **on the command
line**, leaving your saved layout untouched:

| Column | Source |
|---|---|
| RSSI | `loratap.rssi.packet`, rendered as `-42 dBm` |
| SNR | `loratap.rssi.snr`, rendered as `9.0 dB` — **LoRa only**; an FSK capture drops this column, because the SX1262 never measures it |
| Info | `loratap.payload` as hex |
| ASCII | `catnip_lora.ascii` — the same payload as text |

The ASCII column comes from a Lua postdissector,
[`protocol/lora_ascii.lua`](../protocol/lora_ascii.lua), passed with
`-X lua_script:`. It runs after the LoRaTap dissector, picks
`loratap.payload` back up and registers the same bytes a second time as a
string field. Bytes outside printable 7-bit ASCII become `.`, so one packet
stays one line.

The column is only requested when the script is actually present, so a
Wireshark built without Lua — or a build that did not ship the script — still
gets the other columns instead of an error.

---

<a id="decode-as"></a>
## Decode As and the LoRaWAN sync word

Wireshark's LoRaTap dissector picks the payload dissector from the
[sync word](glossary.md#sync-word): `0x34` means
[LoRaWAN](glossary.md#lorawan). A plain-LoRa payload captured on `0x34` then
arrives stamped *LoRaWAN MAC Header malformed* over every frame, which reads
like a broken capture rather than a dissector mismatch.

catnip overrides that with a `-d` argument, so a `0x34` capture is dissected as
raw data: the harmless reading. Nothing is lost — a capture that really is
LoRaWAN is one *Decode As…* away from the LoRaWAN dissector, and the bytes in
the file never changed.

This follows from the sync word alone, so it is not a CLI option: the only
thing a separate flag could achieve is breaking your own capture.

---

<a id="limits"></a>
## Limits

- **One live capture per machine.** The pipe name is fixed (`fcatnip`), so two
  simultaneous Wireshark captures collide. Capture to files instead, and open
  them afterwards.
- **The Sniffle plugin is not bundled** and cannot be installed for you.
- **Elevated permissions** may be needed depending on how Wireshark was
  installed — the usual Debian/Ubuntu answer is membership of the `wireshark`
  group, which its installer offers to set up.
- **Nothing is dissected retroactively.** Columns, `Decode As` and the Lua
  script are applied to the Wireshark that catnip launches; an already-open
  Wireshark reading the same file uses your own configuration.

---

## See also

- The capture flags themselves: [`sniff`](commands/sniff.md).
- Empty windows, missing plugins, stale pipes:
  [Troubleshooting](troubleshooting.md#wireshark-missing).
- Link types and framing: [Protocol](protocol.md).

# Glossary

Terms that appear across these pages, alphabetically. Each entry says what the
word means **here**, and links to the page where it actually matters.

---

<a id="802-15-4"></a>
### 802.15.4

The IEEE standard for low-rate wireless personal area networks: the physical
and MAC layers that both [Zigbee](#zigbee) and [Thread](#thread) are built on.
In the 2.4 GHz band it defines 16 channels, numbered **11 to 26**. Because the
two protocols share the radio layer, one sniffer firmware and one channel map
serve both — which is what [`cativity`](commands/cativity.md) scans.

<a id="airtag"></a>
### AirTag / Find My

Apple's crowdsourced tracking network. An AirTag advertises over
[BLE](#ble); any passing Apple device relays the sighting to iCloud. catnip
carries a dedicated scanner image for the CC1352 that reports those beacons —
see [`sniff airtag_scanner`](commands/sniff.md#sniff-airtag_scanner).

<a id="alias"></a>
### Alias (firmware)

A short name for a firmware image, so you write `catnip flash sniffle` instead
of `sniffle_cc1352p7_1M.hex`. One alias can resolve to different files on
different board generations. The list lives in
[`flash --list`](commands/flash.md) and in [Firmware](firmware.md).

<a id="bandwidth"></a>
### Bandwidth (BW)

How much spectrum a [LoRa](#lora) transmission occupies: `125`, `250` or
`500` kHz. Wider is faster and less sensitive. A receiver only demodulates a
frame whose bandwidth it is already set to, so this is one of the four values
that must match the transmitter exactly — with
[frequency](#frequency), [spreading factor](#spreading-factor) and
[sync word](#sync-word).

<a id="ble"></a>
### BLE (Bluetooth Low Energy)

The 2.4 GHz protocol behind beacons, wearables and most smart-home gadgets.
Advertising happens on three channels only — **37** (2402 MHz), **38**
(2426 MHz) and **39** (2480 MHz). catnip sniffs it with
[Sniffle](#sniffle): [`sniff ble`](commands/sniff.md#sniff-ble).

<a id="bootloader"></a>
### Bootloader

The small program that accepts a firmware image over USB or serial. Two of them
matter here: the **CC1352 serial bootloader**, used by
[`flash`](commands/flash.md), and the host MCU's **UF2 bootloader**, which
mounts the board as a USB volume and is what
[`update`](commands/flash.md#catnip-update) and the manual recovery steps use.

<a id="cat-ports"></a>
### Cat-Bridge / Cat-LoRa / Cat-Shell

The three USB serial ports every CatSniffer exposes, one per function:
**Cat-Bridge** carries CC1352 traffic and firmware transfers, **Cat-LoRa**
carries SX1262 traffic, and **Cat-Shell** is the interactive command shell of
the host MCU — board identity, firmware version, bootloader entry. They are not
interchangeable. See [`devices`](commands/devices.md).

<a id="cativity"></a>
### Cativity

catnip's own name for its [802.15.4](#802-15-4) activity monitor: it hops
channels, counts packets, and tells you where the traffic is before you commit
a capture to one channel. [`cativity`](commands/cativity.md).

<a id="catsniffer"></a>
### CatSniffer v1 / v2 / v3

The board generations. A **v2** pairs a SAMD21 host MCU with a CC1352P1 radio;
a **v3** pairs an [RP2040](#rp2040) with a CC1352P7. The generation decides
which firmware images exist, whether firmware metadata can be stored in
[NVS](#nvs), and whether [VHCI](#vhci) works. Details in
[Firmware](firmware.md).

<a id="cc1352"></a>
### CC1352

The Texas Instruments multi-protocol radio SoC on the CatSniffer — `CC1352P1`
on a v2, `CC1352P7` on a v3. It is the chip that gets **reflashed** per
protocol: BLE, Zigbee, Thread and the AirTag scanner are different images for
the same silicon.

<a id="channel"></a>
### Channel

A fixed slice of spectrum. [802.15.4](#802-15-4) uses 11–26 in the 2.4 GHz
band, [BLE](#ble) advertising uses 37–39. A sniffer hears **one channel at a
time**: the wrong channel looks exactly like no traffic.

<a id="coding-rate"></a>
### Coding rate (CR)

[LoRa](#lora)'s forward error correction ratio, `5` to `8` (meaning 4/5 to
4/8). Higher values survive more interference and send fewer payload bits per
second.

<a id="extcap"></a>
### extcap

Wireshark's external-capture plugin interface. A plugin advertises a capture
source, and Wireshark shows it as an interface alongside `eth0` and friends.
BLE capture uses NCC Group's `sniffle_extcap`, which is **not bundled** —
see [Wireshark](wireshark.md).

<a id="fifo"></a>
### FIFO / named pipe

The one-way file-like channel a live capture flows through: catnip writes
[pcap](#pcap) bytes into it and Wireshark reads them out. On Linux and macOS it
is a filesystem FIFO (`/tmp/fcatnip`); on Windows a named pipe
(`\\.\pipe\fcatnip`).

<a id="frequency"></a>
### Frequency

The sub-GHz carrier, in Hz, for [LoRa](#lora) and [FSK](#fsk) — `915000000`
for 915 MHz. The antenna matching network is fixed in hardware, so values far
from the 433 / 470 / 868 / 915 MHz bands receive nothing regardless of what
the radio accepts.

<a id="fsk"></a>
### FSK / GFSK

Frequency-shift keying: the other modulation the [SX1262](#sx1262) can
demodulate, used by many sub-GHz remotes, sensors and alarm systems. Simpler
and shorter-range than LoRa. [`sniff fsk`](commands/sniff.md#sniff-fsk).

<a id="iq"></a>
### IQ

In-phase and quadrature, the two components of a sampled radio signal. Two
distinct uses here: **IQ polarity** (`normal` / `inverted`) is a LoRa setting —
LoRaWAN downlinks are inverted — and *IQ Activity Monitor* is the CLI's own
description of [`cativity`](commands/cativity.md).

<a id="lora"></a>
### LoRa

A chirp-spread-spectrum modulation for long-range, low-rate sub-GHz links. On
the CatSniffer it lives on the [SX1262](#sx1262), reached over Cat-LoRa. Four
parameters must match the transmitter for anything to be received:
[frequency](#frequency), [spreading factor](#spreading-factor),
[bandwidth](#bandwidth) and [sync word](#sync-word).

<a id="loratap"></a>
### LoRaTap

The pcap link type (DLT **270**) that carries a LoRa frame plus its radio
metadata — RSSI, SNR, sync word, bandwidth. Wireshark dissects it natively, so
LoRa captures need no plugin, unlike [BLE](#ble). 2.4 GHz captures use DLT
**147** (USER0) instead.

<a id="lorawan"></a>
### LoRaWAN

The network protocol layered on top of [LoRa](#lora), with gateways, join
procedures and encryption. It is identified on the air by the **public**
[sync word](#sync-word) `0x34`; plain LoRa links use `0x12`. Wireshark picks
its dissector from that byte.

<a id="meshtastic"></a>
### Meshtastic

An open-source mesh messaging protocol on top of [LoRa](#lora), with its own
packet format, channel presets (`LongFast`, `ShortTurbo`, …) and sync word
`0x2B`. catnip decodes it offline, live, or in a chat-style TUI:
[`meshtastic`](commands/meshtastic.md).

<a id="nvs"></a>
### NVS (Non-Volatile Storage)

A small key/value area in the host MCU's flash where a **v3** records which
CC1352 image was last written. That record is what lets
[`status`](commands/status.md) answer "what firmware is on the radio" without
probing it. A v2 has no NVS — hence `ERR not supported on this board` — which
is why firmware detection on a v2 falls back to behavioural checks.

<a id="pcap"></a>
### pcap / pcapng

The two capture file formats. `.pcap` is the classic flat format; `.pcapng` is
the modern one, with per-interface metadata and comments. catnip picks by
extension: `-w capture.pcapng` writes pcapng, anything else writes pcap.

<a id="preamble"></a>
### Preamble

The run of known symbols that opens a [LoRa](#lora) frame so the receiver can
lock onto it, counted **in symbols** (6–65535, default 12). A
receiver with too short a preamble setting misses the start of the frame and
hears nothing.

<a id="rp2040"></a>
### RP2040

The host MCU on a **v3**: it runs the USB interfaces, the Cat-Shell command
shell and the CMSIS-DAP debug probe used to
[restore](commands/restore.md) a CC1352 whose bootloader no longer answers.
On a **v2** the equivalent chip is a SAMD21, which has neither
[NVS](#nvs) nor the probe.

<a id="rssi"></a>
### RSSI

Received signal strength indicator, in dBm — always negative, closer to zero is
stronger. Reported per packet in captures and in the live panels. Paired with
**SNR** (signal-to-noise ratio) on LoRa, where a frame can decode at negative
SNR.

<a id="sniffle"></a>
### Sniffle

NCC Group's open-source BLE sniffer firmware for TI radios, and the image
catnip flashes for [`sniff ble`](commands/sniff.md#sniff-ble). Its companion
[extcap](#extcap) plugin is what feeds Wireshark. It is also the firmware the
[VHCI](#vhci) bridge speaks to.

<a id="spreading-factor"></a>
### Spreading factor (SF)

How many chips encode one [LoRa](#lora) symbol, `7` to `12`. Higher spreads the
signal further in time: more range and sensitivity, lower data rate, longer
airtime. Must match the transmitter exactly.

<a id="sx1262"></a>
### SX1262

The Semtech sub-GHz transceiver on the CatSniffer, reached over Cat-LoRa. It
does [LoRa](#lora) and [FSK](#fsk). Unlike the [CC1352](#cc1352) it is not
reflashed per protocol — it is **configured**, which is why those commands take
radio parameters instead of a firmware name.

<a id="sync-word"></a>
### Sync word

The byte that opens a [LoRa](#lora) frame and separates coexisting networks on
one frequency: `0x12` private (the default), `0x34` public
([LoRaWAN](#lorawan)), `0x2B` [Meshtastic](#meshtastic). Wrong sync word, no
packets — and Wireshark also picks its payload dissector from it.

<a id="thread"></a>
### Thread

An IPv6 mesh networking protocol over [802.15.4](#802-15-4), used by Matter
devices and HomeKit accessories. Same radio layer and channel numbering as
[Zigbee](#zigbee), different stack above it:
[`sniff thread`](commands/sniff.md#sniff-thread).

<a id="ti-sniffer"></a>
### TI sniffer firmware

Texas Instruments' multi-protocol sniffer image (`ti_sniffer`), the one catnip
flashes for Zigbee and Thread capture. Originally built for TI's own
SmartRF Packet Sniffer 2.

<a id="uf2"></a>
### UF2

The USB flashing format the host MCU's [bootloader](#bootloader) accepts:
the board mounts as a USB volume (`RPI-RP2` on a v3, `SNIFFER` on a v2) and
copying the `.uf2` file onto it flashes it. This is the path
[`update`](commands/flash.md#catnip-update) drives, and the manual recovery
route when the board no longer enumerates.

<a id="vhci"></a>
### VHCI

Linux's virtual HCI interface (`/dev/vhci`, kernel module `hci_vhci`). Writing
HCI packets to it makes BlueZ register a controller as `hciN`. catnip uses it
to present the CatSniffer as an ordinary Bluetooth adapter to `bluetoothctl`,
`btmon` and anything else that speaks BlueZ: [`vhci`](commands/vhci.md).

<a id="zigbee"></a>
### Zigbee

A mesh protocol over [802.15.4](#802-15-4), widely used by smart bulbs, plugs
and sensors. Channels 11–26; channel 15 is a common default. Same radio layer
as [Thread](#thread): [`sniff zigbee`](commands/sniff.md#sniff-zigbee).

---

## See also

- Global options and exit codes: [Reference](reference.md).
- The end-to-end flow these terms describe: [Usage](usage.md).

# CatSniffer recipes

These are worked scenarios built from catnip commands. Each one assumes:

- `catnip devices` already shows the board.
- The user is authorised to capture the target.

Add `-d N` whenever more than one board is connected.

## 1. Investigate a Zigbee or Thread network (v3 only)

```sh
catnip status                         # must be v3: v2 has no TI sniffer image
catnip cativity                       # hop 11-26, watch which channel lights up
catnip cativity -c 20 -t -p zigbee    # park on it and map devices (needs minutes of traffic)
catnip sniff zigbee -c 20 -ws -w zb.pcapng
```

- **Thread**: swap `zigbee` for `thread` in the commands above.
- **Wireshark shows raw data**: create the `Zigbee` / `Thread` configuration profiles with USER0 (DLT 147) mapped to `wpan`.
- **Decrypting**: add the network key under *Protocols → ZigBee → Security*, or the Thread master key under *IEEE 802.15.4 → Decryption keys*.

**Offline analysis:**

```sh
tshark -r zb.pcapng -c 20
```

## 2. BLE

```sh
catnip sniff ble                              # flashes Sniffle if needed
catnip sniff ble -c 37 -m passive_scan        # listen only, one adv channel
catnip sniff ble -m conn_follow -ws           # follow connections into Wireshark
```

- **Wireshark** needs `sniffle_extcap.py` from NCC Group's Sniffle in the extcap directory. Find the directory under *Help → About → Folders*.
- **`active_scan` transmits** SCAN_REQ. Use it only when that is acceptable.
- **v2 boards** get the CC1352P1 build of Sniffle automatically.

## 3. LoRa / LoRaWAN

```sh
catnip sniff profiles -c lora                         # built-in presets
catnip sniff lora -freq 868100000 -sf 7 -bw 125 -sw public -w up.pcapng      # LoRaWAN uplinks (EU)
catnip sniff lora -freq 869525000 -sf 9 -bw 125 -sw public --iq inverted     # LoRaWAN RX2 downlinks (EU)
catnip sniff lora -freq 903900000 -sf 7 -bw 125 -sw public                   # US915 uplink ch.8
catnip sniff lora -l                                                         # live RSSI/SNR panel
```

**Save settings that work, and reuse them by name:**

```sh
catnip sniff lora -freq 868100000 -sf 7 -sw public --save-profile eu-lorawan-up
catnip sniff lora -P eu-lorawan-up
```

LoRaTap (DLT 270) is dissected natively. In Wireshark, use *Decode As* to apply the LoRaWAN dissector to the payload.

## 4. Unknown sub-GHz transmitter

```sh
catnip lora spectrum --start-freq 860 --end-freq 930     # where is the energy?
catnip lora scan -f 868.1,868.3,868.5 --dwell 5          # which SF/BW hears frames?
catnip lora scan -f 915 --sf 10,11,12 --bw 125 --dwell 8 # slow modes need longer dwell
```

What to do next depends on the scan:

- **The scan finds frames**: capture with those exact settings using `catnip sniff lora ...`.
- **The scan finds nothing, but `lora spectrum` shows energy**: the signal is probably FSK, not LoRa. Go to recipe 5.

## 5. (G)FSK: meters, alarms, 802.15.4g / Wi-SUN

FSK only demodulates frames that match its settings exactly:

- bitrate
- deviation
- sync word
- whitening

```sh
catnip sniff profiles -c fsk          # built-ins are LoRa only; this lists your saved FSK profiles
catnip sniff fsk -freq 868950000 -br 100000 -fd 50000 -bw 234.3 -l
catnip sniff fsk -freq 915000000 -sw 2DD4 --whitening -w wisun.pcapng   # 802.15.4g-style
catnip sniff fsk --bt off ...                                           # plain FSK, no Gaussian shaping
```

**Bandwidth**: the RX bandwidth must be at least `bitrate + 2 × deviation`. Otherwise the firmware falls back to 187.2 kHz.

## 6. Meshtastic

```sh
catnip meshtastic config node-export.jsonc                # pull channel PSKs out of a config export
catnip meshtastic live -f 906.875 -ps LongFast            # US default channel, decode live
catnip meshtastic dashboard -f 869.525 -ps LongFast       # EU, chat-style TUI
catnip meshtastic decode -i <hex> -k <base64-psk>         # one packet; -k nokey / ham for open channels
catnip sniff lora -P us915-meshtastic-longfast -w mesh.pcapng  # raw capture instead of decoding
```

**Sync word**: Meshtastic uses `0x2B`. The `*-meshtastic-*` profiles set it for you.

## 7. A v1/v2 (SAMD21) board

- `catnip status` shows `Board: v2 SAMD21 CC1352P1`.
- **What works**: BLE (Sniffle P1 build), LoRa, FSK and Meshtastic.
- **What does not work**: Zigbee, Thread, AirTag, `restore` and `vhci`. These exit with code **5**. Retrying will not help. Tell the user it is a hardware limit.
- **`update`** uses `v2.X.Y.Z` releases and the `SNIFFER` UF2 volume.

## 8. Recovery

The board stopped answering after a flash:

```sh
catnip devices                 # 3 ports present? If not, it's the host MCU -> catnip update (prints manual Boot Mode steps if undetected)
catnip status                  # CC1352 unknown but shell alive -> try catnip flash <alias> again
catnip restore                 # v3 only: RP2040 becomes a CMSIS-DAP probe, OpenOCD reflashes the CC1352
catnip restore my.hex --board v3   # only if the shell is dead AND the user knows it is a v3
catnip verify
```

**v2 boards** cannot be restored this way. They need an external cJTAG programmer.

## 9. Scripting / CI

```sh
set -e
catnip devices                                   # exit 0 even if empty: parse the output, don't trust the code
catnip status -d 1 || { echo "board 1 unhealthy ($?)"; exit 1; }
timeout 60 catnip sniff zigbee -d 1 -c 15 -w "zb-$(date +%s).pcap" || true   # timeout returns 124
CATNIP_DEBUG=1 catnip flash zigbee -d 1          # full traceback in logs
```

Notes:

- **Treat every non-zero exit as a failure.** "No device" exits 1, not 4.
- **One live `-ws` capture per machine**, because the FIFO name is fixed. For parallel captures across boards, use `-w` files.
- **Banner**: every command prints it, so parse output with care. There is no supported flag to suppress it.

## 10. Use the CatSniffer as a Linux Bluetooth adapter (VHCI, v3)

```sh
catnip flash sniffle
sudo modprobe hci_vhci
catnip vhci check                 # module, /dev/vhci, root, packages
sudo catnip vhci start            # prints "Created hciN"
# in another terminal:
sudo bluetoothctl                 # select <bridge BD_ADDR>, scan on, connect ...
sudo btmon -i hciN
```

The board can then be used from BlueZ tools: bettercap (`set ble.device N`) and bleak (`adapter="hciN"`).

- **The bridge transmits**: it acts as a real BLE controller.
- **Idle timeout**: after GATT resolution there is a 60 s idle window before the watchdog drops the link.
- **Details and quirks**: `catnip/modules/protocols/vhci/README.md`.

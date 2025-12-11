# Context

Esta version nueva pretende ser una combinacion de todas las herramientas actuales.

Por lo que en lugar de tener scripts individuales, se utilizara un solo script que permita realizar las funciones de los scripts individuales.

## Cambios

Al iniciar de cero la herramienta comienza a descargar los releases del repo

```shell
python3 catsniffer.py
[10:20:29] [*] Looking for local releases
           [*] No Local release folder found!
           [*] Local release folder created: /Users/astrobyte/ElectronicCats/CatSniffer-Tools/envcat/release_board-v3.x-v1.2.2
           [*] Local metadata created
[10:20:30] [*] Firmware airtag_scanner_CC1352P_7_v1.0.hex done.
           [*] airtag_scanner_CC1352P_7_v1.0.hex Checksum SHA256 verified
           [*] Firmware airtag_spoofer_CC1352P_7_v1.0.hex done.
           [*] airtag_spoofer_CC1352P_7_v1.0.hex Checksum SHA256 verified
[10:20:31] [*] Firmware justworks_scanner_CC1352P7_1.hex done.
           [*] justworks_scanner_CC1352P7_1.hex Checksum SHA256 verified
           [*] Firmware sniffer_fw_CC1352P_7_v1.10.hex done.
           [*] sniffer_fw_CC1352P_7_v1.10.hex Checksum SHA256 verified
[10:20:34] [*] Firmware sniffle_cc1352p7_1M.hex done.
           [*] sniffle_cc1352p7_1M.hex Checksum SHA256 verified
           [*] Current Release board-v3.x-v1.2.2 - 2025-06-09T22:07:38Z
Usage: catsniffer.py [OPTIONS] COMMAND [ARGS]...

  CatSniffer: All in one catsniffer tools environment.

Options:
  --help  Show this message and exit.

Commands:
  cativity  IQ Activity Monitor
  flash     Flash firmware
  releases  Show Firmware releases
  sniff     Sniffer protocol control
```

El script genera un archivo de metadatos dentro del folder de release, en este archivo se guarda cuando fue la ultima consulta, si esta comparacion es diferente, el script vuelve a mandar un request hacia github para buscar nuevos releases.

## Flash CC1352

> El script detecta automaticamente la catsniffer, pero si es necesario se puede utilizar `-p` para declarar el puerto

```shell
python3 catsniffer.py releases
[10:45:15] [*] Looking for local releases
           [*] Local release folder found!
           [*] Local metadata loaded
           [*] Current Release board-v3.x-v1.2.2 - 2025-06-09T22:07:38Z
                                                                                      Releases board-v3.x-v1.2.2
┏━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ No. ┃ Firmware                                  ┃ Microcontroller ┃ Description                                                                                                                     ┃
┡━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 0   │ LoRa-CLI.uf2                              │ RP2040          │ LoRa Command Line Interface                                                                                                     │
│ 1   │ sniffer_fw_CC1352P_7_v1.10.hex            │ CC1352          │ Multiprotocol sniffer from Texas Instrument (Windows)                                                                           │
│ 2   │ airtag_scanner_CC1352P_7_v1.0.hex         │ CC1352          │ Apple Airtag Scanner firmware (Windows/Linux/Mac)                                                                               │
│ 3   │ sniffle_cc1352p7_1M.hex                   │ CC1352          │ BLE sniffer for Bluetooth 5 and 4.x (LE) from NCC Group. See [Sniffle](https://github.com/nccgroup/Sniffle) (Windows/Linux/Mac) │
│ 4   │ firmware.uf2                              │ RP2040          │ Meshtastic port for Catsniffer                                                                                                  │
│ 5   │ airtag_spoofer_CC1352P_7_v1.0.hex         │ CC1352          │ Apple Airtag Spoofer firmware (Windows/Linux/Mac)                                                                               │
│ 6   │ LoraSniffer.uf2                           │ RP2040          │ CLI LoRa for connection with pycatsniffer as sniffer                                                                            │
│ 7   │ justworks_scanner_CC1352P7_1.hex          │ CC1352          │ Justworks scanner for scanner vulnerable devices                                                                                │
│ 8   │ free_dap_catsniffer.uf2                   │ RP2040          │ Debugger firmware for CC1352                                                                                                    │
│ 9   │ LoRa-CAD.uf2                              │ RP2040          │ Channel activity detector                                                                                                       │
│ 10  │ SerialPassthroughwithboot_RP2040_v1.1.uf2 │ RP2040          │ Serialpassthrough for CC1352 applications                                                                                       │
└─────┴───────────────────────────────────────────┴─────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```


```shell
python3 catsniffer.py flash --help
[10:36:24] [*] Looking for local releases
           [*] Local release folder found!
           [*] Local metadata loaded
           [*] Current Release board-v3.x-v1.2.2 - 2025-06-09T22:07:38Z
Usage: catsniffer.py flash [OPTIONS] FIRMWARE

  Flash CC1352 Firmware

Options:
  -f, --firmware TEXT  Firmware name or path.
  -p, --port TEXT      Catsniffer Path
  --help               Show this message and exit.
```

### Flashing

```shell
python3 catsniffer.py flash sniffle
[10:43:11] [*] Looking for local releases
           [*] Local release folder found!
           [*] Local metadata loaded
           [*] Current Release board-v3.x-v1.2.2 - 2025-06-09T22:07:38Z
[10:43:11] [*] Flashing firmware: sniffle
           [*] Opening port /dev/cu.usbmodem2123401 at baud: 500000
           [*] Connecting to target..
           [-] Unrecognized chip ID. Trying CC13xx/CC26xx
           [*] Chip details:
                   Package: CC1350 PG2.0 - 704 KB Flash - 20KB SRAM - CCFG.BL_CONFIG at 0x000AFFD8
                   Primary IEEE Address: 00:12:4B:00:2A:79:BF:AC
           [*] Performing mass erase
           [*] Erase done
[10:43:14] [*] Write done
           [*] Verifying by comparing CRC32 calculations.
[10:43:15] [*] Verified match: 0x6d6c64a5

```


### Errors

```shell
python3 catsniffer.py flash sniffle -p /dev/tty.usbmodem2123401
[10:34:43] [*] Looking for local releases
           [*] Local release folder found!
           [*] Local metadata loaded
           [*] Current Release board-v3.x-v1.2.2 - 2025-06-09T22:07:38Z
[10:34:43] [*] Flashing firmware: sniffle
           [*] Opening port /dev/tty.usbmodem2123401 at baud: 500000
           [*] Connecting to target..
[10:34:45] [X] Please reset your board manually, disconnect and reconnect or press the RESET_CC1 and RESET1 buttons.
           Error: Timeout waiting for ACK/NACK after 'Synch (0x55 0x55)'
[10:34:45] [X] Error flashing: sniffle
```

## Sniffing

Podemos realizzar el sniffing utilizando el nombre del firmware, en caso de que no se detecte el firmware, este comenzara a flashearlo antes de inicializar el sniffer.

### Zigbee

```bash
python3 catsniffer.py sniff zigbee -c 25 -p /dev/tty.usbmodem2123401
[10:59:51] [*] Looking for local releases
           [*] Local release folder found!
           [*] Local metadata loaded
           [*] Current Release board-v3.x-v1.2.2 - 2025-06-09T22:07:38Z
[10:59:52] [*] Firmware found!
           [*] Sniffing Zigbee at channel: 25
[10:59:52] [*] Pipeline created: /tmp/fcatsniffer
```

### Thread

```bash
python3 catsniffer.py sniff thread -c 25 -p /dev/tty.usbmodem2123401
[10:59:51] [*] Looking for local releases
           [*] Local release folder found!
           [*] Local metadata loaded
           [*] Current Release board-v3.x-v1.2.2 - 2025-06-09T22:07:38Z
[10:59:52] [*] Firmware found!
           [*] Sniffing Thread at channel: 25
[10:59:52] [*] Pipeline created: /tmp/fcatsniffer
```


### Warnings  and Firmware update

Si existe una instancia de un pipeline en donde no se cerrara correctamente, nos mandara un mensaje de `Pipeline already exists`

```shell
 python3 catsniffer.py sniff thread -c 25 -p /dev/tty.usbmodem2123401
[11:02:26] [*] Looking for local releases
           [*] Local release folder found!
           [*] Local metadata loaded
           [*] Current Release board-v3.x-v1.2.2 - 2025-06-09T22:07:38Z
[11:02:28] [-] Firmware not found! - Flashing Sniffer TI
[11:02:29] [*] Opening port /dev/tty.usbmodem2123401 at baud: 500000
           [*] Connecting to target...
           [-] Unrecognized chip ID. Trying CC13xx/CC26xx
           [*] Chip details:
                   Package: CC1350 PG2.0 - 704 KB Flash - 20KB SRAM - CCFG.BL_CONFIG at 0x000AFFD8
                   Primary IEEE Address: 00:12:4B:00:2A:79:BF:AC
           [*] Performing mass erase
           [*] Erase done
[11:02:32] [*] Write done
           [*] Verifying by comparing CRC32 calculations.
           [*] Verified match: 0x52c24bf8
[11:02:32] [*] Sniffing Thread at channel: 25
[11:02:32] [-] Pipeline already exists.
```

# Futuras mejoras
[] Descargar el firmware con correccion de errores y reintentos
> Actualmente si falla una descarga no se recupera el firmware
[] Poder inicializar sniffle desde la terminal
[] Compatibilidad de los recursos para utilizarse por medio de Jupyter

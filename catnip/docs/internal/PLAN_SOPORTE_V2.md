# Soporte dual CatSniffer v2 / v3 en catnip — Análisis, Plan y Progress Log

> **Documento autónomo.** Una sesión futura puede retomar el trabajo leyendo solo este archivo.
> Todas las afirmaciones están respaldadas por `archivo:línea` verificadas leyendo el código real
> de `CatSniffer-Tools/catnip` y `CatSniffer-Firmware` (ambos repos en `~/Documentos/CatSniffer/`).
>
> - Creado: 2026-09-10
> - Rama de trabajo en el momento de creación: `fix/CLI_Control`
> - Última actualización del progress log: 2026-09-10 (Bloques A, B y C-sin-hardware
>   cerrados; T-08 y T-12 cerradas — 13 DONE, 0 WIP, 4 TODO)

---

## 0. Corrección de premisa (leer antes que nada)

La premisa de partida era *"el CLI actual fue diseñado solo para V3.0"*. **Eso ya no es exacto.**
Una parte sustancial de la abstracción de placa ya está implementada y probada:

| Ya existe | Dónde |
|---|---|
| Modelo de generación de placa (`BoardInfo`, `BOARD_V2`, `BOARD_V3`) | `modules/firmware/board.py:31-66` |
| Detección de placa por `fw_version` | `modules/firmware/board.py:73-123` |
| Gate anti-brickeo (imagen P7 en placa P1 y viceversa) | `modules/firmware/board.py:126-183` |
| Catálogo de imágenes por generación | `modules/firmware/fw_aliases.py:57-126` |
| Update/UF2/volumen de bootloader por generación | `modules/firmware/fw_update.py:246-303, 681-712` |
| Selección de imagen consciente de placa al flashear | `modules/firmware/flasher.py:768-1000` |
| `catnip devices` y `catnip status` muestran la placa | `modules/device/cli.py:61-64, 159-166` |
| Suite de tests de soporte dual | `tests/test_board_support.py` (todo el archivo) |
| Release CI por familia de tag (`v2.X.Y.Z` / `v3.X.Y.Z`) | `CatSniffer-Firmware/.github/workflows/firmware-release.yml:42-69` |

**Lo que falta no es construir la abstracción, sino cerrarla.** El trabajo real es:
(a) tres subsistemas que siguen asumiendo RP2040, (b) consolidar los condicionales
`if board.generation == "v3"` dispersos en atributos de `BoardInfo`, y (c) un riesgo de
seguridad concreto en el fallback de detección (ver **T-01**, es lo más urgente del plan).

`modules/core/cli.py` — el archivo abierto en el editor — es **neutral respecto a la placa**
y no necesita cambios: solo ensambla el árbol de comandos (`build_cli()`, `cli.py:162-184`)
y traduce excepciones a exit codes (`main_cli()`, `cli.py:187-239`). La lógica de placa vive
en los módulos de feature.

---

# FASE 1 — Análisis comparativo v2 vs v3

## 1.1 Especificaciones del microcontrolador anfitrión

| | **CatSniffer v1.x / v2.x** | **CatSniffer v3.x** |
|---|---|---|
| MCU anfitrión | ATSAMD21E17A (Cortex-M0+, 48 MHz, núcleo único) | RP2040 (Cortex-M0+ dual, hasta 133 MHz) |
| SRAM | 16 KB — confirmado en `SAMD21/catsniffer/src/main.c:71` | 264 KB |
| Flash | 128 KB internos (`samx2xx17.dtsi`, `catsniffer_v2.dts:24`) | QSPI externa (2 MB en el módulo Pico) |
| Radio TI | CC1352P1 — 352 KB (`board.py:27`) | CC1352P7 — 704 KB (`board.py:28`) |
| Radio LoRa | SX1262 (SERCOM3, `catsniffer_v2.dts:16-19`) | SX1262 (SPI, `boards/rpi_pico.overlay`) |
| Bootloader | uf2-samdx1, volumen `SNIFFER` | Boot ROM RP2040, volumen `RPI-RP2` |
| Almacenamiento no volátil para metadata | **No hay** — `prj.conf` sin `CONFIG_NVS` | NVS + Settings (`RP2040/catsniffer/prj.conf:19-23`) |
| Tag de release | `v2.X.Y.Z` | `v3.X.Y.Z` |
| Board Zephyr | `catsniffer_v2` (board propio del repo) | `rpi_pico` + overlay |

Ambas versiones compilan **el mismo firmware Zephyr** desde árboles paralelos
(`SAMD21/catsniffer/` y `RP2040/catsniffer/`), con `main.c` y `shell_commands.c`
casi idénticos: el diff completo es de 421 y 149 líneas respectivamente, y **ninguna
de esas diferencias añade o quita un comando**.

### Consecuencias de las 16 KB de SRAM

Todas las diferencias de firmware relevantes para el host descienden de este único hecho:

| Recurso | v2 (SAMD21) | v3 (RP2040) | Referencia |
|---|---|---|---|
| Ring buffer del puente CC1352 | 256 B/dirección (128 en `debug.conf`) | 16384 B | `SAMD21/include/catsniffer.h:26` vs `RP2040/include/catsniffer.h:25` |
| Ring buffer LoRa | 264 B (un paquete de 255 + cabecera) | 16384 B | ídem |
| Ring buffer del shell | 128 B | 16384 B | ídem |
| Stack del hilo LoRa | 1024 B | 4096 B | `main.c:72` en cada árbol |
| Stack de ISR / main / workqueue | 768 / 1536 / 1024 B (fijados a mano) | por defecto de Zephyr | `SAMD21/prj.conf:39-43` |
| RX del UART CC1352 | **DMA asíncrono continuo** (SERCOM no tiene FIFO de RX; a 921600 baudios llega un byte cada 11 µs y un M0+ a 48 MHz no sostiene una ISR por byte) | Interrupción + FIFO, con `uart_err_check()` para detectar overrun | `SAMD21/src/main.c:202-260` vs `RP2040/src/main.c` (handler IRQ) |
| Parseo del shell | Diferido al hilo principal (`shell_poll()`, `main.c:341-359`); la ISR solo encola | Se parsea dentro de la propia ISR de CDC2 | diff `main.c` |
| Escritura de respuestas del shell | Troceada, con espera activa acotada a 500 ms a que el host drene el ring de 128 B (`main.c:480-515`) | Escritura directa | ídem |

## 1.2 Diferencias en protocolos de comunicación

**No hay diferencias de protocolo.** Ambas placas exponen:

- El mismo VID/PID USB: `0x1209:0xBABB` (`usb_connection.py:46-47`, `prj.conf` de ambos árboles).
- Los mismos tres puertos CDC-ACM en el mismo orden: **CDC0** puente CC1352,
  **CDC1** LoRa/SX1262, **CDC2** shell de configuración.
- Los mismos baudios hacia el CC1352: 921600 en passthrough, 500000 en modo boot
  (`main.c:466-474` en ambos árboles).
- Terminación de línea `\r\n` y comandos terminados en `\n`/`\r`.

Lo que sí cambia es el **perfil temporal**: con 256 B de ring de puente contra 16384 B,
una v2 aplica contrapresión al CC1352 mucho antes, y las respuestas del shell llegan en
más ráfagas y más pequeñas. El bucle de lectura por ventana de silencio ya existente
(`_SILENCE_S = 0.15 s`, `usb_connection.py:584, 635-647`) es precisamente el mecanismo
correcto para eso, pero nunca se ha medido contra una v2 real.

## 1.3 Diferencias en comandos disponibles

**Ninguna.** Ambos firmwares registran exactamente los mismos **39 comandos**, en el mismo
orden, en la misma tabla (`shell_commands.c:130-173` en ambos árboles):

```
help boot exit band1 band2 band3 reboot status loss_reset fw_version
lora_freq lora_sf lora_bw lora_cr lora_power lora_mode lora_preamble lora_syncword
lora_iq lora_config lora_apply cc1352_fw_id
fsk_freq fsk_bitrate fsk_fdev fsk_bw fsk_power fsk_preamble fsk_syncword fsk_crc
fsk_whitening fsk_pktlen fsk_payload fsk_bt fsk_config fsk_apply
modulation radio identify
```

Esto incluye **toda la API de LoRa y FSK**: la v2 tiene el mismo SX1262 y el mismo juego
de comandos de modulación que la v3. Cualquier suposición de que LoRa/FSK es exclusivo de
la v3 es falsa.

## 1.4 Diferencias en formatos de respuesta

Cuatro respuestas difieren. Son las únicas cuatro que el host debe tratar con cuidado:

| Comando | v2 (SAMD21) | v3 (RP2040) | Impacto |
|---|---|---|---|
| `fw_version` | línea `Board: v2 SAMD21 CC1352P1` | línea `Board: v3 RP2040 CC1352P7` | **Es el mecanismo de detección**. `shell_commands.c:286` en cada árbol |
| `status` | Incluye buffer de trazas, `dma_regress=%u` en la línea de pérdidas, `Stack unused: main=/lora=/isr=`, log de fallos y un volcado por hilo | Solo `uart_overrun` y `ring_dropped` | Un parser que asuma un conjunto fijo de líneas se rompe |
| `cc1352_fw_id set/get/clear` | `ERR not supported on this board` (no hay NVS) | `OK ...`, o `ERR storage unavailable` si el NVS falla | La v2 **nunca** persiste el ID de firmware del CC1352 |
| `reboot` | `Entering UF2 bootloader...` → magic `0xf01669ef` en el tope de SRAM + reset frío → volumen `SNIFFER` | `Entering USB bootloader...` → `reset_usb_boot()` → volumen `RPI-RP2` | Volumen de destino distinto tras el reboot |

## 1.5 Limitaciones y características únicas de cada versión

**Solo en v2:**
- Diagnóstico extendido en `status` (trazas, headroom de stacks, log de fallos, hilos) —
  existe *porque* la placa va justa de RAM.
- Contador `dma_regress` (regresiones de progreso de DMA reportadas por el driver).

**Limitaciones de v2:**
- Sin almacenamiento de metadata del firmware del CC1352 (`cc1352_fw_id`).
- El CC1352P1 tiene 352 KB de flash frente a 704 KB: **varias imágenes no existen para v2**.
  El catálogo por placa (`fw_aliases.py:60-66`) solo tiene `sniffle` (imagen
  `sniffle_cc1352p1_cc2652p1_1M`, mirroreada desde el release de nccgroup,
  `flasher.py:44-48`) y `catnip_v2`. **No hay** `ti_sniffer` (Zigbee/Thread/802.15.4),
  ni `airtag_scanner`, ni `airtag_spoofer`, ni `justworks_scanner` para v2.
- El release de firmware v2 **no publica ningún .hex de CC1352**: `tools/get_hex_files.py:45`
  solo emite la clave `board_v3`, y el workflow salta la recolección de hex para la familia 2
  (`firmware-release.yml:111-112`).
- No puede hacerse de programador JTAG de sí misma (ver 1.6, `restore`).

**Limitaciones de v3:** ninguna respecto a v2, salvo que carece del diagnóstico extendido.

## 1.6 Impacto directo de cada diferencia sobre el CLI

| # | Diferencia | Impacto en el CLI | Estado actual |
|---|---|---|---|
| D1 | Línea `Board:` en `fw_version` | Único mecanismo de detección de generación | ✅ Implementado (`board.py:73-86`) |
| D2 | Variante de CC1352 y tamaño de flash | Flashear la imagen equivocada deshabilita el bootloader serie y exige un programador cJTAG para recuperar | ✅ Gate implementado (`board.py:140-175`, aplicado en `flasher.py:891-1000`) |
| D3 | Volumen de bootloader (`SNIFFER` / `RPI-RP2`) | El update por UF2 debe buscar el volumen correcto | ✅ `fw_update.py:246-265` |
| D4 | Familia de tag de release | Cada placa tiene su propia línea de releases | ✅ `flasher.py:768-800` |
| D5 | Catálogo de imágenes reducido en v2 | `sniff zigbee`, `sniff airtag` y `cativity` no tienen imagen para v2 (`meshtastic` **sí** funciona: es LoRa puro, no usa el CC1352) | ✅ **Resuelto (T-06/T-07)**: `require_firmware_for_board()` rechaza antes de abrir puertos y `flash --list` ya no ofrece lo que no se puede flashear |
| D6 | Sin NVS en v2 | `cc1352_fw_id` siempre falla | ✅ Degradación silenciosa (`fw_metadata.py:121-124`) |
| D7 | `status` con líneas extra en v2 | El parser del host no debe asumir un conjunto fijo | ✅ **Resuelto (T-08)**: `fw_status.parse_status_response()` es línea a línea y sin orden fijo; `catnip status` muestra el bloque extendido y `--diagnostics` vuelca hilos y traza |
| D8 | `restore` usa el RP2040 como sonda CMSIS-DAP | Una v2 no tiene RP2040: el flujo entero es inaplicable | ✅ **Resuelto (T-05)**: detecta la placa al entrar y rechaza en v2 con `UnsupportedOnBoardError` antes de tocar OpenOCD |
| D9 | Rings 64× más pequeños en v2 | Throughput y ráfagas del shell distintos | ❌ Nunca medido contra hardware v2 (ver T-09) |
| D10 | Firmware antiguo sin línea `Board:` ⇒ se asume v3 | Si alguna vez una v2 respondiera sin la línea, el gate D2 la trataría como v3 | ✅ **Resuelto (T-01)**: sin línea `Board:` y sin tag `v3.` ⇒ placa desconocida ⇒ se rechaza |

---

# FASE 2 — Plan de implementación

## 2.1 Cambios necesarios en el CLI, por módulo

### Bloqueante de seguridad

**`modules/firmware/board.py:73-86` — el fallback a v3 es el único punto donde una
detección fallida puede llevar a brickear una placa.** `parse_board_line()` devuelve
`BOARD_V3` cuando no encuentra la línea `Board:`, y `image_allowed_for_board()`
(`board.py:151-153`) permite en v3 cualquier imagen cuyo nombre no declare variante.
Encadenados, un firmware v2 que respondiera sin la línea `Board:` aceptaría una imagen P7.

El invariante que hace esto seguro hoy está escrito solo en un comentario
(`board.py:18-21`: *"el firmware SAMD21 tiene la línea desde su primer release"*).
Debe convertirse en (a) un test que lo verifique contra el árbol de firmware, y
(b) una segunda fuente de verdad independiente del texto del shell.

### Consolidación de la abstracción

Hay al menos seis condicionales `board.generation == "v3"` dispersos —
`fw_update.py:641, 687, 743, 798` y `flasher.py:850-855` — cada uno codificando una
regla distinta. Todas esas reglas son propiedades de la placa y pertenecen a `BoardInfo`:

```python
@dataclass(frozen=True)
class BoardInfo:
    # ... campos actuales ...
    has_fw_id_storage: bool      # v2: False  (sin NVS)
    can_self_program_cc1352: bool # v2: False (sin RP2040 como sonda CMSIS-DAP)
    ships_cc1352_hex_assets: bool # v2: False (get_hex_files.py solo emite board_v3)
    bridge_ring_bytes: int        # v2: 256, v3: 16384
```

Regla: **ningún módulo fuera de `board.py` debe volver a comparar `generation` con un
literal.** Un test estático (mismo patrón AST que `tests/test_cli_main.py:299-330`) puede
imponerlo.

### Subsistemas con hueco real

| Módulo | Situación | Qué hacer |
|---|---|---|
| `modules/firmware/restore.py` | RP2040-only de principio a fin: carga `free_dap` sobre el RP2040 (`restore.py:8-15, 379-395`), URL fijada al release `v3.1.0.0` (`restore.py:55-58`), `DEFAULT_CC1352_FW` es el hex v3 (`restore.py:68`). `TAPID_CC1352P1` ya está definido (`restore.py:62`) pero el flujo es inalcanzable en v2 | Detectar la placa al entrar y **rechazar con mensaje accionable** en v2. Opcionalmente, modo sonda externa (`--probe`) |
| `modules/sniff/cli.py` | Cero referencias a placa. Delega en `Flasher`, que sí es consciente, pero el fallo ocurre al intentar flashear | Verificación temprana: resolver el firmware requerido contra `official_ids_for_board()` antes de tocar el hardware |
| `modules/protocols/cli/cativity.py`, `vhci.py` | Igual que `sniff`: dependen de `ti_sniffer`/`sniffle`, sin comprobación previa | Misma verificación temprana, vía un helper compartido. **`meshtastic.py` queda fuera**: solo usa el puerto LoRa (SX1262) y el shell, nunca el CC1352, así que funciona igual en v2 |
| `modules/device/cli.py:142-182` (`status`) | Muestra la placa, pero no las capacidades derivadas ni el diagnóstico extra de v2 | Añadir filas por capacidad y, en v2, las líneas de `status` del firmware |
| `modules/firmware/cli.py` (`flash --list`) | Lista el catálogo completo | Filtrar por la placa conectada, o marcar las no disponibles |

### Deuda menor detectada de paso

- `board.py:140, 166`: anotación `-> (bool, str)` inválida (debe ser `Tuple[bool, str]`).
  Ya estaba registrada en `MERGE_PLAN.md`.
- `fw_metadata.py:121` reconoce `"not supported"` pero no `"storage unavailable"`
  (la variante v3 con NVS caído). Ambas deberían tratarse igual.
- `detect_board()` abre el puerto shell con 2 s de timeout **por dispositivo** en
  `catnip devices` (`device/cli.py:61`). Con varias placas conectadas es notablemente lento;
  ya está anotado en `MERGE_PLAN.md:360-369` sin resolver.

## 2.2 Estrategia de detección de versión

Cadena de tres niveles, de más fiable a menos, y **sin adivinar en el último escalón**:

1. **Placa viva, shell accesible** → `fw_version` y su línea `Board:`
   (`board.py:73-123`). Es lo que ya se hace.
2. **Placa en modo bootloader** → nombre del volumen montado: `SNIFFER` ⇒ v2,
   `RPI-RP2` ⇒ v3 (`fw_update.py:246-276`, ya implementado en `find_any_board_mount_point`).
3. **CC1352 en modo bootloader serie** → tamaño de flash reportado por el chip
   (`board_for_chip_size()`, `board.py:178-183`; ya usado en `flasher.py:983`).

**Cambio propuesto sobre el estado actual:** el fallback silencioso a v3 de
`parse_board_line()` debe distinguir *"no hubo respuesta"* de *"hubo respuesta sin
línea Board"*. El primero ya devuelve `None` en `detect_board()`; el segundo devuelve
`BOARD_V3` y es el caso peligroso. Propuesta:

- `parse_board_line()` mantiene el default v3 **solo** para respuestas que contengan
  `FW:` con un tag `v3.` explícito.
- Cualquier otra respuesta sin línea `Board:` ⇒ `None` (desconocida) ⇒ ninguna operación
  destructiva permitida, y mensaje pidiendo actualizar el firmware.
- Añadir `--board {v2,v3}` como override manual explícito para recuperación.

## 2.3 Implementación de la abstracción (sin duplicar código)

El principio ya establecido en el repo se mantiene: **una tabla de datos, no ramas de código.**

1. `BoardInfo` crece con los campos de capacidad de 2.1. Ninguna lógica nueva.
2. Un helper único de precondición, en `modules/firmware/board.py`:
   ```python
   def require_capability(board, capability, feature_name) -> None:
       """Lanza UnsupportedOnBoardError si la placa no soporta la feature."""
   ```
   Lo consumen `sniff`, `cativity`, `meshtastic`, `vhci` y `restore` — un import, una llamada.
3. Nueva excepción tipada `UnsupportedOnBoardError(CatnipError)` en
   `modules/core/exceptions.py`, con `hint` (qué placa hace falta, o qué alternativa existe),
   siguiendo el contrato de exit codes ya vigente (`core/cli.py:213-227`).
4. El catálogo por placa (`fw_aliases.OFFICIAL_ID_TO_FILENAME_BY_BOARD`) sigue siendo la
   única fuente de verdad de qué imagen existe para qué generación. No se duplica.

## 2.4 Cambios en la API del CLI

| Cambio | Tipo | Justificación |
|---|---|---|
| `--board {v2,v3}` en `flash`, `update`, `restore` | Aditivo, opcional | Override manual cuando la detección falla; imprescindible para recuperación |
| Nueva fila *Capabilities* y bloque de diagnóstico en `catnip status` | Aditivo | Hacer visible por qué una feature no está disponible |
| `catnip flash --list` filtrado por placa conectada (con `--all` para el catálogo completo) | **Cambio de comportamiento** | Hoy ofrece imágenes que no se pueden flashear en la placa presente |
| Nuevo exit code para `UnsupportedOnBoardError` | Aditivo | Scripts pueden distinguir "no soportado en esta placa" de "falló" |

Sin cambios incompatibles: ningún comando existente cambia de nombre ni de firma
posicional. `flash --list` es el único cambio de comportamiento y es intencional.

## 2.5 Scope de pruebas

**Unitarias (sin hardware) — ampliar `tests/test_board_support.py`:**
- Fixtures de `fw_version` para ambas placas (ya existen: `test_board_support.py:37-44`).
- Nuevo: respuesta sin línea `Board:` y sin tag `v3.` ⇒ debe dar `None`, no `BOARD_V3`.
- Nuevo: `require_capability` lanza `UnsupportedOnBoardError` en cada combinación
  (placa × capacidad) y no lanza en las soportadas.
- Nuevo: parser de `status` tolera el formato v2 (líneas extra) y el v3 (líneas mínimas).
- Nuevo: test estático AST que prohíba `generation == "v3"` fuera de `board.py`.
- Actualizar `tests/test_cli_structure.py` si se añaden flags (ese test fija el árbol literal).

**Con hardware — matriz mínima, cada celda ejecutada en v2 y en v3:**

Leyenda: ✔ pendiente, ✅ ejecutado contra hardware real (fecha en T-14).

| Escenario | v2 | v3 |
|---|---|---|
| `devices`, `status`, `identify` | ✅ `devices` OK (2026-09-10) | ✔ esperado OK |
| `flash sniffle` (imagen correcta) | ✔ P1 | ✔ P7 |
| `flash` con imagen de la otra variante | ✔ debe **rechazar** | ✔ debe **rechazar** |
| `update` (UF2 + volumen correcto) | ✔ `SNIFFER` | ✔ `RPI-RP2` |
| `sniff ble` | ✔ | ✔ |
| `sniff zigbee` / `cativity` | ✅ rechazan con exit 5 antes de abrir puertos | ✔ OK |
| `lora` / `meshtastic` (SX1262) | ✔ | ✔ |
| `restore` | ✅ rechaza con exit 5 antes de buscar OpenOCD | ✔ OK |
| Throughput sostenido del puente a 921600 | ✔ **medir**, rings de 256 B | ✔ referencia |

## 2.6 Documentación a actualizar

- `README.md` de catnip: matriz de compatibilidad comando × generación de placa.
- Documentación por comando: nota de disponibilidad en `sniff`, `cativity`, `meshtastic`,
  `restore`, `flash`.
- Esquema de versionado (hardware `vX.Y`, firmware `vA.X.Y.Z`) y su relación con las
  familias de tags de release — hoy solo está en el comentario de cabecera de
  `firmware-release.yml:3-6`.
- Este documento: mantener el progress log al día (es la sección 3).
- `MERGE_PLAN.md`: cerrar los ítems que este plan resuelve (type hints de `board.py`,
  coste de `detect_board` en `devices`).

---

# FASE 3 — Progress Log

## Cómo usar y actualizar este log

- **Estados:** `TODO` → `WIP` → `DONE` (o `BLOCKED` / `WONTFIX` con motivo en Notas).
- Al cerrar una tarea: cambiar el estado, poner la fecha y el commit/PR en **Notas**,
  y actualizar la línea *"Última actualización"* de la cabecera del documento.
- **No borrar filas.** Una tarea descartada se marca `WONTFIX` con su razón.
- Las tareas están ordenadas por dependencia: una tarea solo puede empezar cuando las
  listadas en **Depende de** están en `DONE`.

## Bloque A — Seguridad y cimientos (sin esto, nada más debe tocarse)

| ID | Tarea | Depende de | Complejidad | Estado | Notas |
|---|---|---|---|---|---|
| T-01 | Endurecer `parse_board_line()`: sin línea `Board:` y sin tag `v3.` ⇒ `None` (desconocida), nunca `BOARD_V3`. Ninguna operación destructiva con placa desconocida | — | Media | **DONE** | 2026-09-10, sin commit aún. `board.py:parse_board_line` devuelve `Optional[BoardInfo]`. Callers migrados: `fw_update.board_from_fw_info` + `_print_unknown_board` (update y `--force` rechazan y no reinician), `flasher.find_flash_firmware` rechaza antes de tocar el chip. Tests: `TestParseBoardLine`, `TestUnknownBoardIsRefused` |
| T-02 | Test que verifique el invariante "el firmware v2 siempre emite la línea `Board:`" contra el árbol de `CatSniffer-Firmware` | T-01 | Baja | **DONE** | 2026-09-10. `test_firmware_always_emits_the_board_line[v2/v3]`: extrae el cuerpo de `cmd_fw_version()` de ambos árboles, exige `Board: %s` no condicional y comprueba que el literal (`v2 SAMD21 CC1352P1`) lo lee `parse_board_line`. Ruta por `CATSNIFFER_FIRMWARE_DIR`, skip si el repo no está |
| T-03 | Añadir campos de capacidad a `BoardInfo` (`has_fw_id_storage`, `can_self_program_cc1352`, `ships_cc1352_hex_assets`, `bridge_ring_bytes`) y migrar los 6 condicionales `generation == "v3"` | T-01 | Media | **DONE** | 2026-09-10. Campos añadidos + `accepts_unnamed_images` (el que faltaba: gobierna `image_allowed_for_board` y el fallback de UF2 sin nombre). Los 6 condicionales sustituidos por dos helpers de datos: `fw_update.resolve_board_uf2()` y `fw_update.expected_tag_for_board()` (usa `tag_prefix`). Cero literales `generation ==` fuera de `board.py`, verificado por T-13 |

## Bloque B — Contrato de "no soportado en esta placa"

| ID | Tarea | Depende de | Complejidad | Estado | Notas |
|---|---|---|---|---|---|
| T-04 | Crear `UnsupportedOnBoardError` (`core/exceptions.py`) + helper `require_capability()` en `board.py`, con exit code propio | T-03 | Baja | **DONE** | 2026-09-10. `UnsupportedOnBoardError` con `EXIT_UNSUPPORTED = 5`. En `board.py`: `require_capability()` (estricto: placa desconocida también lanza) y `require_firmware_for_board()` (informativo: placa desconocida **no** bloquea, porque el gate destructivo ya vive en `flasher`). Cada capacidad tiene su razón escrita en `_CAPABILITY_REASON`, así que el mensaje dice *por qué*, no solo "no soportado". Tests: `TestRequireCapability`, `TestRequireFirmwareForBoard` + caso en `test_cli_main.py` |
| T-05 | `restore`: detectar placa al entrar y rechazar en v2 con mensaje accionable | T-04 | Baja | **DONE** | 2026-09-10. `restore_cc1352(board=...)` detecta al entrar y llama a `require_capability(..., "can_self_program_cc1352")` **antes** de buscar OpenOCD. Decisión de diseño: una placa desconocida **no** se rechaza — la placa con el shell muerto es justamente la que se está recuperando, y en una v2 el flujo se detiene solo (no hay volumen `RPI-RP2` donde cargar free_dap). Tests: `TestRestoreRefusesOnV2` |
| T-06 | Verificación temprana de firmware disponible en `sniff` y en `protocols/cli/*` antes de tocar hardware | T-04 | Media | **DONE** | 2026-09-10. El chequeo vive en `device_session()` (cubre los 4 `sniff` de una vez) más una línea en `cativity` y otra en `vhci`. `device_session` gana el parámetro `feature=` para que el mensaje nombre el comando real. `meshtastic` **no** lo necesita: es LoRa puro. **Corrección hecha con la v2 delante**: el gate va justo antes del **flasheo**, no antes de la verificación — la v2 de pruebas está corriendo `ti_sniffer` (imagen P1 flasheada a mano) y la versión estricta le rompía `sniff zigbee` y `cativity`, que funcionan perfectamente. Lo que no existe es la *imagen* para flashear, no la capacidad de correrla. Tests: `TestEarlyFirmwareCheck` |
| T-07 | `flash --list` filtrado por la placa conectada, con `--all` para el catálogo completo | T-04 | Media | **DONE** | 2026-09-10. `_board_for_list()` (respeta `--board` y `--device`), filtro por `board.file_available_for_board()` — que juzga los `.uf2` por `uf2_pattern` y los `.hex` por variante, porque el UF2 de v2 no nombra ninguna variante y el filtro de imágenes lo habría ocultado. Dice cuántas ocultó y por qué. `tests/test_cli_structure.py` actualizado (`--all` en `flash`, `--board` en `restore`) |

## Bloque C — Visibilidad y diagnóstico

| ID | Tarea | Depende de | Complejidad | Estado | Notas |
|---|---|---|---|---|---|
| T-08 | `catnip status`: fila de capacidades por placa y, en v2, volcado del diagnóstico extendido del firmware | T-03 | Media | **DONE** | 2026-09-10. Nuevo módulo `modules/firmware/fw_status.py` (`ShellStatus`, `parse_status_response`, `read_status`): línea a línea, sin orden fijo, toda sección opcional y lo desconocido se guarda en `unparsed` en vez de descartarse. `catnip status` gana la fila *Board can* (de `board.capability_rows()`), una tabla *Firmware diagnostics* y el flag `--diagnostics/-D` para hilos y traza. Avisa cuando el stack más justo baja de 96 B — **en la v2 real el hilo LoRa tiene 56 B libres de 1024**. Cerrado también el pendiente de T-11: `FirmwareMetadata.keeps_firmware_id()` corta el bucle de 5 reintentos de `flasher.py` cuando la placa dice que no tiene dónde guardar |
| T-09 | Medir throughput sostenido del puente en v2 (rings de 256 B) a 921600 y ajustar los timeouts del host si hace falta | T-01 | Alta | TODO | Requiere hardware v2. Referencias: `_SILENCE_S` (`usb_connection.py:584`), `shell_reply` troceado (`SAMD21/src/main.c:480-515`) |
| T-10 | Flag `--board {v2,v3}` como override manual en `flash`, `update`, `restore` | T-01 | Baja | **DONE** | 2026-09-10. `flash` y `update` ya lo tenían; `restore` lo gana con T-05 (el override evita la detección por completo, verificado en `test_board_override_is_honoured`). Nota de diseño: el tamaño de flash que reporta el propio chip sigue mandando sobre el override (es medido, no declarado) |
| T-11 | `fw_metadata`: tratar `"storage unavailable"` igual que `"not supported"` | — | Muy baja | **DONE** | 2026-09-10. `fw_metadata._storage_missing()`. Pendiente menor detectado de paso: el bucle de 5 reintentos de `flasher.py` no consulta este resultado, así que un v3 con NVS caído aún reintenta 5 veces (candidato a T-08) |

## Bloque D — Pruebas, limpieza y documentación

| ID | Tarea | Depende de | Complejidad | Estado | Notas |
|---|---|---|---|---|---|
| T-12 | Ampliar `tests/test_board_support.py` según 2.5 (detección endurecida, capacidades, parser de `status`) | T-04, T-08 | Media | **DONE** | 2026-09-10. 159 tests en el archivo. Todo lo de 2.5 cubierto: detección endurecida, capacidades y sus helpers, rechazo de `restore`, gate previo al flasheo, filtrado de `flash --list`, parser de `status` en ambos formatos y `catnip status` completo. Los fixtures `V2_STATUS`/`V3_STATUS` son **captura literal de la placa v2 real**, no inventados |
| T-13 | Test estático AST que prohíba comparar `generation` con literales fuera de `board.py` | T-03 | Media | **DONE** | 2026-09-10. `test_no_generation_literal_outside_board_module`, parametrizado sobre todos los `.py` de `modules/`. Detecta `Compare` con un `Attribute.generation` y una constante str en cualquier lado |
| T-14 | Ejecutar la matriz de pruebas con hardware de 2.5 en ambas placas | T-05, T-06, T-07, T-10 | Alta | TODO | Requiere una v2 y una v3 físicas. Es el gate de "listo para release". **Parcial (2026-09-10, v2 real, `/dev/ttyACM1-3`)**: `devices` la identifica como v2; `restore`, `sniff zigbee` y `cativity` rechazan con exit code 5 sin tocar el hardware; `flash --list` filtra 7 imágenes v3 y nombra el catálogo v2. **No ejecutado**: nada que escriba en la placa (`flash sniffle`, `update`, `sniff ble`, `lora`) ni ninguna celda de v3 |
| T-15 | Arreglar anotaciones `-> (bool, str)` en `board.py:140,166` | — | Muy baja | **DONE** | 2026-09-10. Ahora `Tuple[bool, str]` |
| T-16 | Reducir el coste de `detect_board()` en `catnip devices` (2 s por dispositivo) | T-01 | Media | TODO | Anotado sin resolver en `MERGE_PLAN.md:360-369`. Opciones: caché por sesión, paralelizar, o solo bajo `--debug`. **Creció con T-08**: `catnip status` abre ahora el puerto shell dos veces (`detect_board` + `read_status`); una sola sesión de shell que sirva ambas consultas resuelve las dos cosas a la vez |
| T-17 | Documentación: matriz de compatibilidad en README, notas por comando, esquema de versionado | T-14 | Media | TODO | Ver 2.6 |

## Resumen de estado

| Bloque | Total | TODO | WIP | DONE |
|---|---|---|---|---|
| A — Seguridad y cimientos | 3 | 0 | 0 | 3 |
| B — Contrato de no-soportado | 4 | 0 | 0 | 4 |
| C — Visibilidad y diagnóstico | 4 | 1 | 0 | 3 |
| D — Pruebas y documentación | 6 | 3 | 0 | 3 |
| **Total** | **17** | **4** | **0** | **13** |

Suite completa tras T-08: **749 tests en verde** (`pytest`, 159 de ellos en
`tests/test_board_support.py`). Lo que queda **no se puede cerrar escribiendo código**:
T-09 y T-14 necesitan medir y ejecutar contra hardware (T-09 además querría una v3
como referencia), T-17 depende de T-14, y T-16 es optimización.

Siguiente paso natural: **T-16** (única tarea de código pura que queda) o entrar ya en
**T-14** con la v2 conectada — pero las celdas que faltan de T-14 *escriben en la placa*
(`flash`, `update`, `sniff ble`), así que necesitan permiso explícito antes.

**Hallazgo de campo (2026-09-10, v2 real, FW v2.1.0.0):** el hilo LoRa corre con
**56 bytes libres** de un stack de 1024, y el hilo de prioridad -11 con otros 56. Es
el margen más estrecho de la placa y ahora `catnip status` lo avisa solo. Si T-09
encuentra pérdidas de throughput, este número es el primer sitio donde mirar.

**Contrato que dejó cerrado el Bloque B** (para no reabrirlo por accidente):

- `require_capability(board, capability, feature)` — estricto. Placa desconocida ⇒ lanza.
  Para lo que *depende* de la generación (`restore`).
- `require_firmware_for_board(board, official_id, feature)` — informativo, y se llama
  **justo antes de flashear**, nunca antes de verificar. Placa desconocida ⇒ deja pasar,
  porque el rechazo destructivo ya está en `flasher.find_flash_firmware`. Guarda el
  flasheo de una imagen inexistente, no el uso de un firmware que ya está corriendo.
- `UnsupportedOnBoardError` sale con **exit code 5**, distinto de `FirmwareError` (3):
  "esta placa no puede" no es "esto falló".

---

## Apéndice — Mapa de archivos clave (para retomar sin contexto)

**En `CatSniffer-Tools/catnip/`:**

| Archivo | Rol en el soporte dual |
|---|---|
| `modules/firmware/board.py` | Fuente de verdad de la generación de placa. Todo cambio estructural empieza aquí |
| `modules/firmware/fw_aliases.py` | Catálogo de imágenes por generación |
| `modules/firmware/fw_status.py` | Parser tolerante del `status` del shell (bloque extendido de v2) |
| `modules/firmware/fw_update.py` | Update por UF2: volumen, tag y asset por placa |
| `modules/firmware/flasher.py` | Flasheo con gate anti-brickeo; releases por familia de tag |
| `modules/firmware/restore.py` | Recuperación por JTAG — **RP2040-only** |
| `modules/device/cli.py` | `devices`, `identify`, `status` — ya conscientes de placa |
| `modules/sniff/cli.py`, `modules/protocols/cli/*` | Conscientes de placa vía `device_session()` y `require_firmware_for_board()` |
| `modules/core/cli.py` | Neutral: ensamblado de comandos y exit codes. No requiere cambios |
| `tests/test_board_support.py` | Suite de soporte dual existente |

**En `CatSniffer-Firmware/`:**

| Ruta | Contenido |
|---|---|
| `SAMD21/catsniffer/src/{main.c,shell_commands.c}` | Firmware v2 |
| `RP2040/catsniffer/src/{main.c,shell_commands.c}` | Firmware v3 |
| `SAMD21/catsniffer/boards/catsniffer_v2/` | Definición de placa Zephyr para v2 |
| `.github/workflows/firmware-release.yml` | Release por familia de tag (`v2.` / `v3.`) |
| `tools/get_hex_files.py` | Recolección de hex del CC1352 — solo emite `board_v3` |

**Comandos útiles para reverificar el estado del firmware:**

```bash
# Confirmar que ambos firmwares siguen exponiendo los mismos comandos
diff <(sed -n '125,185p' SAMD21/catsniffer/src/shell_commands.c | grep -oP '^\s*\{\s*"\K[^"]+') \
     <(sed -n '125,185p' RP2040/catsniffer/src/shell_commands.c | grep -oP '^\s*\{\s*"\K[^"]+')

# Ver las diferencias reales entre ambos firmwares
diff -u SAMD21/catsniffer/src/shell_commands.c RP2040/catsniffer/src/shell_commands.c
diff -u SAMD21/catsniffer/prj.conf RP2040/catsniffer/prj.conf
```

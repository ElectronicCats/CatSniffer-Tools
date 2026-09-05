# MERGE_PLAN.md — Integración de `feat/catsniffer-v2-support` en `fix/CLI_Control`

> **Estado global:** ✅ **EJECUTADO.** Merge integrado y verificado en `fix/CLI_Control`. Sin push.
> **Última actualización:** 2026-09-04 (Sesión 2)

---

## 1. Contexto (para sesiones futuras)

### 1.1 Qué pasó

Dos líneas de trabajo divergieron del commit base **`a06b7887`**:

| Rama | Autor | Contenido |
|---|---|---|
| `fix/CLI_Control` (HEAD, `4b5dedb`) | Yo (Darcko) | Refactor de la CLI: partir el monolito `modules/core/cli.py` en módulos por dominio |
| `feat/catsniffer-v2-support` → merged a `main` (`bc80979`) | Compañero | Soporte de placas CatSniffer v1/v2 (SAMD21 + CC1352P1) |

### 1.2 Corrección importante a la premisa inicial

**La suposición de partida era que `main` estaba sobre la arquitectura ANTIGUA. No es así.**

El compañero hizo un `merge main into feat/catsniffer-v2-support` en el commit
**`c173477`**, que ya trajo a su rama la reestructuración de paquetes
(`modules/core/`, `modules/firmware/`, `modules/protocols/`, `modules/utils/`) y
movió su `modules/board.py` → `modules/firmware/board.py`.

Verificación:

```bash
git ls-tree -r --name-only a06b7887 -- catnip/modules/   # ya tiene core/ firmware/ protocols/
git ls-tree -r --name-only main      -- catnip/modules/   # idem + firmware/board.py
```

Es decir: el commit base `a06b7887` **ya contiene** la nueva estructura de paquetes.
Lo único que mi rama añade encima es un **segundo nivel de refactor**: extraer los
comandos Click de `modules/core/cli.py` (2394 líneas eliminadas) a módulos por
dominio (`sniff/cli.py`, `device/cli.py`, `firmware/cli.py`, `protocols/cli/*.py`,
`utils/completion.py`, `utils/system_cli.py`, `utils/cli_options.py`).

### 1.3 Consecuencia práctica

La superficie de conflicto es **mucho menor** de lo temido. Intersección real de
archivos tocados por ambas ramas:

```bash
comm -12 <(git diff --name-only a06b7887..HEAD | sort) \
         <(git diff --name-only a06b7887..main | sort)
# → catnip/modules/core/cli.py     (y nada más)
```

**Un solo archivo en común**, con **9 líneas** cambiadas por el compañero
(2 hunks). Todo lo demás entra limpio.

### 1.4 Qué NO hay que hacer

- ❌ No revertir el split de la CLI para "encajar" los cambios del compañero.
- ❌ No hacer `git merge main` a ciegas: los 2 hunks de `core/cli.py` apuntan a
  funciones que ya **no viven ahí** (`devices` → `device/cli.py`, `update` →
  `firmware/cli.py`). Git resolvería mal o marcaría conflicto inútil.
- ✅ Sí: traer los 8 archivos no solapados tal cual, y **re-apuntar a mano**
  los 2 hunks de `core/cli.py` a sus nuevas ubicaciones.

---

## 2. Comandos de referencia

```bash
BASE=a06b7887a20693129ffb2ed567ed73284908d0a6

# Log del PR del compañero
git log --oneline --graph $BASE..main

# Diff aislado
git diff $BASE..main -- catnip/

# Commits relevantes
#   bafe99f  feat(catnip): CatSniffer v1/v2 (SAMD21 + CC1352P1) support   ← el grueso
#   c173477  merge main into feat/... ; move board.py to modules/firmware ← merge, sin lógica nueva
#   1ecb7e8  fix(catnip): copy the UF2 to the board's bootloader volume
#   b114942  style: black formatting for board support modules            ← PR #57
#   220460b  ci: pre-commit on detached checkout                          ← PR #59, ajeno al feature
```

> **Nota:** `220460b` (PR #59, CI) es ajeno al feature v2 pero entra en el mismo
> rango. Se trata aparte (§3.9).

---

## 3. Inventario de cambios y mapeo a la nueva arquitectura

Leyenda de estado: ⬜ pendiente · 🟨 en progreso · ✅ completado · ⚠️ requiere decisión

### 3.1 `modules/firmware/board.py` — **ARCHIVO NUEVO** (183 líneas)

| | |
|---|---|
| **Origen** | `main:catnip/modules/firmware/board.py` |
| **Destino** | `modules/firmware/board.py` — **misma ruta, sin cambios** |
| **Conflicto** | Ninguno. Mi rama no tiene ese archivo. |
| **Acción** | `git checkout main -- catnip/modules/firmware/board.py` |
| **Estado** | ✅ completado |

Contenido: `BoardInfo` (dataclass frozen), `BOARD_V2` / `BOARD_V3`, `BOARDS`,
`parse_board_line()`, `detect_board()`, `image_variant()`,
`image_allowed_for_board()`, `image_fits_chip()`, `board_for_chip_size()`.

**Dependencia verificada:** `detect_board()` importa
`from ..core.usb_connection import ShellConnection` → existe en mi rama en
[modules/core/usb_connection.py](catnip/modules/core/usb_connection.py). ✅ Compatible.

---

### 3.2 `modules/firmware/fw_aliases.py`

| | |
|---|---|
| **Destino** | Misma ruta. Mi rama **no** tocó este archivo. |
| **Conflicto** | Ninguno. |
| **Acción** | `git checkout main -- catnip/modules/firmware/fw_aliases.py` |
| **Estado** | ✅ completado |

Cambios: añade `OFFICIAL_ID_TO_FILENAME_BY_BOARD` (catálogo por generación),
alias `catnip_v2`, cambia firma a
`get_filename_pattern(official_id, board_generation="v3")` y añade
`official_ids_for_board()`.

**Compatibilidad hacia atrás verificada:**
- `from typing import ... List` ya está importado en ambas versiones. ✅
- La firma nueva tiene default `"v3"` → llamadas existentes de 1 argumento siguen funcionando. ✅
- [tests/test_fw_modules.py:202-211](catnip/tests/test_fw_modules.py#L202-L211) llama con
  1 argumento y con `None`/`""` → `table.get(None)` devuelve `None`. ✅ Sigue pasando.
- [tests/test_catsniffer.py:724](catnip/tests/test_catsniffer.py#L724) parchea la
  función entera con `return_value` → indiferente a la firma. ✅

---

### 3.3 `modules/firmware/fw_metadata.py`

| | |
|---|---|
| **Destino** | Misma ruta. Mi rama **no** tocó este archivo. |
| **Conflicto** | Ninguno. |
| **Acción** | `git checkout main -- catnip/modules/firmware/fw_metadata.py` |
| **Estado** | ✅ completado |

Cambio: 5 líneas. Detecta respuesta `"not supported"` del shell (las SAMD21 no
tienen NVS para el `cc1352_fw_id`) y devuelve `False` en vez de reintentar.

---

### 3.4 `modules/firmware/fw_update.py`

| | |
|---|---|
| **Destino** | Misma ruta. Mi rama **no** tocó este archivo. |
| **Conflicto** | Ninguno. |
| **Acción** | `git checkout main -- catnip/modules/firmware/fw_update.py` |
| **Estado** | ✅ completado |

Funciones nuevas: `find_board_mount_point()`, `find_any_board_mount_point()`,
`find_board_uf2()`, `confirm_reboot()`.
Firmas cambiadas: `flash_rp2040_uf2(uf2_path, mount_point=None)`,
`check_and_update_rp2040(device, flasher, force=False)`,
`_perform_rp2040_update(device, flasher, board=None, tag=None, force=False)`.

**Dependencia verificada:** `parse_fw_version_response()` (mi rama,
[modules/firmware/fw_update.py:192](catnip/modules/firmware/fw_update.py#L192)) parsea
genéricamente `^(\w+):\s*(.+)$`, así que la línea `Board: v2 SAMD21 CC1352P1`
produce `result["board"]` sin ningún cambio. El test
`test_parse_fw_version_keeps_board` pasa tal cual. ✅

---

### 3.5 `modules/firmware/flasher.py`

| | |
|---|---|
| **Destino** | Misma ruta. Mi rama **no** tocó este archivo. |
| **Conflicto** | Ninguno. |
| **Acción** | `git checkout main -- catnip/modules/firmware/flasher.py` |
| **Estado** | ✅ completado |

Cambios principales:
- `CCLoader.drain_bridge()` — vacía el buffer del bridge antes del synch.
- `CCLoader.sync_device(retries=3)` — llama a `drain_bridge()` y, al fallar, hace
  `exit_bootloader()` antes de `close_exit()`.
- `Flasher.fetch_asset_by_pattern()`, `get_release_for_board()`, `fetch_board_uf2()`.
- `find_flash_firmware()` — detecta la placa y filtra imágenes por generación.
- `flash_firmware()` — **gate de seguridad** antes del erase (nombre + tamaño de
  imagen vs chip reportado por el bootloader) y
  `_leave_bootloader_after_failure()`.
- Mirror de dos imágenes Sniffle (`GITHUB_SNIFFLE_HEXES`).

**Beneficio colateral:** [modules/firmware/restore.py:497](catnip/modules/firmware/restore.py#L497)
llama a `flasher.find_flash_firmware(...)`, así que el comando `restore` de mi
rama hereda el gate de seguridad automáticamente. No hay nada que portar ahí. ✅

---

### 3.6 `modules/core/cli.py` — ⚠️ **EL ÚNICO SOLAPE** (2 hunks, 9 líneas)

Mi rama vació este archivo (2394 líneas eliminadas). Los dos hunks del compañero
deben re-apuntarse:

#### Hunk A — columna "Board" en la tabla de `devices`

| | |
|---|---|
| **Origen** | `core/cli.py`, función `devices()`, líneas ~1301-1316 |
| **Destino** | [modules/device/cli.py:36-62](catnip/modules/device/cli.py#L36-L62), función `devices()` |
| **Estado** | ✅ completado |

Aplicar sobre `modules/device/cli.py`:
1. Tras `table.add_column("Device", ...)` (línea 47), insertar
   `table.add_column("Board", style="magenta", justify="left")`.
2. Antes del bucle `for dev in devs:`, añadir `from ..firmware.board import detect_board`.
3. Dentro del bucle, añadir
   `board = detect_board(dev.shell_port)` y
   `board_status = board.label if board else "[yellow]unknown[/yellow]"`.
4. Cambiar `table.add_row(str(dev), bridge_status, lora_status, shell_status)`
   → `table.add_row(str(dev), board_status, bridge_status, lora_status, shell_status)`.

> **Nota de estilo:** el compañero usó import diferido dentro de la función
> (`from ..firmware.board import detect_board`). En `device/cli.py` el import
> puede subir a la cabecera junto a los otros `from ..core...` — no hay ciclo
> (`firmware.board` importa `core.usb_connection`, y `device.cli` no es
> importado por `firmware`). **Decisión sugerida:** subirlo a la cabecera por
> coherencia con el resto del módulo. Ver §5.1.

#### Hunk B — propagar `force` a `check_and_update_rp2040`

| | |
|---|---|
| **Origen** | `core/cli.py`, función `update()`, línea ~2088 |
| **Destino** | [modules/firmware/cli.py:401](catnip/modules/firmware/cli.py#L401) |
| **Estado** | ✅ completado (aplicado literal, decisión del usuario) |

Cambio literal: `check_and_update_rp2040(device=dev, flasher=flasher_inst)`
→ `check_and_update_rp2040(device=dev, flasher=flasher_inst, force=force)`.

---

### 3.7 `tests/test_board_support.py` — **ARCHIVO NUEVO** (305 líneas)

| | |
|---|---|
| **Destino** | `tests/test_board_support.py` — misma ruta |
| **Conflicto** | Ninguno. |
| **Acción** | `git checkout main -- catnip/tests/test_board_support.py` |
| **Estado** | ✅ completado — 34 tests pasan |

**Riesgo identificado (bajo, pero verificar):** el test se escribió antes de que
mi rama añadiera [tests/conftest.py](catnip/tests/conftest.py), que instala mocks
globales en `sys.modules` (`serial`, `rich.table`, `scapy`, `matplotlib`…).
`test_board_support.py` hace su propio `sys.path.insert` y usa `patch` local, sin
tocar `sys.modules`, así que **en principio son compatibles** — pero hay que
correr la suite completa (no el archivo aislado) para confirmar que el
`conftest.py` no interfiere con `TestDetectBoard`, que parchea
`ShellConnection`.

---

### 3.8 `changelog.md` y `README.md`

| | |
|---|---|
| **Destino** | Mismas rutas. Mi rama no las tocó. |
| **Conflicto** | Ninguno a nivel de git. |
| **Estado** | ✅ entra limpio · ⬜ corrección de rutas obsoletas pendiente (§5.3) |

`README.md` (+23 líneas): sección "Board Generations (v1/v2 vs v3)". Entra limpia.

`changelog.md` (+20 líneas): entra limpio **pero contiene rutas obsoletas**
(`modules/board.py`, `modules/fw_aliases.py`) heredadas de antes del merge
`c173477`. Deben corregirse a `modules/firmware/board.py` y
`modules/firmware/fw_aliases.py`.

---

### 3.9 `.github/workflows/.pre-commit.yml` — ajeno al feature

| | |
|---|---|
| **Origen** | `220460b` (PR #59) |
| **Destino** | Misma ruta, fuera de `catnip/` |
| **Conflicto** | Ninguno. |
| **Estado** | ✅ completado |

Añade `ref: ${{ github.sha }}` al checkout para que pre-commit corra en HEAD
desacoplado. **No forma parte del feature v2**, pero conviene traerlo en el mismo
merge para que el CI de mi rama se comporte igual que el de `main`.

---

## 4. Estrategia de ejecución propuesta

Como el solape es un único archivo con 2 hunks, la vía más limpia es un **merge
real de `main`** (preserva el historial y deja `main` como ancestro, evitando
que el próximo merge vuelva a arrastrar todo) con resolución manual del único
conflicto:

```bash
git checkout fix/CLI_Control
git merge main                      # conflicto esperado SOLO en catnip/modules/core/cli.py
# Resolver: quedarse con MI versión de core/cli.py (la vaciada)
git checkout --ours catnip/modules/core/cli.py
git add catnip/modules/core/cli.py
# Los otros 8 archivos entran automáticamente
```

Y **después**, en commits separados y revisables:
1. Aplicar Hunk A en `modules/device/cli.py` (§3.6).
2. Aplicar Hunk B en `modules/firmware/cli.py` (§3.6), según decisión de §5.2.
3. Corregir rutas del `changelog.md` (§5.3).
4. Correr la suite completa y regenerar el snapshot si procede (§6).

> **Por qué merge y no cherry-pick:** un cherry-pick dejaría `main` sin ser
> ancestro de mi rama, y el siguiente `git merge main` volvería a intentar
> aplicar los mismos cambios. El merge lo resuelve de una vez.

> **Alternativa si se prefiere historial lineal:** `git checkout main -- <los 8
> archivos>` + commits manuales. Más limpio de leer, pero deja la deuda del
> párrafo anterior. **Recomendación: merge.**

---

## 5. Ambigüedades y decisiones pendientes

### 5.1 ⚠️ Ubicación del import de `detect_board` en `device/cli.py`

El compañero usó import diferido dentro de la función. Mi `device/cli.py` importa
todo en cabecera. **Opciones:** (a) subir el import a cabecera — coherente con el
módulo, sin ciclo detectado; (b) dejarlo diferido — respeta literalmente su
código y evita el coste de importar `usb_connection` al arrancar la CLI.
**No decido por mi cuenta.**

### 5.2 ⚠️ El parámetro `force` del Hunk B parece código muerto

En `update()`, la llamada a `check_and_update_rp2040(..., force=force)` está en la
rama `else` de `if force:` — es decir, `force` **siempre vale `False`** ahí. El
cambio no tiene efecto observable.

Lecturas posibles:
1. Es un resto de refactor y el compañero pensaba unificar ambas rutas.
2. Es intencional como preparación para un cambio futuro.
3. Hay un bug latente: quizá quería que `force` llegara al `confirm_reboot()`
   por otra vía.

**Propuesta:** aplicarlo literalmente (preserva su intención, coste cero) y
abrir una pregunta al compañero. **No "arreglarlo" por nuestra cuenta**, porque
cambiaría el comportamiento de su feature.

### 5.3 ⚠️ Rutas obsoletas en `changelog.md`

El changelog cita `modules/board.py` y `modules/fw_aliases.py`. **Propuesta:**
corregir a `modules/firmware/...`. Es documentación, riesgo nulo, pero se anota
porque técnicamente altera el contenido del PR del compañero.

### 5.4 ⚠️ Coste de `detect_board()` en `catnip devices`

`detect_board()` abre el puerto shell con `timeout=2.0` por cada dispositivo
listado. Con varios CatSniffer conectados, `catnip devices` puede tardar
notablemente más y **ocupar el puerto shell** durante la consulta.

No es un problema introducido por el merge (existe ya en `main`), pero mi rama
añadió el flag `--debug` a `devices`. **Pregunta abierta:** ¿dejarlo tal cual, o
hacer la columna Board opcional / con timeout más corto? **Fuera del alcance de
este merge salvo que se decida lo contrario.**

### 5.5 ℹ️ Observaciones menores (no bloquean)

- `board.py`: anotaciones `-> (bool, str)` no son typing válido (sería
  `Tuple[bool, str]`). Funciona en runtime; `mypy` se quejaría.
- `fw_update.py`: `from .board import detect_board, BOARD_V3` en
  `force_update_rp2040()` importa `BOARD_V3` sin usarlo.
- `flasher.py`: `from .board import image_allowed_for_board` aparece dos veces
  dentro de `find_flash_firmware()`.

Son cosas del código del compañero. **Propuesta: no tocarlas en este merge**
para mantener el diff de integración limpio; anotarlas como follow-up.

---

## 6. Verificación posterior al merge — RESULTADOS

Ejecutado en Sesión 2. Entorno: `pytest 9.1.1`, `black 25.9.0`, `click 8.1.6`
(venv temporal con `--system-site-packages`; el proyecto no trae venv propio y
el `python3` del sistema no tenía `pytest`).

| Comprobación | Resultado |
|---|---|
| `pytest tests/` (suite completa) | **425 pasan, 1 falla** — la falla es preexistente, ver abajo |
| `tests/test_board_support.py` | ✅ **34/34 pasan** dentro de la suite completa; el `conftest.py` global no interfiere |
| Snapshot `cli_tree_linux.txt` | ✅ **Idéntico.** El árbol de comandos no cambió, como se predijo |
| Ciclos de importación | ✅ Ninguno. `modules.device.cli` importa `detect_board` de `modules.firmware.board` sin problema |
| `black --check` en los 2 archivos editados | ✅ Limpio (black colapsó ambos cambios a una línea) |
| `test_sync_device_*` | ✅ Pasan. Sí se confirmó la ralentización prevista |

### 6.1 Falla preexistente (NO causada por el merge)

`tests/test_cli_sniff.py::TestSniffGroup::test_sniff_missing_required_args`

Verificado ejecutando el mismo test sobre `backup/pre-merge-v2-20260904` en un
worktree aparte: **falla exactamente igual antes del merge.**

Causa: con `click 8.1.6`, `catnip sniff` sin subcomando imprime la ayuda y sale
con código **0**, mientras el test espera `returncode != 0` o la palabra
`"Error"` en la salida. Es una dependencia de la versión de Click, no del
soporte v2. **Fuera del alcance de este merge**; anotado como follow-up.

### 6.2 Ralentización confirmada en `test_sync_device_fail_exits`

| | Antes del merge | Después |
|---|---|---|
| `test_sync_device_fail_exits` | 1.01 s | **3.07 s** |

Causa exacta la prevista en §6 original: el nuevo `drain_bridge()` lee de
`self.cmd.sp`, que en ese test es un `MagicMock` cuyo `.read()` devuelve siempre
un objeto *truthy*, así que el bucle agota el `max_ms` de 1500 ms en cada uno de
los 3 intentos. **El test pasa**, solo tarda más.

Arreglo opcional (no aplicado, para no tocar los tests del compañero ni los
míos en el mismo merge): en `TestCCLoader._loader`, fijar
`loader.cmd.sp.read.return_value = b""`.

Los tests de `TestFlasherFindFlash` también subieron a ~2 s cada uno por el
`detect_board()` que `find_flash_firmware()` ahora invoca. Mismo patrón, misma
solución opcional.

### 6.3 Deuda de formato preexistente

`black --check` sobre todo `catnip/` reporta 3 archivos sin formatear:

- `modules/utils/cli_options.py`
- `tests/test_cli_options.py`
- `tests/test_cli_main.py`

Verificado que **ya estaban así antes del merge** (comprobado sobre
`backup/pre-merge-v2-20260904`). Son de mi propio refactor de la CLI, no del PR
del compañero. **No corregidos aquí** para mantener limpio el diff de
integración, pero el hook `black` de pre-commit los bloqueará en el próximo
commit que los toque. Ver follow-up F3.

### 6.4 Pendiente de hardware

- ⬜ `catnip devices` con una placa v3 real → debe mostrar la columna Board.
- ⬜ `catnip devices` con una placa v2 real → debe mostrar `v2 (SAMD21 + CC1352P1)`.
- ⬜ `catnip update` sobre v2 → debe pedir confirmación antes de reiniciar.

---

## 7. Resumen ejecutivo

| Métrica | Valor |
|---|---|
| Commit base | `a06b7887` |
| Archivos tocados por el compañero | 9 |
| Archivos tocados por mí | 32 |
| **Archivos en conflicto real** | **1** (`modules/core/cli.py`) |
| Líneas a re-apuntar a mano | **9** (2 hunks) |
| Archivos que entran sin tocar nada | 8 |
| Decisiones pendientes | 4 (§5.1–§5.4) |

**La fusión es mucho más simple de lo previsto**, porque el compañero ya había
integrado la reestructuración de paquetes en su rama antes del PR. Solo hay que
mover 2 hunks de `core/cli.py` a `device/cli.py` y `firmware/cli.py`.

---

## 8. Progress Log

### Sesión 1 — 2026-09-04

- **Hecho:**
  - Identificado el commit base: `a06b7887` (`git merge-base fix/CLI_Control main`).
  - Aislado el rango `a06b7887..main`: 4 commits de contenido + 2 merges de PR.
  - **Hallazgo clave:** la premisa inicial era incorrecta. `main` NO está sobre la
    arquitectura antigua; el compañero ya mergeó la nueva estructura de paquetes
    en `c173477`. La divergencia real es solo mi segundo nivel de refactor de la CLI.
  - Calculada la intersección de archivos: **un solo archivo** (`modules/core/cli.py`).
  - Revisados y mapeados los 9 archivos del PR del compañero.
  - Verificadas las dependencias cruzadas: `ShellConnection`,
    `parse_fw_version_response`, `List` en `fw_aliases`, `restore.py`.
  - Escrito este plan.
- **Estado:** ⬜ Esperando aprobación. **Ningún archivo de código modificado.**
- **Siguiente paso:** resolver §5.1 y §5.2, luego ejecutar §4.

### Sesión 2 — 2026-09-04 (ejecución)

Decisiones del usuario: §5.1 → import en cabecera · §5.2 → aplicar `force` literal.
Autorización: commits sí, **push no**.

- **Hecho:**
  1. Rama de respaldo `backup/pre-merge-v2-20260904` creada antes de tocar nada.
  2. `git merge main --no-commit --no-ff` → **un único conflicto**, en
     `catnip/modules/core/cli.py`, exactamente como predecía §3.6. Los otros 8
     archivos entraron limpios y se verificó que son **byte-idénticos a `main`**.
  3. Conflicto resuelto con `--ours` (mi `core/cli.py` refactorizado). Verificado
     que el resultado es idéntico a HEAD y sin marcadores.
  4. Commit de merge `ae39d32`.
  5. **Hunk A** aplicado en `modules/device/cli.py` → commit `3d898fd`.
     Import `detect_board` en cabecera. Comprobado antes que
     `modules/firmware/__init__.py` está vacío y que `board.py` solo carga
     `re`/`dataclasses` a nivel de módulo (`ShellConnection` sigue diferido
     dentro de `detect_board`), así que **no añade coste al `catnip --help`** —
     la preocupación que documenta `modules/device/__init__.py`.
  6. **Hunk B** aplicado literal en `modules/firmware/cli.py` → commit `c16b473`.
  7. `black 25.9.0` ejecutado sobre ambos archivos: colapsó los dos cambios a una
     sola línea. El Hunk B queda **carácter por carácter idéntico** al del compañero.
  8. Verificación completa (§6): 425/426 tests, snapshot idéntico, sin ciclos.
  9. Worktree temporal de comparación eliminado.

- **Bloqueos:** ninguno.

- **Estado:** ✅ Merge completo y verificado en local. **NO se ha hecho push**
  (restricción explícita del usuario). 3 commits por delante de `main`.

- **Siguiente paso:** revisar los 3 commits y decidir sobre los follow-ups F1-F4.

---

## 9. Follow-ups (fuera del alcance de este merge)

| ID | Asunto | Origen | Prioridad |
|---|---|---|---|
| **F1** | `test_sniff_missing_required_args` falla con `click 8.1.6` (`catnip sniff` sale con 0). Preexistente. | Mi rama | Media — rompe el CI |
| **F2** | Tests lentos por `drain_bridge()`/`detect_board()` con `MagicMock` (§6.2). Fijar `sp.read.return_value = b""`. | PR #56 | Baja |
| **F3** | 3 archivos sin formatear con `black` (§6.3). Preexistente en mi rama. | Mi rama | Media — el hook los bloqueará |
| **F4** | Rutas obsoletas en `changelog.md` (§5.3) y detalles menores del código del compañero (§5.5). | PR #56 | Baja |
| **F5** | Coste de `detect_board()` por dispositivo en `catnip devices` (§5.4). | PR #56 | A decidir con el compañero |

Además, quedan abiertas las dos preguntas para el compañero:
- El `force` de §5.2 no tiene efecto observable. ¿Intencional o resto de refactor?
- ¿La columna Board debería ser opcional para no abrir el puerto shell en cada listado?

---

<!-- Plantilla para próximas sesiones:
### Sesión N — YYYY-MM-DD
- **Hecho:**
- **Bloqueos:**
- **Estado:**
- **Siguiente paso:**
-->

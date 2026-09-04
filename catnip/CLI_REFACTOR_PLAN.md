# Plan de refactorización del CLI de catnip

**Objetivo:** dividir `modules/core/cli.py` (2 484 líneas) en módulos `cli.py` por
funcionalidad, dejando el núcleo como un simple ensamblador de comandos — siguiendo
el patrón ya establecido en `bombercat-tools`.

**Estado:** propuesta, pendiente de aprobación.
**Fecha:** 2026-09-03
**Rama base:** `fix/CLI_Control`
**Referencia:**: @/home/darcko/Documentos/ElectronicCats/BomberCat/bombercat-tools

---

## 1. Motivación

`modules/core/cli.py` mezcla hoy tres responsabilidades distintas:

1. La definición del grupo raíz y el branding (`print_header`, frases, versión).
2. Helpers de infraestructura (Wireshark/extcap, PuTTY, resolución de dispositivos).
3. La implementación completa de **25 comandos y subcomandos** repartidos en
   6 grupos.

Como referencia, `bombercat-tools` resuelve esto repartiendo el CLI en 10 archivos
(4 375 líneas en total) donde `modules/core/cli.py` son solo 654 líneas dedicadas
casi por completo al ensamblaje:

```python
# bombercat-tools/modules/core/cli.py
from ..device.cli import device as _device
from ..capture.cli import capture as _capture
from ..firmware.cli import flash as _flash
...

def main_cli() -> None:
    cli.add_command(_device)
    cli.add_command(_capture)
    cli.add_command(_flash)
```

---

## 2. Restricciones impuestas por el empaquetado

Se revisaron los 5 workflows de `.github/workflows/`, ambos `.spec` de PyInstaller,
`setup.py` y el launcher de Debian.

**Conclusión: ningún workflow necesita cambios**, siempre que se respeten las tres
reglas de la sección 2.2.

### 2.1 Cómo consume cada build el árbol de `modules/`

| Pieza | Mecanismo | Impacto del refactor |
|---|---|---|
| `.github/workflows/build-deb.yml:45` | `cp -r catnip/modules/ "$PKG_DIR/"` | Copia recursiva — los subpaquetes nuevos entran solos |
| `.github/workflows/build-arch.yml:63` | Idéntico `cp -r` | Sin cambios |
| `catnip.spec` (Linux/macOS) | `Analysis(['catnip.py'])` sigue la cadena de imports **estáticos** | Correcto solo con imports estáticos |
| `catnip_windows.spec:50` | `datas = [('modules', 'modules')]` | Copia el árbol completo como data |
| `setup.py` | `find_packages(include=["modules", "modules.*"])` | Requiere `__init__.py` en cada paquete nuevo |
| `.github/workflows/tests.yml` | `pytest tests/ --cov=modules` | La cobertura ya abarca todo `modules` |
| `packaging/debian/usr/bin/catnip` | `from catnip.modules.core.cli import main_cli` | El punto de entrada no cambia |

### 2.2 Reglas de oro

> **Regla 1 — Todo vive bajo `modules/`.**
> Un directorio nuevo en la raíz del proyecto (`commands/`, `cli/`) obligaría a
> añadir líneas `cp` en `build-deb.yml` **y** `build-arch.yml`. Los `cp -r` actuales
> solo copian `catnip/modules/` y `catnip/protocol/`.

> **Regla 2 — Cada paquete nuevo lleva su `__init__.py`.**
> Sin él, `find_packages()` lo descarta en silencio. Los `.deb`/Arch seguirían
> funcionando (namespace packages implícitos de Python 3), pero `pip install .`
> generaría un paquete al que le faltan comandos, sin ningún error en el build.

> **Regla 3 — Imports estáticos y en el nivel superior del módulo.**
> Nada de registro dinámico por `pkgutil.iter_modules` ni `importlib`. PyInstaller
> no detecta esos imports, y los binarios de Windows/macOS se publicarían sin
> subcomandos y sin fallar el build. El patrón de bombercat
> (`from ..device.cli import device as _device` arriba del archivo) es exactamente
> lo que PyInstaller necesita.

### 2.3 Regla anti-ciclos

`core/cli.py` importa los `modules/<feature>/cli.py`; estos importan helpers desde
`core/device_utils.py` y `core/extcap.py`, que **no** importan nada de `cli`.

> **Invariante:** ningún `modules/<x>/cli.py` puede importar de `modules.core.cli`.
> Si un comando necesita algo que hoy vive en `core/cli.py`, ese algo baja primero
> a un módulo sin Click.

### 2.4 Bug preexistente detectado (no causado por el refactor)

`.github/workflows/build-mac.yml:54` escribe la versión en
`catnip/modules/_version.py`, pero el archivo real es `modules/utils/_version.py`:

```yaml
# build-mac.yml:54  — ruta incorrecta
echo "__version__ = \"${VERSION}\"" > catnip/modules/_version.py
```

Efecto: en macOS la inyección de versión no surte efecto (el binario reporta la
versión commiteada en el repo) y se crea un archivo huérfano. `build-windows.yml:88`
sí usa la ruta correcta (`modules\utils\_version.py`).

**Decisión pendiente:** arreglarlo en este PR o abrir uno aparte.

---

## 3. Estructura objetivo

```
modules/
├── core/
│   ├── cli.py              # ~130 líneas: grupo raíz + print_header + build_cli/main_cli
│   ├── device_utils.py     # NUEVO: get_device_or_exit, send_identify_command
│   └── extcap.py           # NUEVO: run_extcap_directly, find_extcap_plugin,
│                           #        find_putty_path, _find_python_executable
├── sniff/                  # NUEVO paquete (Fase 3 ✅)
│   ├── __init__.py
│   └── cli.py              # grupo `sniff`: ble, zigbee, thread, lora, airtag_scanner
├── device/                 # NUEVO paquete
│   ├── __init__.py
│   └── cli.py              # `devices`, `identify`, _print_raw_port_debug
├── firmware/
│   └── cli.py              # NUEVO: `flash`, `update`, `restore`, `verify` (Fase 4 ✅)
├── protocols/
│   └── cli/                # NUEVO subpaquete (ver Fase 2: los `__init__.py`
│       ├── __init__.py     #   de los paquetes de protocolo son eager)
│       ├── meshtastic.py   # NUEVO: grupo `meshtastic`
│       ├── sx1262.py       # NUEVO: grupo `lora`
│       ├── vhci.py         # NUEVO: grupo `vhci`
│       └── cativity.py     # NUEVO: `cativity`
└── utils/
    ├── completion.py       # NUEVO: grupo `completion`
    └── system_cli.py       # NUEVO: `setup-env`
```

### 3.1 Mapa de migración detallado

Líneas referidas al `modules/core/cli.py` actual.

| Líneas actuales | Contenido | Destino |
|---:|---|---|
| 96 | `wireshark = Wireshark()` (global muerto) | **Borrar** |
| 105–134 | `print_header` | `core/cli.py` (se queda) |
| 137–149 | `get_device_or_exit` | `core/device_utils.py` |
| 152–176 | `find_wireshark_path` (sin llamadores) | **Borrar** |
| 179–210 | `find_putty_path` | `core/extcap.py` |
| 213–254 | `open_wireshark_sniffle_simple` (sin llamadores) | **Borrar** |
| 257–459 | `run_extcap_directly` | `core/extcap.py` |
| 462–509 | `find_extcap_plugin` | `core/extcap.py` |
| 512–535 | `_find_python_executable` | `core/extcap.py` |
| 538–544 | grupo raíz `cli` | `core/cli.py` (se queda) |
| 547–995 | grupo `sniff` (ble, zigbee, thread, lora, airtag) | `sniff/cli.py` |
| 998–1018 | `send_identify_command` | `core/device_utils.py` |
| 1021–1282 | `flash` | `firmware/cli.py` |
| 1285–1354 | `devices` + `_print_raw_port_debug` | `device/cli.py` |
| 1357–1386 | `identify` | `device/cli.py` |
| 1389–1443 | `verify` | `firmware/cli.py` |
| 1446–1494 | `cativity` | `protocols/cli/cativity.py` |
| 1497–1753 | grupo `meshtastic` (decode, live, dashboard, config) | `protocols/cli/meshtastic.py` |
| 1756–1821 | grupo `lora` (spectrum) | `protocols/cli/sx1262.py` |
| 1824–2035 | grupo `vhci` (start, check) | `protocols/cli/vhci.py` |
| 2038–2097 | `update` | `firmware/cli.py` |
| 2100–2163 | `restore` | `firmware/cli.py` |
| 2166–2406 | grupo `completion` | `utils/completion.py` |
| 2409–2466 | `setup-env` | `utils/system_cli.py` |
| 2469–2484 | `main_cli` | `core/cli.py` (se queda, reescrito) |

Balance estimado: **~2 300 líneas movidas**, `core/cli.py` pasa de 2 484 a ~130.

### 3.2 Detalle de Click: `@cli.command` → `@click.command`

Cinco comandos se registran hoy por decoración directa sobre el grupo raíz
(`flash`, `devices`, `identify`, `verify`, `update`). Al salir del archivo deben
convertirse a comandos sueltos y registrarse explícitamente:

```python
# ANTES — modules/core/cli.py
@cli.command()
@click.option("--device", "-d", ...)
def flash(firmware, device, list, full) -> None:
    ...

# DESPUÉS — modules/firmware/cli.py
@click.command()
@click.option("--device", "-d", ...)
def flash(firmware, device, list, full) -> None:
    ...

# DESPUÉS — modules/core/cli.py
from ..firmware.cli import flash as _flash
cli.add_command(_flash)
```

Los nombres de comando expuestos al usuario **no cambian**: Click deriva el nombre
de la función igual en ambos casos.

### 3.3 `build_cli()` para poder testear el árbol

`main_cli()` hoy mezcla el registro de comandos con la ejecución y con
`print_header()`, lo que impide inspeccionar el árbol desde un test. Se separa:

```python
def build_cli() -> click.Group:
    """Registra todos los comandos y devuelve el grupo raíz ensamblado."""
    cli.add_command(_sniff)
    cli.add_command(_cativity)
    cli.add_command(_meshtastic)
    cli.add_command(_restore)
    cli.add_command(_lora)
    cli.add_command(_flash)
    cli.add_command(_devices)
    cli.add_command(_identify)
    cli.add_command(_update)
    cli.add_command(_verify)
    if platform.system() == "Linux":
        cli.add_command(_vhci)
        cli.add_command(_setup_env)
    if platform.system() in ["Linux", "Darwin"]:
        cli.add_command(_completion)
    return cli


def main_cli() -> None:
    if not os.environ.get("_CATNIP_COMPLETE"):
        module = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
        print_header(module)
    build_cli()(prog_name="catnip")
```

Se conserva el condicionamiento por plataforma tal cual está hoy (`vhci` y
`setup-env` solo en Linux; `completion` en Linux/macOS).

---

## 4. Fases de ejecución

Cada fase es un commit independiente que deja el CLI **totalmente funcional**.

### Fase 0 — Red de seguridad ✅

- [x] Volcar el árbol de comandos actual a un snapshot de referencia
      (`catnip --help` más el `--help` de cada subcomando):
      `scripts/dump_cli_tree.py` → `tests/snapshots/cli_tree_linux.txt`.
- [x] Extraer `build_cli()` de `main_cli()` (sección 3.3).
- [x] Añadir `tests/test_cli_structure.py`: afirma que los comandos y
      subcomandos están registrados, y que ningún grupo perdió opciones.

Este test es el que detecta una migración incompleta en cualquier fase posterior.

**Notas de ejecución:**

- El recuento real es de **26 comandos y subcomandos** (13 en la raíz + 13
  anidados), no 25. El desglose queda fijado en `EXPECTED_PARAMS`.
- El snapshot depende de la versión de Click (el formateo del `--help` cambia
  entre versiones), así que el diff contra `cli_tree_linux.txt` es una
  comprobación **manual**; el test de pytest solo compara estructura (nombres de
  comando y flags), que sí es estable entre versiones. `dump_cli_tree.py`
  imprime la versión de Click por *stderr* para poder explicar un diff raro.
- `tests/test_cli_structure.py` incorpora además dos invariantes de empaquetado
  de la sección 2: la Regla 2 (`__init__.py` en cada paquete bajo `modules/`) y
  el invariante 2.3 (ningún `modules/<x>/cli.py` importa de `modules.core.cli`).
- Se añadió `!**/tests/snapshots/*.txt` al `.gitignore` de la raíz, que ignora
  `*.txt` de forma global y habría descartado el snapshot en silencio.
- **Bug preexistente corregido:** en `sniff_ble` el docstring estaba *después*
  de `flasher = Flasher()`, así que Python no lo registraba como docstring y
  `catnip sniff --help` mostraba `ble` sin descripción. El snapshot de
  referencia se generó ya con la corrección aplicada.

### Fase 1 — Helpers compartidos (sin mover comandos) ✅

- [x] Crear `modules/core/device_utils.py` con `get_device_or_exit` y
      `send_identify_command`.
- [x] Crear `modules/core/extcap.py` con `run_extcap_directly`,
      `find_extcap_plugin`, `find_putty_path` y `_find_python_executable`.
- [x] Borrar el código muerto identificado: `wireshark = Wireshark()` (línea 96),
      `open_wireshark_sniffle_simple` y `find_wireshark_path` — ~65 líneas sin
      ningún llamador.
- [x] `core/cli.py` importa de los módulos nuevos; los comandos siguen en su sitio.

**Notas de ejecución:**

- `core/cli.py`: 2 484 → 2 065 líneas. `device_utils.py` 57, `extcap.py` 342.
  El código se movió **verbatim** (extracción por AST), sin retoques.
- `core/cli.py` solo importa dos nombres de `extcap` (`find_putty_path`,
  `run_extcap_directly`); `find_extcap_plugin` y `_find_python_executable` son
  internos de ese módulo. En la Fase 3 esos dos imports se van con `sniff/cli.py`
  y `core/cli.py` deja de depender de `extcap` por completo.
- Imports que quedaron sin uso en `core/cli.py` y se eliminaron: `tempfile`,
  `threading`, `shutil` y `from .pipes import Wireshark, UnixPipe, WindowsPipe`
  (el único uso restante de `pipes` era el global muerto de la línea 96).
- `tests/test_catsniffer.py` se ajustó:
  - se borró `TestFindWiresharkPath` (5 tests) y
    `TestRobustness::test_find_wireshark_exception_handled`, porque prueban
    `find_wireshark_path`, que era código muerto y ya no existe;
  - `TestFindPuttyPath` importa ahora de `modules.core.extcap`;
  - `TestGetDeviceOrExit` importa de `modules.core.device_utils` y parchea
    `modules.core.device_utils.catnip_get_device`. **Esto era obligatorio:**
    parchear `modules.core.cli.catnip_get_device` habría seguido "pasando" sin
    interceptar nada, porque `get_device_or_exit` ya resuelve el nombre en su
    módulo nuevo.
- Verificación: `diff` contra `tests/snapshots/cli_tree_linux.txt` **sin
  diferencias**, y `pytest tests/ -q` → 325 pasados, 6 fallos **preexistentes**
  (confirmados contra un worktree en HEAD: `TestRunBridge`/`TestRunSxBridge`
  keyboard-interrupt y los 3 de `TestCLISubprocess`, que fallan por falta del
  módulo `usb` en el entorno local, no por el refactor).

### Fase 2 — Protocolos (piloto) ✅

- [x] `protocols/cli/meshtastic.py` — grupo `meshtastic` (254 líneas movidas).
- [x] `protocols/cli/sx1262.py` — grupo `lora` (63 líneas movidas).
- [x] `protocols/cli/vhci.py` — grupo `vhci` (209 líneas movidas).
- [x] `protocols/cli/cativity.py` — `cativity` (49 líneas movidas).

Se empieza aquí porque estos grupos son los más autocontenidos: es el piloto de
menor riesgo para validar el patrón.

**Desviación de la sección 3: `protocols/cli/<x>.py`, no `protocols/<x>/cli.py`.**

La ruta original es inviable. Para importar `modules.protocols.sx1262.cli`,
Python **debe** ejecutar antes `modules/protocols/sx1262/__init__.py`, y esos
`__init__.py` son *eager*:

| Paquete | `__init__.py` | Efecto del import estático desde `core/cli.py` |
|---|---|---|
| `cativity/` | vacío | sin coste |
| `sx1262/` | `from .spectrum import …` → matplotlib + numpy | **+1,14 s** en cada `catnip --help` (base: 0,13 s) |
| `meshtastic/` | `from .decoder import …` → `import meshtastic` | **ModuleNotFoundError**: el CLI entero deja de arrancar si falta la dependencia |
| `vhci/` | `from .bridge import …` → `import fcntl` | **rompe Windows**: `fcntl` no existe ahí, y la Regla 3 obliga a importar el módulo aunque `vhci` solo se registre en Linux |

Hoy no ocurre porque los comandos difieren esos imports dentro de la función.

La estructura elegida evita el problema sin tocar ningún `__init__.py`
existente: el padre `modules/protocols/__init__.py` ya está vacío y el nuevo
`modules/protocols/cli/__init__.py` también, así que el coste de import es cero.
Cumple las tres reglas de oro (vive bajo `modules/`, lleva `__init__.py`, y
`core/cli.py` la importa de forma estática y en el nivel superior).

```
modules/protocols/
├── __init__.py          (vacío, ya existía)
├── cli/                 NUEVO
│   ├── __init__.py      (solo docstring)
│   ├── cativity.py
│   ├── meshtastic.py
│   ├── sx1262.py
│   └── vhci.py
├── cativity/  meshtastic/  sx1262/  vhci/   (sin tocar)
```

**Notas de ejecución:**

- `core/cli.py`: 2 065 → 1 472 líneas. Los cuerpos se movieron **verbatim**
  (extracción por AST); el único cambio es la profundidad de los imports
  relativos: desde `modules/protocols/cli/` el antiguo `..protocols.X` pasa a
  ser `..X`, y `..utils.output` / `.device_utils` pasan a `...utils.output` /
  `...core.device_utils`.
- Los imports diferidos dentro de las funciones (`from ..meshtastic import
  MeshtasticDecoder`, `from ..sx1262.spectrum import SpectrumScan`, …) se
  conservan diferidos a propósito: son la razón de que el arranque siga siendo
  barato.
- `queue` quedó sin uso en `core/cli.py` (solo lo usaba `meshtastic live`) y se
  eliminó. `CatSnifferDevice` también está sin uso, pero ya lo estaba antes de
  esta fase; se deja para no ampliar el alcance.
- `tests/test_cli_structure.py`: el invariante §2.3 buscaba con
  `rglob("cli.py")`, que **no** habría cubierto los archivos nuevos (no se
  llaman `cli.py`). Se amplió con `(_MODULES_DIR / "protocols" / "cli").glob("*.py")`.
- Nadie fuera de `core/cli.py` dependía de los re-exports de esos `__init__.py`:
  tests y `modules/core/vhci_bridge.py` importan siempre el submódulo directo
  (`.core`, `.spectrum`, `.bridge`, `.live`, `.decoder`). Por eso emptying/lazy
  de los `__init__.py` también eran opciones viables; se descartaron por ser más
  invasivas (y la vía PEP 562 habría exigido `hiddenimports` en los `.spec`).
- Verificación: `diff` contra `tests/snapshots/cli_tree_linux.txt` **sin
  diferencias**; `import modules.core.cli` en 0,126 s (antes 0,13 s, sin
  regresión); ningún paquete de protocolo aparece en `sys.modules` tras importar
  el CLI. `pytest tests/ -q` → **325 pasados, 6 fallos**, idénticos a los de un
  worktree en HEAD (mismos nombres): son los preexistentes de
  `TestRunBridge`/`TestRunSxBridge` y los 3 de `TestCLISubprocess` por falta del
  módulo `usb` en el entorno local.

### Fase 3 — `sniff` ✅

- [x] Crear `modules/sniff/__init__.py` y `modules/sniff/cli.py` (449 líneas
      movidas: grupo `sniff` con `ble`, `zigbee`, `thread`, `lora` y
      `airtag_scanner`).

El bloque más grande y único consumidor de `core/extcap.py`.

**Notas de ejecución:**

- `core/cli.py`: 1 472 → 1 019 líneas. `sniff/cli.py` son 477 (449 movidas
  **verbatim** + 28 de cabecera e imports); no se retocó ni una línea de los
  cuerpos.
- Como estaba previsto en la Fase 1, `core/cli.py` **deja de depender de
  `core/extcap.py` por completo**: `find_putty_path` y `run_extcap_directly`
  se fueron con `sniff`. Con ellos se eliminaron también los imports que
  quedaron sin uso: `from .bridge import run_bridge, run_sx_bridge` y, de
  `.catnip`, `SniffingFirmware`, `SniffingBaseFirmware` y `Catnip`.
  `CatSnifferDevice` (sin uso desde antes de la Fase 2) se fue en la misma
  línea de import al reescribirla.
- `sniff/cli.py` redeclara `logger = logging.getLogger("rich")`. Es el **mismo
  objeto** que el de `core/cli.py` (`getLogger` cachea por nombre), así que
  `catnip sniff -v` sigue subiendo el nivel del logger que `core/cli.py`
  configura con `basicConfig`. No se duplicó `basicConfig`: la configuración
  del handler sigue viviendo solo en `core/cli.py`.
- `modules/sniff/__init__.py` se deja **vacío a propósito** (solo docstring):
  `core/cli.py` lo importa de forma estática, así que cualquier import eager
  ahí se pagaría en cada `catnip --help` — la lección de la Fase 2.
- `tests/test_cli_structure.py` no necesitó cambios: el invariante §2.3 usa
  `rglob("cli.py")`, que sí cubre `modules/sniff/cli.py` (a diferencia de los
  archivos de `protocols/cli/`, que hubo que añadir aparte en la Fase 2).
- Ningún test parcheaba nombres de `sniff` en `modules.core.cli`, así que no
  se repitió el ajuste de mocks que hizo falta en la Fase 1.
- Verificación: `diff` contra `tests/snapshots/cli_tree_linux.txt` **sin
  diferencias**; `find_packages(include=["modules", "modules.*"])` lista
  `modules.sniff` (Regla 2); `import modules.core.cli` en 0,17-0,18 s sin
  regresión, y ningún paquete de protocolo aparece en `sys.modules`.
  `pytest tests/ -q` → **328 pasados, 3 fallos**, idénticos a los de un
  worktree en HEAD (`TestRunBridge`/`TestRunSxBridge`, preexistentes). El
  recuento difiere del de la Fase 2 (325/6) solo porque aquel se corrió con un
  intérprete sin el módulo `usb`; con el venv del proyecto los 3 de
  `TestCLISubprocess` pasan.

### Fase 4 — `firmware` ✅

- [x] `modules/firmware/cli.py` con `flash`, `verify`, `update` y `restore`
      (447 líneas movidas).

**Notas de ejecución:**

- `core/cli.py`: 1 019 → 570 líneas. `firmware/cli.py` son 483 (447 movidas
  **verbatim** + 36 de cabecera e imports). Se conserva el **orden del
  archivo original** (`flash`, `verify`, `update`, `restore`) para que el diff
  sea legible; el orden de registro no afecta al `--help` porque Click ordena
  los comandos alfabéticamente.
- Primera fase que aplica la **sección 3.2**: `flash`, `verify` y `update`
  estaban decorados con `@cli.command()` (registro implícito sobre el grupo
  raíz) y pasan a `@click.command()` + `cli.add_command(...)` explícito en
  `build_cli()`. `restore` ya era `@click.command()` y ya se registraba a mano.
  Los nombres expuestos al usuario no cambian.
- `modules/firmware/` **ya era un paquete** con `__init__.py` vacío, así que no
  hizo falta crearlo ni hubo riesgo de import eager (a diferencia de la Fase 2).
- Los tres imports diferidos dentro de las funciones pierden un nivel de
  anidamiento: `..firmware.fw_aliases` → `.fw_aliases`, `..firmware.fw_update`
  → `.fw_update` y `..firmware.restore` → `.restore`. Siguen siendo diferidos a
  propósito. Verificado que tras `import modules.core.cli` ninguno de esos tres
  módulos aparece en `sys.modules`.
- Imports que quedaron sin uso en `core/cli.py` y se eliminaron: `Flasher`,
  `run_verification` (con lo que `core/cli.py` **deja de importar de
  `..firmware.*` salvo el grupo de comandos**), `send_identify_command`,
  `catnip_get_device`, `time`, y de `output` los `print_title`,
  `print_subtitle` y `print_alias_item`. `get_device_or_exit` y
  `catnip_get_devices` siguen en uso (`identify`/`devices`).
- El `import usb.core` / `import serial` dentro de `verify` es una comprobación
  de dependencias en un `try/except ImportError`, no un import muerto; se mueve
  tal cual.
- Verificación: `diff` contra `tests/snapshots/cli_tree_linux.txt` **sin
  diferencias**; `catnip flash` sin argumentos ejecutado con `CliRunner` para
  comprobar que el import diferido de `.fw_aliases` resuelve (falla con el
  mensaje esperado, exit 1); `find_packages` sigue listando `modules.firmware`;
  `import modules.core.cli` en 0,17-0,18 s sin regresión. `pytest tests/ -q` →
  **328 pasados, 3 fallos**, los mismos preexistentes de la Fase 3.

### Fase 5 — `device`

- [ ] Crear `modules/device/__init__.py` y `modules/device/cli.py` con `devices`,
      `identify` y `_print_raw_port_debug` (~100 líneas).

### Fase 6 — Sistema y completado de shell

- [ ] `modules/utils/completion.py` — grupo `completion` (~241 líneas de
      post-procesado de scripts de shell).
- [ ] `modules/utils/system_cli.py` — `setup-env` (~58 líneas).

### Fase 7 — Verificación de empaquetado

- [ ] Reproducir en local los pasos de `build-deb.yml`, instalar con `dpkg -i` y
      ejecutar `catnip --help` más un par de subcomandos desde el binario
      instalado. Valida que el launcher `/usr/bin/catnip` sigue resolviendo la
      estructura nueva.
- [ ] Ejecutar `pyinstaller catnip.spec` en local. Es el único riesgo que el CI no
      detectaría hasta el momento del release.

---

## 5. Verificación

En cada fase:

```bash
python catnip.py --help                      # árbol completo de comandos
diff <(dump_cli_tree) snapshot_fase0.txt     # se esperan cero diferencias
pytest tests/ -q                             # incluye test_cli_structure.py
```

Al cierre del refactor, además:

```bash
pyinstaller catnip.spec                      # confirma imports resueltos
# y la reproducción local de build-deb.yml (Fase 7)
```

---

## 6. Riesgos y mitigaciones

| Riesgo | Probabilidad | Mitigación |
|---|---|---|
| Un comando deja de registrarse tras moverlo | Media | `test_cli_structure.py` (Fase 0) más el diff contra el snapshot |
| PyInstaller no resuelve un import nuevo | Baja | Regla 3 (imports estáticos) + build local en Fase 7 |
| `pip install .` pierde un paquete nuevo | Baja | Regla 2 (`__init__.py` obligatorio) |
| Import circular `core/cli` ↔ `<feature>/cli` | Media | Invariante 2.3: los helpers bajan a módulos sin Click |
| Cambia sin querer el nombre de un comando | Baja | Sección 3.2 + snapshot de `--help` |
| Un `__init__.py` eager encarece o rompe el arranque al importarlo estáticamente | Media | Comprobado en Fase 2: solo afecta a `protocols/`; `firmware/` y `utils/` ya se importan hoy, y `sniff/`/`device/` nacen vacíos |

---

## 7. Trabajo de seguimiento (fuera de alcance)

- Arreglar la ruta de `_version.py` en `build-mac.yml` (sección 2.4).
- `setup-env` (líneas 2423–2428) incrusta el contenido de las reglas udev, que ya
  existe en `packaging/debian/lib/udev/rules.d/99-catsniffer.rules`. Son dos copias
  que pueden divergir; convendría leer el archivo empaquetado.
- `modules/core/vhci_bridge.py` parece redundante con `modules/protocols/vhci/`;
  revisar si es código muerto.

# Agent guide: CatSniffer-Tools

This repository holds the software for the Electronic Cats **CatSniffer**, a multi-protocol RF board (BLE, Zigbee, Thread, LoRa, FSK).

**Full guide:** [`.claude/skills/catsniffer/SKILL.md`](.claude/skills/catsniffer/SKILL.md). Start with its **Agent fast start** section. Worked scenarios are in [`references/recipes.md`](.claude/skills/catsniffer/references/recipes.md).

## The essentials

- **`catnip/` is the only maintained tool**, a Python 3.12+ Click CLI. `Legacy/` is retired; do not use it for new work. `catsnifferTUI/` is a bench testbench for testing several boards at once.
- **Run it from source**:

  ```sh
  cd catnip
  python3 -m venv venv && . venv/bin/activate
  pip install -r requirements.txt
  python catnip.py --help
  ```

- **Two radios.**
  - The CC1352 (2.4 GHz) needs a protocol-specific firmware image. `catnip sniff` flashes it automatically.
  - The SX1262 (sub-GHz) needs only radio settings.
- **Board generations**: v2 is SAMD21 + CC1352P1; v3 is RP2040 + CC1352P7. Wrong-generation firmware bricks the bootloader, so **never guess `--board`**.
- **Hardware**: most commands need a board on USB. If none is attached, say so. Never fabricate device output or captures.
- **Transmitting commands**: confirm with the user before running any of these.
  - `verify --test-all`
  - `sniff ble -m active_scan`
  - `vhci`
  - a non-default `-pw`
  - the catsnifferTUI smoke test

## Source of truth

| What | Where |
|---|---|
| Flags | Live `python catnip.py <cmd> --help`. The snapshot in `catnip/tests/snapshots/` can lag behind. |
| User docs | `catnip/docs/` (`usage.md`, `reference.md`, `troubleshooting.md`, `commands/*.md`) |
| Commands | `catnip/modules/core/cli.py` → `catnip/modules/<area>/cli.py` |
| Firmware aliases | `catnip/modules/firmware/fw_aliases.py` |

## Changing code

```sh
cd catnip
pytest -q -m "not hardware"
pytest -k cli_structure
python scripts/dump_cli_tree.py > tests/snapshots/cli_tree_linux.txt   # after any CLI change
```

- **After changing flags**, update `catnip/docs/commands/<cmd>.md` and regenerate the snapshot.
- **Conventions** are in `catnip/docs/contributing.md`.
- **Order-dependent test failures**: `tests/test_catsniffer.py` mocks modules in `sys.modules` and never restores them. In a full run this can break `test_output.py`, `test_pcap_writer.py` and `test_restore.py`. Run those files on their own before treating a failure as your regression.

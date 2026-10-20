<!--
Canonical template for a command-group page. Copy it, do not publish it.

Rules (see docs/internal/plan §2.1):
  - The H1 is the command, in backticks.
  - The one-line description under it is COPIED VERBATIM from `--help`.
    If it reads badly here, fix the `--help` text and copy it again.
  - Command blocks use ```sh. Output blocks use ``` with NO language,
    so input and output are told apart at a glance.
  - Option tables carry the literal `--help` text, one row per flag.
    `-h, --help` is never listed: every command has it.
  - Links are always relative. Never absolute GitHub URLs to this repo.
  - Outputs are pasted from a real run. Never hand-written or edited.
  - Drop any section that would be empty. Do not keep an empty heading.
-->

# `catnip <group>`

> One-line description, copied from the CLI `--help`.

## Quick Start

```sh
# 1. <step>
catnip <group> <subcommand>

# 2. <step>
catnip <group> <subcommand> --flag
```

---

## How it works

<ASCII diagram or numbered list of the flow. Omit the section if it is trivial.>

---

## Subcommands

All subcommands take the [device selector](../reference.md#device-selection).

### `<group> <subcommand>`

> Description from `--help`.

| Option | Description |
|---|---|
| `-d, --device ID` | Description from `--help`. |

```sh
catnip <group> <subcommand> [options]
```

```
<real CLI output, pasted as-is>
```

---

### Notes

- Firmware requirements, caveats, platform differences.

---

## See also

- [`<other-command>`](other.md) — why it is related.
- End-to-end flow: [Usage](../usage.md).

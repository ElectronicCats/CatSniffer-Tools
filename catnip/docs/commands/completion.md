# `catnip completion`

> Install shell tab completion for catnip.

Tab completion covers every command, subcommand and flag in the CLI, generated
from the live command tree — so it never drifts from the binary you have
installed. Run it once per machine.

**Linux and macOS only.** The group is not registered on Windows.

## Quick Start

```sh
# 1. Install for the shell you are using (auto-detected)
catnip completion install

# 2. Reload the shell so it picks up the new script
exec $SHELL
```

```
ℹ Detected shell: zsh
✓ Completion script written to: ~/.zfunc/_catnip
✓ Added fpath entry to ~/.zshrc

ℹ Restart your shell or run:
  source ~/.zshrc && compinit -u
```

---

## Subcommands

### `completion install`

> Install tab completion for your shell.

| Option | Description |
|---|---|
| `--shell [bash\|zsh\|fish]` | Shell to install completion for (auto-detected if omitted) |

The shell is detected from `$SHELL`. Name it explicitly when you are installing
for a shell other than the one you are currently in, or when detection fails:

```sh
catnip completion install --shell zsh
```

If `$SHELL` holds something the installer does not recognise, it stops rather
than guessing:

```
✗ Could not detect shell. Use --shell bash|zsh|fish.
```

---

## Where the script is installed

| Shell | File | Extra step |
|---|---|---|
| `bash` | `~/.local/share/bash-completion/completions/catnip` | none |
| `zsh` | `~/.zfunc/_catnip` | an `fpath` entry plus `compinit` is appended to `~/.zshrc` |
| `fish` | `~/.config/fish/completions/catnip.fish` | none |

Only zsh needs the rc-file edit, because `~/.zfunc` is not on the default
`fpath`. For bash and fish the directory is already searched by the shell.

---

### Notes

- Completion is registered for **three spellings** of the program: `catnip`,
  `catnip.py` and `./catnip.py`. A wrapper is also registered on `python` and
  `python3`, so `python catnip.py <TAB>` completes as well — useful when you run
  from a checkout instead of an installed package.
- The generated script calls catnip by **absolute path** (the interpreter and
  the script that installed it), so completion keeps working whether or not
  `catnip` is on your `PATH`. The flip side: if you move or reinstall the venv,
  rerun `catnip completion install`.
- On Windows the command exits with `✗ Shell completion is not supported on
  Windows.` and status 1.
- Reinstalling overwrites the previous script. It is safe to rerun after a
  catnip upgrade that added commands.

---

## See also

- [`setup-env`](setup-env.md) — the other one-off machine setup command (udev rules, groups).
- Install and packaging: [Installation](../installation.md).

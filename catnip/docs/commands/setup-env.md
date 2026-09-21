# `catnip setup-env`

> Setup environment: install udev rules and add user to groups.

A fresh Linux install will not let an unprivileged user open the CatSniffer's
serial ports, and the [VHCI bridge](vhci.md) cannot open `/dev/vhci` either.
This command fixes both, once, for the machine.

**Linux only.** The command is not registered on macOS or Windows.

## Quick Start

```sh
# 1. Run once, as root
sudo catnip setup-env

# 2. Log out and back in — group membership is read at login
# 3. Confirm the device is now visible
catnip devices
```

Without `sudo` it refuses rather than half-applying the changes:

```
✗ Root privileges required. Please run with sudo:
  sudo catnip.py setup-env
```

---

## What it changes

Three things, in this order:

1. **Writes `/etc/udev/rules.d/99-catsniffer.rules`** with two rules:

   ```
   # Permission to VHCI (Bluetooth Virtual)
   KERNEL=="vhci", MODE="0660", GROUP="bluetooth", TAG+="uaccess"

   # Permission to CatSniffer (RP2040)
   SUBSYSTEM=="tty", ATTRS{idVendor}=="2e8a", ATTRS{idProduct}=="00c0", MODE="0660", GROUP="dialout", TAG+="uaccess"
   ```

2. **Adds you to `dialout` and `bluetooth`** with `usermod -aG`. The account it
   modifies is `$SUDO_USER` — the user who invoked `sudo`, not `root`.

3. **Reloads udev** with `udevadm control --reload-rules` followed by
   `udevadm trigger`, so the rules apply to the device already plugged in
   without a reboot.

---

### Notes

- **Group membership only takes effect at next login.** The command says so at
  the end, and it is the single most common reason `catnip devices` still finds
  nothing right after running it. Log out and back in; `newgrp dialout` works as
  a per-shell stopgap.
- The `ATTRS{idProduct}=="00c0"` rule matches the **RP2040 (v3)** USB id. A v2
  board (SAMD21) has a different id and is not covered by this rule; on v2 the
  `dialout` group membership is what grants access.
- Each of the three steps reports its own failure and the command keeps going —
  a missing `bluetooth` group prints a warning, it does not abort the udev work.
  Read the output rather than only the exit code.
- Rerunning is safe: the rules file is overwritten with the same content and
  `usermod -aG` is idempotent.

---

## See also

- [`vhci`](vhci.md) — the command whose `/dev/vhci` access these rules grant; `vhci check` verifies them.
- [`devices`](devices.md) — what to run afterwards to confirm the ports are readable.
- Per-OS install steps: [Installation](../installation.md).

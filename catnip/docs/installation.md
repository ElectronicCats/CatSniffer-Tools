# Installation

Packages for Windows, macOS and Linux, plus the from-source route. Whichever
you pick, the work is not finished when the package installs: on Linux the
serial ports need permissions, and that is [`setup-env`](commands/setup-env.md).

- [Which download](#assets)
- [Windows](#windows)
- [macOS](#macos)
- [Linux — Debian / Ubuntu](#debian)
- [Linux — Arch](#arch)
- [From source](#from-source)
- [Post-installation](#post-installation)
- [Verifying the install](#verifying)
- [Uninstalling](#uninstalling)

---

<a id="assets"></a>
## Which download

Release assets live on the
[Releases page](https://github.com/ElectronicCats/CatSniffer-Tools/releases).
Take the exact file names from there — the versions below are written as
`<version>`:

| Platform | Asset | Installed as |
|---|---|---|
| Windows 10/11 (64-bit) | `Catnip-Setup.exe` | `C:\Program Files\Catnip\` + Start Menu entry |
| macOS 11+ (Intel or Apple Silicon) | `catnip-<version>.pkg` | `/usr/local/opt/catnip/`, symlinked into `/usr/local/bin` |
| Debian 11+ / Ubuntu 20.04+ | `catnip-<version>.deb` | `/usr/bin/catnip` |
| Arch and derivatives | `catnip-<version>.pkg.tar.zst`, or the AUR | `/usr/bin/catnip` |
| Any (developers) | the repository | wherever your virtualenv is |

About 100 MB of disk space in every case: the packaged builds bundle a Python
runtime and every dependency, so nothing else has to be installed first.

---

<a id="windows"></a>
## Windows

1. Download `Catnip-Setup.exe`.
2. **Run it as administrator** — right-click → *Run as administrator*, then
   accept the UAC prompt. The USB drivers need it.
3. Follow the wizard: language, install directory (default
   `C:\Program Files\Catnip`), components — keep them all.
4. Confirm the driver installation when Windows asks.
5. Finish. `catnip` is on the Start Menu.

Then, in Command Prompt or PowerShell:

```powershell
catnip --help
catnip devices
```

If the board does not appear, check *Device Manager → Ports (COM & LPT)*. A
warning icon there means the USB-serial driver did not install: rerun the
installer as administrator, or install the drivers by hand from
`C:\Program Files\Catnip\drivers`.

> [!Note]
> Three commands do not exist on Windows: `vhci`, `setup-env` and `completion`.
> See [Limitations](limitations.md#platform-support).

---

<a id="macos"></a>
## macOS

Check which build you need:

```sh
uname -m        # arm64 = Apple Silicon · x86_64 = Intel
```

Then download the matching `.pkg` and install it:

```sh
curl -LO https://github.com/ElectronicCats/CatSniffer-Tools/releases/latest/download/catnip-<version>.pkg
sudo installer -allowUntrusted -pkg catnip-<version>.pkg -target /
```

The package installs into `/usr/local/opt/catnip/` and symlinks `catnip` and
`lora_extcap` into `/usr/local/bin`. Its postinstall script also installs
**OpenOCD** through your Homebrew, which [`restore`](commands/restore.md)
needs; if Homebrew is not present it says so and leaves you to run
`brew install openocd` yourself.

If Gatekeeper blocks the package — *"cannot be opened because the developer
cannot be verified"* — open *System Settings → Privacy & Security* and choose
**Open Anyway**.

```sh
catnip --help
catnip devices
```

macOS does not gate `/dev/tty.usbmodem*` behind a group the way Linux gates
`/dev/ttyACM*`, so there is no `setup-env` step here — the command is not
registered on macOS at all.

---

<a id="debian"></a>
## Linux — Debian / Ubuntu

```sh
# 1. Install the package
sudo dpkg -i catnip-<version>.deb

# 2. Pull in anything it declares and you do not have yet
sudo apt-get install -f
```

It depends on `python3`, `libusb-1.0-0` and `openocd`, installs
`/usr/bin/catnip`, a desktop entry, and the udev rule at
`/lib/udev/rules.d/99-catsniffer.rules`. Its postinstall creates the `dialout`
and `bluetooth` groups if they are missing and reloads udev.

**You still have to join those groups** — see
[Post-installation](#post-installation).

---

<a id="arch"></a>
## Linux — Arch

```sh
sudo pacman -U catnip-<version>.pkg.tar.zst
```

Or through an AUR helper:

```sh
yay -S catnip
paru -S catnip
```

---

<a id="from-source"></a>
## From source

The route for development, and the only one that gets you the test suite.

```sh
# 1. System dependencies
sudo apt-get install python3 python3-pip python3-venv libusb-1.0-0 libmagic1   # Debian/Ubuntu
sudo pacman -S python python-pip python-virtualenv libusb file                 # Arch

# 2. The repository
git clone https://github.com/ElectronicCats/CatSniffer-Tools.git
cd CatSniffer-Tools/catnip

# 3. A virtualenv, always
python3 -m venv venv
source venv/bin/activate

# 4. Dependencies and the package itself
pip install -r requirements.txt
pip install -e .
```

**Python 3.12 or newer.** `setup.py` still declares `>=3.9`, which is wrong —
the code uses 3.10+ syntax and CI tests 3.12, 3.13 and 3.14. See
[Limitations](limitations.md#known-gaps).

After `pip install -e .` the `catnip` entry point is on your `PATH` while the
virtualenv is active. Without installing, `python catnip.py <command>` works
from the checkout just as well.

The `Makefile` wraps the same steps:

```sh
make install         # pip install . plus a global symlink (uses sudo)
make uninstall       # remove both
make clean           # build artefacts
```

---

<a id="post-installation"></a>
## Post-installation

**On Linux, this is not optional.** Without it the ports are visible and
unopenable:

```sh
# 1. udev rules and group membership
sudo catnip setup-env

# 2. Log out and back in — group changes only apply at login
#    (newgrp dialout works as a per-shell stopgap)

# 3. Confirm
catnip devices
```

What `setup-env` changes, and the caveats for a v2 board, are documented in
[`setup-env`](commands/setup-env.md).

Optional everywhere it exists — tab completion for every command, subcommand
and flag:

```sh
catnip completion install
exec $SHELL
```

---

<a id="verifying"></a>
## Verifying the install

```sh
# 1. The CLI runs and the banner names a version
catnip --help

# 2. The board is seen, with its three ports
catnip devices

# 3. The board answers — firmware, capabilities, generation
catnip status

# 4. The hardware actually works
catnip verify
```

There is **no `--version` flag**: the version is in the banner every command
prints.

On Linux, if you plan to use the Bluetooth bridge:

```sh
sudo modprobe hci_vhci
catnip vhci check
```

Nothing found at step 2? [Troubleshooting](troubleshooting.md#no-devices)
works through it in order.

---

<a id="uninstalling"></a>
## Uninstalling

**Windows** — *Settings → Apps → Catnip → Uninstall*, or rerun the installer
and choose *Remove*.

**macOS**

```sh
sudo pkgutil --forget com.electroniccats.catsniffer
sudo rm -rf /usr/local/opt/catnip
sudo rm -f /usr/local/bin/catnip /usr/local/bin/lora_extcap
```

**Debian / Ubuntu**

```sh
sudo dpkg -r catnip
```

**Arch**

```sh
sudo pacman -R catnip
```

**From source**

```sh
pip uninstall catnip        # or: make uninstall
```

None of these remove `~/.catnip/`, the downloaded firmware cache, or
`~/.config/catnip/profiles.toml`. Delete them by hand if you want the machine
clean:

```sh
rm -rf ~/.catnip ~/.config/catnip
```

Completion scripts are left behind too — `~/.zfunc/_catnip`,
`~/.local/share/bash-completion/completions/catnip` or
`~/.config/fish/completions/catnip.fish`, plus the `fpath` lines
`catnip completion install` appended to `~/.zshrc`.

---

## See also

- Building the packages yourself: [Packaging](packaging.md).
- First capture after installing: [Usage](usage.md).
- Per-command platform support: [Limitations](limitations.md#platform-support).

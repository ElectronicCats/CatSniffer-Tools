# Packaging

Building the distributable artefacts yourself: the Debian package, the macOS
`.pkg`, the Windows installer, and the PyInstaller bundles underneath them. If
you only want catnip installed, [Installation](installation.md) is the page you
want.

- [What a packaged build contains](#contents)
- [Debian / Ubuntu (.deb)](#deb)
- [macOS (.pkg)](#pkg)
- [Windows (.exe)](#exe)
- [Nuitka](#nuitka)
- [Makefile targets](#make)
- [Things to check before shipping](#gotchas)

---

<a id="contents"></a>
## What a packaged build contains

Every binary artefact is built with **PyInstaller in `--onedir` mode**: one
directory holding the frozen interpreter, every dependency, and the resources
that have to stay real files on disk.

Two of those resources matter:

- **`protocol/lora_ascii.lua`** — Wireshark loads it by path, so it cannot be
  frozen into the archive. Both specs add it as a data file.
- **`VERSION`** — read by `_version.py`, which falls back to installed package
  metadata when the file is absent.

Libraries that need their data files collected wholesale (`scapy`, `textual`,
`meshtastic`, `rich`, `matplotlib`, `cryptography`, `numpy`, `intelhex`,
`requests`) are pulled in with `collect_all`. `libusb`, `magic` and the
pyserial port tools come in as hidden imports.

`lora_extcap.py` is built too — as a second binary on Linux and macOS, and
folded into the same analysis on Windows — because Wireshark has to be able to
execute it on its own.

---

<a id="deb"></a>
## Debian / Ubuntu (.deb)

The package tree is checked in at [`packaging/debian/`](../packaging/debian):

```
packaging/debian/
├── DEBIAN/
│   ├── control              # catnip, Depends: python3, libusb-1.0-0, openocd
│   └── postinst             # creates dialout/bluetooth, reloads udev
├── usr/bin/catnip           # launcher: vendor path + package path, then main_cli()
├── usr/share/applications/catnip.desktop
└── lib/udev/rules.d/99-catsniffer.rules
```

There is **no build script in the repository** — assemble the tree and build it
with `dpkg-deb`:

```sh
# 1. Stage the Python package into the tree (dist-packages under usr/lib)
#    alongside what is already checked in.
# 2. Keep DEBIAN/control's Version in step with VERSION.
# 3. Build.
dpkg-deb --build packaging/debian catnip-$(cat VERSION).deb

# 4. Check what you produced before shipping it.
dpkg-deb --info catnip-$(cat VERSION).deb
dpkg-deb --contents catnip-$(cat VERSION).deb
lintian catnip-$(cat VERSION).deb
```

`usr/bin/catnip` is a Python launcher rather than a symlink: it inserts the
package's `vendor/` directory and the package directory itself into `sys.path`
before importing `catnip.modules.core.cli`, which is what makes the installed
layout behave like a checkout.

The postinstall does two things and no more: create the `dialout` and
`bluetooth` groups if the system lacks them, and reload udev so the shipped
rule applies to a board that is already plugged in. **It does not add the user
to those groups** — that is [`setup-env`](commands/setup-env.md), deliberately,
because a package install has no business changing an account's privileges.

**Arch**: the AUR recipe is not in this repository. The `.pkg.tar.zst` asset on
the Releases page is built elsewhere.

---

<a id="pkg"></a>
## macOS (.pkg)

One script does the whole job:

```sh
brew install libusb libmagic     # build prerequisites
./build_mac.sh
```

It runs PyInstaller twice (`catnip`, then `lora_extcap`), verifies both
binaries exist, stages them into `pkg_root`, and calls `pkgbuild`:

| | |
|---|---|
| Install location | `/usr/local/opt/catnip/{catnip,lora_extcap}/` |
| Symlinks | `/usr/local/bin/catnip`, `/usr/local/bin/lora_extcap` |
| Identifier | `com.electroniccats.catsniffer` |
| Version | the contents of `VERSION` |
| Output | `catnip-<version>.pkg` |

**OpenOCD is not bundled on macOS.** The postinstall script
([`packaging/macos/scripts/postinstall`](../packaging/macos/scripts/postinstall))
installs it through the logged-in user's Homebrew — checking
`/opt/homebrew/bin/brew` before `/usr/local/bin/brew`, so Apple Silicon is
tried first — and, if Homebrew is missing, prints the manual command rather
than failing the install. `restore` is the command that needs it.

The script is deliberately forgiving: every step ends in `|| true` or an
explanatory message, because a failed postinstall marks the whole package as
failed for something that is only needed by one command.

---

<a id="exe"></a>
## Windows (.exe)

Two stages: PyInstaller, then Inno Setup.

```bat
build_windows.bat
```

It installs the dependencies (including **pywin32**, which the named-pipe
capture path needs), downloads libusb if `libusb\` is absent, and builds with
[`catnip_windows.spec`](../catnip_windows.spec). That spec differs from the
generic one in ways worth knowing:

- it analyses **both** `catnip.py` and `lora_extcap.py` in one pass;
- it adds the `win32file` / `win32pipe` / `win32event` / `pywintypes` hidden
  imports;
- it hunts for the 64-bit `libusb-1.0.dll` under `libusb\` and bundles it;
- it bundles **OpenOCD** from `openocd_dist\` when CI has downloaded it, and
  prints `WARNING: OpenOCD scripts not found … 'catnip restore' will not work`
  when it has not;
- it ships `README.md`, `LICENSE` and `VERSION` alongside the binary.

Then the installer, from
[`installer/catsniffer_installer.iss`](../installer/catsniffer_installer.iss),
compiled with Inno Setup. It reads the version straight out of `VERSION`,
installs to `{autopf}\Catnip`, requires admin, and offers three tasks: a
desktop icon, adding the install directory to the system `PATH`, and running
[`scripts/install_windows_drivers.ps1`](../scripts/install_windows_drivers.ps1)
to install the USB drivers. Output is `dist\Catnip-Setup.exe`.

---

<a id="nuitka"></a>
## Nuitka

An alternative to PyInstaller for Linux, producing a compiled standalone tree:

```sh
./compile.sh                 # nuitka --standalone --follow-imports
make compile-install         # the same, then copy the binary to /usr/local/bin
```

It is not what the release artefacts are built with. Treat it as the
experimental path.

---

<a id="make"></a>
## Makefile targets

```sh
make install          # pip install . + scripts/install.sh for a global symlink
make compile-install  # compile.sh, then install dist/catnip.dist/catnip
make uninstall        # pip uninstall + remove the symlink
make clean            # build/, dist/, *.egg-info, __pycache__
```

`make install` runs [`scripts/install.sh`](../scripts/install.sh) under sudo to
symlink catnip into `/usr/local/bin`. The reason is narrow and worth keeping in
mind: `sudo`'s `secure_path` does not include a virtualenv or `~/.local/bin`,
so without that symlink `sudo catnip vhci start` cannot find the binary that
plain `catnip` resolves to.

---

<a id="gotchas"></a>
## Things to check before shipping

- **`catnip.spec` does not include `VERSION`.** `build_mac.sh` passes
  `--add-data "VERSION:."` on its own command line and `catnip_windows.spec`
  lists it among the extra files, but a build driven by `catnip.spec` alone has
  neither. Check what the banner reports before publishing such a build.
- **Version lives in three places.** `VERSION` is the source; `setup.py` reads
  it, the Inno Setup script reads it, `build_mac.sh` reads it — but
  `packaging/debian/DEBIAN/control` carries its own `Version:` field. CI papers
  over this (`build-deb.yml` rewrites the field from `VERSION` before calling
  `dpkg-deb`), so only a **local** `.deb` build can ship the stale number.
- **OpenOCD differs per platform**: a dependency on Debian, a Homebrew install
  on macOS, bundled into the binary on Windows. `restore` is broken on any
  build where it is missing, and nothing else notices.
- **CI builds all four artefacts.** `build-deb.yml`, `build-arch.yml`,
  `build-mac.yml` and `build-windows.yml` live at the **repository root**
  (`../../.github/workflows/`), not under `catnip/`, because GitHub Actions
  only reads workflows from the root of the monorepo. They attach their assets
  to a GitHub release on `release: [created]` or a manual `workflow_dispatch`.
  Building locally, as described above, is for testing a build before you tag —
  see [Release](release.md#workflows).

---

## See also

- Installing what you built: [Installation](installation.md).
- Cutting a release: [Release](release.md).
- What is in the tree being packaged: [Architecture](architecture.md).

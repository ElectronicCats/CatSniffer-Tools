# Release

Cutting a version of catnip: what to bump, what to check, and what a published
release changes for people already running the tool.

- [Version numbering](#numbering)
- [Where the version lives](#where)
- [The procedure](#procedure)
- [What CI does](#workflows)
- [Checklist](#checklist)
- [What a release changes for users](#effects)

---

<a id="numbering"></a>
## Version numbering

Four components, `A.B.C.D`, tagged `vA.B.C.D` — `v3.3.2.1`, `v3.3.2.0`,
`v3.2.1.1`. The leading `3` tracks the hardware line the tool is built around;
the rest is ordinary release numbering.

Tags live on the [`CatSniffer-Tools`](https://github.com/ElectronicCats/CatSniffer-Tools)
repository as a whole, not on the `catnip/` subdirectory.

**Firmware versions are a separate scheme.** Images are `vA.X.Y.Z` where `A` is
the board generation they are built for, released from
`CatSniffer-Firmware`. The two never share a number — see
[Firmware](firmware.md#versions).

---

<a id="where"></a>
## Where the version lives

| Place | How it gets there |
|---|---|
| [`VERSION`](../VERSION) | **the source**. One line, no `v` prefix. |
| `modules/utils/_version.py` | reads `VERSION`; falls back to the installed package metadata when the file is absent |
| `setup.py` | reads `VERSION` at build time |
| `installer/catsniffer_installer.iss` | reads `VERSION` at compile time |
| `build_mac.sh` | reads `VERSION` for `pkgbuild --version` and the output file name |
| `packaging/debian/DEBIAN/control` | **hand-edited** — the one that drifts |
| the git tag | `v` + the contents of `VERSION` |

So a bump is: edit `VERSION`, edit `DEBIAN/control`, commit, tag.

---

<a id="procedure"></a>
## The procedure

```sh
# 1. Everything green, on the branch you are releasing from
pytest -q

# 2. The CLI snapshot matches the CLI
python scripts/dump_cli_tree.py > tests/snapshots/cli_tree_linux.txt
git diff --stat tests/snapshots/cli_tree_linux.txt   # expect: no change

# 3. Bump
echo "3.3.3.0" > VERSION
$EDITOR packaging/debian/DEBIAN/control              # Version: 3.3.3.0
                                                    # build-deb.yml rewrites this
                                                    # from VERSION, but the file
                                                    # is committed, so keep it

# 4. Confirm the banner reports what you just wrote
python catnip.py --help | head -20

# 5. Commit and tag
git commit -am "release: v3.3.3.0"
git tag -a v3.3.3.0 -m "v3.3.3.0"
git push origin main --tags
```

Then create a GitHub release from the tag. That is the step that produces the
artefacts — see below.

---

<a id="workflows"></a>
## What CI does

**The artefacts are built by CI.** The workflows live at the **repository
root**, not under `catnip/` — catnip is one directory of the `CatSniffer-Tools`
monorepo, and GitHub Actions only reads `.github/workflows/` from the root:

| Workflow | Builds | Asset attached to the release |
|---|---|---|
| [`build-deb.yml`](../../.github/workflows/build-deb.yml) | Debian package | `catnip-<version>.deb` |
| [`build-arch.yml`](../../.github/workflows/build-arch.yml) | Arch package | `catnip-<version>.pkg.tar.zst` |
| [`build-mac.yml`](../../.github/workflows/build-mac.yml) | macOS installer, one job per architecture | `catnip-<version>-x86_64.pkg`, `catnip-<version>-arm64.pkg` |
| [`build-windows.yml`](../../.github/workflows/build-windows.yml) | Inno Setup installer | `catnip-<version>.exe` |

Each attaches its asset with `softprops/action-gh-release` when the event is a
published release (`release: [created]`) or a manual `workflow_dispatch` given
a `release_tag`. **Creating the GitHub release from the tag is what produces
the artefacts** — you do not build and upload them by hand. Building locally,
which [Packaging](packaging.md) covers, is for testing a build before tagging.

[`tests.yml`](../../.github/workflows/tests.yml) runs pytest on Python 3.12,
3.13 and 3.14 against `ubuntu-latest`, on pushes and pull requests to `main`,
`develop` and `refactor`, filtered to changes under `catnip/`.

> [!Note]
> `catnip/.github/workflows/tests.yml` is a second copy of the test workflow
> that **GitHub never runs** — workflows are only read from the repository
> root. Edit the root one.

---

<a id="checklist"></a>
## Checklist

Before tagging:

- [ ] `pytest -q` green.
- [ ] `tests/snapshots/cli_tree_linux.txt` regenerated and unchanged, or the
      change is intended and `docs/commands/` was updated to match it.
- [ ] `VERSION` and `packaging/debian/DEBIAN/control` agree.
- [ ] The banner shows the new version.
- [ ] Docs updated for any new command, subcommand or flag — a new group also
      needs a row in [`reference.md`](reference.md#commands) and in the
      README's documentation table.

Before publishing the release:

- [ ] The four build workflows went green and attached their assets:
      `catnip-<version>.deb`, `catnip-<version>.pkg.tar.zst`,
      `catnip-<version>-x86_64.pkg`, `catnip-<version>-arm64.pkg` and
      `catnip-<version>.exe`.
- [ ] Each one installs on a clean machine and `catnip devices` runs.
- [ ] The Windows build bundles OpenOCD, or `restore` is known-broken there.
- [ ] The macOS `.pkg` postinstall finds Homebrew, or its message is accurate.
- [ ] Release notes name the firmware versions this release was tested against.

---

<a id="effects"></a>
## What a release changes for users

Publishing a release is not inert. [`catnip update`](commands/flash.md#catnip-update)
queries the **latest release of `CatSniffer-Tools`** and compares its tag
against the local `VERSION`:

- **Local older** — it offers the update.
- **Local equal** — nothing to do.
- **Local newer** — the development warning, which is what a working checkout
  ahead of the last tag reports:

  ```
  ⚠ Development version detected! Local: 3.3.3.0 > Latest release: 3.3.2.1
  ⚠ This build is ahead of the latest release and may be unstable.
  ⚠ Use it for testing only — firmware compatibility is not guaranteed.
  ```

That check is also how the tool decides whether the **firmware catalogue** it
knows about is current, so a release with a stale catalogue misleads every user
who runs `update` — not only the ones who upgrade.

---

## See also

- Building each artefact: [Packaging](packaging.md).
- How the version reaches the banner: [Architecture](architecture.md).
- Firmware release lines: [Firmware](firmware.md#versions).

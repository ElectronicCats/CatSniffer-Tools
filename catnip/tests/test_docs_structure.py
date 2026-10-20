"""
test_docs_structure.py
======================
Guardrails for the ``docs/`` tree, added at the end of the documentation
restructure that split the 2 464-line README into ``docs/`` + ``docs/commands/``.

The docs are plain markdown rendered by GitHub -- there is no site generator,
so nothing fails when a page is renamed, a heading someone links to is
reworded, or a new command ships without a page.  The regression is silent and
only a reader hits it.  These tests pin the three invariants the restructure
depends on:

* every CLI group has a page in ``docs/commands/`` (and no page outlives its
  command);
* every published page is reachable from ``README.md``, which is the index;
* every relative link and in-page anchor resolves.

Companion files: ``docs/commands/_template.md`` is the canonical page skeleton,
and ``scripts/dump_cli_tree.py`` dumps the ``--help`` text the pages quote.
"""

import platform
import re
import unicodedata
from pathlib import Path

import pytest

from modules.core.cli import build_cli

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
COMMANDS = DOCS / "commands"

# Commands documented inside another group's page, the way BomberCat folds
# ``identify`` into ``device.md``.  Both are the same workflow as their host.
FOLDED_INTO = {"identify": "devices.md", "update": "flash.md"}

# Not published: the template is a skeleton with placeholder links, and
# ``internal/`` holds work plans that the front page deliberately never indexes.
TEMPLATE = COMMANDS / "_template.md"
INTERNAL = DOCS / "internal"

_ATX = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_HTML_ANCHOR = re.compile(r'<a\s+id="([^"]+)"')
_FENCE = re.compile(r"^\s*(```|~~~)")
# ``[text](target)`` with one level of nested brackets, ignoring an optional title.
_LINK = re.compile(r'\[(?:[^\[\]]|\[[^\]]*\])*\]\(([^)\s]+)(?:\s+"[^"]*")?\)')


def _pages():
    """Every markdown file the tests consider, README included."""
    return sorted(DOCS.rglob("*.md")) + [ROOT / "README.md"]


def _outside_fences(path):
    """Yield ``(lineno, line)`` skipping fenced code blocks.

    Without this, every ``# comment`` in a ``sh`` block reads as a heading and
    every ``pip install foo[bar](baz)`` reads as a link.
    """
    inside = False
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if _FENCE.match(line):
            inside = not inside
            continue
        if not inside:
            yield lineno, line


def _slug(text):
    """GitHub's heading slug: strip markup, lowercase, spaces to hyphens.

    GitHub keeps letters, digits, ``-`` and ``_`` and drops the rest, so
    ``### Step 2: Define `__init__.py``` becomes ``step-2-define-__init__py``.
    """
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*~]", "", text)
    out = []
    for char in text.strip().lower():
        if (
            char.isalnum()
            or char in "-_"
            or unicodedata.category(char).startswith(("L", "N", "M"))
        ):
            out.append(char)
        elif char in " \t":
            out.append("-")
    return "".join(out)


def _anchors(path):
    """Link targets a page offers: slugged headings plus explicit ``<a id>``."""
    found = set()
    for _, line in _outside_fences(path):
        heading = _ATX.match(line)
        if heading:
            slug = base = _slug(heading.group(2))
            suffix = 1
            while slug in found:  # GitHub disambiguates repeats with -1, -2...
                slug, suffix = f"{base}-{suffix}", suffix + 1
            found.add(slug)
        found.update(m.group(1) for m in _HTML_ANCHOR.finditer(line))
    return found


def _relative_links(path):
    """Yield ``(lineno, target)`` for every non-external link on the page."""
    for lineno, line in _outside_fences(path):
        for match in _LINK.finditer(line):
            target = match.group(1)
            if not target.startswith(("http://", "https://", "mailto:", "#!")):
                yield lineno, target


@pytest.mark.unit
def test_every_command_has_a_doc_page():
    """A new command must not ship without its page in ``docs/commands/``."""
    missing = sorted(
        name
        for name in build_cli().commands
        if name not in FOLDED_INTO and not (COMMANDS / f"{name}.md").exists()
    )
    assert not missing, f"commands without docs/commands/<name>.md: {missing}"


@pytest.mark.unit
def test_folded_commands_are_documented_in_their_host_page():
    """``identify`` and ``update`` have no page of their own, so the page that
    absorbed them must actually mention them."""
    for name, host in FOLDED_INTO.items():
        page = COMMANDS / host
        assert page.exists(), f"{host} is missing"
        assert name in page.read_text(
            encoding="utf-8"
        ), f"{host} never mentions {name!r}"


@pytest.mark.unit
@pytest.mark.skipif(
    platform.system() != "Linux",
    reason="vhci and setup-env are only registered on Linux, completion off Windows",
)
def test_no_doc_page_outlives_its_command():
    """A renamed command shows up here as a page nothing maps to."""
    registered = set(build_cli().commands)
    orphans = sorted(
        page.name
        for page in COMMANDS.glob("*.md")
        if page != TEMPLATE and page.stem not in registered
    )
    assert not orphans, f"pages with no matching command: {orphans}"


@pytest.mark.unit
def test_no_published_page_is_unreachable_from_the_readme():
    """``README.md`` is the index: every published page hangs off it, directly
    or through the command pages it links to."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    reachable = set(readme.split())
    for page in COMMANDS.glob("*.md"):
        reachable.update(page.read_text(encoding="utf-8").split())
    unreachable = sorted(
        page.relative_to(ROOT).as_posix()
        for page in DOCS.rglob("*.md")
        if INTERNAL not in page.parents
        and page != TEMPLATE
        and not any(page.name in token for token in reachable)
    )
    assert not unreachable, f"pages nothing links to: {unreachable}"


@pytest.mark.unit
@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.name)
def test_relative_links_resolve(page):
    """Links are always relative, so a moved file breaks them silently."""
    if page == TEMPLATE:
        pytest.skip("the template links to placeholder names on purpose")
    broken = []
    for lineno, target in _relative_links(page):
        path_part = target.partition("#")[0]
        if path_part and not (page.parent / path_part).resolve().exists():
            broken.append(f"{page.name}:{lineno} -> {target}")
    assert not broken, f"links to files that do not exist: {broken}"


@pytest.mark.unit
@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.name)
def test_anchors_resolve(page):
    """Renaming a heading breaks every ``#anchor`` pointed at it."""
    if page == TEMPLATE:
        pytest.skip("the template links to placeholder names on purpose")
    broken = []
    for lineno, target in _relative_links(page):
        path_part, _, fragment = target.partition("#")
        if not fragment:
            continue
        destination = (page.parent / path_part).resolve() if path_part else page
        if destination.suffix != ".md" or not destination.exists():
            continue  # ``file.py#L12`` is a GitHub line link, not an anchor
        if fragment not in _anchors(destination):
            broken.append(f"{page.name}:{lineno} -> {target}")
    assert not broken, f"anchors that do not exist: {broken}"

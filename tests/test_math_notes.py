"""Checks of the notes in math/ (protocol 2026-11-18): links point to existing files, no stray control characters
(a mangled escape like `\\t` turning into a tab), and no symbol registered twice in notation.md."""

import re
from pathlib import Path

import pytest

MATH = Path(__file__).parents[1] / "math"
NOTES = sorted(MATH.glob("*.md"))
LINK = re.compile(r"\]\(([^)#\s]+\.md)(?:#[^)]*)?\)")
SYMBOL = re.compile(r"\$([^$]+)\$")


@pytest.mark.parametrize("note", NOTES, ids=lambda p: p.name)
def test_links_point_to_existing_files(note):
    text = note.read_text(encoding="utf-8")
    missing = sorted({t for t in LINK.findall(text) if "://" not in t and not (note.parent / t).resolve().exists()})
    assert not missing, f"{note.name}: links to missing files {missing}"


@pytest.mark.parametrize("note", NOTES, ids=lambda p: p.name)
def test_no_control_characters(note):
    bad = [(n, line) for n, line in enumerate(note.read_text(encoding="utf-8").splitlines(), 1)
           if any(ord(c) < 32 for c in line)]
    assert not bad, f"{note.name}: control characters (tab, mangled escape) in lines {[n for n, _ in bad]}"


def test_no_symbol_registered_twice():
    # the first column of the notation tables, without the correspondence tables (they repeat ours on purpose)
    text = (MATH / "notation.md").read_text(encoding="utf-8")
    own = text.split("## Correspondence to the sources")[0] + text.split("## Simulation (DES)")[-1]
    seen: dict[str, int] = {}
    for line in own.splitlines():
        if line.startswith("| $"):
            for sym in SYMBOL.findall(line.split("|")[1]):
                seen[sym.strip()] = seen.get(sym.strip(), 0) + 1
    twice = sorted(s for s, n in seen.items() if n > 1)
    assert not twice, f"notation.md: symbols registered more than once: {twice}"

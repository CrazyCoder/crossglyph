"""What version of CrossGlyph this is, and which of two is the greater.

Deliberately free of everything else in the package: `crossglyph --version`
reads this, and it should not pay for a wasm runtime to print a string.
"""
from __future__ import annotations

import importlib.metadata
import re

#: Three numbers and nothing else. [0-9] rather than \d, which matches Arabic
#: and Devanagari digits too -- int() would then happily order a version
#: nobody typed.
_PLAIN = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)")


def installed() -> str:
    """The version this package was installed as.

    uv installs the project into the venv for a checkout and a release alike,
    so the metadata is there either way.
    """
    return importlib.metadata.version("crossglyph")


def parse(text: str) -> tuple[int, int, int] | None:
    """MAJOR.MINOR.PATCH as numbers, or None for anything else.

    None rather than a guess. A version that will not parse is not grounds for
    telling somebody to update, and every caller has a "cannot say" branch
    already.
    """
    found = _PLAIN.fullmatch(text.strip())
    if not found:
        return None
    major, minor, patch = found.groups()
    return int(major), int(minor), int(patch)


def is_newer(candidate: str, than: str) -> bool:
    """True only when both parse and the first is strictly the greater."""
    one, two = parse(candidate), parse(than)
    return one is not None and two is not None and one > two

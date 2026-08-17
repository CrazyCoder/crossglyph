"""Where the tests find a real font, for the few that a synthesized one fails.

Almost everything here builds its own faces with fontsmith. What cannot be
synthesized is a face with real hinting, real kerning and a CFF outline, so
those tests read one off the machine and skip when there is none.

A firmware checkout beside this one carries NotoSans, which covers the
TrueType side. The CFF side needs a font nobody ships, so it is an environment
variable or nothing.
"""
from __future__ import annotations

import os
import pathlib

from crossglyph.render import stamp

#: The firmware's own built-in font sources. Whichever checkout the render
#: core is built from, so the one setup CONTRIBUTING describes -- an engine
#: clone and no working one -- still finds the face. Naming a directory here
#: instead skipped every test that reads it, and a skip says nothing.
FIRMWARE_TTF = (stamp.FIRMWARE / "lib" / "EpdFont" / "builtinFonts"
                / "source" / "NotoSans" / "NotoSans-Regular.ttf")


#: The firmware's Arabic face. Its bismillah ligature is one glyph drawn as a
#: whole phrase, and the only one in practice wide enough to reach the
#: .cpfont per-glyph size cap.
FIRMWARE_ARABIC = (stamp.FIRMWARE / "lib" / "EpdFont" / "builtinFonts"
                   / "source" / "NotoSansArabic" / "NotoSansArabic-Regular.ttf")


def _declared(variable: str) -> pathlib.Path | None:
    named = os.environ.get(variable)
    if not named:
        return None
    path = pathlib.Path(named)
    return path if path.is_file() else None


def truetype() -> pathlib.Path | None:
    """A text face to render whole pages with, or None.

    Named rather than guessed: the tests that use it check line breaking,
    hyphenation and glyph coverage, so they need the face they were written
    against and not merely some font that happens to be installed.
    """
    return _declared("CROSSGLYPH_TEST_FONT")


def noto() -> pathlib.Path | None:
    """The firmware's own NotoSans, or None.

    A fixed face, because what reads it asserts its metrics: NotoSans has a
    negative lineGap, and its declared band exceeds its pitch by a pixel.
    """
    return FIRMWARE_TTF if FIRMWARE_TTF.is_file() else None


def arabic_with_wide_ligature() -> pathlib.Path | None:
    """A face whose U+FDFD is wider than a .cpfont glyph can be, or None."""
    return FIRMWARE_ARABIC if FIRMWARE_ARABIC.is_file() else None


def italic() -> pathlib.Path | None:
    """The italic companion of `truetype`, or None."""
    return _declared("CROSSGLYPH_TEST_ITALIC")


def cff() -> pathlib.Path | None:
    """An OpenType face with a CFF outline and real ligatures, or None.

    Only the Adobe CFF driver applies stem darkening, so the tests that cover
    it cannot use a TrueType face at all. The same face stands in for the
    ligature tests, which need a GSUB table somebody actually designed.
    """
    return _declared("CROSSGLYPH_TEST_OTF")

"""Synthesize a font containing nothing but the fixed-width spaces.

CrossPoint draws nothing for a codepoint no font in the chain supplies, so
U+2006 -- which fb2cng puts after every dialogue dash -- silently disappears in
the many reading faces that omit it. The bundled Noto fallbacks do carry it, but
turning them on to get one space also drags in several thousand symbol, maths
and dingbat glyphs.

This is the narrow version of that fix: a font whose entire cmap is the space
characters, passed as a default fallback. A fallback only supplies codepoints
the primary face lacks, so a font that already has U+2006 keeps its own, and
one that does not gains a real glyph at the correct width rather than a
substitution in the book's text.

The glyphs are empty outlines with an advance width, which is exactly how a
space is represented in any font -- the converter already handles that shape for
U+0020.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

UNITS_PER_EM = 1000

# Advance widths as fractions of an em, from the Unicode names and the values
# typography has used for these since metal type. U+00A0 and U+202F are omitted
# deliberately: ChapterHtmlSlimParser rewrites those two into a plain space
# token before layout, so the device never asks a font for them.
DEFAULT_SPACE_WIDTHS = {
    0x2000: 1 / 2,    # EN QUAD
    0x2001: 1 / 1,    # EM QUAD
    0x2002: 1 / 2,    # EN SPACE
    0x2003: 1 / 1,    # EM SPACE
    0x2004: 1 / 3,    # THREE-PER-EM SPACE
    0x2005: 1 / 4,    # FOUR-PER-EM SPACE
    0x2006: 1 / 6,    # SIX-PER-EM SPACE
    0x2007: 1 / 2,    # FIGURE SPACE, the width of a tabular digit
    0x2008: 1 / 4,    # PUNCTUATION SPACE, the width of a period
    0x2009: 1 / 5,    # THIN SPACE
    0x200A: 1 / 10,   # HAIR SPACE
    0x205F: 2 / 9,    # MEDIUM MATHEMATICAL SPACE, 4/18 em
    0x3000: 1 / 1,    # IDEOGRAPHIC SPACE
}

#: What builds up to now left in the output folder. Nothing writes it any
#: more; a build sweeps it out of the folders that have one, since that folder
#: is what people copy to a card and this was never a font to read with.
STRAY_NAME = ".crossglyph-spaces.ttf"


def cache_name(overrides: dict[int, float] | None = None) -> str:
    """What the face for these widths is called.

    The digest is in the name because the file is kept between builds and the
    widths are a setting: a table edited in all.conf has to produce a different
    file rather than find the old one already there and use it. Twelve hex
    digits, which is a collision nobody will see and a filename that still
    fits on a screen.
    """
    return f"crossglyph-spaces-{spec_digest(overrides)[:12]}.ttf"


def resolve_widths(overrides: dict[int, float] | None = None) -> dict[int, float]:
    """The space table with any per-codepoint overrides applied.

    Only widths are overridable, not membership: a codepoint the reader never
    asks a font for (U+00A0, U+202F) gains nothing from being added, and one
    that is missing from the table is drawn as nothing at all.
    """
    widths = dict(DEFAULT_SPACE_WIDTHS)
    for cp, width in (overrides or {}).items():
        if cp not in widths:
            raise KeyError(f"U+{cp:04X} is not one of the fixed-width spaces")
        widths[cp] = width
    return widths


def spec_digest(overrides: dict[int, float] | None = None) -> str:
    """Hash of the resolved table, for the build stamp.

    The generated file itself is not hashed: fontTools stamps head.created, so
    the bytes differ run to run while the font does not.
    """
    blob = json.dumps({f"{cp:04X}": round(w, 6)
                       for cp, w in sorted(resolve_widths(overrides).items())},
                      sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build(path: pathlib.Path,
          overrides: dict[int, float] | None = None) -> pathlib.Path:
    """Write the space-only font. Requires fontTools."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    space_widths = resolve_widths(overrides)
    names = {cp: f"uni{cp:04X}" for cp in space_widths}
    order = [".notdef"] + [names[cp] for cp in sorted(space_widths)]

    builder = FontBuilder(UNITS_PER_EM, isTTF=True)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({cp: names[cp] for cp in space_widths})

    empty = TTGlyphPen(None).glyph()
    builder.setupGlyf({name: empty for name in order})
    metrics = {".notdef": (UNITS_PER_EM // 2, 0)}
    metrics.update({names[cp]: (round(UNITS_PER_EM * width), 0)
                    for cp, width in space_widths.items()})
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({
        "familyName": "CrossGlyph Spaces",
        "styleName": "Regular",
        "psName": "CrossGlyphSpaces-Regular",
    })
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800,
                     usWinDescent=200)
    builder.setupPost()

    path.parent.mkdir(parents=True, exist_ok=True)
    builder.save(str(path))
    return path

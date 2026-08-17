"""Arabic presentation forms, and the coverage a build of them implies.

FORK: not upstream. CrossPoint shapes Arabic itself, in MiniBidi, and asks the
font for the shaped codepoint rather than the letter that was typed: do_shape()
rewrites every letter in the range shapetypes[] covers into an Arabic
Presentation Forms-B codepoint through shape_form(), and turns a lam followed
by an alef into one of the four lam-alef ligatures. There is no GSUB on the
device, so a face that carries only the letters has nothing at the codepoint
the reader looks up, and every word comes out blank.

The table below is derived from unicodedata rather than transcribed from the
firmware, so it cannot drift by a typo. tests/test_arabic.py asserts the two
agree against shapetypes[] itself.
"""
from __future__ import annotations

import functools
import typing
import unicodedata
from collections.abc import Iterable

#: The range shapetypes[] covers, mirrored from SHAPE_FIRST and SHAPE_LAST.
SHAPE_FIRST, SHAPE_LAST = 0x0621, 0x064A

#: Form offsets, in the order shape_form() adds them to a letter's isolated
#: codepoint. Unicode lays the Presentation Forms-B block out in the same
#: order, which is what makes the table below derivable rather than typed out.
ISOLATED, FINAL, INITIAL, MEDIAL = 0, 1, 2, 3

_DECOMPOSITION_FORMS = {"<isolated>": ISOLATED, "<final>": FINAL,
                        "<initial>": INITIAL, "<medial>": MEDIAL}

#: The letter a lam-alef ligature needs in front of it.
LAM = 0x0644


def _derive_forms() -> dict[tuple[int, int], int]:
    """{(letter, form): presentation codepoint}, read out of Unicode itself."""
    table: dict[tuple[int, int], int] = {}
    for code in range(0xFE70, 0xFF00):
        parts = unicodedata.decomposition(chr(code)).split()
        if len(parts) != 2 or parts[0] not in _DECOMPOSITION_FORMS:
            continue
        base = int(parts[1], 16)
        if SHAPE_FIRST <= base <= SHAPE_LAST:
            table[(base, _DECOMPOSITION_FORMS[parts[0]])] = code
    return table


PRESENTATION_FORMS = _derive_forms()

#: The lam-alef ligatures, which minibidi.c hardcodes rather than deriving.
#: Keyed by the alef that follows the lam, and by whether the pair is final.
#: Unicode decomposes these to two letters, so they cannot come out of
#: _derive_forms.
LAM_ALEF = {
    (0x0622, ISOLATED): 0xFEF5, (0x0622, FINAL): 0xFEF6,
    (0x0623, ISOLATED): 0xFEF7, (0x0623, FINAL): 0xFEF8,
    (0x0625, ISOLATED): 0xFEF9, (0x0625, FINAL): 0xFEFA,
    (0x0627, ISOLATED): 0xFEFB, (0x0627, FINAL): 0xFEFC,
}


def forms_for(codepoints: Iterable[int]) -> set[int]:
    """Every codepoint the device can ask for, given these letters.

    A lam-alef ligature needs both halves present, because the device only
    forms one where the text has a lam followed by that alef.
    """
    letters = set(codepoints)
    asked = {form for (base, _), form in PRESENTATION_FORMS.items()
             if base in letters}
    if LAM in letters:
        asked |= {form for (alef, _), form in LAM_ALEF.items()
                  if alef in letters}
    return asked


def implied_coverage(intervals) -> tuple[tuple[int, int], ...]:
    """The same coverage, plus the shapes those letters will be asked by.

    An implication rather than a guess: the device converts a letter before it
    draws it, so a build holding the letters and not their shapes has nothing
    it can draw. Nothing is added for coverage with no Arabic in it.
    """
    covered = {cp for start, end in intervals for cp in range(start, end + 1)}
    asked = forms_for(covered) - covered
    if not asked:
        return tuple(tuple(pair) for pair in intervals)

    merged: list[tuple[int, int]] = []
    for code in sorted(covered | asked):
        if merged and code == merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], code)
        else:
            merged.append((code, code))
    return tuple(merged)


# --- resolving a face's own joining rules ---------------------------------

#: Forces a joining context without contributing a letter of its own.
ZWJ = "‍"

#: The string that puts a letter in each joining context, and which character
#: of it the letter is. A zero-width joiner on a side makes the shaper treat
#: that side as connected, which is how a form is asked for out of context.
_CONTEXTS = {
    ISOLATED: ("{c}", 0),
    FINAL: (ZWJ + "{c}", 1),
    INITIAL: ("{c}" + ZWJ, 0),
    MEDIAL: (ZWJ + "{c}" + ZWJ, 1),
}


class GlyphRun(typing.NamedTuple):
    """One shaped form: the glyphs that draw it, and what it advances by.

    Offsets and advance are in font units, so a run is independent of the size
    being rasterized and can be resolved once per face rather than once per
    size.
    """
    pieces: tuple[tuple[int, int, int], ...]
    advance: int


def _shape(blob, upem, text):
    """[(glyph, cluster, x_offset, y_offset, x_advance)], in font units."""
    import uharfbuzz as hb

    font = hb.Font(hb.Face(blob))
    font.scale = (upem, upem)
    buffer = hb.Buffer()
    buffer.add_str(text)
    buffer.guess_segment_properties()
    hb.shape(font, buffer)
    return [(info.codepoint, info.cluster, pos.x_offset, pos.y_offset,
             pos.x_advance)
            for info, pos in zip(buffer.glyph_infos, buffer.glyph_positions)]


def _run(shaped) -> GlyphRun:
    """Shaped output as one run, each glyph placed past the one before it.

    Arabic shapes right to left, but HarfBuzz reports a run in visual order,
    so accumulating the advances left to right lays the pieces out as they are
    drawn.
    """
    pieces, advance = [], 0
    for glyph, _cluster, x_offset, y_offset, x_advance in shaped:
        pieces.append((glyph, advance + x_offset, y_offset))
        advance += x_advance
    return GlyphRun(tuple(pieces), advance)


@functools.lru_cache(maxsize=8)
def presentation_forms(font_path) -> dict[int, GlyphRun]:
    """{codepoint the device asks for: the run of glyphs that draws it}.

    Only forms the face does not already carry are worth resolving, so a face
    that cmaps the presentation forms outright returns nothing and pays one
    cmap walk for the question. A face with no Arabic pays the same and no
    more.
    """
    import uharfbuzz as hb
    from fontTools.ttLib import TTFont

    path = str(font_path)
    with TTFont(path, fontNumber=0, lazy=True) as ttf:
        cmap = set(ttf.getBestCmap() or {})
        upem = ttf["head"].unitsPerEm
    if not any(SHAPE_FIRST <= code <= SHAPE_LAST for code in cmap):
        return {}

    blob = hb.Blob.from_file_path(path)
    # A joiner draws something in most faces, usually a space, and HarfBuzz
    # merges its cluster into the letter's. So it has to be dropped by which
    # glyph it is rather than by where it sits.
    joiner = {glyph for glyph, *_ in _shape(blob, upem, ZWJ)}

    resolved: dict[int, GlyphRun] = {}
    for (base, form), code in PRESENTATION_FORMS.items():
        if base not in cmap or code in cmap:
            continue
        template, at = _CONTEXTS[form]
        shaped = [piece
                  for piece in _shape(blob, upem, template.format(c=chr(base)))
                  if piece[1] == at and piece[0] not in joiner]
        if not shaped:
            continue
        resolved[code] = _run(shaped)

    # A lam followed by an alef is a ligature the device asks for by its own
    # codepoint, so it has to be resolved as a pair rather than a letter. A
    # face with a real lam-alef rule shapes it to one glyph; a face without
    # gives back the two joined halves, which compose to the same picture.
    for (alef, form), code in LAM_ALEF.items():
        if LAM not in cmap or alef not in cmap or code in cmap:
            continue
        prefix = ZWJ if form == FINAL else ""
        shaped = [piece
                  for piece in _shape(blob, upem,
                                      prefix + chr(LAM) + chr(alef))
                  if piece[0] not in joiner]
        if shaped:
            resolved[code] = _run(shaped)
    return resolved

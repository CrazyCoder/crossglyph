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

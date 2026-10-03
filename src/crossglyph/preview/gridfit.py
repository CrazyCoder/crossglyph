"""Grid Fit: how cleanly the straight strokes of a page sit on the pixel grid.

The device paints four levels. A stem that lands on whole pixels is black to
its edges; one that lands between them carries a column of grey beside it,
which reads as blur on an e-ink panel. This module counts that grey, using the
same bytes the device would get: it reads the glyph bitmaps out of a built
.cpfont rather than rasterizing anything itself.

A straight feature is a cross-section that repeats unchanged on at least
MINRUN consecutive rows (a vertical stem, judged across X) or columns (a
horizontal bar, judged across Y). A cross-section is one run of non-white
pixels, at its exact position and with its exact levels. A curve changes from
one row to the next, so it adds nothing either way. Each repeated
cross-section adds its two edges to the count and its grey pixels to the
defect, both times the length of the run.

The score is for the text on the page, weighted by how often each letter
appears in each style. Measured against whole books, a page of ordinary prose
picks the same render size as the book does, while a fixed set of probe
letters or an unweighted glyph set often does not. Only letters count: a line
of digits is a column of perfect stems that books rarely have.

The idea of choosing a render size by stem fringe comes from cpfont-editor
(MIT). This measure is written from scratch.
"""
from __future__ import annotations

import collections
import dataclasses
import struct
import unicodedata
from collections.abc import Iterable, Mapping, Sequence

from crossglyph.fontconf import size_label
from crossglyph.preview import markup

#: Bump when the measure or its constants change, so two scores from
#: different rulers are never compared.
VERSION = 1

#: Rows or columns a cross-section has to repeat for to count as straight.
MINRUN = 4
#: Weight of a light-grey (level 1) and a dark-grey (level 2) edge pixel. A
#: light pixel beside a stem is the blur; a dark one mostly reads as a stem
#: one pixel wider.
LIGHT_W = 1.0
DARK_W = 0.5
#: The loss per edge pixel at which the score reaches 0.
BAD = 1.0
#: Fewer letters than this and the score is marked as unsure. Prose agreed
#: with whole books from about 300 characters, and better from 600.
MIN_LETTERS = 300

_MAGIC = b"CPFONT\x00\x00"
_HEADER_SIZE = 32
_ENTRY_SIZE = 32
_INTERVAL = struct.Struct("<III")
_GLYPH = struct.Struct("<BBHhhH2xI")


@dataclasses.dataclass
class Evidence:
    """Straight-edge length, and the grey pixels found along it."""
    edge: float = 0.0
    light: float = 0.0
    dark: float = 0.0

    def add(self, other: Evidence, weight: float = 1.0) -> None:
        self.edge += other.edge * weight
        self.light += other.light * weight
        self.dark += other.dark * weight

    @property
    def fit(self) -> float | None:
        """0 to 100, or None when there is no straight edge to judge."""
        if not self.edge:
            return None
        loss = (LIGHT_W * self.light + DARK_W * self.dark) / self.edge
        return 100.0 * max(0.0, min(1.0, 1.0 - loss / BAD))


@dataclasses.dataclass
class GlyphEvidence:
    x: Evidence
    y: Evidence


def _segments(line: bytes) -> Iterable[tuple[int, bytes]]:
    x, n = 0, len(line)
    while x < n:
        if not line[x]:
            x += 1
            continue
        start = x
        while x < n and line[x]:
            x += 1
        yield start, line[start:x]


def straight(lines: Sequence[bytes]) -> Evidence:
    """Evidence from the cross-sections that repeat across consecutive lines."""
    ev = Evidence()

    def close(pattern: bytes, length: int) -> None:
        if length >= MINRUN:
            ev.edge += 2 * length
            ev.light += pattern.count(1) * length
            ev.dark += pattern.count(2) * length

    runs: dict[tuple[int, bytes], int] = {}
    for line in lines:
        seen = {key: runs.get(key, 0) + 1 for key in _segments(line)}
        for key, length in runs.items():
            if key not in seen:
                close(key[1], length)
        runs = seen
    for key, length in runs.items():
        close(key[1], length)
    return ev


def decode(width: int, height: int, packed: bytes) -> list[bytes]:
    """A glyph's 2-bit stream as rows of levels 0 to 3. Four pixels a byte,
    first pixel in the high bits, and rows run on without padding."""
    rows = []
    for y in range(height):
        base = y * width
        rows.append(bytes((packed[i >> 2] >> (6 - 2 * (i & 3))) & 3
                          for i in range(base, base + width)))
    return rows


def glyph_evidence(width: int, height: int, packed: bytes) -> GlyphEvidence:
    rows = decode(width, height, packed)
    columns = [bytes(row[x] for row in rows) for x in range(width)]
    return GlyphEvidence(straight(rows), straight(columns))


Glyph = tuple[int, int, bytes]


def read_glyphs(font: bytes) -> dict[int, dict[int, Glyph]]:
    """{style: {codepoint: (width, height, packed)}} from a .cpfont.

    Each style's sections follow its dataOffset in a fixed order: intervals,
    glyph records, the two kerning class tables, the kerning matrix,
    ligatures, then the bitmaps. Every length comes from the counts in the
    style's entry, which is how the device finds them too.
    """
    if len(font) < _HEADER_SIZE or font[:8] != _MAGIC:
        return {}
    style_count = font[12]
    out: dict[int, dict[int, Glyph]] = {}
    for n in range(style_count):
        entry = _HEADER_SIZE + n * _ENTRY_SIZE
        (style, intervals, glyphs, _advance, _asc, _desc, kern_left, kern_right,
         left_classes, right_classes, ligatures, offset) = struct.unpack_from(
            "<B3xIIBhhHHBBBI", font, entry)
        glyph_table = offset + intervals * _INTERVAL.size
        bitmaps = (glyph_table + glyphs * _GLYPH.size
                   + (kern_left + kern_right) * 3
                   + left_classes * right_classes + ligatures * 8)
        table: dict[int, Glyph] = {}
        for i in range(intervals):
            start, end, first = _INTERVAL.unpack_from(
                font, offset + i * _INTERVAL.size)
            for cp in range(start, end + 1):
                (width, height, _adv, _left, _top, length,
                 data) = _GLYPH.unpack_from(
                    font, glyph_table + (first + cp - start) * _GLYPH.size)
                table[cp] = (width, height,
                             font[bitmaps + data:bitmaps + data + length])
        out[style] = table
    return out


def letter_weights(text: str, styles: Iterable[int]) -> dict[int, collections.Counter]:
    """How often each letter appears in each style on the page.

    `styles` are the ones the font carries. A word in a style it lacks is
    drawn with the regular face on the device, so it counts there.
    """
    have = set(styles)
    plain, word_styles = markup.parse(text)
    out: dict[int, collections.Counter] = {}
    for word, style in zip(plain.split(), word_styles):
        letters = [ord(c) for c in word if unicodedata.category(c)[0] == "L"]
        if letters:
            out.setdefault(style if style in have else 0,
                           collections.Counter()).update(letters)
    return out


@dataclasses.dataclass(frozen=True)
class Score:
    fit: float | None
    x: float | None
    y: float | None
    #: Per style on the page.
    styles: Mapping[int, float | None]
    letters: int
    confident: bool
    version: int = VERSION


def score(font: bytes, text: str, *, mono: bool = False) -> Score:
    """Grid Fit of `text` drawn with `font`.

    Under mono there is no grey to find, which says nothing about alignment,
    so there is no score.
    """
    glyphs = read_glyphs(font)
    weights = letter_weights(text, glyphs)
    letters = sum(sum(counter.values()) for counter in weights.values())
    confident = letters >= MIN_LETTERS
    if mono:
        return Score(None, None, None, {}, letters, confident)

    cache: dict[tuple[int, int], GlyphEvidence] = {}
    x, y = Evidence(), Evidence()
    styles = {}
    for style, counter in weights.items():
        sx, sy = Evidence(), Evidence()
        for cp, count in counter.items():
            glyph = glyphs[style].get(cp)
            if glyph is None or not glyph[0] or not glyph[1]:
                continue
            if (style, cp) not in cache:
                cache[style, cp] = glyph_evidence(*glyph)
            ev = cache[style, cp]
            sx.add(ev.x, count)
            sy.add(ev.y, count)
        styles[style] = _pooled(sx, sy).fit
        x.add(sx)
        y.add(sy)
    return Score(_pooled(x, y).fit, x.fit, y.fit, styles, letters, confident)


# --- choosing sizes -------------------------------------------------------

#: Render sizes tried for a label, as offsets from it. Every one of them
#: rounds to the label (fontconf.size_label is half up), so the number in the
#: reader's Font Size list stays what it was.
OFFSETS = (-0.5, -0.25, 0.0, 0.25)
#: Fits within this many points of the best count as a tie.
TIE = 1.0
#: The size knob's range, which a range of sizes has to stay inside.
SIZE_MIN, SIZE_MAX = 6, 40
#: Four fills the first row of size boxes, eight fills both.
COUNTS = (4, 8)


def candidates(label: int) -> list[float]:
    return [label + offset for offset in OFFSETS]


def targets(*, sizes: Sequence[float] = (), low: int | None = None,
            high: int | None = None, count: int | None = None,
            ) -> list[tuple[float, int]]:
    """(size now, label) for each size to fit.

    Either the sizes the family has, each keeping its own label, or `count`
    whole sizes spread evenly from `low` to `high`, which have no size of
    their own yet and start at their label.
    """
    if low is None:
        return [(size, size_label(size)) for size in sizes]
    if count not in COUNTS:
        raise ValueError(f"the count is {' or '.join(map(str, COUNTS))} sizes")
    if high is None or not SIZE_MIN <= low < high <= SIZE_MAX:
        raise ValueError(f"a range runs from a smaller size to a larger one, "
                         f"between {SIZE_MIN} and {SIZE_MAX}")
    labels = [int(low + i * (high - low) / (count - 1) + 0.5) for i in range(count)]
    if len(set(labels)) < count:
        raise ValueError(f"{low} to {high} is too narrow for {count} sizes: "
                         f"it holds {high - low + 1}")
    return [(label, label) for label in labels]


def pick(label: int, fits: Mapping[float, float | None]) -> float | None:
    """The best-fitting size, or None when no candidate could be judged.

    A near tie goes to the size nearest the label, then to the smaller one: a
    point of score is not worth moving the size for.
    """
    judged = {size: fit for size, fit in fits.items() if fit is not None}
    if not judged:
        return None
    best = max(judged.values())
    near = [size for size, fit in judged.items() if fit >= best - TIE]
    return min(near, key=lambda size: (abs(size - label), size))


def _pooled(x: Evidence, y: Evidence) -> Evidence:
    both = Evidence()
    both.add(x)
    both.add(y)
    return both

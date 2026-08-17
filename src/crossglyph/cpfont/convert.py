#!/usr/bin/env python3
"""Generate .cpfont binary files for SD card font loading.

Outputs binary .cpfont files containing glyph metadata and uncompressed
2-bit bitmaps, matching the EpdFontData/EpdGlyph/EpdUnicodeInterval struct
layout on the ESP32-C3 (little-endian, RISC-V).

Usage:
    # Single file with specific presets
    python fontconvert_sdcard.py \\
      --intervals latin-ext,greek,cyrillic \\
      --size 14 --style regular \\
      NotoSans-Regular.ttf \\
      -o NotoSansExt_14.cpfont

    # All 4 sizes at once
    python fontconvert_sdcard.py \\
      --intervals cjk-sc \\
      --sizes 12,14,16,18 --style regular \\
      NotoSansCJKsc-Regular.otf \\
      --output-dir NotoSansCJK/

"""

from __future__ import annotations

import functools
import struct
import sys
import os
import re
import math
import argparse
import dataclasses
from collections import namedtuple

from .arabic import implied_coverage, presentation_forms
from .tuning import Tuning
from .version import CPFONT_VERSION

# --- Unicode interval presets ---

# ASCII and general punctuation, and nothing else -- no Latin-1, no Greek, no
# Cyrillic. A build restricted to "base" draws *nothing* for non-Latin text, so
# a test that renders Cyrillic through it passes while producing a blank page.
# Reach for "cyrillic" or "default" whenever the sample text is not ASCII.
BASE_INTERVALS = [(0x0000, 0x007F), (0x2000, 0x206F)]

DEFAULT_INTERVALS = [(0x0080, 0x00FF), (0x0100, 0x017F),
                     (0x01A0, 0x01A1), (0x01AF, 0x01B0), (0x01C4, 0x021F),
                     (0x0300, 0x036F), (0x0400, 0x04FF), (0x1EA0, 0x1EF9),
                     (0x20A0, 0x20CF), (0x2070, 0x209F), (0x2190, 0x21FF),
                     (0x2200, 0x22FF), (0xFB00, 0xFB06)]

INTERVAL_PRESETS = {
    # Minimum readable coverage. This is included in every generated .cpfont.
    "base":        BASE_INTERVALS,
    # Broad CrossPoint-style reading coverage. Users can add this on top of base.
    "default":     DEFAULT_INTERVALS,
    "latin-ext":   [(0x0020, 0x007E), (0x0080, 0x00FF), (0x0100, 0x024F),
                    (0x1E00, 0x1EFF), (0x2000, 0x206F), (0xFB00, 0xFB06)],
    "greek":       [(0x0370, 0x03FF), (0x1F00, 0x1FFF)],
    "cyrillic":    [(0x0400, 0x04FF), (0x0500, 0x052F)],
    "hebrew":      [(0x0590, 0x05FF), (0xFB1D, 0xFB4F)],
    # The Forms-A range runs to the end of the block. The honorific ligatures
    # at its top are ordinary in Arabic prose and small at every size; what
    # made the range stop short was their neighbour U+FDFD, one glyph drawn as
    # a whole phrase, which is handled at GLYPH_SIZE_CAP instead.
    "arabic":      [(0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)],
    "georgian":    [(0x10A0, 0x10FF), (0x2D00, 0x2D2F)],
    "armenian":    [(0x0530, 0x058F)],
    "ethiopic":    [(0x1200, 0x137F), (0x1380, 0x139F), (0x2D80, 0x2DDF)],
    "vietnamese":  [(0x01A0, 0x01B0), (0x1EA0, 0x1EF9)],
    "cjk-sc":      [(0x3000, 0x303F), (0x4E00, 0x9FFF),
                    (0xF900, 0xFAFF), (0xFF00, 0xFFEF)],
    # Traditional Chinese: cjk-sc plus Bopomofo (zhuyin) and CJK Extension A,
    # which TC texts draw on noticeably more than SC.
    "cjk-tc":      [(0x3000, 0x303F), (0x3100, 0x312F), (0x31A0, 0x31BF),
                    (0x3400, 0x4DBF), (0x4E00, 0x9FFF),
                    (0xF900, 0xFAFF), (0xFF00, 0xFFEF)],
    "cjk-jp":      [(0x3000, 0x303F), (0x3040, 0x309F), (0x30A0, 0x30FF),
                    (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0xFF00, 0xFFEF)],
    "hangul":      [(0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x3130, 0x318F)],
    "cherokee":    [(0x13A0, 0x13FF), (0xAB70, 0xABBF)],
    "tifinagh":    [(0x2D30, 0x2D7F)],
    "thai":        [(0x0E00, 0x0E7F)],
    # Bengali block plus the shared Devanagari danda/double-danda punctuation.
    "bengali":     [(0x0964, 0x0965), (0x0980, 0x09FF)],
    # Symbol blocks commonly seen in scifi/popsci/literary fiction.

    "symbols":     [(0x2070, 0x209F), (0x20A0, 0x20CF), (0x2150, 0x218F),
                    (0x2190, 0x21FF), (0x2200, 0x22FF), (0x2500, 0x257F),
                    (0x25A0, 0x25FF), (0x2600, 0x26FF), (0x2700, 0x27BF)],
    # Composite preset for English-language literary fiction including scifi/popsci.
    # Includes default coverage so selecting reading preserves the old behavior.
    # Greek for physics terms, math operators, geometric shapes, uncommon
    # dialogue punctuation, CJK quote marks, miscellaneous symbols (♪♫♬), dingbats.
    "reading":     DEFAULT_INTERVALS + [
                    (0x0180, 0x019F), (0x01A2, 0x01AE), (0x01B1, 0x01C3),
                    (0x0220, 0x024F), (0x0370, 0x03FF), (0x1E00, 0x1E9F),
                    (0x1EFA, 0x1EFF), (0x2150, 0x218F), (0x2500, 0x257F),
                    (0x25A0, 0x25FF), (0x2600, 0x26FF), (0x2700, 0x27BF),
                    (0x2900, 0x29FF), (0x2E00, 0x2E7F), (0x3000, 0x303F)],

    # IPA characters
    "ipa-chars":    [(0x0250, 0x02AF), (0x02B0, 0x02FF)],
}

# Every generated .cpfont gets this minimum first; user-selected presets and
# custom ranges are additive.
BASE_INTERVAL_PRESETS = ("base",)

# Regex for parsing unnamed hex range intervals: (0xSTART-0xEND)
_HEX_RANGE_PATTERN = re.compile(r'^\(0x([0-9a-fA-F]+)-0x([0-9a-fA-F]+)\)$')

def parse_hex_range(s: str) -> tuple[int, int] | None:
    match = _HEX_RANGE_PATTERN.fullmatch(s)
    if not match:
        return None

    start_hex, end_hex = match.groups()
    start, end = int(start_hex, 16), int(end_hex, 16)

    # Validating Unicode range bounds.
    if start > end or end > 0x10FFFF:
        return None
    return start, end


def resolve_intervals(preset_str):
    """Resolve comma-separated preset names into a merged, sorted, deduplicated interval list."""
    all_intervals = []
    parsed_tokens = [(name, None) for name in BASE_INTERVAL_PRESETS]

    for name in [name.strip().lower() for name in preset_str.split(",") if name.strip()]:
        unnamed_interval = parse_hex_range(name)
        if name not in INTERVAL_PRESETS and unnamed_interval is None:
            print(f"Error: unknown interval preset '{name}'", file=sys.stderr)
            print(f"Available presets: {', '.join(sorted(INTERVAL_PRESETS.keys()))}", file=sys.stderr)
            print("You can also specify unnamed hex ranges like (0x2100-0x214F)", file=sys.stderr)
            sys.exit(1)
        parsed_tokens.append((name, unnamed_interval))

    for name, unnamed_interval in parsed_tokens:
        name = name.strip().lower()
        if unnamed_interval is not None:
            all_intervals.append(unnamed_interval)
        else:
            all_intervals.extend(INTERVAL_PRESETS[name])

    # Always add replacement character
    all_intervals.append((0xFFFD, 0xFFFD))
    return merge_intervals(all_intervals)


def merge_intervals(intervals):
    """Sorted, with overlapping and adjacent runs joined into one.

    FORK: split out of resolve_intervals so every path into a build can be
    held to it. The .cpfont interval table is searched on the assumption that
    it ascends, so an unsorted one packs without complaint and produces a file
    the reader rejects with nothing to say about why.
    """
    merged = []
    for start, end in sorted(tuple(pair) for pair in intervals):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


class RasterGlyph(namedtuple("RasterGlyph",
                             "width rows pitch buffer pixel_mode "
                             "left top advance")):
    """One rendered glyph, however many outlines went into it.

    FORK: a synthesized Arabic form can be several glyphs with offsets, so the
    rasterizing loop cannot read a single FreeType slot. Both paths build one
    of these instead. The bitmap field names match FT_Bitmap's on purpose, so
    the loop that reads them did not have to change.
    """


def raster_from_slot(slot):
    """FORK: one FreeType glyph slot, as the loop wants to read it."""
    bitmap = slot.bitmap
    return RasterGlyph(bitmap.width, bitmap.rows, bitmap.pitch,
                       bytes(bitmap.buffer), bitmap.pixel_mode,
                       slot.bitmap_left, slot.bitmap_top,
                       slot.linearHoriAdvance)


def scale_units(value, face):
    """FORK: font units to 26.6 pixels, the way FreeType scales them itself."""
    return (value * face.size.x_scale + 0x8000) >> 16


def scale_advance(value, face):
    """FORK: font units to 16.16 pixels, the unit linearHoriAdvance is in.

    x_scale maps font units to 26.6, so 16.16 is the same product shifted ten
    places less. A composed glyph reports its advance the way a slot does,
    because the packer downstream reads only the one field.
    """
    return (value * face.size.x_scale) >> 6


def _coverage_rows(piece):
    """FORK: a glyph's coverage as one byte per pixel, however it was rendered.

    A mono render is one bit per pixel, most significant first, and the pitch
    can be negative when the rows are stored bottom-up. Both have to be undone
    before two glyphs can be blended.
    """
    import freetype

    rows = []
    for y in range(piece.rows):
        start = (y if piece.pitch >= 0 else piece.rows - 1 - y) * abs(piece.pitch)
        if piece.pixel_mode == freetype.FT_PIXEL_MODE_MONO:
            rows.append([255 if piece.buffer[start + (x >> 3)] & (0x80 >> (x & 7))
                         else 0 for x in range(piece.width)])
        else:
            rows.append(list(piece.buffer[start:start + piece.width]))
    return rows


def compose_raster(drawn, face, advance):
    """FORK: blend rendered pieces at their shaped offsets into one bitmap.

    Offsets arrive in font units and land on whole pixels, which is as fine as
    the target can be: the device places one bitmap per codepoint and has no
    subpixel positioning to lose.

    The result is reported as greyscale even when the pieces were rendered
    mono, because blending needs a byte per pixel. The values are still only 0
    and 255, so the thresholds downstream reach the same two levels they would
    have reached from the bits.
    """
    import freetype

    placed = []
    for piece, x_offset, y_offset in drawn:
        if not (piece.width and piece.rows):
            continue
        placed.append((piece,
                       piece.left + (scale_units(x_offset, face) >> 6),
                       piece.top + (scale_units(y_offset, face) >> 6)))
    if not placed:
        return RasterGlyph(0, 0, 0, b"", freetype.FT_PIXEL_MODE_GRAY, 0, 0,
                           advance)

    left = min(x for _, x, _ in placed)
    top = max(y for _, _, y in placed)
    right = max(x + piece.width for piece, x, _ in placed)
    bottom = min(y - piece.rows for piece, _, y in placed)
    width, rows = right - left, top - bottom

    canvas = bytearray(width * rows)
    for piece, x, y in placed:
        for row_index, row in enumerate(_coverage_rows(piece)):
            start = (top - y + row_index) * width + (x - left)
            for column, value in enumerate(row):
                if value > canvas[start + column]:
                    canvas[start + column] = value
    return RasterGlyph(width, rows, width, bytes(canvas),
                       freetype.FT_PIXEL_MODE_GRAY, left, top, advance)


def resolve_style_coverage(primary_face, fallback_faces, intervals,
                           synthesized=()):
    """Resolve intervals against primary coverage, then optional fallback chain.

    Returns (validated_intervals, codepoint_sources, source_codepoints).
    codepoint_sources maps codepoint -> source index (0 = primary, 1+ = fallbacks).
    Each fallback face only fills holes left by earlier faces in the chain.

    FORK: `synthesized` is one set of codepoints per source face, primary
    first, holding what that face draws through its own shaping rather than
    through a cmap entry. CrossPoint asks for shaped Arabic codepoints, and a
    face that joins through GSUB has no cmap entry at any of them, so without
    this every form is dropped here before it can be drawn. Per face rather
    than for the primary alone, or an Arabic family named as a fallback would
    draw a replacement box where the primary has no Arabic at all. See
    arabic.presentation_forms.
    """
    validated_intervals = []
    codepoint_sources = {}
    source_codepoints = [set()]
    source_codepoints.extend(set() for _ in fallback_faces)
    faces = [primary_face, *fallback_faces]
    shaped = list(synthesized) + [frozenset()] * (len(faces) - len(synthesized))

    for i_start, i_end in intervals:
        run_start = None
        run_end = None
        for code_point in range(i_start, i_end + 1):
            source_index = None
            for idx, source_face in enumerate(faces):
                if source_face is None:
                    continue
                if (code_point in shaped[idx]
                        or source_face.get_char_index(code_point) > 0):
                    source_index = idx
                    break

            if source_index is None:
                if run_start is not None:
                    validated_intervals.append((run_start, run_end))
                    run_start = None
                    run_end = None
                continue

            source_codepoints[source_index].add(code_point)
            codepoint_sources[code_point] = source_index

            if run_start is None:
                run_start = code_point
            run_end = code_point

        if run_start is not None:
            validated_intervals.append((run_start, run_end))

    return validated_intervals, codepoint_sources, source_codepoints


GlyphProps = namedtuple("GlyphProps", [
    "width", "height", "advance_x", "left", "top", "data_length", "data_offset", "code_point"
])

# Intermediate data from rasterizing one font style
StyleRasterData = namedtuple("StyleRasterData", [
    "style_id",                # 0=regular, 1=bold, 2=italic, 3=bolditalic
    "intervals",               # validated intervals [(start, end), ...]
    "all_glyphs",              # [(GlyphProps, packed_bytes), ...]
    "total_bitmap_size",       # int
    "advanceY", "ascender", "descender",
    "kern_left_classes", "kern_right_classes", "kern_matrix",
    "kern_left_class_count", "kern_right_class_count",
    "ligature_pairs",
])


def norm_floor(val):
    return int(math.floor(val / (1 << 6)))


def norm_ceil(val):
    return int(math.ceil(val / (1 << 6)))


# Fixed-point (fp4) output conventions (must match EpdFontData.h / fp4 namespace):
#
#   advanceX    12.4 unsigned fixed-point (uint16_t).
#               12 integer bits, 4 fractional bits = 1/16-pixel resolution.
#               Encoded from FreeType's 16.16 linearHoriAdvance.
#
#   kernMatrix  4.4 signed fixed-point (int8_t).
#               4 integer bits, 4 fractional bits = 1/16-pixel resolution.
#               Range: -8.0 to +7.9375 pixels.
#               Encoded from font design-unit kerning values.
#
# Both share 4 fractional bits so the renderer can add them directly into a
# single int32_t accumulator and defer rounding until pixel placement.

def fp4_from_ft16_16(val):
    """Convert FreeType 16.16 fixed-point to 12.4 fixed-point with rounding."""
    return (val + (1 << 11)) >> 12

def fp4_from_design_units(du, scale):
    """Convert a font design-unit value to 4.4 fixed-point, clamped to int8_t.

    Multiplies by scale (ppem / units_per_em) and shifts into 4 fractional
    bits.  The result is rounded to nearest and clamped to [-128, 127].
    """
    raw = round(du * scale * 16)
    return max(-128, min(127, raw))


# Standard Unicode ligature codepoints for known input sequences.
# Used as a fallback when the GSUB substitute glyph has no cmap entry.
STANDARD_LIGATURE_MAP = {
    (0x66, 0x66):       0xFB00,  # ff
    (0x66, 0x69):       0xFB01,  # fi
    (0x66, 0x6C):       0xFB02,  # fl
    (0x66, 0x66, 0x69): 0xFB03,  # ffi
    (0x66, 0x66, 0x6C): 0xFB04,  # ffl
    (0x17F, 0x74):      0xFB05,  # long-s + t
    (0x73, 0x74):       0xFB06,  # st
}


def _extract_pairpos_subtable(subtable, glyph_to_cp, raw_kern):
    """Extract kerning from a PairPos subtable (Format 1 or 2)."""
    if subtable.Format == 1:
        # Individual pairs
        for i, coverage_glyph in enumerate(subtable.Coverage.glyphs):
            if coverage_glyph not in glyph_to_cp:
                continue
            pair_set = subtable.PairSet[i]
            for pvr in pair_set.PairValueRecord:
                if pvr.SecondGlyph not in glyph_to_cp:
                    continue
                xa = 0
                if hasattr(pvr, 'Value1') and pvr.Value1:
                    xa = getattr(pvr.Value1, 'XAdvance', 0) or 0
                if xa != 0:
                    key = (coverage_glyph, pvr.SecondGlyph)
                    raw_kern[key] = raw_kern.get(key, 0) + xa
    elif subtable.Format == 2:
        # Class-based pairs — iterate by class, not by glyph, to avoid
        # O(glyphs²) explosion for CJK fonts with many requested glyphs.
        class_def1 = subtable.ClassDef1.classDefs if subtable.ClassDef1 else {}
        class_def2 = subtable.ClassDef2.classDefs if subtable.ClassDef2 else {}
        coverage_set = set(subtable.Coverage.glyphs)

        # Build reverse mappings: class_id -> list of glyph names
        left_by_class = {}   # only glyphs in coverage AND glyph_to_cp
        for glyph in glyph_to_cp:
            if glyph not in coverage_set:
                continue
            c1 = class_def1.get(glyph, 0)
            left_by_class.setdefault(c1, []).append(glyph)

        right_by_class = {}  # all glyphs in glyph_to_cp
        for glyph in glyph_to_cp:
            c2 = class_def2.get(glyph, 0)
            right_by_class.setdefault(c2, []).append(glyph)

        # Iterate class pairs (typically << glyph pairs)
        #
        # FORK: indexed rather than enumerated, on both axes. The table is a
        # full class matrix and fontTools decompiles a record the moment it is
        # reached, so walking it to skip most of it is the whole cost of a
        # build: Merriweather's is 123,000 value records, a second a face, to
        # keep the handful of classes a page of text actually uses. The same
        # pairs come out -- the skipped records are exactly the ones the two
        # `continue`s above threw away.
        rows = subtable.Class1Record
        columns = sorted(right_by_class)
        for c1 in sorted(left_by_class):
            if c1 >= len(rows):
                continue
            class2_records = rows[c1].Class2Record
            for c2 in columns:
                if c2 >= len(class2_records):
                    continue
                c2_rec = class2_records[c2]
                xa = 0
                if hasattr(c2_rec, 'Value1') and c2_rec.Value1:
                    xa = getattr(c2_rec.Value1, 'XAdvance', 0) or 0
                if xa == 0:
                    continue
                for lg in left_by_class[c1]:
                    for rg in right_by_class[c2]:
                        key = (lg, rg)
                        raw_kern[key] = raw_kern.get(key, 0) + xa


class FontBuildError(Exception):
    """A build failure with a message suitable for showing to the end user."""


def extract_kerning_fonttools(font_path, codepoints, ppem, figure_subs=None):
    """Kerning for one face, cached on everything that decides it.

    FORK: the cache. Reading these pairs is the most expensive thing a build
    does on a font with a real GPOS -- a second a face for Merriweather, whose
    kern feature is a hundred PairPos subtables -- and the preview rebuilds on
    every turn of every knob. None of those knobs is in this answer: the pairs
    depend on the file, the codepoints, the size and the figure substitution,
    and on nothing else.

    Design coordinates are not among them, which is why two slots of one
    variable file share an answer. That is a real limitation and not only a
    caching decision: these pairs are read at the font's default instance, so a
    bold slot uses the roman's kerning. Adding coordinates here means keying
    them in as well.

    The stamp is in the key so a font replaced under a running preview is read
    again. What comes back is shared and must not be written to.
    """
    try:
        stat = os.stat(font_path)
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = None
    return _extract_kerning_cached(
        str(font_path), stamp, tuple(sorted(codepoints)), ppem,
        tuple(sorted((figure_subs or {}).items())))


@functools.lru_cache(maxsize=32)
def _extract_kerning_cached(font_path, stamp, codepoints, ppem, figure_subs):
    return _extract_kerning(font_path, codepoints, ppem, dict(figure_subs))


def _extract_kerning(font_path, codepoints, ppem, figure_subs=None):
    """Extract kerning pairs from a font file using fonttools.

    Returns dict of {(leftCp, rightCp): pixel_adjust} for the given
    codepoints.  Values are scaled from font design units to integer
    pixels at ppem.

    FORK: `figure_subs` is the pnum mapping. The substitute is the glyph
    actually rasterized, so its pairs are the correct ones -- without this the
    digits would carry the tabular figures' kerning. It *replaces* rather than
    adds to the original name, unlike the firmware's version: the legacy kern
    table below accumulates, so a digit reachable under two names would have
    its adjustment counted twice.
    """
    from fontTools.ttLib import TTFont

    # FORK: lazy. fontTools otherwise decompiles the whole GPOS -- 136,000
    # objects for Calibri, 180 ms a face -- to reach the one kern lookup this
    # walks. Deferred, the same pairs come out in 24 ms.
    font = TTFont(font_path, lazy=True)
    units_per_em = font['head'].unitsPerEm
    cmap = font.getBestCmap() or {}

    # Build glyph_name -> [codepoints] map (preserves aliases where multiple
    # codepoints share a glyph, e.g. space/nbsp)
    glyph_to_cps = {}
    for cp in codepoints:
        gname = cmap.get(cp)
        if gname:
            gname = (figure_subs or {}).get(gname, gname)
            glyph_to_cps.setdefault(gname, []).append(cp)
    # Flat dict for membership checks and subtable extraction (uses keys only)
    glyph_to_cp = glyph_to_cps

    # Collect raw kerning values in font design units
    raw_kern = {}  # (left_glyph_name, right_glyph_name) -> design_units

    # 1. Legacy kern table
    if 'kern' in font:
        for subtable in font['kern'].kernTables:
            if hasattr(subtable, 'kernTable'):
                for (lg, rg), val in subtable.kernTable.items():
                    if lg in glyph_to_cp and rg in glyph_to_cp:
                        raw_kern[(lg, rg)] = raw_kern.get((lg, rg), 0) + val

    # 2. GPOS 'kern' feature
    if 'GPOS' in font:
        gpos = font['GPOS'].table
        kern_lookup_indices = set()
        if gpos.FeatureList:
            for fr in gpos.FeatureList.FeatureRecord:
                if fr.FeatureTag == 'kern':
                    kern_lookup_indices.update(fr.Feature.LookupListIndex)
        for li in kern_lookup_indices:
            lookup = gpos.LookupList.Lookup[li]
            for st in lookup.SubTable:
                actual = st
                # Unwrap Extension (lookup type 9) wrappers. After unwrapping,
                # `lookup.LookupType` is still 9, so we must look at the
                # *effective* type carried on the extension subtable to know
                # whether `actual` is a PairPos table.
                if lookup.LookupType == 9 and hasattr(st, 'ExtSubTable'):
                    actual = st.ExtSubTable
                effective_type = getattr(st, 'ExtensionLookupType', lookup.LookupType)
                if hasattr(actual, 'Format'):
                    # _extract_pairpos_subtable assumes a Type-2 (PairPos)
                    # subtable. Other lookup types reachable through the kern
                    # feature (cursive attachment, mark-to-mark, contextual,
                    # etc.) have a different shape and crash inside the
                    # extractor. Skip them with a debug note rather than
                    # aborting the whole build. Modern fonts often ship kern
                    # via Extension-wrapped PairPos, so checking the effective
                    # type instead of the outer type is what makes those
                    # lookups actually reach the extractor.
                    if effective_type == 2:
                        _extract_pairpos_subtable(actual, glyph_to_cp, raw_kern)
                    else:
                        print(f"  Debug: skipping unsupported GPOS kern lookupType="
                              f"{effective_type} (outer={lookup.LookupType}, Format={actual.Format})",
                              file=sys.stderr)

    font.close()

    # Scale design-unit kerning values to 4.4 fixed-point pixels.
    # Expand glyph aliases: if multiple codepoints share a glyph, emit kern
    # pairs for all codepoint combinations.
    scale = ppem / units_per_em
    result = {}  # (leftCp, rightCp) -> 4.4 fixed-point adjust
    for (lg, rg), du in raw_kern.items():
        adjust = fp4_from_design_units(du, scale)
        if adjust != 0:
            for lcp in glyph_to_cps[lg]:
                for rcp in glyph_to_cps[rg]:
                    result[(lcp, rcp)] = adjust
    return result


def derive_kern_classes(kern_map):
    """Derive class-based kerning from a pair map.

    Returns (kern_left_classes, kern_right_classes, kern_matrix,
             kern_left_class_count, kern_right_class_count) where:
    - kern_left_classes: sorted list of (codepoint, classId) tuples
    - kern_right_classes: sorted list of (codepoint, classId) tuples
    - kern_matrix: flat list of int8 values (left_class_count * right_class_count)
    - kern_left_class_count: number of distinct left classes
    - kern_right_class_count: number of distinct right classes
    """
    if not kern_map:
        return [], [], [], 0, 0

    all_left_cps = {lcp for lcp, _ in kern_map}
    all_right_cps = {rcp for _, rcp in kern_map}

    sorted_right_cps = sorted(all_right_cps)
    sorted_left_cps = sorted(all_left_cps)

    # Group left codepoints by identical adjustment row
    left_profile_to_class = {}
    left_class_map = {}
    left_class_id = 1
    for lcp in sorted(all_left_cps):
        row = tuple(kern_map.get((lcp, rcp), 0) for rcp in sorted_right_cps)
        if row not in left_profile_to_class:
            left_profile_to_class[row] = left_class_id
            left_class_id += 1
        left_class_map[lcp] = left_profile_to_class[row]

    # Group right codepoints by identical adjustment column
    right_profile_to_class = {}
    right_class_map = {}
    right_class_id = 1
    for rcp in sorted(all_right_cps):
        col = tuple(kern_map.get((lcp, rcp), 0) for lcp in sorted_left_cps)
        if col not in right_profile_to_class:
            right_profile_to_class[col] = right_class_id
            right_class_id += 1
        right_class_map[rcp] = right_profile_to_class[col]

    kern_left_class_count = left_class_id - 1
    kern_right_class_count = right_class_id - 1

    if kern_left_class_count > 255 or kern_right_class_count > 255:
        print(f"WARNING: kerning class count exceeds uint8_t range "
              f"(left={kern_left_class_count}, right={kern_right_class_count}), "
              f"dropping kerning for this style",
              file=sys.stderr)
        return ([], [], [], 0, 0)

    # Build the class x class matrix
    kern_matrix = [0] * (kern_left_class_count * kern_right_class_count)
    for (lcp, rcp), adjust in kern_map.items():
        lc = left_class_map[lcp] - 1
        rc = right_class_map[rcp] - 1
        kern_matrix[lc * kern_right_class_count + rc] = adjust

    # Build sorted class entry lists
    kern_left_classes = sorted(left_class_map.items())
    kern_right_classes = sorted(right_class_map.items())

    return (kern_left_classes, kern_right_classes, kern_matrix,
            kern_left_class_count, kern_right_class_count)


def extract_figure_subs(font_path):
    """GSUB `pnum` substitutions, as {glyph_name: proportional_glyph_name}.

    FORK: the firmware's own fontconvert.py has this behind --pnum; the
    website's copy, which this file forked, never did. Tabular figures pad
    every digit to a common width so columns align, which leaves visible gaps
    around a narrow digit in running prose -- a book is prose.

    An empty dict means the font declares no pnum feature, and the knob is then
    honestly inert, the same way ligatures are on a face with no pairs.
    """
    from fontTools.ttLib import TTFont

    font = TTFont(font_path, lazy=True)
    try:
        if 'GSUB' not in font:
            return {}
        gsub = font['GSUB'].table
        lookup_indices = set()
        if gsub.FeatureList:
            for fr in gsub.FeatureList.FeatureRecord:
                if fr.FeatureTag == 'pnum':
                    lookup_indices.update(fr.Feature.LookupListIndex)
        subs = {}
        for li in lookup_indices:
            lookup = gsub.LookupList.Lookup[li]
            for st in lookup.SubTable:
                actual = st
                # Extension lookups (type 7) wrap the real subtable, exactly as
                # the GPOS kern walk above has to unwrap type 9.
                if lookup.LookupType == 7 and hasattr(st, 'ExtSubTable'):
                    actual = st.ExtSubTable
                if hasattr(actual, 'mapping'):
                    subs.update(actual.mapping)
        return subs
    finally:
        font.close()


def figure_glyph_overrides(font_path):
    """{codepoint: glyph index} for a font's proportional figures.

    FORK: FreeType addresses glyphs by the font's own glyph ID, which is the
    order fontTools reports -- so an index resolved here selects the same
    outline in the rasterizing face. The substitutes have no cmap entry of
    their own, which is why they can only be reached by index.
    """
    from fontTools.ttLib import TTFont

    subs = extract_figure_subs(font_path)
    if not subs:
        return {}
    font = TTFont(font_path, lazy=True)
    try:
        cmap = font.getBestCmap() or {}
        order = {name: i for i, name in enumerate(font.getGlyphOrder())}
        overrides = {}
        for cp, gname in cmap.items():
            index = order.get(subs.get(gname), 0)
            if index > 0:
                overrides[cp] = index
        return overrides
    finally:
        font.close()


def gsub_ligature_sequences(font_path):
    """Every ligature rule the font carries: input codepoints -> output codepoint.

    FORK: split out of extract_ligatures_fonttools, which is this walk plus a
    filter against the glyph set being built. The preview needs the walk on its
    own, to ask which output codepoints a given text can reach *before* it
    decides what to rasterize -- a ligature whose output is outside the built
    set is dropped by that filter, so a text-derived build would silently lose
    the ligatures it was meant to show. Costs about half a millisecond after
    fontTools is imported.
    """
    from fontTools.ttLib import TTFont

    font = TTFont(font_path, lazy=True)
    cmap = font.getBestCmap() or {}
    dropped = 0

    # Build glyph_name -> codepoint and codepoint -> glyph_name maps
    glyph_to_cp = {}
    cp_to_glyph = {}
    for cp, gname in cmap.items():
        glyph_to_cp[gname] = cp
        cp_to_glyph[cp] = gname

    # Collect raw ligature rules: (sequence_of_codepoints) -> ligature_codepoint
    raw_ligatures = {}  # tuple of codepoints -> ligature codepoint

    if 'GSUB' in font:
        gsub = font['GSUB'].table

        LIGATURE_FEATURES = ('liga', 'rlig')
        liga_lookup_indices = set()
        if gsub.FeatureList:
            for fr in gsub.FeatureList.FeatureRecord:
                if fr.FeatureTag in LIGATURE_FEATURES:
                    liga_lookup_indices.update(fr.Feature.LookupListIndex)

        for li in liga_lookup_indices:
            lookup = gsub.LookupList.Lookup[li]
            for st in lookup.SubTable:
                actual = st
                # Unwrap Extension (lookup type 7) wrappers
                if lookup.LookupType == 7 and hasattr(st, 'ExtSubTable'):
                    actual = st.ExtSubTable
                # LigatureSubst is lookup type 4
                if not hasattr(actual, 'ligatures'):
                    continue
                for first_glyph, ligature_list in actual.ligatures.items():
                    if first_glyph not in glyph_to_cp:
                        continue
                    first_cp = glyph_to_cp[first_glyph]
                    for lig in ligature_list:
                        component_cps = []
                        valid = True
                        for comp_glyph in lig.Component:
                            if comp_glyph not in glyph_to_cp:
                                valid = False
                                break
                            component_cps.append(glyph_to_cp[comp_glyph])
                        if not valid:
                            continue
                        seq = tuple([first_cp] + component_cps)
                        if lig.LigGlyph in glyph_to_cp:
                            lig_cp = glyph_to_cp[lig.LigGlyph]
                        elif seq in STANDARD_LIGATURE_MAP:
                            lig_cp = STANDARD_LIGATURE_MAP[seq]
                        else:
                            dropped += 1
                            continue
                        raw_ligatures[seq] = lig_cp

    # FORK: one line rather than one per rule. A face with a full `liga` set
    # drops dozens here -- every f-ligature a designer drew and gave no
    # codepoint -- and none of them is actionable: the format addresses a
    # ligature by codepoint, so one without is unreachable however the font is
    # rebuilt. At a page redraw that is fifty lines of log per keystroke.
    if dropped:
        print(f"ligatures: {dropped} not reachable by codepoint, skipped",
              file=sys.stderr)
    font.close()
    return raw_ligatures


def ligature_codepoints(font_path, codepoints):
    """FORK: the codepoints ligatures would substitute *into* for this text.

    The output glyph of a ligature is a codepoint of its own, and it has to be
    in the built set or extract_ligatures_fonttools drops the rule. Text alone
    never names it -- nobody types U+FB01 -- so a build sized to the text has to
    add these or lose every ligature it has.
    """
    codepoints = set(codepoints)
    return {lig_cp
            for seq, lig_cp in gsub_ligature_sequences(font_path).items()
            if all(cp in codepoints for cp in seq)}


def extract_ligatures_fonttools(font_path, codepoints):
    """Extract ligature substitution pairs from a font file using fonttools.

    Returns list of (packed_pair, ligature_codepoint) for the given codepoints.
    Multi-character ligatures are decomposed into chained pairs.
    """
    raw_ligatures = gsub_ligature_sequences(font_path)

    # Filter: only keep ligatures where all input and output codepoints are
    # in our generated glyph set, and all codepoints fit in 16 bits.
    #
    # The on-disk format packs each component as a uint16 (the 3+ chained
    # path packs `intermediate_cp << 16 | last_cp`, where `intermediate_cp`
    # is the lig_cp of the prefix). Dropping any seq with an SMP cp here —
    # plus any lig_cp > 0xFFFF — means every cp that reaches `packed = … <<
    # 16 | …` below is already 16-bit safe, including the chained path
    # (intermediate_cp = filtered[prefix] is filtered too).
    codepoints_set = set(codepoints)
    filtered = {}
    for seq, lig_cp in raw_ligatures.items():
        if lig_cp not in codepoints_set or lig_cp > 0xFFFF:
            continue
        if any(cp > 0xFFFF for cp in seq):
            continue
        if all(cp in codepoints_set for cp in seq):
            filtered[seq] = lig_cp

    # Decompose into chained pairs
    pairs = []
    # First pass: collect all 2-codepoint ligatures
    two_char = {seq: lig_cp for seq, lig_cp in filtered.items() if len(seq) == 2}
    for seq, lig_cp in two_char.items():
        packed = (seq[0] << 16) | seq[1]
        pairs.append((packed, lig_cp))

    # Second pass: decompose 3+ codepoint ligatures into chained pairs
    for seq, lig_cp in filtered.items():
        if len(seq) < 3:
            continue
        prefix = seq[:-1]
        last_cp = seq[-1]
        if prefix in filtered:
            intermediate_cp = filtered[prefix]
            packed = (intermediate_cp << 16) | last_cp
            pairs.append((packed, lig_cp))
        else:
            print(f"ligatures: skipping {len(seq)}-char ligature "
                  f"({', '.join(f'U+{cp:04X}' for cp in seq)}) -> U+{lig_cp:04X}: "
                  f"no intermediate ligature for prefix", file=sys.stderr)

    # Sort by packed pair key — on-device lookup uses binary search
    pairs.sort(key=lambda p: p[0])
    return pairs


def apply_stem_darkening(enabled):
    """Toggle FreeType's stem darkening on every module that implements it.

    FORK. A library-global property rather than a per-face one, so it is set
    for the duration of one rasterize call.

    Its reach is narrower than the four module names suggest. The code is in
    two engines: the Adobe CF2 interpreter in psaux, which the cff, type1 and
    t1cid drivers share, and the auto-hinter. Each puts a condition of its own
    on top of the property. CF2 darkens a scaled load; the auto-hinter darkens
    at a light target.

    So a CFF face moves under any hinting but `auto`. A TrueType face has no
    CF2 path at all, and reaches the auto-hinter only at `light`, the TrueType
    driver being the one that does not claim to hint lightly. And `auto` moves
    neither format: it targets normal hinting, and the auto-hinter reloads the
    glyph with FT_LOAD_NO_SCALE, which fails both conditions at once. That
    second half is the load-bearing one -- without it a CFF face would still
    darken underneath the auto-hinter.

    The two differ in size as well as in reach. Through CF2 the effect on the
    final 2-bit bitmap is slight, well under a percent of set pixels; through
    the light auto-hinter it is the largest thing in this file.

    Measured over 132 faces on FreeType 2.13.2, and read against that version's
    source. A CFF face whose stems fall where the darkening curve rounds to
    nothing is unmoved too, which is why the preview greys the switch on the
    two cases above and leaves the rest alone.

    freetype-py binds FT_Property_Set without an error check, so a property a
    build does not carry is set silently and does nothing at all. The guard is
    for a freetype-py old enough not to bind the call: FreeType gained it in
    2.7, and the binding is behind a try/except that leaves the name undefined.
    """
    import freetype

    handle = freetype.get_handle()
    value = freetype.c_bool(not enabled)
    for module in (b"autofitter", b"cff", b"type1", b"t1cid"):
        try:
            freetype.FT_Property_Set(handle, module, b"no-stem-darkening",
                                     freetype.byref(value))
        except Exception:      # noqa: BLE001 -- see the docstring
            pass


def apply_interpreter(grayscale):
    """Pick the TrueType bytecode interpreter: version 35 when `grayscale`.

    FORK. Library-global like stem darkening above, and set for the duration of
    one rasterize call. crengine-ng offers the same choice for the same reason
    (lvfreetypefontman.cpp SetTrueTypeInterpreterVersion).

    It only reaches a face whose own bytecode is what draws it. CFF has no
    bytecode at all; a TrueType face with no glyph instructions, no `fpgm` and
    no `prep` goes to the auto-hinter whatever is set here (base/ftobjs.c); and
    so does any face under `light`, `auto` or `none`, unless FreeType calls it
    tricky, which exempts it from that dispatch entirely.

    Nothing reports a build that does not carry the property: the binding
    discards FreeType's error, so the call does nothing and the page is drawn
    with whichever interpreter the build defaults to. See apply_stem_darkening.
    """
    import freetype

    handle = freetype.get_handle()
    value = freetype.c_int(35 if grayscale else 40)
    try:
        freetype.FT_Property_Set(handle, b"truetype", b"interpreter-version",
                                 freetype.byref(value))
    except Exception:          # noqa: BLE001 -- see the docstring
        pass


def set_design_coords(face, axes):
    """FORK: put a variable font's face at the given design coordinates.

    FreeType wants a value for every axis, in the font's own fvar order, so the
    ones not named here are filled from the face's own defaults -- a short list
    would leave the rest at zero, which is outside most axes' range.

    A static face has no axes to set and is left alone. Anything else that goes
    wrong is raised: coordinates that fail to apply would rasterize the file's
    default instance instead, and ship a Bold that is drawn Light.
    """
    import freetype

    if not axes or not (face.face_flags & freetype.FT_FACE_FLAG_MULTIPLE_MASTERS):
        return
    master = face.get_variation_info()
    face.set_var_design_coords(
        [axes.get(axis.tag, axis.default) for axis in master.axes])


def rasterize_font_style(fontfile, size, intervals, style_id=0, force_autohint=False,
                         fallback_fontfiles=None, darken_aa=False, tuning=None,
                         axes=None):
    """Rasterize all glyphs for one font style. Returns StyleRasterData.

    FORK: `tuning` is crossglyph's addition -- see cpfont/tuning.py. `darken_aa`
    stays for compatibility with upstream's flag and is read as the threshold
    preset it always was.

    FORK: `axes` is a variable font's design coordinates, {tag: value}. A
    variable font is several faces in one file and FreeType draws whichever
    the coordinates name, so this is what makes the bold slot bold when the
    family ships no separate bold file. Without it the file's own default
    instance is drawn, which is not always the text weight -- Merriweather
    defaults to Light.
    """
    import freetype

    style_names = {0: "regular", 1: "bold", 2: "italic", 3: "bolditalic"}
    style_label = style_names.get(style_id, str(style_id))

    face = freetype.Face(fontfile)
    # FORK: before the size, because the coordinates change the outlines the
    # size is then applied to. Only the named axes move; the rest keep the
    # font's own defaults.
    if axes:
        set_design_coords(face, axes)
    # Set font size at 150 DPI (matching fontconvert.py) BEFORE any glyph load.
    # load_glyph() with FT_LOAD_RENDER renders at the active size, so calling
    # it before set_char_size() would waste work at the default size and risk
    # Invalid_Size_Handle on some fonts.
    # 26.6 fixed point, so a fractional point size is native to FreeType and
    # costs nothing here. The integer step is 150/72 = 2.08 px/em, which at
    # reading sizes is a jump of about 10% -- fine tuning wants finer.
    fixed = round(size * 64)
    face.set_char_size(fixed, fixed, 150, 150)
    fallback_faces = []
    for fallback_fontfile in (fallback_fontfiles or []):
        fallback_face = freetype.Face(fallback_fontfile)
        fallback_face.set_char_size(fixed, fixed, 150, 150)
        fallback_faces.append(fallback_face)
    source_faces = [face] + fallback_faces

    tuning = tuning or Tuning()
    # --darken-aa lowers the thresholds so partially-covered edge pixels round
    # up to a darker shade more readily. The reading fonts a self-built one is
    # put beside were made this way, so without it your own renders visibly
    # lighter than they do at the same nominal weight.
    #
    # FORK: upstream calls those three "the built-in reading fonts
    # (Bitter/Lexend Deca/ChareInk)", and not one of them is built in.
    # CrossPoint compiles in NotoSans, NotoSerif, Ubuntu and OpenDyslexic
    # (lib/EpdFont/builtinFonts/source/); Bitter alone is among the card fonts
    # its own script builds (lib/EpdFont/scripts/sd-fonts.yaml); and the trio
    # together is what the CrossInk fork ships in place of the defaults
    # (crosspoint-reader README, "Community forks").
    #
    # An explicit tuning that sets thresholds itself wins.
    if darken_aa and tuning.thresholds == Tuning().thresholds:
        tuning = dataclasses.replace(tuning, thresholds=Tuning.DARKEN_AA)

    load_flags = tuning.load_flags(freetype)
    if force_autohint:
        load_flags |= freetype.FT_LOAD_FORCE_AUTOHINT
    # Emboldening needs the outline, which FT_LOAD_RENDER would have consumed,
    # so that flag is added only when there is no outline work to do -- and
    # only when the load can ask for the raster that is wanted, which light
    # hinting with a bilevel one cannot.
    embolden = round(tuning.weight * 64)
    two_step = bool(embolden) or not tuning.renders_on_load()
    if not two_step:
        load_flags |= freetype.FT_LOAD_RENDER
    render_mode = tuning.render_mode(freetype)

    aa_thresholds = tuning.thresholds
    lut = tuning.coverage_lut()
    apply_stem_darkening(tuning.stem_darkening)
    apply_interpreter(tuning.grayscale_hinting)

    # FORK: advanceX is 12.4 fixed point, so a pixel of tracking is 16 units
    # and the smallest step is 1/16 px.
    tracking = round(tuning.letter_spacing * 16)
    word_extra = round(tuning.word_spacing * 16)

    # FORK: synthesise an oblique by shearing the outline. Set on every face so
    # a glyph taken from a fallback leans with the rest of the line.
    if tuning.slant:
        matrix = freetype.Matrix(0x10000, int(tuning.slant * 0x10000),
                                 0, 0x10000)
        for target_face in source_faces:
            target_face.set_transform(matrix, freetype.Vector(0, 0))

    # FORK: proportional figures, resolved per source face so a digit taken
    # from a fallback follows the same rule as one from the primary.
    if tuning.figures == "proportional":
        figure_overrides = [figure_glyph_overrides(path)
                            for path in [fontfile] + list(fallback_fontfiles or [])]
    else:
        figure_overrides = [{} for _ in source_faces]

    # FORK: the shaped Arabic codepoints CrossPoint will ask each face for.
    # A modern Arabic face carries its joining rules and none of the shaped
    # codepoints, and the device has no shaper, so the rules are run here and
    # the result filed where the device looks. Empty for a face with no
    # Arabic, and for one that carries the shaped codepoints already.
    #
    # Per source face, as the figures above are, so an Arabic family used as
    # somebody's fallback is repaired the same way it would be as a primary.
    arabic_runs = [presentation_forms(path)
                   for path in [fontfile] + list(fallback_fontfiles or [])]

    # FORK: asking for Arabic letters is asking for the shapes they are drawn
    # by, since the device converts a letter before it looks a glyph up. A
    # build holding the letters and not the shapes draws a replacement box for
    # every word. Normalized as well, so a caller that assembled its own
    # coverage cannot hand the packer an unsorted table.
    intervals = merge_intervals(implied_coverage(intervals))

    def load_one_glyph(target_face, glyph_index):
        if glyph_index > 0:
            target_face.load_glyph(glyph_index, load_flags)
            if embolden:
                # FORK: FT_Outline_Embolden fattens the outline without moving
                # linearHoriAdvance, so text gets heavier at unchanged spacing.
                #
                # byref, and it segfaults without it. The function takes an
                # FT_Outline*, and freetype-py declares no argtypes for it, so
                # handing over the structure passes it by value. On Windows
                # x64 that survives: the ABI puts anything larger than eight
                # bytes behind a pointer, which is what the callee reads. The
                # System V ABI puts it on the stack instead, so the callee
                # takes the first eight bytes of the outline for its address
                # and writes through it. That is a crash on every Linux and
                # macOS build the moment somebody moves the weight knob.
                freetype.FT_Outline_Embolden(
                    freetype.byref(target_face.glyph.outline._FT_Outline),
                    embolden)
            if two_step:
                # FT_LOAD_RENDER was withheld, so rendering is ours to do.
                freetype.FT_Render_Glyph(target_face.glyph._FT_GlyphSlot,
                                         render_mode)
            return target_face
        return None

    def load_glyph_for_face(target_face, code_point, face_index=0):
        # FORK: a shaped Arabic form is drawn from the face's own glyphs, which
        # may be one glyph or several with offsets. A run of one is the same
        # code as a run of many, so a face that spells a letter whole and one
        # that spells it as a mark plus a base cannot behave differently.
        run = arabic_runs[face_index].get(code_point)
        if run is not None:
            drawn = []
            for glyph_index, x_offset, y_offset in run.pieces:
                if load_one_glyph(target_face, glyph_index) is None:
                    continue
                drawn.append((raster_from_slot(target_face.glyph),
                              x_offset, y_offset))
            if not drawn:
                return None
            return compose_raster(drawn, target_face,
                                  scale_advance(run.advance, target_face))

        glyph_index = figure_overrides[face_index].get(code_point) or 0
        if not glyph_index:
            glyph_index = target_face.get_char_index(code_point)
        if load_one_glyph(target_face, glyph_index) is None:
            return None
        return raster_from_slot(target_face.glyph)

    # Validate intervals against the primary font first, then let the fallback
    # font fill any holes. That keeps the primary family authoritative while
    # still widening glyph coverage for SD-card fonts.
    print(f"  [{style_label}] Validating intervals against font coverage...", file=sys.stderr)
    intervals, codepoint_sources, source_codepoints = resolve_style_coverage(
        face, fallback_faces, intervals,
        synthesized=[frozenset(runs) for runs in arabic_runs])
    total_glyphs = sum(end - start + 1 for start, end in intervals)
    print(f"  [{style_label}] Validated: {len(intervals)} intervals, {total_glyphs} glyphs", file=sys.stderr)
    coverage_parts = [f"{len(source_codepoints[0])} primary"]
    for idx in range(1, len(source_codepoints)):
        fallback_name = os.path.basename(fallback_fontfiles[idx - 1]) if fallback_fontfiles else f"fallback{idx}"
        coverage_parts.append(f"{len(source_codepoints[idx])} fallback{idx} ({fallback_name})")
    print(f"  [{style_label}] Coverage split: {', '.join(coverage_parts)}", file=sys.stderr)

    # Rasterize all glyphs
    total_bitmap_size = 0
    all_glyphs = []

    for i_start, i_end in intervals:
        for code_point in range(i_start, i_end + 1):
            face_index = codepoint_sources.get(code_point, 0)
            source_face = source_faces[face_index]
            f = load_glyph_for_face(source_face, code_point, face_index)
            if f is None:
                glyph = GlyphProps(0, 0, 0, 0, 0, 0, total_bitmap_size, code_point)
                all_glyphs.append((glyph, b''))
                continue

            bitmap = f

            # FORK: EpdGlyph packs width and height as uint8, so a glyph over
            # GLYPH_SIZE_CAP on either axis has nowhere to go. One glyph
            # reaches it in practice: U+FDFD, an Arabic ligature drawn as a
            # whole phrase, which in Noto Sans Arabic passes 255 px at about
            # 12.6 pt and so is over at every ordinary reading size. A device
            # that cannot store it draws nothing for it either way, so this
            # stores the empty entry rather than aborting a whole family over
            # one glyph. Without it the packer raises struct.error, which names
            # no codepoint and suggests nothing.
            if bitmap.width > GLYPH_SIZE_CAP or bitmap.rows > GLYPH_SIZE_CAP:
                print(f"WARNING: U+{code_point:04X} renders "
                      f"{bitmap.width}x{bitmap.rows} px, over the "
                      f"{GLYPH_SIZE_CAP} px per-glyph cap; drawn as blank",
                      file=sys.stderr)
                glyph = GlyphProps(0, 0, 0, 0, 0, 0, total_bitmap_size,
                                   code_point)
                all_glyphs.append((glyph, b''))
                continue

            # Build 4-bit greyscale bitmap (same logic as fontconvert.py).
            #
            # pitch is the row stride in bytes, and it can be negative when the
            # rows are stored bottom-up. Iterating the buffer linearly assumes
            # pitch == width and a top-down layout — that holds in the common
            # case but breaks on padded or flipped bitmaps and corrupts the
            # output. Walk by (row, col) using the real pitch instead.
            #
            # FORK: the buffer is copied out of the FreeType slot once per
            # glyph, in raster_from_slot, and read here as plain bytes. Reading
            # a ctypes array per pixel instead is catastrophically slow, since
            # each field access builds a new Python wrapper.
            pixels4g = []
            px = 0
            buf = bitmap.buffer
            abs_pitch = abs(bitmap.pitch)
            # FORK: a mono render is one bit per pixel, most significant first,
            # so a row has to be unpacked before it can be read by column.
            # Done per row rather than per pixel: the loop below runs once for
            # every pixel of every glyph in the coverage set.
            mono = bitmap.pixel_mode == freetype.FT_PIXEL_MODE_MONO
            for y in range(bitmap.rows):
                row_offset = y * abs_pitch if bitmap.pitch >= 0 else (bitmap.rows - 1 - y) * abs_pitch
                if mono:
                    row, base = bytes(
                        255 if buf[row_offset + (i >> 3)] & (0x80 >> (i & 7))
                        else 0 for i in range(bitmap.width)), 0
                else:
                    row, base = buf, row_offset
                for x in range(bitmap.width):
                    v = row[base + x]
                    # FORK: curve the coverage before it is truncated to 4
                    # bits, so the LUT has all 256 levels to work with.
                    if lut is not None:
                        v = lut[v]
                    if x % 2 == 0:
                        px = (v >> 4)
                    else:
                        px = px | (v & 0xF0)
                        pixels4g.append(px)
                        px = 0
                if bitmap.width % 2 > 0:
                    pixels4g.append(px)
                    px = 0

            # Downsample to 2-bit bitmap
            pixels2b = []
            px = 0
            pitch = (bitmap.width // 2) + (bitmap.width % 2)
            for y in range(bitmap.rows):
                for x in range(bitmap.width):
                    px = px << 2
                    bm = pixels4g[y * pitch + (x // 2)]
                    bm = (bm >> ((x % 2) * 4)) & 0xF

                    if bm >= aa_thresholds[2]:
                        px += 3
                    elif bm >= aa_thresholds[1]:
                        px += 2
                    elif bm >= aa_thresholds[0]:
                        px += 1

                    if (y * bitmap.width + x) % 4 == 3:
                        pixels2b.append(px)
                        px = 0
            if (bitmap.width * bitmap.rows) % 4 != 0:
                # Outer parens are for clarity: in Python `*` binds tighter
                # than `<<`, so the original `px << (4 - … % 4) * 2` already
                # evaluates as `px << ((4 - … % 4) * 2)`. Match the explicit
                # bracketing here so the shift width is obvious at a glance,
                # mirroring the inner-loop style in fontconvert.py.
                px = px << ((4 - (bitmap.width * bitmap.rows) % 4) * 2)
                pixels2b.append(px)

            packed = bytes(pixels2b)
            advance = fp4_from_ft16_16(f.advance) + tracking
            if code_point == 0x20:
                # As CSS word-spacing does, this stacks on letter-spacing. The
                # device takes the word gap from this glyph
                # (GfxRenderer.cpp:1880).
                advance += word_extra
            glyph = GlyphProps(
                width=bitmap.width,
                height=bitmap.rows,
                advance_x=max(0, min(0xFFFF, advance)),
                left=f.left,
                top=f.top,
                data_length=len(packed),
                data_offset=total_bitmap_size,
                code_point=code_point,
            )
            total_bitmap_size += len(packed)
            all_glyphs.append((glyph, packed))

    # Get font metrics from the primary font. This keeps line metrics stable for
    # the selected family even when a fallback contributes some glyphs.
    load_glyph_for_face(face, ord('|'))

    natural_advance_y = norm_ceil(face.size.height)
    advanceY = natural_advance_y
    ascender = norm_ceil(face.size.ascender)
    descender = norm_floor(face.size.descender)

    # FORK: the font's own hhea/OS-2 line height varies enormously between
    # families -- 0.89 to 2.11 em across 686 faces measured -- and the device's
    # Tight setting only takes 5% off it (CrossPointSettings.cpp:268), from a
    # table calibrated for Bookerly whatever family is loaded. This is the only
    # place it can be fixed. ascender and descender are deliberately left alone:
    # they place the baseline inside the line and drive underline and sup/sub
    # offsets, while advanceY is only the pitch to the next line.
    if tuning.line_height is not None:
        advanceY = tuning.line_height.resolve(natural_advance_y,
                                              size * 150.0 / 72.0)

    print(f"  [{style_label}] Metrics: advanceY={advanceY}, ascender={ascender}, descender={descender}", file=sys.stderr)
    print(f"  [{style_label}] Bitmap: {total_bitmap_size} bytes ({total_bitmap_size / 1024:.1f} KB)", file=sys.stderr)

    # --- Extract kerning and ligatures ---
    ppem = size * 150.0 / 72.0

    kern_map = {}
    source_fontfiles = [fontfile]
    source_fontfiles.extend(fallback_fontfiles or [])
    # FORK: a substituted figure is the glyph that got rasterized, so its pairs
    # are the ones to read -- otherwise the digits keep the tabular kerning.
    figure_subs = [{} if tuning.figures == "default" else extract_figure_subs(p)
                   for p in source_fontfiles]
    for idx, cps in enumerate(source_codepoints):
        if cps:
            try:
                kern_map.update(extract_kerning_fonttools(
                    source_fontfiles[idx], cps, ppem, figure_subs[idx]))
            except Exception as e:
                raise FontBuildError(
                    f"The font file '{os.path.basename(source_fontfiles[idx])}' appears to be "
                    f"corrupt or malformed and could not be processed ({e}). "
                    f"Try re-exporting the font or uploading a different file.") from e
    # SMP codepoints (> U+FFFF) cannot be stored in the uint16 kern codepoint
    # field; drop them before class derivation to avoid a downstream
    # struct.error when packing the binary kern tables.
    kern_map = {(lcp, rcp): v for (lcp, rcp), v in kern_map.items() if lcp <= 0xFFFF and rcp <= 0xFFFF}
    # FORK: scale before deriving classes, which groups codepoints by identical
    # adjustment rows -- scaling afterwards would leave the class count computed
    # from the unscaled values. Adjustments are int8 4.4 fixed point, and those
    # that round to zero are dropped, as extract_kerning_fonttools already does.
    if tuning.kerning != 1.0:
        kern_map = {pair: scaled
                    for pair, value in kern_map.items()
                    if (scaled := max(-128, min(127,
                                                round(value * tuning.kerning))))}
    print(f"  [{style_label}] Kerning: {len(kern_map)} pairs extracted", file=sys.stderr)

    (kern_left_classes, kern_right_classes, kern_matrix,
     kern_left_class_count, kern_right_class_count) = derive_kern_classes(kern_map)

    if kern_map:
        matrix_size = kern_left_class_count * kern_right_class_count
        entries_size = (len(kern_left_classes) + len(kern_right_classes)) * 3
        print(f"  [{style_label}] Kerning classes: {kern_left_class_count} left, {kern_right_class_count} right, "
              f"{matrix_size + entries_size} bytes", file=sys.stderr)

    # SMP codepoints in ligature inputs / outputs are filtered inside
    # extract_ligatures_fonttools (see the codepoints_set filter), so every
    # entry returned here is already 16-bit safe.
    ligature_pairs = []
    # FORK: skipping this also skips a full GSUB parse per source face.
    if tuning.ligatures:
        for idx, cps in enumerate(source_codepoints):
            if cps:
                ligature_pairs.extend(extract_ligatures_fonttools(source_fontfiles[idx], cps))
        ligature_pairs.sort(key=lambda p: p[0])
    if len(ligature_pairs) > 255:
        print(f"  [{style_label}] WARNING: {len(ligature_pairs)} ligature pairs exceeds uint8_t max (255), truncating",
              file=sys.stderr)
        ligature_pairs = ligature_pairs[:255]
    print(f"  [{style_label}] Ligatures: {len(ligature_pairs)} pairs", file=sys.stderr)

    return StyleRasterData(
        style_id=style_id,
        intervals=intervals,
        all_glyphs=all_glyphs,
        total_bitmap_size=total_bitmap_size,
        advanceY=advanceY,
        ascender=ascender,
        descender=descender,
        kern_left_classes=kern_left_classes,
        kern_right_classes=kern_right_classes,
        kern_matrix=kern_matrix,
        kern_left_class_count=kern_left_class_count,
        kern_right_class_count=kern_right_class_count,
        ligature_pairs=ligature_pairs,
    )


# --- Binary packing helpers ---

# EpdGlyph struct: 16 bytes, little-endian
GLYPH_STRUCT_FORMAT = "<BBHhhH2xI"
assert struct.calcsize(GLYPH_STRUCT_FORMAT) == 16

#: FORK: the first two fields above are width and height as uint8, which is
#: what caps how large a single glyph can be.
GLYPH_SIZE_CAP = 0xFF


def pack_style_sections(sd):
    """Pack one StyleRasterData into binary section bytearrays.
    Returns (intervals_data, glyphs_data, kern_left, kern_right, kern_matrix, ligatures, bitmaps)."""
    intervals_data = bytearray()
    offset = 0
    for i_start, i_end in sd.intervals:
        intervals_data += struct.pack("<III", i_start, i_end, offset)
        offset += i_end - i_start + 1

    glyphs_data = bytearray()
    for glyph, packed in sd.all_glyphs:
        glyphs_data += struct.pack(GLYPH_STRUCT_FORMAT,
                                   glyph.width, glyph.height, glyph.advance_x,
                                   glyph.left, glyph.top,
                                   glyph.data_length, glyph.data_offset)

    kern_left_data = bytearray()
    for cp, cls in sd.kern_left_classes:
        kern_left_data += struct.pack("<HB", cp, cls)

    kern_right_data = bytearray()
    for cp, cls in sd.kern_right_classes:
        kern_right_data += struct.pack("<HB", cp, cls)

    kern_matrix_data = bytearray()
    if sd.kern_matrix:
        kern_matrix_data = bytearray(struct.pack(f"<{len(sd.kern_matrix)}b", *sd.kern_matrix))

    ligature_data = bytearray()
    for packed_pair, lig_cp in sd.ligature_pairs:
        ligature_data += struct.pack("<II", packed_pair, lig_cp)

    bitmap_data = bytearray()
    for glyph, packed in sd.all_glyphs:
        bitmap_data += packed
    assert len(bitmap_data) == sd.total_bitmap_size

    return (intervals_data, glyphs_data, kern_left_data, kern_right_data,
            kern_matrix_data, ligature_data, bitmap_data)


def style_sections_total_size(sections):
    """Total byte size of all sections returned by pack_style_sections()."""
    return sum(len(s) for s in sections)


# --- File writers ---

def generate_cpfont_multistyle(style_fonts, size, intervals, output_path,
                               force_autohint=False, fallback_style_fonts=None,
                               darken_aa=False, tuning=None, style_axes=None):
    """Generate a multi-style v4 .cpfont file.

    style_fonts: dict of {style_id: fontfile_path} e.g. {0: "Regular.ttf", 2: "Italic.ttf"}
    tuning: a cpfont.tuning.Tuning, or None for upstream's defaults (FORK).
    style_axes: {style_id: {axis_tag: value}} design coordinates (FORK). One
        variable file can fill several slots this way, each at its own weight.
    """
    MAGIC = b"CPFONT\x00\x00"
    HEADER_SIZE = 32
    STYLE_TOC_ENTRY_SIZE = 32
    flags = 1  # always 2-bit greyscale
    style_count = len(style_fonts)

    # Rasterize each style
    raster_data = {}  # style_id -> StyleRasterData
    for style_id in sorted(style_fonts.keys()):
        fontfile = style_fonts[style_id]
        fallback_fontfiles = []
        if fallback_style_fonts:
            if style_id != 0:
                fallback_fontfiles.extend(fallback_style_fonts.get(style_id, []))
            fallback_fontfiles.extend(fallback_style_fonts.get(0, []))
        print(f"  Rasterizing style {style_id}...", file=sys.stderr)
        raster_data[style_id] = rasterize_font_style(
            fontfile, size, intervals, style_id=style_id,
            force_autohint=force_autohint, fallback_fontfiles=fallback_fontfiles or None,
            darken_aa=darken_aa, tuning=tuning,
            axes=(style_axes or {}).get(style_id))

    # Pack binary sections for each style
    packed_sections = {}  # style_id -> tuple of section bytearrays
    for style_id, sd in raster_data.items():
        packed_sections[style_id] = pack_style_sections(sd)

    # Calculate data offsets (after header + TOC)
    data_start = HEADER_SIZE + style_count * STYLE_TOC_ENTRY_SIZE
    current_offset = data_start

    style_offsets = {}  # style_id -> absolute file offset
    for style_id in sorted(packed_sections.keys()):
        style_offsets[style_id] = current_offset
        current_offset += style_sections_total_size(packed_sections[style_id])

    # Build global header
    # V4 header: magic(8) + version(2) + flags(2) + styleCount(1) + reserved(19) = 32
    header = struct.pack("<8sHHB19s", MAGIC, CPFONT_VERSION, flags, style_count, bytes(19))
    assert len(header) == HEADER_SIZE

    # Build style TOC entries
    # Each entry: styleId(1) + pad(3) + intervalCount(4) + glyphCount(4) +
    #   advanceY(1) + ascender(2) + descender(2) + kernL(2) + kernR(2) +
    #   kernLCls(1) + kernRCls(1) + ligCount(1) + dataOffset(4) + reserved(4) = 32
    STYLE_TOC_FORMAT = "<B3xIIBhhHHBBBI4x"
    assert struct.calcsize(STYLE_TOC_FORMAT) == STYLE_TOC_ENTRY_SIZE

    toc_data = bytearray()
    for style_id in sorted(raster_data.keys()):
        sd = raster_data[style_id]
        if sd.advanceY > 255:
            print(f"ERROR: advanceY ({sd.advanceY}) exceeds uint8 range for "
                  f"style {style_id} size {size}. This likely means the font "
                  f"size is too large for this format.",
                  file=sys.stderr)
            sys.exit(1)
        toc_data += struct.pack(STYLE_TOC_FORMAT,
                                style_id,
                                len(sd.intervals), len(sd.all_glyphs),
                                sd.advanceY, sd.ascender, sd.descender,
                                len(sd.kern_left_classes), len(sd.kern_right_classes),
                                sd.kern_left_class_count, sd.kern_right_class_count,
                                len(sd.ligature_pairs),
                                style_offsets[style_id])

    # Write output
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    total_file_size = 0
    with open(output_path, "wb") as f:
        f.write(header)
        f.write(toc_data)
        for style_id in sorted(packed_sections.keys()):
            for section in packed_sections[style_id]:
                f.write(section)
        total_file_size = f.tell()

    # Print summary
    print(f"  Output: {output_path} (v4, {style_count} styles)", file=sys.stderr)
    print(f"    Header+TOC: {HEADER_SIZE + len(toc_data)} bytes", file=sys.stderr)
    for style_id in sorted(raster_data.keys()):
        sd = raster_data[style_id]
        secs = packed_sections[style_id]
        style_names = {0: "regular", 1: "bold", 2: "italic", 3: "bolditalic"}
        sname = style_names.get(style_id, str(style_id))
        ssize = style_sections_total_size(secs)
        print(f"    {sname}: {len(sd.all_glyphs)} glyphs, {len(sd.intervals)} intervals, "
              f"{ssize} bytes", file=sys.stderr)
    print(f"    Total: {total_file_size} bytes ({total_file_size / 1024 / 1024:.2f} MB)", file=sys.stderr)
    return total_file_size


def main():
    parser = argparse.ArgumentParser(
        description="Generate .cpfont files for SD card font loading.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Available interval presets: {', '.join(sorted(INTERVAL_PRESETS.keys()))}"
    )

    # Font file (positional, optional for multi-style mode)
    parser.add_argument("fontfile", nargs="?", default=None,
                        help="Path to the font file (single-style mode).")
    parser.add_argument("--intervals", dest="intervals",
                        help="Comma-separated additional interval presets (e.g., 'default,latin-ext,cjk-jp'). Base coverage is always included.")
    parser.add_argument("--size", type=int, dest="size",
                        help="Single font size to generate.")
    parser.add_argument("--sizes", dest="sizes",
                        help="Comma-separated sizes (e.g., '12,14,16,18').")
    parser.add_argument("--style", dest="style", default="regular",
                        choices=["regular", "bold", "italic", "bolditalic"],
                        help="Font style for single-style mode (default: regular).")
    parser.add_argument("--name", dest="name",
                        help="Font family name for output filenames (default: derived from font filename).")
    parser.add_argument("--force-autohint", dest="force_autohint", action="store_true",
                        help="Force FreeType auto-hinter instead of native font hinting.")
    parser.add_argument("--darken-aa", dest="darken_aa", action="store_true",
                        help="Use darker 2-bit anti-aliasing thresholds, matching the reading "
                             "fonts shipped ready-built.")
    parser.add_argument("-o", "--output", dest="output",
                        help="Output file path (for single-size mode).")
    parser.add_argument("--output-dir", dest="output_dir",
                        help="Output directory for multi-size mode.")
    parser.add_argument("--list-presets", action="store_true",
                        help="List available interval presets and exit.")

    # Multi-style mode: per-style font file arguments (generates v4 .cpfont)
    parser.add_argument("--regular", dest="font_regular",
                        help="Font file for regular style (enables multi-style v4 mode).")
    parser.add_argument("--bold", dest="font_bold",
                        help="Font file for bold style.")
    parser.add_argument("--italic", dest="font_italic",
                        help="Font file for italic style.")
    parser.add_argument("--bolditalic", dest="font_bolditalic",
                        help="Font file for bold-italic style.")
    parser.add_argument("--fallback-regular", dest="fallback_font_regular",
                        help="Fallback font file for regular style.")
    parser.add_argument("--fallback2-regular", dest="fallback2_font_regular",
                        help="Second fallback font file for regular style.")
    parser.add_argument("--fallback-bold", dest="fallback_font_bold",
                        help="Fallback font file for bold style.")
    parser.add_argument("--fallback-italic", dest="fallback_font_italic",
                        help="Fallback font file for italic style.")
    parser.add_argument("--fallback-bolditalic", dest="fallback_font_bolditalic",
                        help="Fallback font file for bold-italic style.")
    parser.add_argument("--default-fallback-font", dest="default_fallback_fonts",
                        action="append", default=[],
                        help="Bundled default fallback font file. Repeat to append multiple fonts after user fallbacks.")

    args = parser.parse_args()

    if args.list_presets:
        print("Available interval presets:")
        for name, ranges in sorted(INTERVAL_PRESETS.items()):
            total = sum(e - s + 1 for s, e in ranges)
            print(f"  {name:15s}  {len(ranges)} range(s), ~{total} codepoints")
        sys.exit(0)

    # Detect multi-style mode
    style_fonts = {}
    if args.font_regular:
        style_fonts[0] = args.font_regular
    if args.font_bold:
        style_fonts[1] = args.font_bold
    if args.font_italic:
        style_fonts[2] = args.font_italic
    if args.font_bolditalic:
        style_fonts[3] = args.font_bolditalic

    fallback_style_fonts = {}
    if args.fallback_font_regular:
        fallback_style_fonts.setdefault(0, []).append(args.fallback_font_regular)
    if args.fallback2_font_regular:
        fallback_style_fonts.setdefault(0, []).append(args.fallback2_font_regular)
    if args.fallback_font_bold:
        fallback_style_fonts.setdefault(1, []).append(args.fallback_font_bold)
    if args.fallback_font_italic:
        fallback_style_fonts.setdefault(2, []).append(args.fallback_font_italic)
    if args.fallback_font_bolditalic:
        fallback_style_fonts.setdefault(3, []).append(args.fallback_font_bolditalic)
    for default_fallback_font in args.default_fallback_fonts:
        fallback_style_fonts.setdefault(0, []).append(default_fallback_font)

    is_multistyle = len(style_fonts) > 0
    fontfile = args.fontfile

    # A font can be generated without choosing any extra presets; base coverage
    # is still added inside resolve_intervals().
    if not args.intervals:
        args.intervals = "base"

    intervals = resolve_intervals(args.intervals)

    # Determine sizes
    if args.sizes:
        sizes = [int(s.strip()) for s in args.sizes.split(",")]
    elif args.size:
        sizes = [args.size]
    else:
        print("Error: --size or --sizes is required", file=sys.stderr)
        sys.exit(1)

    # Validate early: single-style mode requires a font file
    if not is_multistyle and not fontfile:
        print("Error: fontfile is required in single-style mode", file=sys.stderr)
        sys.exit(1)

    # Determine font name
    if args.name:
        font_name = args.name
    elif is_multistyle:
        # Derive from the regular font file
        ref_file = style_fonts[min(style_fonts.keys())]
        base = os.path.splitext(os.path.basename(ref_file))[0]
        for suffix in ["-Regular", "-Bold", "-Italic", "-BoldItalic",
                       "-regular", "-bold", "-italic", "-bolditalic"]:
            if base.endswith(suffix):
                base = base[:-len(suffix)]
                break
        font_name = base
    else:
        base = os.path.splitext(os.path.basename(fontfile))[0]
        for suffix in ["-Regular", "-Bold", "-Italic", "-BoldItalic",
                       "-regular", "-bold", "-italic", "-bolditalic"]:
            if base.endswith(suffix):
                base = base[:-len(suffix)]
                break
        font_name = base

    if not is_multistyle:
        # Single font file provided: wrap as a single-style v4 font
        style_map = {"regular": 0, "bold": 1, "italic": 2, "bolditalic": 3}
        style_fonts[style_map[args.style]] = fontfile

    # Always generate v4 format
    if args.output and len(sizes) != 1:
        print("Error: --output can only be used with a single size", file=sys.stderr)
        sys.exit(1)
    output_dir = args.output_dir if args.output_dir else f"{font_name}/"
    total_size = 0
    for sz in sizes:
        if args.output and len(sizes) == 1:
            output_path = args.output
        else:
            filename = f"{font_name}_{sz}.cpfont"
            output_path = os.path.join(output_dir, filename)
        print(f"Generating {output_path} (size {sz}, {len(style_fonts)} style(s), v4)...", file=sys.stderr)
        total_size += generate_cpfont_multistyle(
            style_fonts, sz, intervals, output_path,
            force_autohint=args.force_autohint,
            fallback_style_fonts=fallback_style_fonts or None,
            darken_aa=args.darken_aa)
    print(f"\nTotal: {len(sizes)} files, {total_size / 1024 / 1024:.2f} MB", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except FontBuildError as e:
        # The workflow greps for this prefix to report the message to the user.
        print(f"BUILD ERROR: {e}", file=sys.stderr)
        sys.exit(1)

"""A fork of the CrossPoint website's .cpfont converter, with tuning knobs.

Upstream is crosspoint-tools/scripts/font-builder/; see UPSTREAM for the pin
and the refresh procedure. Forked rather than referenced because crossglyph adds
rasterization controls -- gamma, anti-aliasing thresholds, weight, slant,
hinting, stem darkening -- that upstream has no place for, and because a live
preview cannot afford to spawn a subprocess per keystroke.
"""
from . import arabic
from .convert import (INTERVAL_PRESETS, FontBuildError,
                      figure_glyph_overrides, generate_cpfont_multistyle,
                      gsub_ligature_sequences, ligature_codepoints,
                      parse_hex_range, resolve_intervals)
from .version import CPFONT_VERSION

__all__ = ["CPFONT_VERSION", "INTERVAL_PRESETS", "FontBuildError", "arabic",
           "figure_glyph_overrides", "generate_cpfont_multistyle",
           "gsub_ligature_sequences", "ligature_codepoints",
           "parse_hex_range", "resolve_intervals"]

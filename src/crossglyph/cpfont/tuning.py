"""Every rasterization knob, in one place.

These are the settings that decide how a glyph looks once it has been quantized
to two bits -- the stage where most of a face's character is won or lost, and
the one upstream exposes as a single boolean (`--darken-aa`).

Two groups, acting at different points:

  gamma, thresholds    on the coverage bitmap, after FreeType has rendered it
  weight, slant,       on the outline and on how FreeType fits it to the pixel
  hinting, stem_       grid, so they change the coverage the quantizer sees
  darkening

Which of the three thresholds matters depends on the reader's
Settings > Text > Anti-Aliasing switch: with it off, GfxRenderer paints every
non-zero level solid black (GfxRenderer.cpp:449) and only the first has any
effect.
"""
from __future__ import annotations

import dataclasses

HINTING = ("normal", "light", "none", "auto")


#: Figure styles. "default" is whatever the cmap gives; "proportional" applies
#: the font's GSUB `pnum` feature. Named rather than boolean so `tabular`
#: (`tnum`) and `oldstyle` (`onum`) can join without a schema change.
FIGURES = ("default", "proportional")


@dataclasses.dataclass(frozen=True)
class LineHeight:
    """A requested line pitch, in one of three units.

    Fonts disagree wildly about their own line height -- measured across 686
    faces, advanceY/em runs from 0.89 to 2.11 -- so the em-relative form is the
    one that makes families comparable: `1.15` means 1.15 x the em square
    whatever the font's hhea table claims. That is also CSS's unitless
    line-height semantics.
    """
    value: float
    mode: str            # "em" | "scale" | "px"

    @classmethod
    def parse(cls, raw: str) -> "LineHeight":
        text = raw.strip().lower()
        if text.endswith("px"):
            mode, number = "px", text[:-2]
        elif text.endswith("x"):
            mode, number = "scale", text[:-1]
        else:
            mode, number = "em", text
        try:
            value = float(number)
        except ValueError:
            raise ValueError(
                f"line_height must be a number, optionally suffixed with 'x' "
                f"(a multiple of the font's own height) or 'px', "
                f"got {raw!r}") from None
        if value <= 0:
            raise ValueError(f"line_height must be positive, got {raw!r}")
        return cls(value, mode)

    def resolve(self, natural: int, ppem: float) -> int:
        """The advanceY to store, clamped to the uint8 the format allows."""
        if self.mode == "px":
            pixels = self.value
        elif self.mode == "scale":
            pixels = self.value * natural
        else:
            pixels = self.value * ppem
        return max(1, min(255, round(pixels)))

    def __str__(self) -> str:
        if self.mode == "px":
            return f"{self.value:g}px"
        if self.mode == "scale":
            return f"{self.value:g}x"
        return f"{self.value:g}"


@dataclasses.dataclass(frozen=True)
class Tuning:
    # Curve applied to coverage before the 4-bit truncation. Above 1 darkens,
    # as it does in crengine -- see coverage_lut().
    gamma: float = 1.0
    # 4-bit cut points for levels 1, 2 and 3.
    thresholds: tuple[int, int, int] = (4, 8, 12)
    # Outline emboldening, in pixels at the rendered size.
    weight: float = 0.0
    # Shear, as a tangent. 0.25 is about 14 degrees.
    slant: float = 0.0
    hinting: str = "normal"
    # Which TrueType bytecode interpreter runs the font's own hinting.
    # FreeType's default is version 40, "roughly equivalent to the hinting
    # provided by DirectWrite ClearType" (ftdriver.h), which hints vertically
    # only: on a subpixel display, snapping a stem sideways costs more than it
    # buys. This picks version 35 instead, of which the same page says "only
    # grayscale and B/W rasterizing is supported" -- which is this panel. It
    # fits both axes, so a stem lands on a pixel instead of straddling two and
    # being drawn twice in grey. Measured over the 303 hinted faces here it
    # leaves 3.8% fewer midtone pixels, and a third fewer on faces like DejaVu.
    #
    # Version 38 is not a third choice: FreeType documents it as the same as 40
    # now that the Infinality code is gone, which is why this is a switch.
    #
    # Only reaches a TrueType face carrying bytecode, and only while that
    # bytecode is what draws it -- see convert.apply_interpreter.
    grayscale_hinting: bool = False
    # Rasterize each glyph as one bit per pixel rather than as coverage.
    #
    # The reader's Anti-Aliasing switch, off, paints every non-white level
    # solid black (GfxRenderer.cpp:449), and the first threshold sits at 4 of
    # 15 -- so a pixel a quarter covered goes black, and at 12px that fattens
    # strokes into each other. FreeType's own 1-bit rasterizer decides the
    # same question with dropout control instead, and keeps the strokes apart:
    # measured on DejaVu Serif at 12px, a third less ink and none of it the
    # ink that was holding the letters open.
    #
    # Not tied to that switch. A font built this way draws in two levels
    # whatever the page is set to, which is the only way to see what it does
    # to a face without changing the page underneath it.
    #
    # It is a build rather than a view: mono hinting rounds advances to whole
    # pixels, so between 2 and 12 of 26 lowercase advances move, and the text
    # sets to different lines.
    mono: bool = False
    stem_darkening: bool = False

    # --- advance metrics, not rasterization ---------------------------------
    # Line pitch. None keeps whatever the font's own hhea/OS-2 tables give.
    line_height: LineHeight | None = None
    # Tracking, in pixels, added to every glyph's advance.
    letter_spacing: float = 0.0
    # Added to U+0020 on top of letter_spacing, as CSS word-spacing is.
    word_spacing: float = 0.0

    # --- pair tables --------------------------------------------------------
    # GPOS kerning, as a factor. 1.0 is the font's own, 0.0 drops the table.
    # A face kerned for print often over-tightens at 12-13px, where one 4.4
    # fixed-point pixel is a large fraction of a stem.
    kerning: float = 1.0
    # GSUB ligatures. fi/fl often blur into one blob at four grey levels.
    ligatures: bool = True
    # GSUB figure style. "default" takes whatever the cmap gives, which is
    # usually tabular -- every digit padded to a common width so columns line
    # up. "proportional" applies the font's `pnum` feature, letting a 1 be
    # narrower than a 0, which sets better in prose than in a table. A font
    # with no pnum feature is unmoved.
    figures: str = "default"

    #: What upstream's --darken-aa does, as a threshold preset.
    DARKEN_AA = (3, 6, 10)

    def __post_init__(self) -> None:
        a, b, c = self.thresholds
        if not 0 < a < b < c < 16:
            raise ValueError(
                f"thresholds must be ascending within 1..15, got {self.thresholds}")
        if self.gamma <= 0:
            raise ValueError(f"gamma must be positive, got {self.gamma}")
        if self.hinting not in HINTING:
            raise ValueError(f"hinting must be one of {', '.join(HINTING)}, "
                             f"got {self.hinting!r}")
        if self.kerning < 0:
            raise ValueError(f"kerning must be zero or positive, "
                             f"got {self.kerning}")
        if self.figures not in FIGURES:
            raise ValueError(f"figures must be one of {', '.join(FIGURES)}, "
                             f"got {self.figures!r}")

    def coverage_lut(self) -> bytes | None:
        """256-entry curve for the 8-bit coverage, or None when it is identity.

        Applied before the converter truncates to 4 bits, so the curve has all
        256 levels to work with rather than 16.

        `1 - (1 - coverage) ** gamma`: the exponent acts on how much *white* is
        left rather than on the ink, so above 1 darkens. A plain
        `coverage ** gamma` runs the other way, which is standard arithmetic
        and the opposite of what every reader with this setting does.

        The shape is borrowed from crengine, which computes the same thing
        (crengine/Tools/GammaGen/gammagen.pl). Matching its numbers is not a
        goal -- it is a continuous knob here and a table of fixed levels there
        -- but it is a curve with a long history of being tuned against by
        eye, which beats inventing one. gamma of 1 is the identity either way.
        """
        if self.gamma == 1.0:
            return None
        return bytes(round(255 * (1 - (1 - i / 255) ** self.gamma))
                     for i in range(256))

    def load_flags(self, freetype) -> int:
        """FreeType load flags, without FT_LOAD_RENDER.

        The caller adds that itself, and omits it when it has to embolden the
        outline before rendering.
        """
        flags = freetype.FT_LOAD_NO_BITMAP
        # Sets the hinting target and the render mode together: FreeType reads
        # both from FT_LOAD_TARGET_MODE, so the glyph is fitted for a bilevel
        # grid and then rasterized onto one.
        if self.mono:
            flags |= freetype.FT_LOAD_TARGET_MONO
        if self.hinting == "light":
            flags |= freetype.FT_LOAD_TARGET_LIGHT
        elif self.hinting == "none":
            flags |= freetype.FT_LOAD_NO_HINTING
        elif self.hinting == "auto":
            flags |= freetype.FT_LOAD_FORCE_AUTOHINT
        return flags

    def as_dict(self) -> dict:
        """JSON-stable form, for the build stamp and the preview API.

        Every field, and it has to stay that way: the build stamp hashes this
        to decide whether a family needs rebuilding, so a knob missing here is
        a knob you can change in a .conf without the builder noticing.
        """
        return {"gamma": self.gamma, "thresholds": list(self.thresholds),
                "weight": self.weight, "slant": self.slant,
                "hinting": self.hinting,
                "grayscale_hinting": self.grayscale_hinting,
                "mono": self.mono, "stem_darkening": self.stem_darkening,
                "line_height": (str(self.line_height)
                                if self.line_height else None),
                "letter_spacing": self.letter_spacing,
                "word_spacing": self.word_spacing,
                "kerning": self.kerning, "ligatures": self.ligatures,
                "figures": self.figures}

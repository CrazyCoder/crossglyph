"""A page of type from a font source and a set of knobs.

Pure Python and no HTTP: the CLI, the tests and the server all come through
here, and when the static web version arrives this is the layer that has a
TypeScript twin rather than the layer that gets ported.

Every pixel is the device's. The .cpfont is built by the same converter that
builds the ones on the card, and the page is laid out and drawn by the
firmware's own engine through crossglyph.render. See docs/preview.md.
"""
from __future__ import annotations

import dataclasses
import pathlib
import tempfile
import typing
from collections.abc import Mapping

import freetype
from PIL import Image

from .. import cpfont, render
from ..cpfont.tuning import Tuning
from ..render import image
from . import markup
# One preset per language, and the one a request with no text of its own is
# drawn with. See samples.py for how each is built and where its words are from.
from .samples import SAMPLE_TEXT, SAMPLES

#: Codepoints every preview build carries whether or not the text names them.
#: The space is what the layout measures a word gap with -- getSpaceWidth reads
#: the advance of ' ' and nothing else (GfxRenderer.cpp:1866-1872) -- and the
#: hyphen is what a split word gets appended to it (ParsedText.cpp:1114-1117),
#: so a page with hyphenation on needs a glyph nobody typed.
ESSENTIAL_CODEPOINTS = (0x20, 0x2D)

#: Style ids, as the .cpfont container and EpdFontFamily::Style number them.
REGULAR, BOLD, ITALIC, BOLD_ITALIC = 0, 1, 2, 3

#: Alignment names as the layout engine numbers them (CssStyle.h:6).
ALIGNMENTS = {"justify": 0, "left": 1, "center": 2, "right": 3}

#: The device's own line spacing values for SD card fonts
#: (CrossPointSettings.cpp:268-280).
LINE_SPACINGS = {"tight": 95, "normal": 100, "wide": 110}

#: Reader ids as the render core numbers them.
DEVICES = {"x4": 0, "x3": 1}


@dataclasses.dataclass(frozen=True)
class PageSpec:
    """How the page is laid out -- the reader's settings, not the font's."""

    device: str = "x4"

    # The device's own shipped values (CrossPointSettings.h:217, 239-246), not
    # the prettier combination: hyphenation is off out of the box, and extra
    # paragraph spacing is on -- which is also what turns the first-line indent
    # off (ParsedText.cpp:588-602). A preview that started anywhere else would
    # be tuning against a page the reader does not show until its owner has
    # changed two settings.
    margin: int = 5                     # screenMargin, 5..40
    alignment: str = "justify"
    hyphenation: bool = False
    extra_paragraph_spacing: bool = True
    line_spacing: str = "normal"
    #: Which language's hyphenation patterns to use. The reader takes this from
    #: the book's own metadata; here the text is whatever you paste, so it is a
    #: knob. Empty means no hyphenation patterns at all. It matches the sample
    #: a request with no text of its own is drawn with; the page moves both to
    #: the browser's language the first time it is opened.
    language: str = "en"
    #: The device's Settings > Text > Anti-Aliasing toggle
    #: (EpubReaderActivity.cpp:1667). Off is 1-bit: the reader never draws the
    #: grey planes, and the black-and-white pass paints every non-white level
    #: solid black. Tuning a font *for* that mode is its own use case -- it is
    #: one quantizer threshold that matters rather than three.
    antialiased: bool = True
    #: The device's night mode (Settings > screenInverted). It is not a layout
    #: option and never reaches the core: the reader draws the page exactly as
    #: it does by day and the display complements the framebuffer on its way to
    #: the panel (ActivityManager.cpp:60, FreeInkDisplay.cpp:577), which is why
    #: it applies to the reading surfaces and not to the menus over them.
    inverted: bool = False

    def device_id(self) -> int:
        """The render core's id for this reader, validated."""
        try:
            return DEVICES[self.device]
        except KeyError:
            raise ValueError(
                f"unknown device {self.device!r}; "
                f"expected one of {', '.join(sorted(DEVICES))}") from None

    def to_call_args(self) -> tuple[int, int, int, int, int]:
        """The five ints rc_page_set_spec takes, validated."""
        self.device_id()
        if self.alignment not in ALIGNMENTS:
            raise ValueError(
                f"unknown alignment {self.alignment!r}; "
                f"expected one of {', '.join(sorted(ALIGNMENTS))}")
        if self.line_spacing not in LINE_SPACINGS:
            raise ValueError(
                f"unknown line_spacing {self.line_spacing!r}; "
                f"expected one of {', '.join(sorted(LINE_SPACINGS))}")
        if not 5 <= self.margin <= 40:
            raise ValueError(
                f"margin {self.margin} is outside the device's 5..40")
        return (self.margin, ALIGNMENTS[self.alignment], int(self.hyphenation),
                int(self.extra_paragraph_spacing),
                LINE_SPACINGS[self.line_spacing])


def coverage_for(text: str,
                 sources: pathlib.Path | str | Mapping[int, pathlib.Path | str],
                 ) -> tuple[tuple[int, int], ...]:
    """The codepoints this text needs, as .cpfont intervals.

    A page can only draw what is on it, so a preview build is sized to the text
    in the box rather than to a coverage preset: a few dozen glyphs instead of
    the several hundred a preset resolves to, and the difference is most of the
    build. Turn a knob and the rasterizer redoes the alphabet you are looking
    at, not an alphabet you are not.

    Three things the text does not say for itself go in too: the space and the
    hyphen (see ESSENTIAL_CODEPOINTS), the output codepoints of any ligature
    the text can trigger -- nobody types U+FB01, and a ligature whose output is
    missing from the build is dropped rather than drawn -- and, for Arabic, the
    joined shape of every letter on the page. The device shapes Arabic before
    it looks a glyph up, so it asks for the shape and never for the letter, and
    a build holding only what was typed holds nothing it can draw.

    Markup marks are stripped first, so `*bold*` does not order an asterisk.
    """
    if not isinstance(sources, Mapping):
        sources = {REGULAR: sources}
    codepoints = page_codepoints(text)
    for source in sources.values():
        try:
            codepoints |= cpfont.ligature_codepoints(str(source), codepoints)
        # This reads the face before the rasterizer gets to it, so it is where
        # a file that is not a font first shows up. fontTools raises its own
        # class for that, which nothing downstream knows; the converter says
        # the same thing about a malformed face and this borrows its words.
        except Exception as exc:            # noqa: BLE001 -- see above
            raise cpfont.FontBuildError(
                f"The font file '{pathlib.Path(source).name}' appears to be "
                f"corrupt or malformed and could not be processed ({exc}). "
                f"Try re-exporting the font or uploading a different file."
            ) from exc

    return cpfont.arabic.implied_coverage(as_intervals(codepoints))


def faces_for(text: str,
              sources: pathlib.Path | str | Mapping[int, pathlib.Path | str],
              ) -> dict[int, pathlib.Path | str]:
    """The faces this text actually sets in, of the ones offered.

    The same argument as coverage_for, one level up: a page can only draw the
    styles it uses, and every style in the build is a full rasterization of the
    coverage -- so a plain paragraph rasterizes four times over for three faces
    nothing on the page is set in. The markup says which styles the words wear,
    and that is exactly the set worth building.

    Regular stays in whatever the text says: it is what the device falls back
    to for a style a family has not got (EpdFontFamily.cpp:3-18), and a
    container with no regular in it is not a shape any caller should have to
    reason about.
    """
    if not isinstance(sources, Mapping):
        sources = {REGULAR: sources}
    _, styles = markup.parse(text)
    wanted = set(styles) | {REGULAR}
    return {style: path for style, path in sources.items() if style in wanted}


def missing_codepoints(sources: Mapping[int, pathlib.Path | str],
                       coverage: tuple[tuple[int, int], ...]) -> tuple[int, ...]:
    """The codepoints in `coverage` that none of these faces has a glyph for.

    The question a fallback exists to answer, asked before any fallback is
    opened: on the usual page every character is in the family being tuned, so
    this is what keeps the fallbacks free when they have nothing to do. One
    charmap lookup per codepoint over a few dozen codepoints -- FreeType has
    the cmap in memory once the face is open, and each face is opened once.
    """
    faces = []
    for source in sources.values():
        try:
            faces.append(freetype.Face(str(source)))
        except Exception:                   # noqa: BLE001 -- the rasterizer
            return ()                       # will report it properly
    return tuple(code for start, end in coverage
                 for code in range(start, end + 1)
                 if all(face.get_char_index(code) == 0 for face in faces))


def uncovered(sources: Mapping[int, pathlib.Path | str],
              coverage: tuple[tuple[int, int], ...]) -> bool:
    """Whether this text needs a fallback at all."""
    return bool(missing_codepoints(sources, coverage))


def needed_fallbacks(sources: Mapping[int, pathlib.Path | str],
                     coverage: tuple[tuple[int, int], ...],
                     fallbacks: tuple[pathlib.Path | str, ...],
                     ) -> tuple[pathlib.Path | str, ...]:
    """Which of `fallbacks` actually supply something, in the order given.

    A build's list is a dozen faces and 19 MB, and the converter appends it to
    every style -- so handing it the whole list to fill one Greek letter opens
    forty-odd faces for one glyph. This walks it once, keeps the faces that
    answer a codepoint still missing, and stops when nothing is. First face
    wins, which is the order the converter would have used anyway.
    """
    return fallback_split(sources, coverage, fallbacks).faces


def page_codepoints(text: str) -> set[int]:
    """What the page will actually try to draw.

    The characters somebody typed, plus the space and hyphen the layout
    supplies for itself (ESSENTIAL_CODEPOINTS): a face missing the hyphen
    really does leave a gap, because hyphenation appends one nobody typed.

    This is coverage_for without the ligature outputs, and the difference is
    the whole of it. A build has to carry U+FB00 or the converter drops the
    `ff` rule; a page that cannot draw U+FB00 has no hole in it, because
    nobody types one. Ask this when the question is about the page, and
    coverage_for when it is about the build.
    """
    plain, _ = markup.parse(text)
    # Control characters are not glyphs: the newline is a paragraph break to
    # the layout, and a tab or a stray \r would rasterize as nothing.
    codepoints = {code for code in map(ord, plain)
                  if code >= 0x20 and code != 0x7F}
    codepoints.update(ESSENTIAL_CODEPOINTS)
    return codepoints


def as_intervals(codepoints: set[int]) -> tuple[tuple[int, int], ...]:
    """Codepoints as the runs a .cpfont's interval table wants."""
    intervals: list[tuple[int, int]] = []
    for code in sorted(codepoints):
        if intervals and code == intervals[-1][1] + 1:
            intervals[-1] = (intervals[-1][0], code)
        else:
            intervals.append((code, code))
    return tuple(intervals)


class Drawable(typing.NamedTuple):
    """What a list of fallbacks answers: the faces to open, and the leftovers."""
    faces: tuple[pathlib.Path | str, ...]
    undrawn: frozenset[int]


def fallback_split(sources: Mapping[int, pathlib.Path | str],
                   coverage: tuple[tuple[int, int], ...],
                   fallbacks: tuple[pathlib.Path | str, ...]) -> Drawable:
    """The fallbacks worth opening, and what nothing on the list can draw.

    One walk answers both, and the second answer is not a detail: the layout
    gives a glyph nobody has no width at all, so a paragraph of them comes out
    as blank space rather than as a row of boxes. A page with a hole in it
    looks exactly like a page that came out short.
    """
    missing = set(missing_codepoints(sources, coverage))
    keep = []
    for face_path in fallbacks:
        if not missing:
            break
        try:
            face = freetype.Face(str(face_path))
        except Exception:                   # noqa: BLE001 -- not this layer's
            keep.append(face_path)          # to report; the rasterizer says it
            continue
        supplied = {code for code in missing if face.get_char_index(code)}
        if supplied:
            keep.append(face_path)
            missing -= supplied
    return Drawable(tuple(keep), frozenset(missing))


def build_font(sources: pathlib.Path | str | Mapping[int, pathlib.Path | str],
               size: float, *, tuning: Tuning | None = None,
               coverage: tuple[tuple[int, int], ...] | None = None,
               fallbacks: tuple[pathlib.Path | str, ...] = (),
               axes: Mapping[int, Mapping[str, float]] | None = None) -> bytes:
    """Rasterize a .cpfont in memory, from one face or up to four.

    A bare path is the regular face on its own, which is all a first look at a
    font needs. Pass {REGULAR: ..., ITALIC: ...} to get emphasis on the page;
    any face left out simply falls back to regular when drawn
    (EpdFontFamily.cpp:3-18), exactly as it would on the device.

    `coverage` is what coverage_for returned for the text you are about to draw;
    None builds for the sample text. The two have to agree -- a font built for
    one text and used to draw another leaves every codepoint the first one did
    not name blank, silently -- so preview() takes the text once and derives it.

    `fallbacks` are the faces a build would fill from, in the same order the
    converter takes them: the family's own fallback families first, then the
    bundled Noto set. They are opened only when the text needs them -- every
    codepoint the family already has is drawn from the family, so on a page
    where nothing is missing the list costs one charmap pass and no build.
    That is what makes them affordable here at all: sized to the text, a
    fallback is a handful of glyphs rather than the three thousand a preset
    would order.

    `axes` are per-style design coordinates for a variable font, the same ones
    the build uses. Two faces fill four slots that way, so a page drawn without
    them shows the file's default instance in every slot -- one weight, four
    times over.
    """
    if not isinstance(sources, Mapping):
        sources = {REGULAR: sources}
    if coverage is None:
        coverage = coverage_for(SAMPLE_TEXT, sources)
    if fallbacks and not uncovered(sources, coverage):
        fallbacks = ()
    with tempfile.TemporaryDirectory() as work:
        path = pathlib.Path(work) / "preview.cpfont"
        cpfont.generate_cpfont_multistyle(
            {style: str(source) for style, source in sources.items()},
            size, list(coverage), str(path), tuning=tuning,
            # Style 0's list is appended to all four styles by
            # generate_cpfont_multistyle itself, which is how a regular-only
            # fallback covers a bold word too -- and what the build does.
            fallback_style_fonts={0: [str(face) for face in fallbacks]}
            if fallbacks else None,
            style_axes={style: dict(coords)
                        for style, coords in (axes or {}).items()
                        if style in sources and coords} or None)
        return path.read_bytes()


def preview_page(font_bytes: bytes, text: str = SAMPLE_TEXT,
                 spec: PageSpec = PageSpec()) -> Image.Image:
    """Draw a page with a .cpfont that has already been built.

    The text may carry *bold* and _italic_ marks; a face the font does not have
    falls back to regular, as it would on the device.

    The spec goes to the shared module because that is the one the render will
    use: the core keeps its layout options in module globals, so a spec set on
    a private instance would be dropped without a word. For the same reason the
    lock is held across both -- setting a spec and then drawing with it is one
    operation, and a second thread landing between them would draw this page
    with the other one's settings.
    """
    plain, styles = markup.parse(text)
    with render.exclusive() as module:
        if module.call("rc_set_device", spec.device_id()) != 1:
            raise ValueError(f"the render core rejected device {spec.device!r}")
        module.call("rc_page_set_spec", *spec.to_call_args())
        module.call("rc_page_set_language",
                    module.write(spec.language.encode("utf-8") + b"\x00"))
        return image.render_page_png(font_bytes, plain,
                                     antialiased=spec.antialiased,
                                     styles=styles, inverted=spec.inverted)


def preview(sources: pathlib.Path | str | Mapping[int, pathlib.Path | str],
            size: float, text: str = SAMPLE_TEXT, *,
            tuning: Tuning | None = None,
            fallbacks: tuple[pathlib.Path | str, ...] = (),
            spec: PageSpec = PageSpec()) -> Image.Image:
    """Build a .cpfont from one or more TTF/OTFs and draw a page with it."""
    faces = faces_for(text, sources)
    return preview_page(
        build_font(faces, size, tuning=tuning, fallbacks=fallbacks,
                   coverage=coverage_for(text, faces)),
        text, spec)

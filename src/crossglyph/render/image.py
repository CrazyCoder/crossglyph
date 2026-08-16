"""Compose the device's three render passes into one greyscale page.

The reader draws a page three times -- a black-and-white pass, then the two
grey planes (EpubReaderActivity.cpp:1833-1856) -- and the panel resolves them
into four levels. These are the simulator's own values and its own composition
(crosspoint-simulator/src/HalDisplay.cpp:45-48, 195-224), so a preview here and
a simulator screenshot of the same text are directly comparable.

Two things about the framebuffer the passes land in:

* It is in the selected reader's *panel* layout, one bit per pixel, MSB first:
  800x480 for X4 or 792x528 for X3. The portrait page is logical, and
  GfxRenderer rotates onto the landscape panel as it draws
  (GfxRenderer.cpp:218). Un-rotating is this module's job.
* The BW pass paints -- it starts from white paper and *clears* a bit for ink.
  The grey planes mark -- they start empty and *set* a bit for a pixel that
  needs shading (GfxRenderer.cpp:452-458). Hence the different clear bytes, and
  hence a set bit meaning the opposite thing in the two kinds of plane.
"""
from __future__ import annotations

from PIL import Image, ImageChops

from . import RenderModule, exclusive

WHITE, LIGHT, DARK, BLACK = 255, 200, 96, 0
GREYS = (BLACK, DARK, LIGHT, WHITE)

#: Night mode, which the device does on the way to the panel rather than while
#: drawing: the framebuffer is complemented byte by byte just before it is
#: pushed (FreeInkDisplay.cpp:577, `~buffer[i]`), and put back straight after.
#: So the page is laid out and rasterized exactly as it is by day, and what
#: changes is which level each pixel ends up at -- paper and ink swap, and the
#: two greys swap with each other.
#:
#: A complement of the level, not of the value: these four are the panel's own
#: greys and not an even ramp, so 255 minus a value would ask for 55 and 159,
#: which are not levels this panel can make.
INVERTED = {WHITE: BLACK, LIGHT: DARK, DARK: LIGHT, BLACK: WHITE}
INVERT_TABLE = [INVERTED.get(value, 255 - value) for value in range(256)]


def invert_levels(page: Image.Image) -> Image.Image:
    """The page as night mode shows it."""
    return page.point(INVERT_TABLE)


BW, GRAYSCALE_LSB, GRAYSCALE_MSB = 0, 1, 2

#: What each pass starts from: white paper for the BW pass, an empty plane for
#: the two grey ones.
CLEAR_PAPER, CLEAR_PLANE = 0xFF, 0x00

#: Where the line is drawn on the page by default. The y is the *top* of the
#: line box, not the baseline: drawText adds the font's ascender to reach the
#: baseline itself (GfxRenderer.cpp:570).
ORIGIN_X, ORIGIN_Y = 10, 40


def _read_pass(module: RenderModule, draw, mode: int,
               clear: int) -> Image.Image:
    """One pass, as a 1-bit image still in the panel's own layout."""
    if draw(mode, clear) < 0:
        raise ValueError(
            "the render core could not lay this page out -- most likely a font "
            "whose line height came back as zero")
    return Image.frombytes("1", (module.call("rc_panel_width"),
                                 module.call("rc_panel_height")),
                           module.read(module.call("rc_framebuffer"),
                                       module.call("rc_framebuffer_size")))


def _compose(module: RenderModule, draw, antialiased: bool,
             inverted: bool = False) -> Image.Image:
    """Run the device's passes through `draw(mode, clear)` and compose them.

    `draw` renders one pass into the framebuffer; everything else here is the
    same for a single line and for a whole page.
    """
    paper = _read_pass(module, draw, BW, CLEAR_PAPER)
    ink = ImageChops.invert(paper)

    panel = Image.new("L", paper.size, WHITE)
    panel.paste(BLACK, mask=ink)
    if antialiased:
        # Over ink: the MSB plane alone is light grey, and the LSB plane is
        # dark grey whether or not the MSB is set -- so painting light first
        # and dark over it reproduces HalDisplay.cpp:195-224 exactly. Both are
        # masked by the ink because the simulator leaves white paper alone
        # however the planes are marked.
        msb = _read_pass(module, draw, GRAYSCALE_MSB, CLEAR_PLANE)
        lsb = _read_pass(module, draw, GRAYSCALE_LSB, CLEAR_PLANE)
        panel.paste(LIGHT, mask=ImageChops.logical_and(ink, msb))
        panel.paste(DARK, mask=ImageChops.logical_and(ink, lsb))

    # Last, as the device does it: after every pass has been composed, on the
    # way out. Inverting a plane instead would invert the paper the grey ones
    # are masked against, which is a different picture.
    if inverted:
        panel = invert_levels(panel)

    # Panel back to page: logical (x, y) lives at panel (y, height - 1 - x),
    # the inverse of GfxRenderer's Portrait rotation (GfxRenderer.cpp:218).
    return panel.transpose(Image.Transpose.ROTATE_270)


def _load(module: RenderModule, font_bytes: bytes) -> None:
    if module.call("rc_font_load", module.write(font_bytes),
                   len(font_bytes)) != 1:
        raise ValueError("the render core could not parse these .cpfont bytes")


def render_png(font_bytes: bytes, text: str, antialiased: bool = True,
               x: int = ORIGIN_X, y: int = ORIGIN_Y) -> Image.Image:
    """Draw one line of text with a .cpfont, exactly as the device would.

    `antialiased` off is the device's own black-and-white mode, which paints
    every non-white level solid black (GfxRenderer.cpp:449) rather than
    thresholding it -- so the result is what the panel would show, not a
    flattened version of the grey render.
    """
    with exclusive() as module:
        _load(module, font_bytes)
        pointer = module.write(text.encode("utf-8") + b"\x00")
        return _compose(
            module,
            lambda mode, clear: module.call("rc_render", pointer, x, y, mode,
                                            clear),
            antialiased)


def render_page_png(font_bytes: bytes, text: str, antialiased: bool = True,
                    styles: bytes | None = None,
                    inverted: bool = False) -> Image.Image:
    """Draw a page of paragraphs, separated by newlines.

    The same three passes as render_png; the difference is that the device's
    layout engine decides where the lines break, where they are justified and
    where words hyphenate, rather than the caller placing one string.

    `styles` is one EpdFontFamily::Style byte per word, or None for all-regular
    -- see crossglyph.preview.markup for where they come from.
    """
    with exclusive() as module:
        _load(module, font_bytes)
        pointer = module.write(text.encode("utf-8") + b"\x00")
        styles_pointer = module.write(styles) if styles else 0
        return _compose(
            module,
            lambda mode, clear: module.call("rc_page_render", pointer,
                                            styles_pointer,
                                            len(styles or b""), mode, clear),
            antialiased, inverted)

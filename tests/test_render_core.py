"""The render core: the firmware's own drawing code, compiled to wasm."""
import pathlib

import pytest

import fontpaths

from crossglyph import render

WASM = render.WASM_PATH
needs_wasm = pytest.mark.skipif(
    render.is_stale(),
    reason="the render core is missing or was built from other firmware; "
           "run src/render/build.sh")


@needs_wasm
def test_the_module_loads_and_reports_its_abi():
    assert render.load_module().call("rc_abi_version") == 1


@needs_wasm
def test_the_cpp_standard_library_survived_the_build():
    """std::vector is the part bare clang could not build without a sysroot."""
    module = render.load_module()
    data = bytes([1, 2, 3, 250])
    pointer = module.write(data)
    assert module.call("rc_probe_sum", pointer, len(data)) == 256


@needs_wasm
def test_the_import_surface_is_exactly_what_we_expect():
    """The property the browser phase rests on, asserted rather than intended.

    Not zero: libc links stdio unconditionally, so three WASI functions we
    never call come along. They are standard, so any host can satisfy them.
    What must not appear is anything Emscripten-specific -- that is what
    -sPURE_WASI keeps out, and what this test would catch coming back.
    """
    assert render.module_imports(WASM) == render.EXPECTED_IMPORTS


@needs_wasm
def test_nothing_emscripten_specific_is_imported():
    assert not any(i.startswith("env.")
                   for i in render.module_imports(WASM)), \
        "an Emscripten-specific import would need faking on a non-emcc host"


def test_a_missing_core_says_how_to_build_it(tmp_path):
    with pytest.raises(render.RenderCoreMissing, match="build.sh"):
        render.load_module(tmp_path / "absent.wasm")


# --- staleness ------------------------------------------------------------


@pytest.fixture
def stamped(tmp_path, monkeypatch):
    """A built core with a stamp, both redirected away from the real build."""
    wasm = tmp_path / "render.wasm"
    wasm.write_bytes(b"\0asm")
    stamp = tmp_path / "render.built-from.json"
    monkeypatch.setattr(render, "WASM_PATH", wasm)
    monkeypatch.setattr(render, "STAMP_PATH", stamp)
    monkeypatch.setattr(render, "firmware_commit", lambda source=None: "abc123")
    return stamp


def _write_stamp(stamp, **fields):
    import json
    stamp.write_text(json.dumps(fields), encoding="utf-8")


def test_a_missing_core_counts_as_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "WASM_PATH", tmp_path / "absent.wasm")
    monkeypatch.setattr(render, "STAMP_PATH", tmp_path / "absent.json")
    assert render.is_stale() is True


def test_a_stamp_matching_the_firmware_commit_is_current(stamped):
    _write_stamp(stamped, firmware="abc123")
    assert render.is_stale() is False


def test_a_moved_firmware_makes_it_stale(stamped):
    _write_stamp(stamped, firmware="def456")
    assert render.is_stale() is True


def test_a_core_with_no_stamp_counts_as_stale(stamped):
    """The simulator's rule: a build that kept no record of where it came from
    is not a build we can vouch for. Costs one rebuild the first time."""
    assert not stamped.exists()
    assert render.is_stale() is True
    assert render.build_stamp() is None


def test_an_unreadable_stamp_counts_as_stale(stamped):
    stamped.write_text("{ this is not json", encoding="utf-8")
    assert render.is_stale() is True


def test_staleness_is_judged_against_the_checkout_that_is_there(
        tmp_path, monkeypatch):
    """The stamp records a commit and not a path, so the comparison is against
    the sibling checkout, or whatever $CROSSGLYPH_FIRMWARE names."""
    wasm = tmp_path / "render.wasm"
    wasm.write_bytes(b"\0asm")
    stamp = tmp_path / "render.built-from.json"
    monkeypatch.setattr(render, "WASM_PATH", wasm)
    monkeypatch.setattr(render, "STAMP_PATH", stamp)
    monkeypatch.setattr(render, "firmware_commit", lambda source=None: "here")

    _write_stamp(stamp, firmware="here")
    assert render.is_stale() is False
    _write_stamp(stamp, firmware="elsewhere")
    assert render.is_stale() is True


def test_a_stale_core_says_so_and_loads_anyway(stamped, capsys, monkeypatch):
    """An older renderer draws the page that older firmware drew, which beats
    no preview. The warning is for whoever moved the checkout, because they
    are the one person who can rebuild it."""
    _write_stamp(stamped, firmware="def456")
    monkeypatch.setattr(render, "_said_stale", False)
    monkeypatch.setattr(render, "RenderModule", lambda path: "loaded")

    assert render.load_module() == "loaded"
    said = capsys.readouterr().err
    assert "def456" in said, "say which build it is, so the message is checkable"
    assert "build.sh" in said, "and how to stop seeing it"


def test_the_stale_warning_is_said_once(stamped, capsys, monkeypatch):
    """A page redraws on every knob turn, and a hundred copies of a warning is
    one nobody reads."""
    _write_stamp(stamped, firmware="def456")
    monkeypatch.setattr(render, "_said_stale", False)
    monkeypatch.setattr(render, "RenderModule", lambda path: "loaded")

    render.load_module()
    capsys.readouterr()
    render.load_module()
    assert capsys.readouterr().err == ""


def test_an_explicit_path_is_taken_at_its_word(stamped, tmp_path):
    """Staleness is a fact about the built module, not about any file someone
    names -- a caller passing a path has already said which one they mean."""
    _write_stamp(stamped, firmware="def456")
    with pytest.raises(render.RenderCoreMissing, match="not found"):
        render.load_module(tmp_path / "somewhere-else.wasm")


def test_the_firmware_commit_of_a_directory_that_is_not_a_clone_is_unknown(
        tmp_path):
    assert render.firmware_commit(tmp_path) is None


SRC = fontpaths.truetype()
needs_font = pytest.mark.skipif(SRC is None,
                                reason="set CROSSGLYPH_TEST_FONT to a TTF")


def _cpfont(tmp_path, intervals="base", **kwargs):
    """A real .cpfont, built by the converter these tests share with the CLI."""
    from crossglyph import cpfont
    path = tmp_path / "probe.cpfont"
    cpfont.generate_cpfont_multistyle(
        {0: str(SRC)}, 13, cpfont.resolve_intervals(intervals), str(path),
        **kwargs)
    return path


@needs_wasm
@needs_font
def test_a_real_cpfont_parses_inside_the_module(tmp_path):
    """The device's own parser and ours must agree about the same bytes."""
    from crossglyph import fontbuild

    path = _cpfont(tmp_path)
    blob = path.read_bytes()
    module = render.load_module()
    assert module.call("rc_font_load", module.write(blob), len(blob)) == 1

    ours = fontbuild.style_metrics(path)
    assert module.call("rc_font_advance_y") == ours.advance_y
    assert module.call("rc_font_ascender") == ours.ascender
    assert module.call("rc_font_descender") == ours.descender


@needs_wasm
@needs_font
def test_glyphs_reach_ram_only_once_prewarmed(tmp_path):
    """SdCardFont keeps the glyph table on storage and warms only what is
    asked for (SdCardFont.cpp:1085). Nothing can be drawn before that, which
    makes prewarm a precondition of rendering rather than an optimisation."""
    blob = _cpfont(tmp_path).read_bytes()
    module = render.load_module()
    module.call("rc_font_load", module.write(blob), len(blob))

    assert module.call("rc_font_cached_glyphs") == 0
    assert module.call("rc_font_prewarm", module.write(b"abc\x00")) >= 0
    assert module.call("rc_font_cached_glyphs") >= 3


@needs_wasm
@needs_font
def test_a_font_without_a_replacement_glyph_reports_one_miss(tmp_path):
    """prewarm always requests U+FFFD alongside the text, and the converter
    drops codepoints the face has no glyph for -- sample.ttf has no U+FFFD.
    So one miss here is the device being right, not the module being wrong."""
    blob = _cpfont(tmp_path).read_bytes()
    module = render.load_module()
    module.call("rc_font_load", module.write(blob), len(blob))
    assert module.call("rc_font_prewarm", module.write(b"abc\x00")) == 1


@needs_wasm
def test_prewarming_without_a_font_is_an_error(tmp_path):
    module = render.load_module()
    assert module.call("rc_font_prewarm", module.write(b"abc\x00")) == -1


@needs_wasm
@needs_font
def test_prewarming_more_text_caches_more_glyphs(tmp_path):
    blob = _cpfont(tmp_path).read_bytes()
    module = render.load_module()
    module.call("rc_font_load", module.write(blob), len(blob))
    module.call("rc_font_prewarm", module.write(b"ab\x00"))
    few = module.call("rc_font_cached_glyphs")
    module.call("rc_font_prewarm", module.write(b"abcdefghijklm\x00"))
    assert module.call("rc_font_cached_glyphs") > few


@needs_wasm
@needs_font
def test_a_tuned_line_height_reaches_the_module(tmp_path):
    """End to end: the knob changes the file, the device's parser sees it."""
    from crossglyph.cpfont.tuning import LineHeight, Tuning

    blob = _cpfont(tmp_path,
                   tuning=Tuning(line_height=LineHeight.parse("24px"))).read_bytes()
    module = render.load_module()
    module.call("rc_font_load", module.write(blob), len(blob))
    assert module.call("rc_font_advance_y") == 24


@needs_wasm
def test_nothing_is_loaded_before_a_font_is(tmp_path):
    assert render.load_module().call("rc_font_advance_y") == 0


# --- rendering ------------------------------------------------------------

BW, GRAYSCALE_LSB, GRAYSCALE_MSB = 0, 1, 2


def _loaded(tmp_path, **kwargs):
    blob = _cpfont(tmp_path, **kwargs).read_bytes()
    module = render.load_module()
    assert module.call("rc_font_load", module.write(blob), len(blob)) == 1
    return module


def _draw(module, text, mode=BW, clear=0xFF, x=10, y=40):
    module.call("rc_render", module.write(text.encode("utf-8") + b"\x00"),
                x, y, mode, clear)
    return module.read(module.call("rc_framebuffer"),
                       module.call("rc_framebuffer_size"))


@needs_wasm
def test_the_page_is_portrait_and_the_panel_is_landscape():
    """The 480x800 page everyone talks about is logical; the panel underneath
    is 800x480 and GfxRenderer rotates onto it (GfxRenderer.cpp:218). The
    framebuffer is in panel layout, so the host has to un-rotate it."""
    module = render.load_module()
    assert (module.call("rc_screen_width"),
            module.call("rc_screen_height")) == (480, 800)
    assert (module.call("rc_panel_width"),
            module.call("rc_panel_height")) == (800, 480)
    assert module.call("rc_framebuffer_size") == 800 // 8 * 480


@needs_wasm
def test_a_single_pixel_reaches_the_framebuffer():
    """Separates the pixel path from the text path. This caught the bug where
    an `inline HalDisplay display;` member array gave GfxRenderer a null
    framebuffer while api.cpp saw a valid one -- silently, since the assert
    guarding it is compiled out at -O2."""
    module = render.load_module()
    assert module.call("rc_probe_write_target") == \
        module.call("rc_probe_framebuffer_ptr"), \
        "the renderer is drawing into a different buffer than we read"
    module.call("rc_probe_pixel", 100, 100)
    frame = module.read(module.call("rc_framebuffer"),
                        module.call("rc_framebuffer_size"))
    assert sum(8 - bin(b).count("1") for b in frame) == 1


@needs_wasm
@needs_font
def test_rendering_text_marks_the_framebuffer(tmp_path):
    module = _loaded(tmp_path)
    frame = _draw(module, "Hello")
    assert frame.count(0xFF) < len(frame), "nothing was drawn"


@needs_wasm
@needs_font
def test_an_empty_string_leaves_the_framebuffer_white(tmp_path):
    module = _loaded(tmp_path)
    frame = _draw(module, "")
    assert frame == b"\xff" * len(frame)


@needs_wasm
@needs_font
def test_wider_text_marks_more_pixels(tmp_path):
    """Guards against a stub that marks a fixed region regardless of input."""
    module = _loaded(tmp_path)

    def ink(text):
        return sum(bin(b).count("0") for b in _draw(module, text))

    assert ink("iiii") < ink("WWWW")


@needs_wasm
@needs_font
def test_the_grey_planes_differ_from_the_black_and_white_pass(tmp_path):
    """The three passes are what the device composes into four levels
    (EpubReaderActivity.cpp:1833-1856); if they were identical there would be
    no antialiasing to show."""
    module = _loaded(tmp_path)
    bw = _draw(module, "Wave", BW, clear=0xFF)
    lsb = _draw(module, "Wave", GRAYSCALE_LSB, clear=0x00)
    msb = _draw(module, "Wave", GRAYSCALE_MSB, clear=0x00)
    assert lsb != msb, "the two grey planes carry the same marks"
    assert any(b for b in lsb), "the LSB plane is empty"
    assert bw != lsb


# --- composing the three passes into an image -----------------------------


def _levels(png):
    """The grey levels present, without walking 384,000 pixels in Python."""
    return {value for value, count in enumerate(png.histogram()) if count}


@needs_wasm
@needs_font
def test_the_image_uses_the_simulators_grey_levels(tmp_path):
    from crossglyph.render import image

    png = image.render_png(_cpfont(tmp_path).read_bytes(), "Handgloves")
    assert _levels(png) <= set(image.GREYS)


@needs_wasm
@needs_font
def test_text_outside_ascii_reaches_the_renderer_intact(tmp_path):
    """The string crosses the wasm boundary as UTF-8 and is decoded by the
    firmware's own reader. Worth pinning because the failure is silent: a font
    without the coverage draws nothing rather than complaining, so this needs a
    font that has it -- "base" is ASCII and would pass while proving nothing."""
    from crossglyph.render import image

    blob = _cpfont(tmp_path, intervals="cyrillic").read_bytes()
    png = image.render_png(blob, "Проверка")
    assert _levels(png) - {image.WHITE}, "no ink: the text never arrived"


@needs_wasm
@needs_font
def test_antialiasing_off_is_pure_black_and_white(tmp_path):
    """With AA off only the BW pass runs, and it paints every non-white level
    solid black (GfxRenderer.cpp:449), so no greys can survive."""
    from crossglyph.render import image

    png = image.render_png(_cpfont(tmp_path).read_bytes(), "Wave",
                           antialiased=False)
    assert _levels(png) <= {image.BLACK, image.WHITE}


@needs_wasm
@needs_font
def test_antialiasing_on_produces_greys(tmp_path):
    from crossglyph.render import image

    png = image.render_png(_cpfont(tmp_path).read_bytes(), "Wave")
    assert _levels(png) & {image.DARK, image.LIGHT}, \
        "no grey levels in an antialiased render"


@needs_wasm
@needs_font
def test_the_body_of_a_glyph_stays_solid_black(tmp_path):
    """The other half of the polarity: the grey planes mark a *set* bit
    (GfxRenderer.cpp:452-458, HalDisplay.cpp:195-224). Read the other way round
    every ink pixel looks marked, the stems go grey, and nothing is black."""
    from crossglyph.render import image

    png = image.render_png(_cpfont(tmp_path).read_bytes(), "Wave")
    assert image.BLACK in _levels(png), "an antialiased render with no ink core"


@needs_wasm
@needs_font
def test_the_image_is_the_logical_page_the_right_way_up(tmp_path):
    """The framebuffer is in panel layout, 800x480; the page is 480x800 and has
    to be un-rotated back out of it (GfxRenderer.cpp:218). Getting that wrong
    still yields a plausible-looking image, so pin where the ink lands: a line
    drawn at x=10, y=40 occupies one 13px line box in the top-left corner. The
    y is the top of the line, not the baseline -- drawText adds the ascender
    itself (GfxRenderer.cpp:570)."""
    from PIL import ImageChops

    from crossglyph.render import image

    png = image.render_png(_cpfont(tmp_path).read_bytes(), "Wave", x=10, y=40)
    assert png.size == (480, 800)
    left, top, right, bottom = ImageChops.invert(png).getbbox()
    assert left >= 10, "ink to the left of where the text starts"
    assert top >= 40, "ink above the top of the line"
    assert bottom <= 40 + 40, "ink more than a line height below it"
    assert right < 150, "four glyphs at 13px cannot reach that far"


# --- paragraph layout -----------------------------------------------------

PARAGRAPH = (
    "Съешь ещё этих мягких французских булок, да выпей же чаю. "
    "Широкая электрификация южных губерний даст мощный толчок "
    "подъёму сельского хозяйства."
)


def _lines(module, text, width):
    """Lay a paragraph out and read the lines back as strings."""
    count = module.call("rc_layout_paragraph",
                        module.write(text.encode("utf-8") + b"\x00"), width)
    out = []
    for index in range(count):
        buffer = module.alloc(512)
        written = module.call("rc_layout_line", index, buffer, 512)
        out.append(module.read(buffer, written).decode("utf-8"))
    return out


@needs_wasm
@needs_font
def test_a_paragraph_breaks_into_lines(tmp_path):
    module = _loaded(tmp_path, intervals="cyrillic")
    lines = _lines(module, PARAGRAPH, 400)
    assert len(lines) > 1, "one line at 400px means nothing was measured"


@needs_wasm
@needs_font
def test_line_breaking_keeps_every_word(tmp_path):
    """The strongest cheap invariant: greedy breaking regroups words, it never
    loses or duplicates one. Hyphenation off, so no word is split."""
    module = _loaded(tmp_path, intervals="cyrillic")
    _spec(module, hyphenation=0)
    lines = _lines(module, PARAGRAPH, 400)
    assert " ".join(lines).split() == PARAGRAPH.split()


@needs_wasm
@needs_font
def test_a_narrower_column_takes_more_lines(tmp_path):
    module = _loaded(tmp_path, intervals="cyrillic")
    assert len(_lines(module, PARAGRAPH, 200)) > len(_lines(module, PARAGRAPH, 400))


@needs_wasm
@needs_font
def test_hyphenation_needs_a_language(tmp_path):
    """The reader sets it from the book's own metadata (Section.cpp:410), and
    Section is not in this module -- so without rc_page_set_language the
    hyphenator has no patterns and finds no breaks, silently."""
    module = _loaded(tmp_path, intervals="cyrillic")
    _spec(module, hyphenation=1)
    module.call("rc_page_set_language", module.write(b"\x00"))
    assert not any(line.endswith("-") for line in _lines(module, PARAGRAPH, 200))


@needs_wasm
@needs_font
def test_hyphenation_splits_words_across_lines(tmp_path):
    """Liang patterns for Russian are compiled into the module
    (hyphenation/generated/hyph-ru.trie.h), so this needs no data files."""
    module = _loaded(tmp_path, intervals="cyrillic")
    _spec(module, hyphenation=1)
    module.call("rc_page_set_language", module.write(b"ru\x00"))
    hyphenated = _lines(module, PARAGRAPH, 200)
    assert any(line.endswith("-") for line in hyphenated), \
        "no line ends in a hyphen; the hyphenator did not run"

    _spec(module, hyphenation=0)
    assert " ".join(hyphenated).split() != \
        " ".join(_lines(module, PARAGRAPH, 200)).split(), \
        "hyphenation changed nothing about the words on each line"


@needs_wasm
def test_laying_out_without_a_font_is_an_error():
    module = render.load_module()
    assert module.call("rc_layout_paragraph", module.write(b"x\x00"), 400) == -1


# --- a page of paragraphs -------------------------------------------------

PAGE = "\n".join([PARAGRAPH, PARAGRAPH, PARAGRAPH])

#: A null styles pointer: every word set in the roman.
NO_STYLES = 0


def _row_ink_left(module, lines=2):
    """The x of the leftmost ink on each of the first `lines` lines of text.

    Bands of consecutive inked rows, not a fixed row step: a line of 13px type
    is around twenty rows tall, so stepping by anything less than a line height
    measures the same line twice and every indent looks like none.

    Reads the page back through the same un-rotation render_page_png uses, so
    it measures what the image would show.
    """
    from PIL import Image, ImageChops

    panel = Image.frombytes("1", (module.call("rc_panel_width"),
                                  module.call("rc_panel_height")),
                            module.read(module.call("rc_framebuffer"),
                                        module.call("rc_framebuffer_size")))
    page = ImageChops.invert(panel).transpose(Image.Transpose.ROTATE_270)

    found, left = [], None
    for y in range(page.height):
        row = page.crop((0, y, page.width, y + 1)).getbbox()
        if row:
            left = row[0] if left is None else min(left, row[0])
        elif left is not None:
            found.append(left)
            if len(found) == lines:
                break
            left = None
    return found


@needs_wasm
@needs_font
def test_a_page_of_paragraphs_fills_the_column(tmp_path):
    from PIL import ImageChops

    from crossglyph.render import image

    png = image.render_page_png(
        _cpfont(tmp_path, intervals="cyrillic").read_bytes(), PAGE)
    assert png.size == (480, 800)
    assert _levels(png) <= set(image.GREYS)
    # Three paragraphs of this length cannot fit in the top eighth of a page.
    _, _, _, bottom = ImageChops.invert(png).getbbox()
    assert bottom > 400, "the page stopped after a line or two"


@needs_wasm
@needs_font
def test_a_paragraph_gets_a_first_line_indent(tmp_path):
    """3 space widths, and only without extra paragraph spacing
    (ParsedText.cpp:588-602). The device ships that spacing *on*, so an indent
    is what you get after turning it off -- which is why this asks."""
    module = _loaded(tmp_path, intervals="cyrillic")
    _spec(module, extra_paragraph_spacing=0)
    module.call("rc_page_render",
                module.write(PARAGRAPH.encode("utf-8") + b"\x00"),
                NO_STYLES, 0, BW, 0xFF)
    left = _row_ink_left(module)
    assert left[0] > left[1] + 10, \
        "the first line does not start further in than the second"


@needs_wasm
@needs_font
def test_a_page_stops_at_the_bottom_margin(tmp_path):
    """Twenty paragraphs cannot all be drawn; the count says where it stopped
    rather than running off the page."""
    module = _loaded(tmp_path, intervals="cyrillic")
    many = "\n".join([PARAGRAPH] * 20)
    drawn = module.call("rc_page_render",
                        module.write(many.encode("utf-8") + b"\x00"),
                        NO_STYLES, 0, BW, 0xFF)
    assert 0 < drawn < 20 * len(_lines(module, PARAGRAPH, 400))


@needs_wasm
def test_the_module_is_shared_between_renders():
    """State set on the core -- the font, the language, the layout options --
    lives in module globals, so a knob set on one instance and a page drawn by
    another would be dropped without a word. One instance per process."""
    assert render.shared_module() is render.shared_module()


@needs_wasm
@needs_font
def test_the_hyphenation_language_reaches_a_rendered_page(tmp_path):
    """The knob has to survive from where it is set to where the page is drawn
    -- which it only does because both go through the shared module."""
    from crossglyph.render import image

    blob = _cpfont(tmp_path, intervals="cyrillic").read_bytes()
    module = render.shared_module()
    # Hyphenation is off in the device's defaults, so ask for it: this test is
    # about the language reaching the render, not about the default.
    _spec(module, hyphenation=1)

    module.call("rc_page_set_language", module.write(b"\x00"))
    without = image.render_page_png(blob, PARAGRAPH, antialiased=False)
    module.call("rc_page_set_language", module.write(b"ru\x00"))
    with_ru = image.render_page_png(blob, PARAGRAPH, antialiased=False)
    assert without.tobytes() != with_ru.tobytes(), \
        "hyphenating in Russian drew the same page as not hyphenating at all"


# --- the layout knobs -----------------------------------------------------

JUSTIFY, LEFT, CENTER, RIGHT = 0, 1, 2, 3


def _spec(module, margin=5, alignment=JUSTIFY, hyphenation=1,
          extra_paragraph_spacing=0, compression=100):
    module.call("rc_page_set_spec", margin, alignment, hyphenation,
                extra_paragraph_spacing, compression)


#: More text than any page can hold, so the line count measures what *fits*
#: rather than how much text there is. With only a few paragraphs every spec
#: draws all of them and the geometry knobs look like they do nothing.
OVERFLOWING = "\n".join([PARAGRAPH] * 20)


def _drawn(module, text=None):
    return module.call("rc_page_render",
                       module.write((text or OVERFLOWING).encode("utf-8")
                                    + b"\x00"),
                       NO_STYLES, 0, BW, 0xFF)


@needs_wasm
@needs_font
def test_alignment_changes_the_page_but_not_the_line_breaks(tmp_path):
    """Justification moves words within a line; it does not decide which words
    are on it. Both halves matter: the first says the knob does something, the
    second says it does not do too much."""
    module = _loaded(tmp_path, intervals="cyrillic")
    _spec(module, alignment=JUSTIFY)
    justified_breaks = _lines(module, PARAGRAPH, 400)
    _drawn(module, PARAGRAPH)
    justified = module.read(module.call("rc_framebuffer"),
                            module.call("rc_framebuffer_size"))

    _spec(module, alignment=LEFT)
    assert _lines(module, PARAGRAPH, 400) == justified_breaks
    _drawn(module, PARAGRAPH)
    ragged = module.read(module.call("rc_framebuffer"),
                         module.call("rc_framebuffer_size"))
    assert ragged != justified


@needs_wasm
@needs_font
def test_a_wider_margin_fits_fewer_lines(tmp_path):
    module = _loaded(tmp_path, intervals="cyrillic")
    _spec(module, margin=5)
    narrow = _drawn(module)
    _spec(module, margin=40)
    assert _drawn(module) < narrow


@needs_wasm
@needs_font
def test_tighter_line_spacing_fits_more_lines(tmp_path):
    module = _loaded(tmp_path, intervals="cyrillic")
    _spec(module, compression=110)
    wide = _drawn(module)
    _spec(module, compression=95)
    assert _drawn(module) > wide


@needs_wasm
@needs_font
def test_paragraph_spacing_replaces_the_first_line_indent(tmp_path):
    """Not two independent knobs: the engine indents only when there is no
    extra spacing (ParsedText.cpp:588-602). Pinning it here stops a future
    'fix' from making a page that the device cannot produce."""
    module = _loaded(tmp_path, intervals="cyrillic")
    _spec(module, extra_paragraph_spacing=0)
    _drawn(module, PARAGRAPH)
    indented = _row_ink_left(module)
    assert indented[0] > indented[1] + 10

    _spec(module, extra_paragraph_spacing=1)
    _drawn(module, PARAGRAPH)
    flush = _row_ink_left(module)
    assert abs(flush[0] - flush[1]) <= 2


@needs_wasm
@needs_font
def test_resetting_the_spec_restores_the_devices_defaults(tmp_path):
    module = _loaded(tmp_path, intervals="cyrillic")
    default = _drawn(module)
    _spec(module, margin=40, compression=110)
    assert _drawn(module) != default
    module.call("rc_page_reset_spec")
    assert _drawn(module) == default


@needs_wasm
@needs_font
def test_one_bit_rendering_leaves_no_grey_on_the_page(tmp_path):
    """The device's Settings > Text > Anti-Aliasing toggle
    (EpubReaderActivity.cpp:1667): off, the reader never draws the grey planes
    at all, and the BW pass paints every non-white level solid black. Tuning a
    font *for* that mode is a real use case -- it decides whether you are
    tuning three quantizer thresholds or only the first."""
    from crossglyph.render import image

    blob = _cpfont(tmp_path, intervals="cyrillic").read_bytes()
    one_bit = image.render_page_png(blob, PAGE, antialiased=False)
    two_bit = image.render_page_png(blob, PAGE, antialiased=True)

    assert _levels(one_bit) <= {image.BLACK, image.WHITE}
    assert _levels(two_bit) & {image.DARK, image.LIGHT}, \
        "no grey levels with antialiasing on"
    # Same glyphs either way: the planes shade the ink, they do not add any.
    assert one_bit.histogram()[image.WHITE] == two_bit.histogram()[image.WHITE]


@needs_wasm
@needs_font
def test_a_bold_word_falls_back_when_the_font_has_no_bold(tmp_path):
    """The device has no synthetic bold or oblique: EpdFontFamily::getFont
    falls back to regular for a face the font does not carry
    (EpdFontFamily.cpp:3-18). Marked-up text against a one-face font is
    therefore honest rather than broken."""
    module = _loaded(tmp_path, intervals="cyrillic")
    text = module.write(PARAGRAPH.encode("utf-8") + b"\x00")

    module.call("rc_page_render", text, NO_STYLES, 0, BW, 0xFF)
    plain = module.read(module.call("rc_framebuffer"),
                        module.call("rc_framebuffer_size"))

    words = len(PARAGRAPH.split())
    styles = module.write(bytes([1] * words))
    module.call("rc_page_render", text, styles, words, BW, 0xFF)
    assert module.read(module.call("rc_framebuffer"),
                       module.call("rc_framebuffer_size")) == plain


@needs_wasm
@needs_font
def test_the_wrong_language_hyphenates_nothing_rather_than_wrongly(tmp_path):
    """The firmware has one hyphenation language at a time -- a single static
    in Hyphenator, set per book from dc:language (Section.cpp:410) -- so a book
    that mixes languages hyphenates only the one it declares.

    The failure mode is the benign one, and worth pinning as such: Liang
    patterns are built from their own script's letters, so the wrong language
    finds no breaks at all rather than breaking words in the wrong places.
    """
    module = _loaded(tmp_path, intervals="cyrillic,latin-ext")
    _spec(module, hyphenation=1)
    english = ("Typography is what language looks like, and international "
               "communication depends on consistently readable presentation.")

    module.call("rc_page_set_language", module.write(b"en\x00"))
    with_en = _lines(module, english, 200)
    module.call("rc_page_set_language", module.write(b"ru\x00"))
    with_ru = _lines(module, english, 200)

    assert any(line.endswith("-") for line in with_en), \
        "English patterns found no break in English text"
    assert not any(line.endswith("-") for line in with_ru), \
        "Russian patterns broke an English word -- that would be wrong, " \
        "not merely absent"


@needs_wasm
@needs_font
def test_too_few_styles_fall_back_rather_than_reading_past_the_end(tmp_path):
    """The word count is a contract held on both sides of the wasm boundary --
    the host splits words exactly as addWords does. If the two ever disagree,
    a page set in the wrong faces beats reading off the end of the buffer, so
    the length travels with the array and a word past it draws regular."""
    module = _loaded(tmp_path, intervals="cyrillic")
    text = module.write(PARAGRAPH.encode("utf-8") + b"\x00")

    module.call("rc_page_render", text, NO_STYLES, 0, BW, 0xFF)
    plain = module.read(module.call("rc_framebuffer"),
                        module.call("rc_framebuffer_size"))

    # One byte for a paragraph of many words: every word past it is regular,
    # and with no bold face in this font the first is regular too.
    short = module.write(bytes([1]))
    assert module.call("rc_page_render", text, short, 1, BW, 0xFF) > 0
    assert module.read(module.call("rc_framebuffer"),
                       module.call("rc_framebuffer_size")) == plain


def test_a_firmware_without_git_is_not_called_stale(stamped, monkeypatch):
    """"Cannot check" is not "does not match". A firmware exported as a
    tarball has no commit, so refusing to load and advising a rebuild would
    advise something that records nothing again -- the module could never be
    loaded at all."""
    monkeypatch.setattr(render, "firmware_commit", lambda source=None: None)
    _write_stamp(stamped, firmware="abc123")
    assert render.is_stale() is False
    stamped.unlink()
    assert render.is_stale() is False


def test_a_checkable_firmware_still_calls_a_stampless_build_stale(stamped):
    """The rule only relaxes where it cannot be applied."""
    assert not stamped.exists()
    assert render.is_stale() is True


@needs_wasm
@needs_font
def test_the_defaults_are_the_ones_the_device_ships(tmp_path):
    """CrossPointSettings.h:217,241,246 -- justified, hyphenation OFF, extra
    paragraph spacing ON. Two of the three are the opposite of what looks
    natural, and the pair interacts: paragraph spacing on is also what turns
    the first-line indent off. A preview that started from the prettier
    combination would be tuning against a page the reader never shows until
    its owner has changed two settings."""
    module = _loaded(tmp_path, intervals="cyrillic")
    module.call("rc_page_reset_spec")

    # No hyphens, because hyphenation is off however good the patterns are.
    module.call("rc_page_set_language", module.write(b"ru\x00"))
    assert not any(line.endswith("-") for line in _lines(module, PARAGRAPH, 200))

    # No first-line indent, because the paragraph spacing that replaces it is on.
    _drawn(module, PARAGRAPH)
    left = _row_ink_left(module)
    assert abs(left[0] - left[1]) <= 2, \
        "the default page is indented, so paragraph spacing is off"


def test_a_stamp_carries_no_path(stamped, monkeypatch):
    """The stamp is committed, so a path from the machine that built it would
    travel with the release. A key that arrives anyway is ignored."""
    monkeypatch.setattr(render, "firmware_commit", lambda source=None: "here")
    _write_stamp(stamped, firmware="here", source="/gone/crosspoint-reader")
    assert render.is_stale() is False
    _write_stamp(stamped, firmware="elsewhere", source="/gone/crosspoint-reader")
    assert render.is_stale() is True, \
        "a recorded path silently stopped the comparison"


@needs_wasm
@needs_font
def test_measuring_after_a_release_does_not_read_a_freed_font(tmp_path):
    """release() frees the .cpfont bytes the core borrowed, so the font is
    dropped with them: a caller that measures before it draws would otherwise
    read a heap block malloc has already handed on."""
    blob = _cpfont(tmp_path).read_bytes()
    with render.exclusive() as module:
        module.call("rc_font_load", module.write(blob), len(blob))
        assert module.call("rc_font_advance_y") > 0

    with render.exclusive() as module:          # releases the previous buffers
        assert module.call("rc_font_advance_y") == 0, \
            "the core still thinks it has a font whose bytes are freed"

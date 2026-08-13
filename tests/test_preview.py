"""The preview: a font source and a set of knobs in, a page of type out."""
import pathlib
import struct

import pytest

import fontpaths

from crossglyph import render

SRC = fontpaths.truetype()
ITALIC_SRC = fontpaths.italic()
#: A face with real GSUB ligatures; sample has none at all.
LIGATURE_SRC = fontpaths.cff()
needs = pytest.mark.skipif(
    render.is_stale() or SRC is None,
    reason="needs a render core and CROSSGLYPH_TEST_FONT")
needs_italic = pytest.mark.skipif(ITALIC_SRC is None,
                                  reason="set CROSSGLYPH_TEST_ITALIC to the italic face")
needs_ligatures = pytest.mark.skipif(LIGATURE_SRC is None,
                                     reason="set CROSSGLYPH_TEST_OTF to a face with ligatures")


ONE_PARAGRAPH = ("Съешь ещё этих мягких французских булок, да выпей же чаю, "
                 "и посмотри, куда переносится эта строка.")


def font_for(text, sources=SRC, size=13, **kwargs):
    """A font built for exactly the text it is about to draw.

    What preview() does in one call, and the pairing every direct build_font
    caller has to keep: coverage is derived from the text, so a font built for
    one and used to draw another leaves the difference blank.
    """
    from crossglyph import preview

    return preview.build_font(sources, size,
                              coverage=preview.coverage_for(text, sources),
                              **kwargs)


def _style_toc(font: bytes) -> tuple[int, int, int]:
    """(intervalCount, ligatureCount, dataOffset) for the first style.

    A 32-byte header, then 32-byte style TOC entries -- cpfont/convert.py's
    STYLE_TOC_FORMAT, which is where the offsets below come from.
    """
    intervals, = struct.unpack_from("<I", font, 32 + 4)
    ligatures = font[32 + 23]
    offset, = struct.unpack_from("<I", font, 32 + 24)
    return intervals, ligatures, offset


def styles_in(font: bytes) -> set[int]:
    """The style ids a .cpfont carries: styleCount at byte 12, then the TOC."""
    count = font[12]
    return {font[32 + index * 32] for index in range(count)}


def codepoints_in(font: bytes) -> set[int]:
    """Every codepoint a .cpfont's regular style carries."""
    count, _, offset = _style_toc(font)
    codepoints = set()
    for index in range(count):
        start, end, _ = struct.unpack_from("<III", font, offset + index * 12)
        codepoints.update(range(start, end + 1))
    return codepoints


@needs
def test_a_page_comes_out_of_a_font_source():
    from crossglyph import preview

    page = preview.preview(SRC, 13)
    assert page.size == (480, 800)
    assert page.histogram()[255] < 480 * 800, "the page is blank"


@needs
def test_the_sample_text_is_more_than_one_paragraph():
    from crossglyph import preview

    assert len(preview.SAMPLE_TEXT.split("\n")) >= 3, \
        "one paragraph cannot show a first-line indent or paragraph spacing"


@needs
def test_the_build_carries_the_text_and_nothing_else():
    """What makes a rebuild per knob turn cheap: the page can only draw what is
    on it, so a preset's several hundred codepoints are several hundred
    rasterizations nobody looks at. The marks are markup and not type."""
    font = font_for("*Привет*, мир")
    assert codepoints_in(font) == set(map(ord, "Привет, мир")) | {0x20, 0x2D}


@needs
def test_hyphenation_draws_a_hyphen_the_text_never_asked_for(monkeypatch):
    """A split word gets a '-' appended to it (ParsedText.cpp:1114-1117), and
    the text being hyphenated is exactly the kind that has none of its own. A
    build sized to the text alone would break the line with a blank."""
    from crossglyph import preview

    text = ("Электрификация сельскохозяйственного производства "
            "продемонстрировала высококвалифицированное "
            "переосвидетельствование землепользователей.")
    assert "-" not in text
    spec = preview.PageSpec(hyphenation=True)

    with_hyphen = preview.preview(SRC, 13, text, spec=spec)
    monkeypatch.setattr(preview, "ESSENTIAL_CODEPOINTS", ())
    without = preview.preview(SRC, 13, text, spec=spec)
    assert with_hyphen.tobytes() != without.tobytes(), \
        "the hyphen the layout appends never reached the font"


#: A face and a fallback are a *relationship* -- one lacks what the other has --
#: so they are built here rather than hunted for in a font folder, where what
#: the test asserted would depend on what had been dropped in it.
needs_core = pytest.mark.skipif(
    render.is_stale(), reason="needs a current build/render.wasm")


def _pair(tmp_path):
    """A family with Latin and no Greek, and a fallback that has the Greek."""
    from fontsmith import box_font

    main = box_font(tmp_path / "main.ttf",
                    [*range(0x20, 0x7F), *map(ord, "Привет, мир")])
    fallback = box_font(tmp_path / "fallback.ttf", [0x3B1, 0x3B2, 0x20],
                        family="Probe Fallback")
    return main, fallback


@needs_core
def test_a_fallback_fills_a_codepoint_the_family_lacks(tmp_path):
    """What the device does with `fallbacks = yes`, which is the default -- so
    a preview without it draws a blank where the card would draw a glyph."""
    from crossglyph import preview

    main, fallback = _pair(tmp_path)
    assert 0x3B1 not in codepoints_in(font_for("α", main)), \
        "the probe family has Greek after all"

    blank = font_for("α", main)
    filled = font_for("α", main, fallbacks=(fallback,))
    assert filled != blank, "the fallback face was never opened"

    page = preview.preview_page(filled, "α")
    assert page.tobytes() != preview.preview_page(blank, "α").tobytes(), \
        "the glyph the fallback supplied is not on the page"


@needs_core
def test_a_fallback_is_not_even_opened_while_the_family_covers_the_text(tmp_path):
    """The reason they are affordable here at all. Sized to the text, most
    pages need nothing from a fallback, and one that needs nothing must not pay
    to open twelve faces to find that out -- so the charmap is asked first.

    Proved with a file no rasterizer could read: it is fine to hand this build
    a broken face precisely because the build never reaches for it.
    """
    from crossglyph import preview

    main, _ = _pair(tmp_path)
    junk = tmp_path / "not-a-font.ttf"
    junk.write_bytes(b"not a font at all")
    text = "Привет, мир"
    assert not preview.uncovered({preview.REGULAR: main},
                                 preview.coverage_for(text, main))
    assert font_for(text, main, fallbacks=(junk,)) == font_for(text, main)


@needs
@needs_ligatures
def test_a_ligature_reaches_a_build_sized_to_its_text():
    """Nobody types U+FB01. The ligature's *output* is a codepoint of its own,
    and extract_ligatures_fonttools drops any rule whose output is not in the
    built set -- so deriving coverage from the text alone would quietly turn
    every ligature off."""
    font = font_for("The office finds flags", LIGATURE_SRC)
    _, ligatures, _ = _style_toc(font)
    assert 0xFB01 in codepoints_in(font), "fi has no glyph to substitute into"
    assert ligatures > 0, "the built font carries no ligature pairs"


@needs
def test_a_bigger_size_takes_more_of_the_page():
    """One short paragraph, so the column is not full at either size and the
    ink really is measuring the type rather than the page height."""
    from PIL import ImageChops

    from crossglyph import preview

    def ink_height(size):
        page = preview.preview(SRC, size, ONE_PARAGRAPH)
        top, bottom = ImageChops.invert(page).getbbox()[1::2]
        return bottom - top

    assert ink_height(20) > ink_height(11)


@needs
def test_the_knobs_reach_the_page():
    from crossglyph import preview

    tight = preview.preview(SRC, 13, spec=preview.PageSpec(line_spacing="tight"))
    wide = preview.preview(SRC, 13, spec=preview.PageSpec(line_spacing="wide"))
    assert tight.tobytes() != wide.tobytes()


@needs
def test_a_page_knob_survives_into_the_render():
    """The bug shared_module() exists to prevent: a spec set on one instance
    and a page drawn by another looks fine and ignores the knob."""
    from crossglyph import preview

    font = preview.build_font(SRC, 13)
    justified = preview.preview_page(font, spec=preview.PageSpec())
    ragged = preview.preview_page(font, spec=preview.PageSpec(alignment="left"))
    assert justified.tobytes() != ragged.tobytes()


@needs
def test_one_bit_rendering_is_a_page_knob():
    """Tuning a font for a reader who keeps the device's anti-aliasing off is
    a use case of its own: it decides whether you are tuning three quantizer
    thresholds or only the first."""
    from crossglyph import preview
    from crossglyph.render import image

    font = preview.build_font(SRC, 13)
    one_bit = preview.preview_page(font, spec=preview.PageSpec(antialiased=False))
    levels = {value for value, count in enumerate(one_bit.histogram()) if count}
    assert levels <= {image.BLACK, image.WHITE}


@needs
def test_a_tuning_change_reaches_the_page():
    from crossglyph import preview
    from crossglyph.cpfont.tuning import Tuning

    plain = preview.preview(SRC, 13)
    heavier = preview.preview(SRC, 13, tuning=Tuning(weight=0.5))
    assert plain.tobytes() != heavier.tobytes()


@needs
def test_the_hyphenation_language_is_a_knob():
    from crossglyph import preview

    font = preview.build_font(SRC, 13)
    # Hyphenation is off in the device's defaults, so this has to ask for it.
    russian = preview.preview_page(
        font, spec=preview.PageSpec(hyphenation=True, language="ru"))
    none = preview.preview_page(
        font, spec=preview.PageSpec(hyphenation=True, language=""))
    assert russian.tobytes() != none.tobytes(), \
        "hyphenating in Russian drew the same page as not hyphenating"


@needs
@needs_italic
def test_a_second_face_grows_the_font_but_not_unmarked_text():
    """Faces are additive: the container carries the italic, and text with no
    emphasis in it draws exactly as it did without one. Unmarked text on
    purpose -- SAMPLE_TEXT carries marks, so it would differ, and rightly."""
    from crossglyph import preview

    one = font_for(ONE_PARAGRAPH)
    two = font_for(ONE_PARAGRAPH,
                   {preview.REGULAR: SRC, preview.ITALIC: ITALIC_SRC})
    assert len(two) > len(one)
    assert preview.preview_page(one, ONE_PARAGRAPH).tobytes() == \
        preview.preview_page(two, ONE_PARAGRAPH).tobytes()


def _roman_and_italic(tmp_path):
    """Two faces of one family, built here: which style a build carries is a
    structural question, and it needs no particular typeface to answer."""
    from fontsmith import box_font

    from crossglyph import preview

    codepoints = [*range(0x20, 0x7F), *map(ord, ONE_PARAGRAPH),
                  *map(ord, "обычныйинаклонныйтекст")]
    return {
        preview.REGULAR: box_font(tmp_path / "roman.ttf", codepoints),
        preview.ITALIC: box_font(tmp_path / "italic.ttf", codepoints,
                                 style="Italic"),
    }


@needs_core
def test_only_the_styles_the_text_is_set_in_are_built(tmp_path):
    """Every style in a build is a full rasterization of the coverage, so a
    plain paragraph beside a four-face family rasterized four times over for
    three faces nothing on the page wore. The markup already says which styles
    the words are in."""
    from crossglyph import preview

    both = _roman_and_italic(tmp_path)
    assert preview.faces_for(ONE_PARAGRAPH, both) ==         {preview.REGULAR: both[preview.REGULAR]}
    assert preview.faces_for(f"_{ONE_PARAGRAPH}_", both) == both

    plain = preview.preview(both, 13, ONE_PARAGRAPH)
    # The face it never asked for cannot change what it drew: the same page,
    # pixel for pixel, out of a font that is a quarter of the work.
    everything = preview.preview_page(
        font_for(ONE_PARAGRAPH, both), ONE_PARAGRAPH)
    assert plain.tobytes() == everything.tobytes()


@needs_core
def test_a_style_the_text_uses_is_built_even_where_the_markup_is_nested(tmp_path):
    """The pairing coverage_for already has, one level up: a font built for
    one text and used to draw another is wrong in a way nothing reports."""
    from crossglyph import preview

    font = font_for("обычный _и наклонный_ текст", _roman_and_italic(tmp_path))
    assert styles_in(font) == {preview.REGULAR, preview.ITALIC}


@needs
@needs_italic
def test_marked_up_words_render_in_their_own_face():
    from crossglyph import preview

    font = font_for(ONE_PARAGRAPH,
                    {preview.REGULAR: SRC, preview.ITALIC: ITALIC_SRC})
    plain = preview.preview_page(font, ONE_PARAGRAPH)
    marked = preview.preview_page(font, f"_{ONE_PARAGRAPH}_")
    assert plain.tobytes() != marked.tobytes(), \
        "an all-italic paragraph drew the same as the roman one"


@needs
def test_emphasis_without_the_face_falls_back_rather_than_failing():
    """No synthetic oblique on the device (EpdFontFamily.cpp:3-18), so a
    one-face font renders emphasis as regular -- which is what the reader
    would show for a book whose font has no italic."""
    from crossglyph import preview

    font = font_for(ONE_PARAGRAPH)              # regular only
    assert preview.preview_page(font, ONE_PARAGRAPH).tobytes() == \
        preview.preview_page(font, f"_{ONE_PARAGRAPH}_").tobytes()


def test_an_unknown_alignment_is_refused():
    from crossglyph import preview

    with pytest.raises(ValueError, match="alignment"):
        preview.PageSpec(alignment="diagonal").to_call_args()


def test_an_unknown_line_spacing_is_refused():
    from crossglyph import preview

    with pytest.raises(ValueError, match="line_spacing"):
        preview.PageSpec(line_spacing="airy").to_call_args()


def test_a_margin_outside_the_devices_range_is_refused():
    from crossglyph import preview

    with pytest.raises(ValueError, match="margin"):
        preview.PageSpec(margin=200).to_call_args()


@needs
def test_the_module_is_reused_between_pages():
    assert render.shared_module() is render.shared_module()


# --- markup ---------------------------------------------------------------


def test_markup_strips_its_own_marks():
    from crossglyph.preview import markup

    text, styles = markup.parse("plain *bold* _italic_ plain")
    assert text == "plain bold italic plain"
    assert list(styles) == [0, 1, 2, 0]


def test_markup_spans_several_words():
    from crossglyph.preview import markup

    text, styles = markup.parse("a *two words* b")
    assert text == "a two words b"
    assert list(styles) == [0, 1, 1, 0]


def test_markup_nests_into_bold_italic():
    from crossglyph.preview import markup

    _, styles = markup.parse("*_both_*")
    assert list(styles) == [3]


def test_markup_counts_words_the_way_the_engine_does():
    """One byte per word, paragraphs included, empties dropped -- the contract
    the C side indexes by. Double spaces and newlines must not consume one."""
    from crossglyph.preview import markup

    text, styles = markup.parse("a  b\n*c* d")
    assert text == "a  b\nc d"
    assert list(styles) == [0, 0, 1, 0]


def test_an_unclosed_mark_is_left_alone():
    """Sample text is typed by hand into a box; a stray asterisk should show
    up as an asterisk rather than swallowing the rest of the page."""
    from crossglyph.preview import markup

    text, styles = markup.parse("a *b c")
    assert text == "a *b c"
    assert list(styles) == [0, 0, 0]


def test_the_sample_text_keeps_a_style_for_every_word():
    """The invariant the module indexes by, on the text it actually ships."""
    from crossglyph import preview
    from crossglyph.preview import markup

    text, styles = markup.parse(preview.SAMPLE_TEXT)
    words = [w for para in text.split("\n") for w in para.split(" ") if w]
    assert len(words) == len(styles)
    assert set(styles) > {0}, "the sample shows no emphasis at all"


# --- concurrency ----------------------------------------------------------


@needs
def test_overlapping_renders_do_not_interleave():
    """A server runs sync endpoints in a threadpool, so dragging a slider puts
    two renders in the core at once. Two things go wrong without a lock: a
    wasmtime Store entered from two threads panics inside its stack walker and
    takes the whole process down, and the core's font, spec and framebuffer are
    module globals, so the pages come back built from both requests.

    Each thread here asks for a different margin and must get that margin's
    page, byte for byte, as if it had run alone.
    """
    import concurrent.futures

    from crossglyph import preview

    font = preview.build_font(SRC, 13)
    margins = [5, 12, 19, 26, 33, 40, 8, 15]
    alone = {m: preview.preview_page(
        font, spec=preview.PageSpec(margin=m)).tobytes() for m in margins}

    def render(margin):
        return margin, preview.preview_page(
            font, spec=preview.PageSpec(margin=margin)).tobytes()

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for margin, page in pool.map(render, margins * 3):
            assert page == alone[margin], \
                f"the page for margin {margin} came back built from another"


@needs
def test_a_fractional_size_lands_between_its_neighbours(tmp_path):
    """The integer step is 2.08 px/em at 150 DPI, about 10% at reading sizes.
    A quarter point is a distinct rasterization, not a rounding of one."""
    import io
    from contextlib import redirect_stderr

    from crossglyph import cpfont, fontbuild

    def advance_y(size):
        path = tmp_path / f"probe-{size}.cpfont"
        with redirect_stderr(io.StringIO()):
            cpfont.generate_cpfont_multistyle(
                {0: str(SRC)}, size, cpfont.resolve_intervals("base"),
                str(path))
        return fontbuild.style_metrics(path).advance_y

    tight, middle, loose = advance_y(13), advance_y(13.5), advance_y(14)
    assert tight < middle < loose, (tight, middle, loose)


@needs
def test_rendering_does_not_leak_the_module_s_memory():
    """The core borrows what it is handed, so nothing can be freed mid-render
    -- which made it easy to free nothing at all. A long-lived server turning
    knobs would grow by a font per render: measured at 22 MB over 200 renders
    of a four-face family before this was fixed."""
    from crossglyph import preview, render

    font = font_for(ONE_PARAGRAPH)
    module = render.shared_module()

    def pages():
        return module._memory.size(module._store)

    for _ in range(12):                      # settle any one-off growth
        preview.preview_page(font, ONE_PARAGRAPH)
    settled = pages()
    for n in range(40):
        preview.preview_page(font, ONE_PARAGRAPH,
                             spec=preview.PageSpec(margin=5 + n % 30))
    assert pages() == settled, \
        f"linear memory grew from {settled} to {pages()} pages over 40 renders"


def test_an_underscore_inside_a_word_is_not_emphasis():
    """some_variable_name is a name. Without the word-boundary rule it becomes
    *somevariablename* AND its stray opener swallows the next real _italic_ in
    the paragraph -- text mangled in two places at once."""
    from crossglyph.preview import markup

    text, styles = markup.parse("snake_case and _real italic_")
    assert text == "snake_case and real italic"
    assert list(styles) == [0, 0, 2, 2]

    assert markup.parse("some_variable_name")[0] == "some_variable_name"
    assert markup.parse("a_b_c")[0] == "a_b_c"


@needs
@needs_italic
def test_a_reloaded_font_replaces_the_registered_family():
    """GfxRenderer::insertFont is a map::insert -- a no-op for a fontId that is
    already there, and it only logs, which our stub swallows. One module for
    the whole process means the family captured by the *first* load would stick
    forever, so a regular-only font loaded first left every later italic drawn
    in roman glyphs, spaced for the italic.

    Loading the one-face font first is the whole point of this test."""
    from crossglyph import preview

    one_face = font_for(ONE_PARAGRAPH)
    two_face = font_for(ONE_PARAGRAPH,
                        {preview.REGULAR: SRC, preview.ITALIC: ITALIC_SRC})

    preview.preview_page(one_face, ONE_PARAGRAPH)          # poison the map
    warm = preview.preview_page(two_face, f"_{ONE_PARAGRAPH}_")

    render.shared_module.cache_clear()                     # a pristine instance
    cold = preview.preview_page(two_face, f"_{ONE_PARAGRAPH}_")
    assert warm.tobytes() == cold.tobytes(), \
        "the italic drew differently depending on what was loaded before it"


def test_an_unclosed_mark_is_not_closed_by_an_intraword_one():
    """The partner scan has to skip candidates that are themselves ineligible,
    or the "unmatched marks stay literal" guarantee is hollow: the leading
    underscore would open on the one inside some_var, which is then skipped as
    intraword, leaving the run open to the end of the paragraph."""
    from crossglyph.preview import markup

    text, styles = markup.parse("_open and some_var here")
    assert text == "_open and some_var here"
    assert set(styles) == {0}


def test_the_page_remembers_the_readers_own_settings():
    """The Page knobs persist to localStorage, and every way that breaks is
    silent -- a knob quietly stops being remembered, a stale stored value
    blanks a select, storage throws in a private window. The page has no build
    step and no test framework, so the assertions live in a node script that
    runs the real modules against a stub DOM rather than a copy of them.

    `--experimental-vm-modules` is what lets that script link them as modules,
    each in its own scope, which is the only way a name a module borrowed
    without importing shows up here rather than on the first click.
    """
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node to exercise the page's own script")
    script = pathlib.Path(__file__).with_name("preview_persistence.mjs")
    done = subprocess.run(
        [node, "--experimental-vm-modules", "--no-warnings", str(script)],
        capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr

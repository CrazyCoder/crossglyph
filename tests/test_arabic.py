"""Arabic presentation forms: the table, and the coverage it implies."""
import re

import freetype
import pytest

import fontpaths
import fontsmith
from crossglyph.cpfont import arabic, convert
from crossglyph.render import stamp

#: The firmware's own shaping table, which ours has to agree with.
MINIBIDI = stamp.FIRMWARE / "lib" / "MiniBidi" / "minibidi.c"

#: /* 628 */ {SD, 0x8F},
SHAPE_NODE = re.compile(
    r"/\*\s*([0-9A-F]{3})\s*\*/\s*\{\s*(S[LRDUC])\s*,\s*(0x[0-9A-Fa-f]+)\s*\}")


def test_the_table_covers_the_letters_minibidi_shapes():
    letters = {base for base, _ in arabic.PRESENTATION_FORMS}
    assert letters
    assert all(arabic.SHAPE_FIRST <= base <= arabic.SHAPE_LAST
               for base in letters)


def test_a_dual_joining_letter_has_all_four_forms():
    # U+0628 BEH is the textbook dual-joining letter.
    assert arabic.PRESENTATION_FORMS[(0x0628, arabic.ISOLATED)] == 0xFE8F
    assert arabic.PRESENTATION_FORMS[(0x0628, arabic.FINAL)] == 0xFE90
    assert arabic.PRESENTATION_FORMS[(0x0628, arabic.INITIAL)] == 0xFE91
    assert arabic.PRESENTATION_FORMS[(0x0628, arabic.MEDIAL)] == 0xFE92


def test_a_right_joining_letter_has_only_two():
    # U+0627 ALEF joins to its right only, so it has no initial or medial.
    assert arabic.PRESENTATION_FORMS[(0x0627, arabic.ISOLATED)] == 0xFE8D
    assert arabic.PRESENTATION_FORMS[(0x0627, arabic.FINAL)] == 0xFE8E
    assert (0x0627, arabic.INITIAL) not in arabic.PRESENTATION_FORMS
    assert (0x0627, arabic.MEDIAL) not in arabic.PRESENTATION_FORMS


@pytest.mark.skipif(not MINIBIDI.is_file(),
                    reason=f"no engine checkout at {MINIBIDI}")
def test_the_table_agrees_with_the_firmware_that_reads_it():
    """The one place we duplicate engine logic, checked against the engine.

    shape_form() computes 0xFE00 + form_b + form from shapetypes[]. Ours is
    derived from unicodedata instead, so this asserts the two agree rather than
    assuming a transcription stayed right.
    """
    source = MINIBIDI.read_text(encoding="utf-8", errors="replace")
    nodes = SHAPE_NODE.findall(source)
    assert len(nodes) == arabic.SHAPE_LAST - arabic.SHAPE_FIRST + 1, \
        "shapetypes[] did not parse"
    checked = 0
    for hex_base, _joining, hex_form_b in nodes:
        base, form_b = int(hex_base, 16), int(hex_form_b, 16)
        if not form_b:
            # shape_form() returns the character unchanged when form_b is 0,
            # so the device never asks for a shaped codepoint here. U+0640
            # TATWEEL is one: it joins its neighbours and has no form of its
            # own. Ours must agree by having no entry at all.
            assert (base, arabic.ISOLATED) not in arabic.PRESENTATION_FORMS, \
                f"U+{base:04X} has a form we would build and nothing asks for"
            continue
        assert arabic.PRESENTATION_FORMS[(base, arabic.ISOLATED)] == \
            0xFE00 + form_b, f"U+{base:04X} disagrees with shapetypes[]"
        checked += 1
    assert checked > 30, "almost nothing was compared"


def test_lam_alef_is_keyed_where_minibidi_sends_it():
    # minibidi.c hardcodes these four pairs rather than using shapetypes[].
    assert arabic.LAM_ALEF[(0x0622, arabic.ISOLATED)] == 0xFEF5
    assert arabic.LAM_ALEF[(0x0622, arabic.FINAL)] == 0xFEF6
    assert arabic.LAM_ALEF[(0x0627, arabic.ISOLATED)] == 0xFEFB
    assert arabic.LAM_ALEF[(0x0627, arabic.FINAL)] == 0xFEFC


def test_forms_for_returns_what_the_device_will_ask_for():
    asked = arabic.forms_for({0x0628, 0x0627})
    assert 0xFE8F in asked and 0xFE92 in asked
    assert 0xFE8D in asked and 0xFE8E in asked


def test_forms_for_needs_a_lam_before_it_offers_a_lam_alef():
    """The device only forms one where the text has a lam and then an alef."""
    assert 0xFEFB not in arabic.forms_for({0x0627})
    assert 0xFEFB in arabic.forms_for({0x0644, 0x0627})


def test_forms_for_ignores_text_with_no_arabic():
    assert arabic.forms_for({ord("a"), ord("Z"), 0x0400}) == set()


def test_implied_coverage_adds_the_forms_and_keeps_the_letters():
    covered = arabic.implied_coverage(((0x0600, 0x06FF),))
    flat = {cp for start, end in covered for cp in range(start, end + 1)}
    assert 0x0628 in flat, "the letters asked for must survive"
    assert 0xFE91 in flat, "the shape the device will ask for must be added"


def test_implied_coverage_leaves_a_latin_build_alone():
    latin = ((0x0020, 0x007E),)
    assert arabic.implied_coverage(latin) == latin


# --- resolving a face's own joining rules ---------------------------------


def test_a_joining_face_yields_a_run_for_every_form(tmp_path):
    path = tmp_path / "joining.ttf"
    fontsmith.joining_font(path)
    forms = arabic.presentation_forms(path)

    # The dual-joining letter contributes all four of its codepoints.
    for form in (arabic.ISOLATED, arabic.FINAL, arabic.INITIAL, arabic.MEDIAL):
        assert arabic.PRESENTATION_FORMS[(0x0628, form)] in forms
    # The right-joining one contributes only the two it has.
    assert arabic.PRESENTATION_FORMS[(0x0627, arabic.ISOLATED)] in forms
    assert arabic.PRESENTATION_FORMS[(0x0627, arabic.FINAL)] in forms


def test_a_simple_form_is_one_glyph(tmp_path):
    path = tmp_path / "joining.ttf"
    fontsmith.joining_font(path)
    forms = arabic.presentation_forms(path)
    run = forms[arabic.PRESENTATION_FORMS[(0x0628, arabic.INITIAL)]]
    assert len(run.pieces) == 1
    assert run.advance > 0


def test_each_joining_form_reaches_its_own_glyph(tmp_path):
    """A form that resolved to the same glyph as another did not resolve."""
    path = tmp_path / "joining.ttf"
    fontsmith.joining_font(path)
    forms = arabic.presentation_forms(path)
    reached = {forms[arabic.PRESENTATION_FORMS[(0x0628, form)]].pieces[0][0]
               for form in (arabic.ISOLATED, arabic.FINAL,
                            arabic.INITIAL, arabic.MEDIAL)}
    assert len(reached) == 4, "each joining form must reach its own glyph"


def test_a_decomposed_letter_yields_a_multi_glyph_run(tmp_path):
    """Scheherazade spells the hamza alefs this way, and so does Noto."""
    path = tmp_path / "decomposed.ttf"
    fontsmith.joining_font(path, decompose=(0x0627,))
    forms = arabic.presentation_forms(path)
    run = forms[arabic.PRESENTATION_FORMS[(0x0627, arabic.ISOLATED)]]
    assert len(run.pieces) == 2, "a mark plus a base is two glyphs"
    # The second piece sits past the first rather than on top of it, which is
    # what the composed bitmap has to be wide enough to hold.
    assert run.pieces[1][1] > run.pieces[0][1]


def test_lam_alef_resolves_as_a_pair(tmp_path):
    """The device asks for the pair by its own codepoint, not for two letters.

    Missing this left every "wala" in a page of ordinary prose with a hole in
    it, which the letter-by-letter tests could not see.
    """
    path = tmp_path / "joining.ttf"
    fontsmith.joining_font(path)
    forms = arabic.presentation_forms(path)
    for form in (arabic.ISOLATED, arabic.FINAL):
        run = forms[arabic.LAM_ALEF[(0x0627, form)]]
        assert run.pieces, "the pair drew nothing"
        assert run.advance > 0


def test_lam_alef_is_skipped_when_the_face_has_no_lam(tmp_path):
    path = tmp_path / "nolam.ttf"
    fontsmith.box_font(path, [0x0627, ord(" ")])
    assert arabic.LAM_ALEF[(0x0627, arabic.ISOLATED)] not in \
        arabic.presentation_forms(path)


def test_a_face_that_already_carries_a_form_is_left_alone(tmp_path):
    """Nothing to repair, so nothing is synthesized and nothing is paid for."""
    path = tmp_path / "haspresentation.ttf"
    isolated = arabic.PRESENTATION_FORMS[(0x0628, arabic.ISOLATED)]
    fontsmith.box_font(path, [0x0628, isolated, ord(" ")])
    assert isolated not in arabic.presentation_forms(path)


def test_a_face_with_no_arabic_yields_nothing(tmp_path):
    path = tmp_path / "latin.ttf"
    fontsmith.box_font(path, [ord("a"), ord("b"), ord(" ")])
    assert arabic.presentation_forms(path) == {}


# --- coverage resolution ---------------------------------------------------


def test_a_synthesized_codepoint_survives_coverage_resolution(tmp_path):
    """Without this the forms are dropped before anything is rasterized."""
    path = tmp_path / "joining.ttf"
    fontsmith.joining_font(path)
    face = freetype.Face(str(path))
    initial = arabic.PRESENTATION_FORMS[(0x0628, arabic.INITIAL)]

    intervals, sources, _ = convert.resolve_style_coverage(
        face, [], [(initial, initial)], synthesized=[frozenset({initial})])

    assert intervals == [(initial, initial)]
    assert sources[initial] == 0, "the primary face is what synthesizes it"


def test_an_unsynthesized_missing_codepoint_is_still_dropped(tmp_path):
    path = tmp_path / "joining.ttf"
    fontsmith.joining_font(path)
    face = freetype.Face(str(path))
    initial = arabic.PRESENTATION_FORMS[(0x0628, arabic.INITIAL)]

    intervals, _, _ = convert.resolve_style_coverage(
        face, [], [(initial, initial)], synthesized=[frozenset()])

    assert intervals == [], "nothing can draw it, so it must not be built"


def test_a_fallback_face_synthesizes_its_own_forms(tmp_path):
    """An Arabic family named as somebody's fallback is repaired too.

    Resolving only the primary drew a replacement box for every Arabic word
    whenever the primary was the Latin face it usually is.
    """
    latin = tmp_path / "latin.ttf"
    fontsmith.box_font(latin, [ord("a"), ord(" ")])
    joining = tmp_path / "joining.ttf"
    fontsmith.joining_font(joining)
    initial = arabic.PRESENTATION_FORMS[(0x0628, arabic.INITIAL)]

    intervals, sources, _ = convert.resolve_style_coverage(
        freetype.Face(str(latin)), [freetype.Face(str(joining))],
        [(initial, initial)],
        synthesized=[frozenset(), frozenset({initial})])

    assert intervals == [(initial, initial)]
    assert sources[initial] == 1, "the fallback is what synthesizes it"


def test_synthesized_may_name_fewer_faces_than_the_chain_has(tmp_path):
    """A short list must not raise on the faces it does not reach."""
    path = tmp_path / "joining.ttf"
    fontsmith.joining_font(path)
    face = freetype.Face(str(path))
    intervals, _, _ = convert.resolve_style_coverage(
        face, [freetype.Face(str(path))], [(0x0628, 0x0628)], synthesized=[])
    assert intervals == [(0x0628, 0x0628)]


# --- rasterizing a form from its run ---------------------------------------


def _ink(face_path, codepoint, size=16.0):
    """Pixels the device paints for one codepoint, drawn by that face.

    Measured through the render core rather than read out of the .cpfont, so
    what is asserted is what a reader would actually show.
    """
    from crossglyph.preview import REGULAR, build_font
    from crossglyph.render import image

    font_bytes = build_font({REGULAR: face_path}, size,
                            coverage=((0x0020, 0x0020), (codepoint, codepoint)))
    page = image.render_png(font_bytes, chr(codepoint))
    return sum(1 for value in page.convert("L").getdata() if value < 250)


def test_a_synthesized_form_rasterizes_to_ink(tmp_path):
    path = tmp_path / "joining.ttf"
    fontsmith.joining_font(path)
    initial = arabic.PRESENTATION_FORMS[(0x0628, arabic.INITIAL)]
    assert _ink(path, initial) > 0, "the form drew nothing"


def test_a_composite_form_draws_both_of_its_pieces(tmp_path):
    """Both pieces have to land, not just the first one the run names."""
    decomposed = tmp_path / "decomposed.ttf"
    fontsmith.joining_font(decomposed, decompose=(0x0627,))
    plain = tmp_path / "plain.ttf"
    fontsmith.joining_font(plain)

    isolated = arabic.PRESENTATION_FORMS[(0x0627, arabic.ISOLATED)]
    assert len(arabic.presentation_forms(decomposed)[isolated].pieces) == 2
    assert len(arabic.presentation_forms(plain)[isolated].pieces) == 1

    assert _ink(decomposed, isolated) > _ink(plain, isolated) * 1.5, \
        "a mark plus a base must draw more than the base alone"


def _page_ink(face, coverage, text, fallbacks=(), size=16.0):
    """Ink a page of `text` carries, built from this face and coverage."""
    from crossglyph.preview import REGULAR, build_font
    from crossglyph.render import image

    font = build_font({REGULAR: face}, size, coverage=coverage,
                      fallbacks=tuple(str(p) for p in fallbacks))
    page = image.render_png(font, text)
    return sum(1 for v in page.convert("L").getdata() if v < 250)


#: One joined word the fixture can draw, and the coverage its letters need.
WORD = "ببب"


def test_asking_for_the_letters_asks_for_their_shapes(tmp_path):
    """Coverage naming Arabic letters and not their shapes drew a box a word.

    The device converts a letter before it looks a glyph up, so a build with
    the letters alone has nothing at any codepoint it asks for. This is an
    implication of the coverage, not a preset somebody has to know to add.
    """
    path = tmp_path / "joining.ttf"
    fontsmith.joining_font(path)
    letters = tuple(convert.merge_intervals(
        convert.resolve_intervals("base") + [(0x0600, 0x06FF)]))
    forms = {code for low, high in convert.merge_intervals(
        arabic.implied_coverage(letters)) for code in range(low, high + 1)}

    assert arabic.PRESENTATION_FORMS[(0x0628, arabic.INITIAL)] in forms
    # The build resolves the same implication for itself, so a caller that
    # passed only the letters still gets a page rather than boxes.
    assert _page_ink(path, letters, WORD) > 0


def test_unsorted_coverage_still_builds_a_font_the_reader_accepts(tmp_path):
    """The interval table is searched as though it ascends.

    An unsorted one packed without complaint and produced a file the render
    core rejected outright, saying nothing about which end was wrong.
    """
    path = tmp_path / "latin.ttf"
    fontsmith.box_font(path, [ord(" "), ord("a"), 0x00E9])
    scrambled = ((0x0061, 0x0061), (0x0020, 0x0020), (0x00E9, 0x00E9))
    assert _page_ink(path, scrambled, "aé") > 0


def test_a_synthesized_form_advances_as_its_own_glyph_does(tmp_path):
    """Two paths report an advance, and text is even only if they agree.

    The cmap path reports FreeType's linearHoriAdvance and the synthesized one
    reports the shaper's advance scaled to match. A disagreement would space
    Arabic differently from every other script in the same font.
    """
    import freetype

    path = tmp_path / "joining.ttf"
    fontsmith.joining_font(path)
    face = freetype.Face(str(path))
    face.set_char_size(16 * 64, 16 * 64, 150, 150)

    checked = 0
    for run in arabic.presentation_forms(path).values():
        if len(run.pieces) != 1:
            continue
        face.load_glyph(run.pieces[0][0], freetype.FT_LOAD_DEFAULT)
        assert convert.scale_advance(run.advance, face) == \
            face.glyph.linearHoriAdvance
        checked += 1
    assert checked > 5, "almost nothing was compared"


def test_merge_intervals_sorts_and_joins_what_touches():
    assert convert.merge_intervals([(5, 6), (1, 2), (3, 4)]) == [(1, 6)]
    assert convert.merge_intervals([(10, 20), (1, 2)]) == [(1, 2), (10, 20)]
    assert convert.merge_intervals([(1, 9), (3, 5)]) == [(1, 9)]


# --- the per-glyph size cap ------------------------------------------------


def test_an_oversized_glyph_is_skipped_rather_than_killing_the_build(capfd):
    """EpdGlyph packs width and height as uint8, so 255 px is the ceiling.

    Noto Sans Arabic's bismillah is one glyph drawn as a whole phrase and is
    312 px wide at 32 px. It used to raise struct.error out of the packer,
    naming no codepoint and suggesting nothing.
    """
    from crossglyph.preview import REGULAR, build_font

    face = fontpaths.arabic_with_wide_ligature()
    if face is None:
        pytest.skip(f"no engine checkout at {fontpaths.FIRMWARE_ARABIC}")
    font = build_font({REGULAR: face}, 32.0,
                      coverage=((0x0020, 0x0020), (0xFDFD, 0xFDFD)))
    assert font, "the build must survive a glyph it cannot hold"
    assert "FDFD" in capfd.readouterr().err


def test_a_glyph_inside_the_cap_is_still_drawn():
    """The guard must not be a licence to drop ordinary glyphs."""
    from crossglyph.preview import REGULAR, build_font
    from crossglyph.render import image

    face = fontpaths.arabic_with_wide_ligature()
    if face is None:
        pytest.skip(f"no engine checkout at {fontpaths.FIRMWARE_ARABIC}")
    font = build_font({REGULAR: face}, 32.0,
                      coverage=((0x0020, 0x0020), (0xFDFA, 0xFDFA)))
    page = image.render_png(font, "ﷺ")
    assert sum(1 for v in page.convert("L").getdata() if v < 250) > 0


def test_the_arabic_preset_reaches_the_honorific_ligatures():
    """U+FDFA and U+FDFB are ordinary in Arabic prose and small at every size.

    They were excluded only to dodge the neighbour that overflows the cap,
    which is now handled where it belongs.
    """
    covered = {cp for start, end in convert.resolve_intervals("arabic")
               for cp in range(start, end + 1)}
    assert 0xFDFA in covered
    assert 0xFDFB in covered

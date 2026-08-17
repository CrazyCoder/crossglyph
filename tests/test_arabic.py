"""Arabic presentation forms: the table, and the coverage it implies."""
import re

import freetype
import pytest

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
        face, [], [(initial, initial)], synthesized=frozenset({initial}))

    assert intervals == [(initial, initial)]
    assert sources[initial] == 0, "the primary face is what synthesizes it"


def test_an_unsynthesized_missing_codepoint_is_still_dropped(tmp_path):
    path = tmp_path / "joining.ttf"
    fontsmith.joining_font(path)
    face = freetype.Face(str(path))
    initial = arabic.PRESENTATION_FORMS[(0x0628, arabic.INITIAL)]

    intervals, _, _ = convert.resolve_style_coverage(
        face, [], [(initial, initial)], synthesized=frozenset())

    assert intervals == [], "nothing can draw it, so it must not be built"

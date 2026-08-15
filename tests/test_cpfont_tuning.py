import pathlib

import pytest

import fontpaths

from crossglyph import cpfont
from crossglyph.cpfont.tuning import HINTING, LineHeight, Tuning

SRC = fontpaths.truetype()
needs_font = pytest.mark.skipif(SRC is None,
                                reason="set CROSSGLYPH_TEST_FONT to a TTF")


# --- the dataclass --------------------------------------------------------

def test_defaults_match_todays_behaviour():
    t = Tuning()
    assert t.thresholds == (4, 8, 12)
    assert t.gamma == 1.0
    assert t.coverage_lut() is None      # no LUT work when gamma is identity


def test_darken_aa_is_a_threshold_preset():
    assert Tuning.DARKEN_AA == (3, 6, 10)


def test_gamma_above_one_lifts_the_coverage_ramp():
    """Above 1 darkens, which is crengine's sense (gammagen.pl) rather than a
    plain coverage**gamma. CoolReader is the reference renderer for this
    format, so a gamma read off one tool has to mean the same in the other."""
    lut = Tuning(gamma=1.4).coverage_lut()
    assert lut[0] == 0 and lut[255] == 255
    assert lut[128] > 128


def test_gamma_below_one_pulls_coverage_down():
    assert Tuning(gamma=0.7).coverage_lut()[128] < 128


def test_every_step_of_the_slider_darkens():
    """The property a knob has to have: turning it one notch further never
    goes back. Monotonic across the whole range, not merely at the ends --
    matching any particular renderer's numbers is not a goal, but a slider
    that reverses somewhere in the middle is useless."""
    steps = [round(0.5 + 0.05 * n, 2) for n in range(31)]      # 0.5 .. 2.0
    ink = []
    for gamma in steps:
        lut = Tuning(gamma=gamma).coverage_lut()
        ink.append(sum(lut) if lut is not None else sum(range(256)))
    assert ink == sorted(ink), "the coverage curve is not monotonic in gamma"
    assert ink[0] < ink[-1], "the range does not span light to dark"


def test_thresholds_must_ascend():
    with pytest.raises(ValueError, match="ascending"):
        Tuning(thresholds=(8, 4, 12))


def test_thresholds_must_stay_inside_the_4_bit_ramp():
    with pytest.raises(ValueError, match="ascending"):
        Tuning(thresholds=(4, 8, 16))


def test_gamma_must_be_positive():
    with pytest.raises(ValueError, match="positive"):
        Tuning(gamma=0)


def test_an_unknown_hinting_mode_is_rejected():
    with pytest.raises(ValueError, match="hinting"):
        Tuning(hinting="subpixel")


# --- what FreeType is asked for -------------------------------------------

def _target(flags: int) -> int:
    """The FT_Render_Mode packed into the FT_LOAD_TARGET_* field."""
    return (flags >> 16) & 15


@pytest.mark.parametrize("mono", [False, True])
@pytest.mark.parametrize("hinting", HINTING)
def test_nothing_ever_asks_for_a_subpixel_raster(hinting, mono):
    """FT_LOAD_TARGET_* is one enum in one four-bit field, not one bit each,
    so two of them or-ed together are a third mode: LIGHT is 1, MONO is 2, and
    3 is FT_LOAD_TARGET_LCD. FreeType then returns a subpixel bitmap three
    times too wide for the advance beside it, and the page is a smear."""
    import freetype

    assert _target(Tuning(hinting=hinting, mono=mono).load_flags(freetype)) \
        in (freetype.FT_RENDER_MODE_NORMAL, freetype.FT_RENDER_MODE_LIGHT,
            freetype.FT_RENDER_MODE_MONO)


def test_light_hinting_with_a_bilevel_raster_takes_two_calls():
    """One field holds the hinting algorithm and the render mode both, so a
    load can name only one of them. FT_Render_Glyph names the other."""
    import freetype

    tuning = Tuning(hinting="light", mono=True)
    assert _target(tuning.load_flags(freetype)) == freetype.FT_RENDER_MODE_LIGHT
    assert tuning.render_mode(freetype) == freetype.FT_RENDER_MODE_MONO
    assert not tuning.renders_on_load()


@pytest.mark.parametrize("hinting", ["normal", "none", "auto"])
def test_every_other_pairing_is_one_call(hinting):
    import freetype

    tuning = Tuning(hinting=hinting, mono=True)
    assert _target(tuning.load_flags(freetype)) == freetype.FT_RENDER_MODE_MONO
    assert tuning.renders_on_load()


@pytest.mark.parametrize("hinting, flag", [("none", "FT_LOAD_NO_HINTING"),
                                           ("auto", "FT_LOAD_FORCE_AUTOHINT")])
def test_a_bilevel_target_does_not_displace_the_hinting_flags(hinting, flag):
    """These two are bits of their own rather than targets, so they have to
    survive beside one. Chaining them off the same branch would quietly turn
    `none` with mono into ordinary hinting."""
    import freetype

    flags = Tuning(hinting=hinting, mono=True).load_flags(freetype)
    assert flags & getattr(freetype, flag)


def test_as_dict_is_json_stable():
    assert Tuning().as_dict()["thresholds"] == [4, 8, 12]


def test_as_dict_carries_every_knob():
    """The build stamp hashes this to decide what needs rebuilding, so a knob
    missing from it is a knob you can change in a .conf without the builder
    noticing -- which is exactly what happened to `figures`."""
    import dataclasses

    assert set(Tuning().as_dict()) == \
        {field.name for field in dataclasses.fields(Tuning)}


# --- byte-compatibility ---------------------------------------------------

def _build(tmp_path, name, source=None, **kwargs):
    """`source` defaults to the face the machine supplies. A test whose
    subject is a feature a face lacks passes one it built itself."""
    path = tmp_path / f"{name}.cpfont"
    cpfont.generate_cpfont_multistyle(
        {0: str(source or SRC)}, 13, cpfont.resolve_intervals("base"),
        str(path), **kwargs)
    return path.read_bytes()


@needs_font
def test_default_tuning_is_byte_identical_to_no_tuning(tmp_path):
    assert _build(tmp_path, "a") == _build(tmp_path, "b", tuning=Tuning())


@needs_font
def test_darken_aa_matches_its_threshold_preset(tmp_path):
    assert _build(tmp_path, "a", darken_aa=True) == \
        _build(tmp_path, "b", tuning=Tuning(thresholds=Tuning.DARKEN_AA))


@needs_font
def test_gamma_changes_the_bitmap(tmp_path):
    plain = _build(tmp_path, "p")
    dark = _build(tmp_path, "d", tuning=Tuning(gamma=1.6))
    assert plain != dark
    # Only the coverage ramp moved, so glyph count and metrics are untouched
    # and every bitmap keeps its dimensions -- the file is the same length.
    assert len(plain) == len(dark)


@needs_font
def test_gamma_one_is_the_identity(tmp_path):
    assert _build(tmp_path, "a") == _build(tmp_path, "b", tuning=Tuning(gamma=1.0))


@needs_font
def test_lower_thresholds_put_more_pixels_at_full_ink(tmp_path):
    """Level 3 is 0b11, so a darker font has more bits set across the bitmaps."""
    def ink(blob):
        return sum(bin(b).count("1") for b in blob)

    assert ink(_build(tmp_path, "dark", tuning=Tuning(thresholds=(2, 5, 9)))) > \
        ink(_build(tmp_path, "light", tuning=Tuning(thresholds=(6, 10, 14))))


@needs_font
def test_weight_fattens_glyphs(tmp_path):
    thin = _build(tmp_path, "t")
    fat = _build(tmp_path, "f", tuning=Tuning(weight=0.5))
    assert len(fat) > len(thin), "emboldened outlines need bigger bitmaps"


@needs_font
def test_zero_weight_is_the_identity(tmp_path):
    """The no-embolden path keeps FT_LOAD_RENDER, so it must be bit-for-bit
    what upstream produced before the knob existed."""
    assert _build(tmp_path, "a") == _build(tmp_path, "b", tuning=Tuning(weight=0.0))


@needs_font
def test_slant_widens_the_bounding_boxes(tmp_path):
    upright = _build(tmp_path, "u")
    oblique = _build(tmp_path, "o", tuning=Tuning(slant=0.25))
    assert len(oblique) > len(upright)


@needs_font
def test_zero_slant_is_the_identity(tmp_path):
    assert _build(tmp_path, "a") == _build(tmp_path, "b", tuning=Tuning(slant=0.0))


@needs_font
def test_light_hinting_changes_the_result(tmp_path):
    assert _build(tmp_path, "n") != _build(tmp_path, "l",
                                           tuning=Tuning(hinting="light"))


@needs_font
def test_auto_hinting_matches_the_old_force_autohint_flag(tmp_path):
    assert _build(tmp_path, "a", force_autohint=True) == \
        _build(tmp_path, "b", tuning=Tuning(hinting="auto"))


@needs_font
def test_normal_hinting_is_the_identity(tmp_path):
    assert _build(tmp_path, "a") == _build(tmp_path, "b",
                                           tuning=Tuning(hinting="normal"))


def test_stem_darkening_is_applied_and_reversible():
    from crossglyph.cpfont.convert import apply_stem_darkening
    apply_stem_darkening(True)
    apply_stem_darkening(False)      # must not raise either way


CFF = fontpaths.cff()
needs_cff = pytest.mark.skipif(CFF is None, reason="set CROSSGLYPH_TEST_OTF to a CFF face")


@needs_cff
def test_stem_darkening_reaches_a_cff_face(tmp_path):
    """Here its whole reach is the Adobe CF2 interpreter: a TrueType face is
    unmoved, and so is a CFF face under the auto-hinter, which reloads the
    glyph unscaled and so misses the one condition CF2 darkens on."""
    def build(name, **kwargs):
        path = tmp_path / f"{name}.cpfont"
        cpfont.generate_cpfont_multistyle(
            {0: str(CFF)}, 13, cpfont.resolve_intervals("base"), str(path),
            **kwargs)
        return path.read_bytes()

    assert build("off", tuning=Tuning(stem_darkening=False)) != \
        build("on", tuning=Tuning(stem_darkening=True))


@needs_font
def test_stem_darkening_does_not_reach_a_truetype_face(tmp_path):
    assert _build(tmp_path, "off", tuning=Tuning(stem_darkening=False)) == \
        _build(tmp_path, "on", tuning=Tuning(stem_darkening=True))


@needs_font
def test_an_explicit_tuning_outranks_darken_aa(tmp_path):
    """darken_aa is the old spelling; a tuning that says otherwise wins."""
    assert _build(tmp_path, "a", darken_aa=True,
                  tuning=Tuning(thresholds=(2, 5, 9))) == \
        _build(tmp_path, "b", tuning=Tuning(thresholds=(2, 5, 9)))


# --- line height ----------------------------------------------------------

def test_a_bare_number_is_em_relative():
    assert LineHeight.parse("1.15") == LineHeight(1.15, "em")


def test_an_x_suffix_is_a_multiple_of_the_fonts_own_height():
    assert LineHeight.parse("0.85x") == LineHeight(0.85, "scale")


def test_a_px_suffix_is_absolute():
    assert LineHeight.parse("26px") == LineHeight(26.0, "px")


def test_em_resolves_against_the_em_square_not_the_font():
    # 13pt at 150dpi = 27.083px per em; the font's own 31 is ignored.
    assert LineHeight.parse("1.15").resolve(natural=31, ppem=27.083) == 31
    assert LineHeight.parse("1.0").resolve(natural=31, ppem=27.083) == 27


def test_scale_resolves_against_the_fonts_own_height():
    assert LineHeight.parse("0.85x").resolve(natural=40, ppem=27.083) == 34


def test_px_ignores_both():
    assert LineHeight.parse("26px").resolve(natural=40, ppem=27.083) == 26


def test_the_result_is_clamped_to_the_uint8_field():
    assert LineHeight.parse("400px").resolve(natural=31, ppem=27.083) == 255
    assert LineHeight.parse("0.001x").resolve(natural=31, ppem=27.083) == 1


def test_a_nonsense_spec_is_rejected():
    with pytest.raises(ValueError, match="line_height"):
        LineHeight.parse("wide")


def test_a_negative_line_height_is_rejected():
    with pytest.raises(ValueError, match="positive"):
        LineHeight.parse("-1")


def test_str_round_trips():
    for raw in ("1.15", "0.85x", "26px"):
        assert str(LineHeight.parse(raw)) == raw


def test_the_metric_knobs_default_to_off():
    t = Tuning()
    assert t.line_height is None
    assert t.letter_spacing == 0.0
    assert t.word_spacing == 0.0


def test_as_dict_renders_line_height_as_its_spec():
    assert Tuning().as_dict()["line_height"] is None
    assert Tuning(line_height=LineHeight.parse("1.15")).as_dict()["line_height"] \
        == "1.15"


@needs_font
def test_line_height_overrides_the_fonts_own(tmp_path):
    from crossglyph import fontbuild
    path = tmp_path / "lh.cpfont"
    cpfont.generate_cpfont_multistyle(
        {0: str(SRC)}, 13, cpfont.resolve_intervals("base"), str(path),
        tuning=Tuning(line_height=LineHeight.parse("24px")))
    assert fontbuild.style_metrics(path).advance_y == 24


@needs_font
def test_em_relative_line_height_ignores_the_font(tmp_path):
    """13pt at 150dpi is 27.08px per em, so 1.0em is 27 whatever hhea says."""
    from crossglyph import fontbuild
    path = tmp_path / "em.cpfont"
    cpfont.generate_cpfont_multistyle(
        {0: str(SRC)}, 13, cpfont.resolve_intervals("base"), str(path),
        tuning=Tuning(line_height=LineHeight.parse("1.0")))
    assert fontbuild.style_metrics(path).advance_y == 27


@needs_font
def test_a_scale_line_height_is_relative_to_the_font(tmp_path):
    from crossglyph import fontbuild
    natural = tmp_path / "n.cpfont"
    cpfont.generate_cpfont_multistyle(
        {0: str(SRC)}, 13, cpfont.resolve_intervals("base"), str(natural))
    scaled = tmp_path / "s.cpfont"
    cpfont.generate_cpfont_multistyle(
        {0: str(SRC)}, 13, cpfont.resolve_intervals("base"), str(scaled),
        tuning=Tuning(line_height=LineHeight.parse("0.5x")))
    assert fontbuild.style_metrics(scaled).advance_y == \
        round(fontbuild.style_metrics(natural).advance_y * 0.5)


@needs_font
def test_line_height_leaves_the_baseline_alone(tmp_path):
    """ascender places the baseline inside the line and drives underline and
    sup/sub offsets; only the pitch should move."""
    from crossglyph import fontbuild
    before = tmp_path / "b.cpfont"
    cpfont.generate_cpfont_multistyle(
        {0: str(SRC)}, 13, cpfont.resolve_intervals("base"), str(before))
    after = tmp_path / "a.cpfont"
    cpfont.generate_cpfont_multistyle(
        {0: str(SRC)}, 13, cpfont.resolve_intervals("base"), str(after),
        tuning=Tuning(line_height=LineHeight.parse("20px")))
    assert fontbuild.style_metrics(after).ascender == \
        fontbuild.style_metrics(before).ascender
    assert fontbuild.style_metrics(after).descender == \
        fontbuild.style_metrics(before).descender


@needs_font
def test_no_line_height_is_byte_identical(tmp_path):
    assert _build(tmp_path, "a") == _build(tmp_path, "b", tuning=Tuning())


# --- letter and word spacing ----------------------------------------------

def _advance(path, codepoint):
    """One glyph's advanceX, in pixels, read back out of the .cpfont."""
    import struct
    blob = path.read_bytes()
    interval_count, glyph_count = struct.unpack_from("<II", blob, 32 + 4)
    data_offset = struct.unpack_from("<I", blob, 32 + 24)[0]
    for i in range(interval_count):
        start, end, first = struct.unpack_from("<III", blob, data_offset + i * 12)
        if start <= codepoint <= end:
            index = first + codepoint - start
            break
    else:
        raise AssertionError(f"U+{codepoint:04X} not covered")
    glyphs_at = data_offset + interval_count * 12
    return struct.unpack_from("<H", blob, glyphs_at + index * 16 + 2)[0] / 16


def _pair(tmp_path, tuning):
    plain, tuned = tmp_path / "p.cpfont", tmp_path / "t.cpfont"
    for path, setting in ((plain, None), (tuned, tuning)):
        cpfont.generate_cpfont_multistyle(
            {0: str(SRC)}, 13, cpfont.resolve_intervals("base"), str(path),
            tuning=setting)
    return plain, tuned


@needs_font
def test_letter_spacing_widens_every_glyph(tmp_path):
    plain, wide = _pair(tmp_path, Tuning(letter_spacing=0.5))
    for ch in "aWm":
        assert _advance(wide, ord(ch)) == _advance(plain, ord(ch)) + 0.5


@needs_font
def test_word_spacing_moves_only_the_space(tmp_path):
    plain, wide = _pair(tmp_path, Tuning(word_spacing=1.0))
    assert _advance(wide, 0x20) == _advance(plain, 0x20) + 1.0
    assert _advance(wide, ord("a")) == _advance(plain, ord("a"))


@needs_font
def test_word_spacing_stacks_on_letter_spacing(tmp_path):
    """As in CSS: letter-spacing applies to every character, word-spacing adds
    to the space on top of it."""
    plain, both = _pair(tmp_path, Tuning(letter_spacing=0.25, word_spacing=0.5))
    assert _advance(both, 0x20) == _advance(plain, 0x20) + 0.75


@needs_font
def test_negative_letter_spacing_tightens(tmp_path):
    plain, tight = _pair(tmp_path, Tuning(letter_spacing=-0.25))
    assert _advance(tight, ord("a")) == _advance(plain, ord("a")) - 0.25


@needs_font
def test_zero_spacing_is_byte_identical(tmp_path):
    assert _build(tmp_path, "a") == \
        _build(tmp_path, "b", tuning=Tuning(letter_spacing=0.0, word_spacing=0.0))


# --- kerning and ligatures ------------------------------------------------

def test_the_table_knobs_default_to_on():
    t = Tuning()
    assert t.kerning == 1.0
    assert t.ligatures is True


def test_kerning_must_not_be_negative():
    with pytest.raises(ValueError, match="kerning"):
        Tuning(kerning=-0.5)


def test_kerning_may_be_zero_meaning_off():
    assert Tuning(kerning=0.0).kerning == 0.0


def test_the_table_knobs_are_in_the_stamp_payload():
    assert Tuning().as_dict()["kerning"] == 1.0
    assert Tuning().as_dict()["ligatures"] is True


def _counts(path):
    """(kern left entries, kern right entries, ligature pairs) from the TOC."""
    import struct
    blob = path.read_bytes()
    left, right = struct.unpack_from("<HH", blob, 32 + 17)
    ligatures = struct.unpack_from("<B", blob, 32 + 23)[0]
    return left, right, ligatures


LIGA = fontpaths.noto()
needs_liga = pytest.mark.skipif(
    LIGA is None, reason="needs the firmware's NotoSans source")


def _build_liga(tmp_path, name, **kwargs):
    """A face with real kerning and ligatures, over latin-ext so both fire."""
    path = tmp_path / f"{name}.cpfont"
    cpfont.generate_cpfont_multistyle(
        {0: str(LIGA)}, 13, cpfont.resolve_intervals("latin-ext"), str(path),
        **kwargs)
    return path


@needs_liga
def test_the_reference_face_has_both_tables(tmp_path):
    """Guards the tests below: they prove nothing against an empty table."""
    left, right, ligatures = _counts(_build_liga(tmp_path, "ref"))
    assert left > 0 and right > 0
    assert ligatures > 0


@needs_liga
def test_kerning_off_drops_the_table(tmp_path):
    assert _counts(_build_liga(tmp_path, "off",
                               tuning=Tuning(kerning=0.0)))[:2] == (0, 0)


@needs_liga
def test_kerning_off_leaves_ligatures_alone(tmp_path):
    _, _, ligatures = _counts(_build_liga(tmp_path, "off",
                                          tuning=Tuning(kerning=0.0)))
    assert ligatures > 0


@needs_liga
def test_ligatures_off_drops_only_the_ligature_table(tmp_path):
    left, right, ligatures = _counts(
        _build_liga(tmp_path, "off", tuning=Tuning(ligatures=False)))
    assert ligatures == 0
    assert left > 0 and right > 0


@needs_liga
def test_halved_kerning_never_exceeds_the_original(tmp_path):
    """Scaling down can merge classes but must never add adjustment."""
    full = _build_liga(tmp_path, "full")
    half = _build_liga(tmp_path, "half", tuning=Tuning(kerning=0.5))
    assert half.stat().st_size <= full.stat().st_size


@needs_liga
def test_kerning_one_is_byte_identical(tmp_path):
    assert _build_liga(tmp_path, "a").read_bytes() == \
        _build_liga(tmp_path, "b", tuning=Tuning(kerning=1.0)).read_bytes()


@needs_liga
def test_ligatures_on_is_byte_identical(tmp_path):
    assert _build_liga(tmp_path, "a").read_bytes() == \
        _build_liga(tmp_path, "b", tuning=Tuning(ligatures=True)).read_bytes()


# --- proportional figures -------------------------------------------------

def _figures(tmp_path, source, tuning=None):
    path = tmp_path / ("prop" if tuning else "plain")
    path = path.with_suffix(".cpfont")
    cpfont.generate_cpfont_multistyle(
        {0: str(source)}, 13, cpfont.resolve_intervals("base"), str(path),
        tuning=tuning)
    return path


def test_figures_defaults_to_whatever_the_cmap_gives():
    assert Tuning().figures == "default"


def test_an_unknown_figure_style_is_refused():
    with pytest.raises(ValueError, match="figures"):
        Tuning(figures="oldstyle")


def _pnum_face(tmp_path):
    """A CFF face whose designer drew proportional figures, built here.

    Not a face off the machine. These three want one specific property -- a
    pnum feature that narrows some digits and not others -- and the gate said
    only "a CFF face": point CROSSGLYPH_TEST_OTF at a reasonable one that
    happens not to draw proportional figures, as the bundled CJK face does,
    and all three fail while saying nothing about the converter. Built, they
    also run for everybody rather than for whoever set the variable.

    CFF, because the substitution is read through the Adobe driver here and a
    TrueType face would exercise the other one.
    """
    import fontsmith

    return fontsmith.box_font(tmp_path / "Prop-Regular.ttf",
                              [ord(ch) for ch in "0123456789aHWm "],
                              figures=True, cff=True, family="Prop")


def test_proportional_figures_narrow_the_one(tmp_path):
    """The gap tabular figures leave around a narrow digit in prose is the
    entire reason the feature exists, and the one is the digit it shows on.

    Asserting the width rather than merely "narrower" is what makes this catch
    the substitution landing on the *wrong* glyph: the pnum alternates carry no
    cmap entry, so they are reachable only by glyph index, and an index read
    against the wrong table would still give some other width.
    """
    face = _pnum_face(tmp_path)
    plain = _figures(tmp_path, face)
    prop = _figures(tmp_path, face, Tuning(figures="proportional"))
    ratio = _advance(prop, ord("1")) / _advance(plain, ord("1"))
    assert abs(ratio - 0.5) < 0.05, ratio


def test_proportional_figures_stop_all_digits_being_one_width(tmp_path):
    """The defining property: tabular means every digit shares an advance."""
    face = _pnum_face(tmp_path)
    plain = _figures(tmp_path, face)
    prop = _figures(tmp_path, face, Tuning(figures="proportional"))
    assert len({_advance(plain, ord(d)) for d in "0123456789"}) == 1
    assert len({_advance(prop, ord(d)) for d in "0123456789"}) > 1


def test_proportional_figures_leave_the_letters_alone(tmp_path):
    face = _pnum_face(tmp_path)
    plain = _figures(tmp_path, face)
    prop = _figures(tmp_path, face, Tuning(figures="proportional"))
    for ch in "aHWm":
        assert _advance(prop, ord(ch)) == _advance(plain, ord(ch))


def test_a_font_without_pnum_is_honestly_unmoved(tmp_path):
    """A face with no pnum feature is unmoved by the knob, the same shape as
    ligatures on a face with no ligature pairs. Inert, not broken.

    Built here rather than taken from the machine: the subject is a face
    *without* the feature, and a font somebody points at may well have one.
    This asserted a property of whatever CROSSGLYPH_TEST_FONT happened to
    name, and a build of Arial that carries pnum failed it.
    """
    import fontsmith

    face = fontsmith.box_font(tmp_path / "Probe-Regular.ttf",
                              [ord(ch) for ch in "0123456789abc"])
    assert _build(tmp_path, "a", face) == \
        _build(tmp_path, "b", face, tuning=Tuning(figures="proportional"))


@needs_cff
def test_default_figures_are_byte_identical(tmp_path):
    assert _figures(tmp_path, CFF).read_bytes() == \
        _figures(tmp_path, CFF, Tuning(figures="default")).read_bytes()

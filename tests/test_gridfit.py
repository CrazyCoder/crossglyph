import pytest

from crossglyph.preview import gridfit


def _lines(*rows):
    return [bytes(row) for row in rows]


def _pack(rows):
    """Pack level rows the way the converter does: four pixels a byte, first
    pixel in the high bits, rows continuous."""
    flat = [level for row in rows for level in row]
    flat += [0] * (-len(flat) % 4)
    return bytes((flat[i] << 6) | (flat[i + 1] << 4) | (flat[i + 2] << 2)
                 | flat[i + 3] for i in range(0, len(flat), 4))


def test_a_clean_stem_scores_100():
    ev = gridfit.straight(_lines(*[[3, 3]] * 6))
    assert ev.edge == 12
    assert ev.fit == 100


def test_a_light_fringe_on_a_stem_costs_its_pixels():
    ev = gridfit.straight(_lines(*[[3, 3, 1]] * 6))
    assert (ev.edge, ev.light, ev.dark) == (12, 6, 0)
    assert ev.fit == pytest.approx(50)


def test_a_stem_with_no_solid_core_counts_in_full():
    """Two dark-grey columns are the blurriest a stem gets, and a measure that
    looked for a solid core first would skip it entirely."""
    ev = gridfit.straight(_lines(*[[2, 2]] * 6))
    assert (ev.edge, ev.light, ev.dark) == (12, 0, 12)
    assert ev.fit < 100


def test_a_run_shorter_than_minrun_is_not_a_straight_feature():
    ev = gridfit.straight(_lines(*[[3, 3, 1]] * (gridfit.MINRUN - 1)))
    assert ev.edge == 0
    assert ev.fit is None


def test_a_curve_adds_nothing():
    """Every row of a curve is a different cross-section."""
    ev = gridfit.straight(_lines(
        [0, 0, 1, 3, 3, 1], [0, 1, 3, 3, 1, 0], [1, 3, 3, 1, 0, 0],
        [0, 1, 3, 3, 1, 0], [0, 0, 1, 3, 3, 1]))
    assert ev.edge == 0


def test_a_fringed_stem_lowers_x_and_leaves_y():
    clean = gridfit.glyph_evidence(3, 6, _pack([[3, 3, 0]] * 6))
    fringed = gridfit.glyph_evidence(3, 6, _pack([[3, 3, 1]] * 6))
    assert clean.x.fit == 100
    assert fringed.x.fit < 100
    assert (fringed.y.edge, fringed.y.light) == (clean.y.edge, clean.y.light)


def test_a_fringed_bar_lowers_y_and_leaves_x():
    clean = gridfit.glyph_evidence(6, 3, _pack([[3] * 6, [3] * 6, [0] * 6]))
    fringed = gridfit.glyph_evidence(6, 3, _pack([[3] * 6, [3] * 6, [1] * 6]))
    assert clean.y.fit == 100
    assert fringed.y.fit < 100
    assert (fringed.x.edge, fringed.x.light) == (clean.x.edge, clean.x.light)


def test_decode_reads_rows_across_byte_boundaries():
    rows = [[3, 0, 1], [2, 3, 1]]
    assert gridfit.decode(3, 2, _pack(rows)) == _lines(*rows)


def test_letter_weights_count_letters_per_style():
    weights = gridfit.letter_weights("ab, *b1* _c_", styles={0, 1, 2})
    assert weights[0] == {ord("a"): 1, ord("b"): 1}
    assert weights[1] == {ord("b"): 1}
    assert weights[2] == {ord("c"): 1}


def test_a_style_the_font_lacks_is_counted_as_regular():
    """The device draws a missing style with the regular face."""
    weights = gridfit.letter_weights("a *b*", styles={0})
    assert weights == {0: {ord("a"): 1, ord("b"): 1}}


def _build(tmp_path, codepoints, styles=(0, 1)):
    from fontsmith import box_font

    from crossglyph import cpfont

    face = box_font(tmp_path / "Probe-Regular.ttf", codepoints, family="Probe")
    out = tmp_path / "probe.cpfont"
    cpfont.generate_cpfont_multistyle(
        {style: str(face) for style in styles}, 14,
        [(cp, cp) for cp in sorted(codepoints)], str(out))
    return face, out.read_bytes()


def test_read_glyphs_returns_the_converters_own_bitmaps(tmp_path):
    from crossglyph.cpfont import convert

    codepoints = [0x20, 0x41, 0x61, 0x6E]
    face, blob = _build(tmp_path, codepoints)
    expected = {glyph.code_point: (glyph.width, glyph.height, packed)
                for glyph, packed in convert.rasterize_font_style(
                    str(face), 14, [(cp, cp) for cp in codepoints]).all_glyphs}
    glyphs = gridfit.read_glyphs(blob)
    assert set(glyphs) == {0, 1}
    for style in (0, 1):
        assert glyphs[style] == expected


def test_read_glyphs_finds_bitmaps_past_kerning_and_ligatures(tmp_path, noto_or_skip):
    """Box fonts carry no kerning, so only a real face proves the bitmap
    section is found past the kerning tables and ligatures."""
    import struct

    from crossglyph import cpfont
    from crossglyph.cpfont import convert

    intervals = cpfont.resolve_intervals("base")
    out = tmp_path / "noto.cpfont"
    cpfont.generate_cpfont_multistyle({0: str(noto_or_skip)}, 14, intervals, str(out))
    blob = out.read_bytes()
    kern_left, kern_right = struct.unpack_from("<HH", blob, 32 + 17)
    assert kern_left and kern_right
    expected = {glyph.code_point: (glyph.width, glyph.height, packed)
                for glyph, packed in convert.rasterize_font_style(
                    str(noto_or_skip), 14, intervals).all_glyphs}
    assert gridfit.read_glyphs(blob)[0] == expected


def test_read_glyphs_of_something_else_is_empty():
    assert gridfit.read_glyphs(b"not a font") == {}


def test_score_weights_by_letters_on_the_page(tmp_path):
    _, blob = _build(tmp_path, [0x20, 0x61, 0x6E])
    result = gridfit.score(blob, "an " * 200)
    assert result.letters == 400
    assert result.confident
    assert result.fit is not None
    assert set(result.styles) == {0}


def test_a_short_text_is_not_confident(tmp_path):
    _, blob = _build(tmp_path, [0x20, 0x61, 0x6E])
    result = gridfit.score(blob, "an an")
    assert result.letters == 4
    assert not result.confident


def test_every_candidate_keeps_its_label():
    """The reader's list shows the label, so a suggestion must not move it."""
    from crossglyph.fontconf import size_label

    for label in range(6, 41):
        assert {size_label(size) for size in gridfit.candidates(label)} == {label}


def test_my_sizes_are_targeted_by_their_labels():
    assert gridfit.targets(sizes=[13, 13.75, 15]) == [(13, 13), (13.75, 14), (15, 15)]


def test_a_range_spreads_whole_sizes_evenly():
    assert [label for _, label in gridfit.targets(low=12, high=19, count=8)] == \
        list(range(12, 20))
    assert [label for _, label in gridfit.targets(low=12, high=18, count=4)] == \
        [12, 14, 16, 18]


def test_a_range_too_narrow_for_its_count_is_refused():
    with pytest.raises(ValueError, match="8 sizes"):
        gridfit.targets(low=12, high=14, count=8)


@pytest.mark.parametrize("low, high, count", [(5, 12, 4), (12, 41, 4), (14, 12, 4),
                                              (12, 18, 5)])
def test_a_range_outside_the_knob_or_an_odd_count_is_refused(low, high, count):
    with pytest.raises(ValueError):
        gridfit.targets(low=low, high=high, count=count)


def test_the_pick_is_the_best_fit():
    assert gridfit.pick(13, {12.5: 60, 12.75: 98, 13: 70, 13.25: 64}) == 12.75


def test_a_near_tie_goes_to_the_label_then_the_smaller():
    assert gridfit.pick(13, {12.5: 99.5, 12.75: 90, 13: 99, 13.25: 100}) == 13
    assert gridfit.pick(13, {12.5: 50, 12.75: 99.5, 13: 50, 13.25: 100}) == 12.75


def test_a_label_with_nothing_to_judge_has_no_pick():
    assert gridfit.pick(13, {12.5: None, 12.75: None, 13: None, 13.25: None}) is None


def test_mono_has_no_score(tmp_path):
    _, blob = _build(tmp_path, [0x20, 0x61, 0x6E])
    result = gridfit.score(blob, "an " * 200, mono=True)
    assert result.fit is None
    assert result.x is None and result.y is None

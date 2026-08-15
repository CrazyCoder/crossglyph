"""One real rasterization, end to end. Slow, and skips without the clones."""
import shutil
import struct

import fontpaths
import pytest

from crossglyph import fontbuild, fontconf


@pytest.fixture
def project(tmp_path, noto_or_skip):
    source = tmp_path / "src"
    source.mkdir()
    shutil.copy(noto_or_skip, source / "Probe-Regular.ttf")
    # ASCII only, one small size: enough to exercise the whole pipeline without
    # spending a minute on Cyrillic and Greek coverage. No fallback setting or
    # downloaded set: the default build has to stand on its own.
    (source / "probe.conf").write_text(
        "sizes = 12\nintervals = base\n", encoding="utf-8")
    return fontconf.parse_config(source / "probe.conf").variants()[0]


def _build(variant, tmp_path, force=False):
    return fontbuild.build_variant(variant, tmp_path / "out", force=force)


def test_produces_a_version_4_cpfont(project, tmp_path):
    report = _build(project, tmp_path)
    assert report.built == [12]
    out = tmp_path / "out" / "Probe" / "Probe_12.cpfont"
    blob = out.read_bytes()
    assert blob[:8] == b"CPFONT\x00\x00"
    assert struct.unpack_from("<H", blob, 8)[0] == 4


def test_second_run_rebuilds_nothing(project, tmp_path):
    _build(project, tmp_path)
    report = _build(project, tmp_path)
    assert report.built == []
    assert report.skipped == [12]


def test_a_deleted_output_is_rebuilt(project, tmp_path):
    _build(project, tmp_path)
    (tmp_path / "out" / "Probe" / "Probe_12.cpfont").unlink()
    assert _build(project, tmp_path).built == [12]


def test_changing_the_font_rebuilds(project, tmp_path, noto_or_skip):
    _build(project, tmp_path)
    # Same bytes, new mtime: content hashing must see no reason to rebuild.
    shutil.copy(noto_or_skip, project.config.styles["regular"])
    assert _build(project, tmp_path).built == []


def test_the_pool_really_builds_in_other_processes(tmp_path):
    """The one thing only a real pool can show: a Job survives the trip to a
    spawned interpreter and back. Everything else about a build is tested
    against a stubbed run_jobs, which would never notice a Config that had
    stopped pickling."""
    import fontsmith

    source = tmp_path / "src"
    source.mkdir()
    fontsmith.box_font(source / "Probe-Regular.ttf", range(0x41, 0x5B))
    (source / "probe.conf").write_text(
        "sizes = 10 12\nintervals = base\nfallbacks = no\n", encoding="utf-8")
    variant = fontconf.parse_config(source / "probe.conf").variants()[0]
    out = tmp_path / "out"
    jobs = fontbuild.plan_variant(variant, out)[1]
    assert len(jobs) == 2

    landed = list(fontbuild.run_jobs(jobs, out, workers=2))
    assert sorted(one.job.size for one in landed) == [10, 12]
    assert [one.error for one in landed] == [None, None], landed
    assert all(one.built.bytes > 0 for one in landed)
    for size in (10, 12):
        assert (out / "Probe" / f"Probe_{size}.cpfont").is_file()


def _darkening_moves(face, hinting):
    """Whether turning stem darkening on changes a single size of `face`."""
    from crossglyph.cpfont.tuning import Tuning
    from crossglyph.preview import build_font

    built = [build_font({0: face}, 13, coverage=((0x41, 0x5A),),
                        tuning=Tuning(hinting=hinting, stem_darkening=darken))
             for darken in (False, True)]
    return built[0] != built[1]


def _grayscale_moves(face, hinting):
    """Whether grayscale hinting changes a single size of `face`."""
    from crossglyph.cpfont.tuning import Tuning
    from crossglyph.preview import build_font

    built = [build_font({0: face}, 13, coverage=((0x41, 0x5A),),
                        tuning=Tuning(hinting=hinting, grayscale_hinting=on))
             for on in (False, True)]
    return built[0] != built[1]


def _greys_on_page(font_bytes, text="Hamburgefonstiv illustration"):
    """The distinct grey levels a built font actually draws.

    Off the rendered page rather than out of the file: a .cpfont's bytes are
    header, tables and bitmaps together, and two bits read anywhere in them
    land on all four values whatever the glyphs use.
    """
    from crossglyph.preview import PageSpec, preview_page

    page = preview_page(font_bytes, text, PageSpec(margin=6))
    return set(page.convert("L").getdata())


def test_mono_rasterizing_builds_a_font_with_two_levels():
    """The point of the switch. FreeType's 1-bit rasterizer decides each pixel
    with dropout control rather than by thresholding coverage, so what lands in
    the .cpfont is empty or full and nothing between.

    A real face: a synthesized one is drawn as boxes whose edges fall on the
    pixel grid, so its coverage is already two-valued and the switch would
    prove nothing.
    """
    import fontpaths

    face = fontpaths.truetype()
    if face is None:
        pytest.skip("needs CROSSGLYPH_TEST_FONT")

    from crossglyph.cpfont.tuning import Tuning
    from crossglyph.preview import build_font

    coverage = ((0x41, 0x7A),)
    grey = build_font({0: face}, 12, coverage=coverage, tuning=Tuning())
    mono = build_font({0: face}, 12, coverage=coverage, tuning=Tuning(mono=True))

    assert grey != mono, "mono rasterizing changed nothing"
    # The greyscale build draws the middle levels; the mono one cannot.
    on_grey, on_mono = _greys_on_page(grey), _greys_on_page(mono)
    assert len(on_grey) > 2, f"the greyscale build drew no midtones: {on_grey}"
    assert len(on_mono) == 2, f"a mono build drew midtones: {sorted(on_mono)}"
    assert on_mono <= on_grey, "mono drew a level the four-level palette lacks"


def test_mono_rasterizing_survives_light_hinting():
    """Both switches at once asked FreeType for FT_LOAD_TARGET_LCD, since LIGHT
    and MONO are 1 and 2 in one four-bit field and 3 is LCD. Every glyph came
    back a subpixel bitmap three times too wide for its advance, so the letters
    piled into each other and the page was unreadable, on every face.
    """
    import fontpaths

    face = fontpaths.truetype()
    if face is None:
        pytest.skip("needs CROSSGLYPH_TEST_FONT")

    from crossglyph.cpfont.tuning import Tuning
    from crossglyph.preview import build_font

    coverage = ((0x41, 0x7A),)
    plain = build_font({0: face}, 12, coverage=coverage,
                       tuning=Tuning(mono=True))
    light = build_font({0: face}, 12, coverage=coverage,
                       tuning=Tuning(mono=True, hinting="light"))

    levels = _greys_on_page(light)
    assert len(levels) == 2, f"a mono build drew midtones: {sorted(levels)}"
    # Same glyphs at the same size, so a build carrying three times the pixels
    # is the LCD bitmap and nothing else.
    assert len(light) < 2 * len(plain)
    assert light != plain, "light hinting changed nothing under mono"


def test_mono_rasterizing_is_not_the_thresholds_in_disguise():
    """Thresholding coverage to two levels is what the device already does with
    anti-aliasing off, and it is the thing mono is meant to beat. Pushing every
    cut point to the bottom gives a two-level build too, so the switch has to
    differ from that as well or it is an elaborate way to set thresholds.
    """
    import fontpaths

    face = fontpaths.truetype()
    if face is None:
        pytest.skip("needs CROSSGLYPH_TEST_FONT")

    from crossglyph.cpfont.tuning import Tuning
    from crossglyph.preview import build_font

    coverage = ((0x41, 0x7A),)
    thresholded = build_font({0: face}, 12, coverage=coverage,
                             tuning=Tuning(thresholds=(1, 2, 3)))
    mono = build_font({0: face}, 12, coverage=coverage, tuning=Tuning(mono=True))
    assert thresholded != mono


def test_grayscale_hinting_only_reaches_a_face_the_bytecode_draws():
    """What the preview greys that switch on. It picks FreeType's interpreter
    version 35, so it moves a TrueType face carrying bytecode under `normal`
    hinting and nothing else: `light` and `auto` hand the face to the
    auto-hinter, and `none` hints not at all.

    A real face again, and a hinted one -- the fixtures carry no bytecode, so
    every mode would pass the negatives here while proving nothing. The bundled
    Literata is that case rather than the exception: it is hinted for the
    auto-hinter, and this switch is dead for it in every mode, which is why the
    gate asks the font and not only the hinting row.
    """
    import fontpaths

    face = fontpaths.truetype()
    if face is None:
        pytest.skip("needs CROSSGLYPH_TEST_FONT pointed at a hinted face")

    assert _grayscale_moves(face, "normal"), \
        f"{face.name} no longer answers the interpreter under normal hinting, " \
        f"so either it lost its bytecode or the preview greys a switch that works"
    for hinting in ("light", "auto", "none"):
        assert not _grayscale_moves(face, hinting), \
            f"hinting={hinting} now reaches the interpreter, so the preview " \
            f"is greying a switch that works"


def test_the_bundled_family_is_the_case_the_font_side_gate_is_for():
    """Literata carries a 7-byte `prep` and nothing else, which is a stub: both
    interpreters draw it identically, so the switch is dead for it whatever the
    hinting row says. A gate that read only the hinting mode would offer it on
    the one family every new user opens. This is what pins that, since the
    stub is also what server.face_hinting reads to grey it."""
    face = fontbuild.STARTER_DIR / "Literata[opsz,wght].ttf"
    assert face.is_file(), "the bundled family is what this measures"
    for hinting in ("normal", "light", "auto", "none"):
        assert not _grayscale_moves(face, hinting), hinting


def test_a_truetype_face_is_only_darkened_under_light_hinting():
    """What the preview greys the switch on. FreeType darkens a TrueType face
    through the auto-hinter's light mode and nowhere else, so under any other
    hinting the switch draws the identical page.

    A real face, because a synthesized one cannot show this: the darkening is
    applied to stems the fitter has found, and a fixture drawn as plain boxes
    is unmoved in every mode -- which would pass the three negatives here
    while proving nothing.
    """
    face = fontbuild.STARTER_DIR / "Literata[opsz,wght].ttf"
    assert face.is_file(), "the bundled family is what this measures"

    assert _darkening_moves(face, "light"), \
        "light hinting no longer darkens a TrueType face, so the preview is " \
        "greying a switch that works"
    for hinting in ("normal", "none", "auto"):
        assert not _darkening_moves(face, hinting), \
            f"hinting={hinting} now darkens a TrueType face, so the preview " \
            f"is greying a switch that works"


def test_a_cff_face_is_darkened_unless_the_auto_hinter_is_in_charge():
    """The other half of the rule. Only `auto` is greyed for a CFF face, and
    the reason is not the auto-hinter's own fitting: it reloads the glyph
    unscaled, and CF2 darkens a scaled load only, so neither engine darkens.

    The rest is left alone rather than promised, since a CFF face whose stems
    fall where FreeType's darkening curve rounds to nothing is unmoved too,
    and nothing short of rasterizing can know that.
    """
    name = "NotoSansCJKjp-Regular.otf"
    faces = fontbuild.fallback_dir()
    face = faces / name if faces else None
    if face is None or not face.is_file():
        declared = fontpaths.cff()
        face = declared if declared and declared.name == name else None
    if face is None:
        pytest.skip("needs the fetched Noto CJK face in the fallback folder "
                    "or CROSSGLYPH_TEST_OTF")

    assert not _darkening_moves(face, "auto"), \
        "the auto-hinter now darkens a CFF face, so the preview is greying " \
        "a switch that works"
    assert _darkening_moves(face, "normal"), \
        "the CFF driver stopped darkening, which is the half of the rule " \
        "that leaves the switch alone"


# --- variable fonts -------------------------------------------------------
# These build a synthetic variable face rather than a real one, so they run
# without the clones the fixture above needs.

def _variable_project(tmp_path, extra=""):
    import fontsmith

    source = tmp_path / "src"
    source.mkdir(exist_ok=True)
    fontsmith.variable_box_font(source / "Probe[wght].ttf", range(0x41, 0x5B))
    (source / "probe.conf").write_text(
        "sizes = 12\nintervals = base\nfallbacks = no\nspace_glyphs = no\n" + extra,
        encoding="utf-8")
    return fontconf.parse_config(source / "probe.conf").variants()[0]


def test_one_variable_file_builds_the_bold_slot_too(tmp_path):
    """The family ships one file and the .cpfont carries two styles: the second
    is the same outlines at the weight the font calls Bold."""
    variant = _variable_project(tmp_path)
    assert sorted(variant.config.styles) == ["bold", "regular"]
    _build(variant, tmp_path)
    blob = (tmp_path / "out" / "Probe" / "Probe_12.cpfont").read_bytes()
    assert struct.unpack_from("<I", blob, 12)[0] == 2


def test_the_slots_are_rasterized_at_their_own_weights(tmp_path):
    """The whole point: the coordinates reach FreeType. Built with the bold slot
    pinned back to the regular's weight, the file is a different one -- if the
    coordinates were ignored, both builds would be the same bytes."""
    at_bold = _variable_project(tmp_path)
    _build(at_bold, tmp_path)
    bold = (tmp_path / "out" / "Probe" / "Probe_12.cpfont").read_bytes()

    pinned = _variable_project(tmp_path, "bold = Probe[wght].ttf@wght=400\n")
    _build(pinned, tmp_path)
    light = (tmp_path / "out" / "Probe" / "Probe_12.cpfont").read_bytes()
    assert bold != light


def test_moving_a_coordinate_restales_the_size(tmp_path):
    """The file's hash cannot say which face a slot is when both slots share
    it, so the coordinates are in the stamp."""
    from crossglyph import fontstamp

    variant = _variable_project(tmp_path)
    _build(variant, tmp_path)
    assert _build(variant, tmp_path).built == []

    moved = _variable_project(tmp_path, "bold = Probe[wght].ttf@wght=900\n")
    assert fontstamp.stale_sizes(moved, tmp_path / "out" / "Probe") == [12]

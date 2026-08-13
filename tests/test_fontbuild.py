import pytest

from crossglyph import fontbuild, fontconf, spacefont
from crossglyph.cpfont.tuning import Tuning


@pytest.fixture
def config(tmp_path):
    for name in ("Alto-Medium.otf", "Alto Bold.otf", "Alto Italic.otf",
                 "Alto Bold Italic.otf", "Fallback-Regular.ttf"):
        (tmp_path / name).write_bytes(b"x")
    # The faces a fetch would have put here. Only their names and their
    # presence matter to build_kwargs, which passes paths on to the converter.
    faces = tmp_path / fontbuild.FALLBACK_NAME
    faces.mkdir()
    for name in (list(fontbuild.BUNDLED_FALLBACKS)
                 + [n for pair in fontbuild.CJK_FALLBACKS.values() for n in pair]
                 + [fontbuild.FALLBACK_LICENCE]):
        (faces / name).write_bytes(b"x")
    return tmp_path / "alto.conf"


def _kwargs(config, out, text="", size_index=0, size=None):
    config.write_text(text, encoding="utf-8")
    parsed = fontconf.parse_config(config)
    variant = parsed.variants()[size_index]
    return fontbuild.build_kwargs(variant, size or variant.sizes[0], out)


def test_every_discovered_style_is_passed(config, tmp_path):
    kw = _kwargs(config, tmp_path / "out")
    assert 0 in kw["style_fonts"] and 1 in kw["style_fonts"]
    assert kw["style_fonts"][2].endswith("Alto Italic.otf")


def test_missing_styles_are_not_passed(config, tmp_path):
    (config.parent / "Alto Bold Italic.otf").unlink()
    kw = _kwargs(config, tmp_path / "out")
    assert 3 not in kw["style_fonts"]


def test_the_output_path_carries_the_variant_name_and_size(config, tmp_path):
    kw = _kwargs(config, tmp_path / "out",
                 "sizes = 12 14 16 18\nsizes_mod = 13 15 17 19\n", size_index=1)
    assert kw["output_path"].endswith("AltoMod_13.cpfont")
    assert kw["size"] == 13


def _covers(kw, codepoint):
    """resolve_intervals() merges overlapping ranges, so ask about coverage
    rather than looking for one preset's range verbatim."""
    return any(start <= codepoint <= end for start, end in kw["intervals"])


def test_intervals_default_to_the_website_selection(config, tmp_path):
    kw = _kwargs(config, tmp_path / "out")
    assert _covers(kw, 0x0416)      # cyrillic, Ж
    assert _covers(kw, 0x0041)      # base, A
    assert _covers(kw, 0x03A9)      # greek, Ω


def test_raw_ranges_are_appended_to_the_intervals(config, tmp_path):
    kw = _kwargs(config, tmp_path / "out",
                 "intervals = reading\nranges = (0x2900-0x29FF)\n")
    assert _covers(kw, 0x2950)


def _fallback_names(kw):
    fallbacks = (kw["fallback_style_fonts"] or {}).get(0, [])
    return [f.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] for f in fallbacks]


def test_bundled_fallbacks_are_passed_in_the_workflow_order(config, tmp_path):
    kw = _kwargs(config, tmp_path / "out")
    assert _fallback_names(kw) == \
        list(fontbuild.BUNDLED_FALLBACKS) + ["NotoSansCJKjp-Regular.otf",
                                             spacefont.FILENAME]


def test_bundled_fallbacks_can_be_turned_off(config, tmp_path):
    kw = _kwargs(config, tmp_path / "out", "fallbacks = no\n")
    assert _fallback_names(kw) == [spacefont.FILENAME], \
        "only the space font survives; it is what keeps U+2006 drawable"


def test_the_space_font_can_be_turned_off_separately(config, tmp_path):
    kw = _kwargs(config, tmp_path / "out", "fallbacks = no\nspace_glyphs = no\n")
    assert _fallback_names(kw) == []


def test_the_space_font_comes_last_so_a_real_face_wins(config, tmp_path):
    """A fallback only fills what earlier faces lack, so this ordering is what
    lets a font that has its own U+2006 keep the designer's width."""
    kw = _kwargs(config, tmp_path / "out")
    assert _fallback_names(kw)[-1] == spacefont.FILENAME


def test_simplified_chinese_swaps_in_the_matching_cjk_fallbacks(config, tmp_path):
    kw = _kwargs(config, tmp_path / "out", "intervals = cjk-sc\n")
    passed = _fallback_names(kw)
    assert passed[-3:-1] == ["NotoSansCJKsc-Regular.otf", "NotoSansCJKjp-Regular.otf"]


def test_user_fallback_families_are_passed(config, tmp_path):
    kw = _kwargs(config, tmp_path / "out",
                 "fallback_regular = Fallback-Regular.ttf\n")
    assert _fallback_names(kw)[0] == "Fallback-Regular.ttf", \
        "a user fallback is offered before the bundled ones"


def test_tuning_defaults_to_upstream_behaviour(config, tmp_path):
    kw = _kwargs(config, tmp_path / "out")
    assert kw["tuning"] == Tuning()


def test_tuning_is_passed_when_set(config, tmp_path):
    kw = _kwargs(config, tmp_path / "out",
                 "thresholds = 3,6,10\nhinting = auto\ngamma = 0.8\n")
    assert kw["tuning"] == Tuning(thresholds=Tuning.DARKEN_AA, hinting="auto",
                                  gamma=0.8)


def test_one_call_builds_one_size(config, tmp_path):
    """Each size is its own job, so the converter is never asked for a list."""
    kw = _kwargs(config, tmp_path / "out", "sizes = 12 14 16\n", size=16)
    assert kw["size"] == 16
    assert kw["output_path"].endswith("Alto_16.cpfont")


def test_a_renamed_family_leaves_an_orphan_directory(tmp_path):
    out = tmp_path / "out"
    for name in ("Alto", "AltoMod", "ByHand"):
        (out / name).mkdir(parents=True)
    for name in ("Alto", "AltoMod"):
        (out / name / "_stamp").write_text("{}", encoding="utf-8")
        (out / name / "_stamp").rename(out / name / ".crossglyph.json")
    orphans = fontbuild.orphan_dirs(out, {"Alto"})
    # AltoMod is ours and unwanted; ByHand has no stamp, so it was not built
    # here and must be left alone.
    assert [p.name for p in orphans] == ["AltoMod"]


def test_style_metrics_reads_the_style_toc(tmp_path):
    """advanceY sits at TOC offset +12, ascender +13, descender +15."""
    import struct
    blob = bytearray(b"CPFONT\x00\x00" + struct.pack("<HHB19s", 4, 1, 1, bytes(19)))
    blob += struct.pack("<B3xIIBhhHHBBBI4x", 0, 7, 123, 31, 23, -6,
                        0, 0, 0, 0, 0, 64)
    path = tmp_path / "probe.cpfont"
    path.write_bytes(bytes(blob))
    assert fontbuild.style_metrics(path) == (123, 31, 23, -6)
    assert fontbuild.glyph_count(path) == 123


def test_style_metrics_of_a_non_cpfont_is_zeroed(tmp_path):
    path = tmp_path / "nope.cpfont"
    path.write_bytes(b"not a font")
    assert fontbuild.style_metrics(path).glyphs == 0


def _probe(tmp_path, noto, extra=""):
    import shutil
    source = tmp_path / "src"
    source.mkdir()
    shutil.copy(noto, source / "Probe-Regular.ttf")
    (source / "probe.conf").write_text(
        "sizes = 12\nintervals = base\nfallbacks = no\nspace_glyphs = no\n" + extra,
        encoding="utf-8")
    return fontconf.parse_config(source / "probe.conf").variants()[0]


def test_a_line_height_tighter_than_the_glyph_band_warns(tmp_path, noto_or_skip):
    variant = _probe(tmp_path, noto_or_skip, "line_height = 6px\n")
    built = fontbuild.build_size(fontbuild.Job(variant, 12), tmp_path / "out")
    assert any("line_height" in w and "overlap" in w for w in built.warnings)


def test_a_normal_build_warns_about_nothing(tmp_path, noto_or_skip):
    variant = _probe(tmp_path, noto_or_skip)
    built = fontbuild.build_size(fontbuild.Job(variant, 12), tmp_path / "out")
    assert built.warnings == ()


def test_a_font_whose_own_band_exceeds_its_pitch_does_not_warn(tmp_path, noto_or_skip):
    """NotoSans has a negative lineGap: its declared ascender and descender
    span 35px against a 34px pitch. That is the font's own business, not a
    complaint about a setting nobody made."""
    variant = _probe(tmp_path, noto_or_skip)
    built = fontbuild.build_size(fontbuild.Job(variant, 12), tmp_path / "out")
    metrics = fontbuild.style_metrics(
        tmp_path / "out" / "Probe" / "Probe_12.cpfont")
    assert metrics.ascender - metrics.descender > metrics.advance_y
    assert built.warnings == ()


# --- where the bundled fallback faces live --------------------------------


def test_the_fallback_faces_are_looked_for_beside_the_fonts(tmp_path):
    """A fetch puts them in the workspace, and that is where they are read."""
    from crossglyph import fontbuild

    assert fontbuild.fallback_dir(tmp_path) is None

    beside = tmp_path / fontbuild.FALLBACK_NAME
    beside.mkdir()
    assert fontbuild.fallback_dir(tmp_path) is None, \
        "an empty folder must not shadow a real set"

    (beside / fontbuild.ANCHOR_FACE).write_bytes(b"")
    assert fontbuild.fallback_dir(tmp_path) == beside


def test_all_conf_can_say_where_they_are(tmp_path):
    from crossglyph import fontbuild

    shared = tmp_path / "shared-noto"
    shared.mkdir()
    (shared / fontbuild.ANCHOR_FACE).write_bytes(b"")
    conf = fontbuild.conf_dir(tmp_path)
    conf.mkdir()
    (conf / "all.conf").write_text("fallback_dir = shared-noto\n",
                                   encoding="utf-8")
    assert fontbuild.fallback_dir(tmp_path) == shared


def test_a_latin_build_is_not_held_up_by_a_missing_cjk_face(tmp_path):
    """One CJK face is appended to every build as a catch-all and is 15.7 MB.
    Failing a Cyrillic family over it would be absurd; failing one that ticked
    Japanese is exactly right."""
    from crossglyph import fontbuild

    faces = tmp_path / "fallbacks"
    faces.mkdir()
    for name in fontbuild.BUNDLED_FALLBACKS:
        (faces / name).write_bytes(b"")

    wanted = fontbuild.wanted_fallbacks("reading,cyrillic", faces)
    assert len(wanted) == len(fontbuild.BUNDLED_FALLBACKS)

    with pytest.raises(FileNotFoundError, match="fetch-fallbacks"):
        fontbuild.wanted_fallbacks("cjk-jp", faces)


def test_a_fetch_lands_the_licence_and_leaves_cjk_alone(tmp_path, monkeypatch):
    """15.7 MB of CJK is not something to hand someone building a Cyrillic
    family, and the OFL requires the licence to travel with the faces."""
    import contextlib
    import io

    from crossglyph import fontbuild

    @contextlib.contextmanager
    def serve(*_args, **_kwargs):
        yield io.BytesIO(b"font")

    monkeypatch.setattr("urllib.request.urlopen", serve)

    source = tmp_path / "fonts"
    source.mkdir()
    landed = fontbuild.fetch_fallbacks(source, say=lambda *_: None)
    names = {path.name for path in landed}
    assert fontbuild.ANCHOR_FACE in names
    assert fontbuild.FALLBACK_LICENCE in names, "the licence travels with them"
    assert not any("CJK" in name for name in names), \
        "15.7 MB nobody asked for"
    assert fontbuild.fallback_dir(source) == source / fontbuild.FALLBACK_NAME

    with_cjk = fontbuild.fetch_fallbacks(source, "cjk-jp", say=lambda *_: None)
    assert any("CJK" in path.name for path in with_cjk)


def test_a_half_fetched_face_is_never_left_behind(tmp_path, monkeypatch):
    """Written aside and moved into place: an interrupted download must not
    leave a truncated font that every later run treats as present."""
    from crossglyph import fontbuild

    def die(*_args, **_kwargs):
        raise OSError("network went away")

    monkeypatch.setattr("urllib.request.urlopen", die)
    source = tmp_path / "fonts"
    source.mkdir()
    with pytest.raises(OSError):
        fontbuild.fetch_fallbacks(source, say=lambda *_: None)
    assert list((source / "fallbacks").iterdir()) == []


# --- where the configs live -----------------------------------------------


def test_configs_are_read_from_the_conf_folder(tmp_path):
    import fontsmith

    fontsmith.box_font(tmp_path / "Probe-Regular.ttf", [ord("A")],
                       family="Probe", style="Regular")
    conf = tmp_path / fontbuild.CONF_NAME
    conf.mkdir()
    (conf / "probe.conf").write_text("sizes = 12\nfallbacks = no\n",
                                     encoding="utf-8")
    configs, errors = fontbuild.gather(tmp_path)
    assert not errors
    assert [c.name for c in configs] == ["Probe"]
    assert configs[0].styles["regular"].parent == tmp_path


def test_a_config_beside_the_fonts_is_not_read(tmp_path):
    import fontsmith

    fontsmith.box_font(tmp_path / "Probe-Regular.ttf", [ord("A")],
                       family="Probe", style="Regular")
    (tmp_path / "probe.conf").write_text("sizes = 12\n", encoding="utf-8")
    configs, errors = fontbuild.gather(tmp_path)
    assert errors == []
    # The font is found, since a folder of fonts is a family list. The config
    # sitting beside it rather than in conf/ is what goes unread: sizes are the
    # shipped default and not the 12 it asks for.
    assert [c.name for c in configs] == ["Probe"]
    assert configs[0].sizes == fontconf.DEFAULT_SIZES


# --- the family that ships with the tool -----------------------------------


def test_an_empty_workspace_offers_the_bundled_family(tmp_path):
    """Unpacking a release and being told "no fonts" is a poor first run."""
    configs, errors = fontbuild.gather(tmp_path)
    assert errors == []
    assert [c.name for c in configs] == ["Literata"]
    assert configs[0].derived is True
    # Two variable files fill four slots, so the family it opens on has a bold
    # and an italic to show rather than one weight repeated.
    assert set(configs[0].styles) == {"regular", "bold", "italic", "bolditalic"}
    assert configs[0].styles["regular"].parent == fontbuild.STARTER_DIR


def test_the_bundled_family_steps_aside_for_a_font_of_your_own(tmp_path):
    import fontsmith

    fontsmith.box_font(tmp_path / "Probe-Regular.ttf", [ord("A")],
                       family="Probe", style="Regular")
    configs, _ = fontbuild.gather(tmp_path)
    assert [c.name for c in configs] == ["Probe"]


def test_the_bundled_family_is_drawn_at_the_size_it_is_built_for(tmp_path):
    """Its optical size axis is the reason this is the face that ships: one
    file per posture, redrawn for each size rather than scaled to it."""
    config = fontbuild.gather(tmp_path)[0][0]
    assert config.coords("regular", 13) == {"opsz": 13, "wght": 400}
    assert config.coords("bold", 18) == {"opsz": 18, "wght": 700}


def test_the_bundled_licence_travels_with_the_faces():
    """The OFL requires it, and a wheel carries whatever is in the package."""
    assert sorted(p.name for p in fontbuild.STARTER_DIR.iterdir()) == [
        "Literata-Italic[opsz,wght].ttf", "Literata[opsz,wght].ttf", "OFL.txt"]


def test_text_that_needs_a_cjk_face_brings_one_without_a_coverage_box():
    """Choosing a Japanese sample is asking for the face that can draw it. The
    coverage boxes are a build setting, and making somebody find the right one
    before Fetch will work is a step with nothing behind it."""
    from crossglyph import fontbuild

    plain = fontbuild.fetch_plan("reading,cyrillic", "Привет, мир")
    assert not any("CJK" in name for name in plain), "15.7 MB nobody asked for"

    for text in ("すべての人間は", "모든 인간은", "人人生而自由"):
        wanted = fontbuild.fetch_plan("reading,cyrillic", text)
        assert any("CJK" in name for name in wanted), f"{text} draws as nothing"
    # One face answers all four languages, so there is never a choice to make
    # between them when the coverage has not named a script.
    assert fontbuild.fetch_plan("reading", "すべて") == \
        fontbuild.fetch_plan("reading", "人人生而自由")


def test_a_coverage_that_names_a_script_still_picks_that_face():
    """The text decides only when nothing else has. A build for Traditional
    Chinese wants that face whatever the page happens to be showing."""
    from crossglyph import fontbuild

    plan = fontbuild.fetch_plan("reading,cjk-tc", "The quick brown fox")
    assert "NotoSansCJKtc-Regular.otf" in plan


def test_latin_text_never_drags_a_cjk_face_in():
    from crossglyph import fontbuild

    assert not fontbuild.needs_cjk("The quick brown fox, 1918. Привет!")
    assert fontbuild.needs_cjk("a いろは b")


def test_a_fetch_says_how_far_it_has_got(tmp_path, monkeypatch):
    """A 20 MB download behind a button with no feedback is one people press
    twice. Bytes rather than files: one face is four fifths of the set."""
    import contextlib
    import io

    from crossglyph import fontbuild

    @contextlib.contextmanager
    def serve(request, *_args, **_kwargs):
        yield io.BytesIO(b"x" * 400)

    monkeypatch.setattr("urllib.request.urlopen", serve)
    source = tmp_path / "fonts"
    source.mkdir()

    steps = list(fontbuild.fetch_steps(source, "", ""))
    assert steps[0]["event"] == "plan"
    assert steps[0]["files"] == len(fontbuild.BUNDLED_FALLBACKS) + 1
    assert steps[-1]["event"] == "done"
    assert steps[-1]["faces"] == steps[0]["files"]

    # Every byte counted once, and never more than the plan said there were.
    moving = [s for s in steps if s["event"] == "step"]
    assert moving, "a download that reported no progress at all"
    assert [s["got"] for s in moving] == sorted(s["got"] for s in moving)
    assert all(s["got"] <= max(s["bytes"], s["got"]) for s in moving)
    # And each file is announced before its bytes arrive, so the line under the
    # bar names what is in hand rather than what has just finished.
    assert [s["name"] for s in steps if s["event"] == "start"] == \
        fontbuild.fetch_plan("", "")

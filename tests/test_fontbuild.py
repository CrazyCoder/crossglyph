import pathlib

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


def _parsed(config, text=""):
    config.write_text(text, encoding="utf-8")
    return fontconf.parse_config(config)


def _kwargs(config, out, text="", size_index=0, size=None):
    parsed = _parsed(config, text)
    variant = parsed.variants()[size_index]
    return fontbuild.build_kwargs(variant, size or variant.sizes[0], out)


def _entry_names(entries):
    return [entry["regular"].name for entry in entries]


def _bundled_families():
    """One face per bundled family: what the chain holds, in its order.

    BUNDLED_FALLBACKS is the fetch list and carries NotoSans four times over.
    A chain takes each family once and resolves the styles behind it.
    """
    return [name for name in fontbuild.BUNDLED_FALLBACKS
            if name not in fontbuild.NOTOSANS_STYLES]


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
    kw = _kwargs(config, tmp_path / "out", "fallbacks = yes\n")
    assert _fallback_names(kw) == \
        _bundled_families() + ["NotoSansCJKjp-Regular.otf",
                               spacefont.cache_name()]


def test_bundled_fallbacks_are_disabled_by_default(config, tmp_path):
    kw = _kwargs(config, tmp_path / "out")
    assert _fallback_names(kw) == [spacefont.cache_name()], \
        "only the space font survives; it is what keeps U+2006 drawable"


def test_the_space_font_can_be_turned_off_separately(config, tmp_path):
    kw = _kwargs(config, tmp_path / "out", "fallbacks = no\nspace_glyphs = no\n")
    assert _fallback_names(kw) == []


def test_the_space_font_comes_last_so_a_real_face_wins(config, tmp_path):
    """A fallback only fills what earlier faces lack, so this ordering is what
    lets a font that has its own U+2006 keep the designer's width."""
    kw = _kwargs(config, tmp_path / "out", "fallbacks = yes\n")
    assert _fallback_names(kw)[-1] == spacefont.cache_name()


def test_simplified_chinese_swaps_in_the_matching_cjk_fallbacks(config, tmp_path):
    kw = _kwargs(
        config, tmp_path / "out", "fallbacks = yes\nintervals = cjk-sc\n")
    passed = _fallback_names(kw)
    assert passed[-3:-1] == ["NotoSansCJKsc-Regular.otf", "NotoSansCJKjp-Regular.otf"]


def test_user_fallback_families_are_passed(config, tmp_path):
    kw = _kwargs(
        config, tmp_path / "out",
        "fallbacks = yes\nfallback_regular = Fallback-Regular.ttf\n")
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


def test_the_worker_count_leaves_a_core_for_whoever_asked(monkeypatch):
    """A build that takes every core makes the machine it runs on unusable
    for as long as it lasts, and the preview is one of the things on it."""
    for cores, want in ((1, 1), (2, 1), (8, 7), (32, 12)):
        monkeypatch.setattr(fontbuild.os, "cpu_count", lambda n=cores: n)
        assert fontbuild.default_jobs() == want, cores


def _plans(tmp_path, sizes="12 14", mod=""):
    """Two families' worth of jobs, without building anything."""
    text = f"sizes = {sizes}\n" + (f"sizes_mod = {mod}\n" if mod else "")
    (tmp_path / "alto.conf").write_text(text, encoding="utf-8")
    parsed = fontconf.parse_config(tmp_path / "alto.conf")
    return [job for variant in parsed.variants()
            for job in fontbuild.plan_variant(variant, tmp_path / "out")[1]]


def test_a_build_reports_sizes_in_whatever_order_they_land(config, tmp_path):
    """The pool answers as each size finishes, not in the order they were
    submitted, so the run has to be reported from what comes back."""
    jobs = _plans(tmp_path, sizes="12 14", mod="9 10")
    assert len(jobs) == 4

    def scrambled(js, out_dir, workers=None):
        for job in reversed(js):
            yield fontbuild.Landed(job, 1.0, None, fontbuild.Built(100, 5))

    import unittest.mock
    with unittest.mock.patch.object(fontbuild, "run_jobs", scrambled):
        steps = list(fontbuild.build_families(
            [fontconf.parse_config(tmp_path / "alto.conf")], tmp_path / "out"))

    sizes = [s for s in steps if s["event"] == "size"]
    assert [s["done"] for s in sizes] == [1, 2, 3, 4], "the bar has to count up"
    assert {(s["family"], s["size"]) for s in sizes} == \
        {("Alto", 12), ("Alto", 14), ("AltoMod", 9), ("AltoMod", 10)}
    done = steps[-1]
    assert done["bytes"] == 400
    assert sorted(f["built"] for f in done["families"]) == [[9, 10], [12, 14]]


def test_a_family_that_fails_is_counted_once_however_many_sizes_land(config, tmp_path):
    """Its other sizes are written off the moment one fails, so a result that
    arrives for them afterwards must not be counted twice -- the bar would
    run past its own total."""
    jobs = _plans(tmp_path, sizes="12 14 16")

    def one_bad(js, out_dir, workers=None):
        yield fontbuild.Landed(js[0], 1.0, "no regular face", fontbuild.Built(0, 0))
        for job in js[1:]:
            yield fontbuild.Landed(job, 1.0, None, fontbuild.Built(100, 5))

    import unittest.mock
    with unittest.mock.patch.object(fontbuild, "run_jobs", one_bad):
        steps = list(fontbuild.build_families(
            [fontconf.parse_config(tmp_path / "alto.conf")], tmp_path / "out"))

    assert [s["event"] for s in steps] == ["plan", "failed", "done"]
    assert steps[1]["done"] == steps[0]["total"] == len(jobs)
    family = steps[-1]["families"][0]
    assert family["failed"] == [12, 14, 16] and family["built"] == []


def test_a_second_family_declared_in_all_conf_is_still_claimed(tmp_path):
    """`sizes_mod` is shareable, so a family can build two directories while
    its own config says nothing about the second. Read the file alone and the
    next build takes that one for an orphan."""
    import fontsmith

    from crossglyph import fontbuild

    fontsmith.box_font(tmp_path / "Probe-Regular.ttf", [ord("A")],
                       family="Probe", style="Regular")
    conf = fontbuild.conf_dir(tmp_path)
    conf.mkdir(parents=True, exist_ok=True)
    (conf / "all.conf").write_text("sizes_mod = 9 10\n", encoding="utf-8")
    (conf / "probe.conf").write_text("sizes = 12\n", encoding="utf-8")

    # Spelled as the config spells it, which is why orphan_dirs compares
    # without case: the directory took its capitals from the font file.
    assert {name.casefold() for name in fontbuild.claimed_names(tmp_path)} == \
        {"probe", "probemod"}


def test_a_second_space_font_never_writes_over_the_first(tmp_path):
    """Several workers reach it together, and each finds the file missing.
    Whoever loses writes its own copy and drops it rather than replacing one
    the converter may already have open."""
    # Widths of this test's own, so the file it writes to is nobody else's:
    # the face is kept per machine now, and the suite runs several at once.
    mine = {0x2009: 0.311}
    first = fontbuild.ensure_space_font(mine)
    marked = first.read_bytes()
    first.write_bytes(marked + b"\0")           # tell this copy from another
    try:
        again = fontbuild.ensure_space_font(mine)
        assert again == first
        assert first.read_bytes() == marked + b"\0", "it was written over"
        leftovers = [path.name for path in first.parent.iterdir()
                     if path.name.startswith(first.name)]
        assert leftovers == [first.name], "a temporary copy was left behind"
    finally:
        first.unlink(missing_ok=True)


def test_the_space_face_is_not_left_where_a_build_is_copied_from(tmp_path):
    """The output folder is the one folder here whose whole purpose is to be
    copied onto a card, and this is an input to a build rather than a font to
    read with: fourteen invisible glyphs, and a reader who copies it gains
    nothing at all."""
    assert fontbuild.space_font_path().parent != tmp_path
    assert "cpfont" not in str(fontbuild.space_font_path().parent).lower()


def test_a_different_space_table_is_a_different_file(tmp_path):
    """Kept between builds and keyed on nothing, the first table written won
    for good: a width edited in all.conf rebuilt every .cpfont from the spaces
    as they were, with no way back short of deleting a hidden file."""
    plain = fontbuild.space_font_path()
    edited = fontbuild.space_font_path({0x2009: 0.9})
    assert plain != edited


def test_the_stray_space_face_is_swept_from_an_output_folder(tmp_path):
    """Builds up to now left one in there, so the folders people already have
    keep it until something takes it out."""
    from crossglyph import spacefont

    out = tmp_path / "out"
    out.mkdir()
    (out / spacefont.STRAY_NAME).write_bytes(b"")
    list(fontbuild.build_families([], out, keep=None))
    assert not (out / spacefont.STRAY_NAME).exists()


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


def test_a_pinned_face_picks_up_its_siblings(tmp_path):
    """A config names one file. The other styles of that family are beside it,
    and a bold run should get the bold."""
    for name in ("NotoSerif-Regular.ttf", "NotoSerif-Bold.ttf",
                 "NotoSerif-Italic.ttf"):
        (tmp_path / name).write_bytes(b"")

    faces = fontbuild.pinned_faces(tmp_path / "NotoSerif-Regular.ttf")

    assert faces["regular"].name == "NotoSerif-Regular.ttf"
    assert faces["bold"].name == "NotoSerif-Bold.ttf"
    assert faces["italic"].name == "NotoSerif-Italic.ttf"
    assert "bolditalic" not in faces


def test_a_pinned_face_is_the_regular_whatever_its_suffix(tmp_path):
    """Pinning a bold file means that file is what the family offers, so it
    cannot be filed under a slot the chain would then skip."""
    (tmp_path / "NotoSerif-Bold.ttf").write_bytes(b"")

    faces = fontbuild.pinned_faces(tmp_path / "NotoSerif-Bold.ttf")

    assert faces["regular"].name == "NotoSerif-Bold.ttf"


def test_a_named_family_is_found_in_the_fallbacks_folder(tmp_path):
    folder = tmp_path / fontbuild.FALLBACK_NAME
    folder.mkdir()
    for name in ("NotoSans-Regular.ttf", "NotoSans-Bold.ttf"):
        (folder / name).write_bytes(b"")

    faces = fontbuild.named_faces("NotoSans", folder, tmp_path)

    assert faces["regular"].name == "NotoSans-Regular.ttf"
    assert faces["bold"].name == "NotoSans-Bold.ttf"


def test_a_named_family_falls_through_to_the_workspace(tmp_path):
    """A name the bundled set does not have is looked for among your own
    families, so a fallback can be any family in the workspace."""
    folder = tmp_path / fontbuild.FALLBACK_NAME
    folder.mkdir()
    (folder / fontbuild.ANCHOR_FACE).write_bytes(b"")
    (tmp_path / "MyIcons-Regular.ttf").write_bytes(b"")

    faces = fontbuild.named_faces("MyIcons", folder, tmp_path)

    assert faces["regular"].name == "MyIcons-Regular.ttf"


def test_the_fallbacks_folder_wins_a_name_both_places_have(tmp_path):
    """A bundled name means the same thing in every workspace. A family of
    yours called NotoSans must not rewrite everyone else's chain."""
    folder = tmp_path / fontbuild.FALLBACK_NAME
    folder.mkdir()
    (folder / "NotoSans-Regular.ttf").write_bytes(b"")
    (tmp_path / "NotoSans-Regular.ttf").write_bytes(b"")

    faces = fontbuild.named_faces("NotoSans", folder, tmp_path)

    assert faces["regular"].parent == folder


def test_a_name_nothing_has_resolves_to_nothing(tmp_path):
    folder = tmp_path / fontbuild.FALLBACK_NAME
    folder.mkdir()
    (folder / fontbuild.ANCHOR_FACE).write_bytes(b"")

    assert fontbuild.named_faces("Nowhere", folder, tmp_path) == {}


def test_every_style_gets_a_chain_of_its_own(config, tmp_path):
    kw = _kwargs(config, tmp_path / "out", "fallbacks = yes\n")

    assert sorted(kw["fallback_style_fonts"]) == [0, 1, 2, 3]


def test_a_style_borrows_from_the_matching_face_when_there_is_one(config, tmp_path):
    """The point of the whole change: a bold run gets the bold."""
    (tmp_path / fontbuild.FALLBACK_NAME / "NotoSans-Bold.ttf").write_bytes(b"x")

    kw = _kwargs(config, tmp_path / "out", "fallbacks = yes\n")
    bold = [pathlib.Path(p).name for p in kw["fallback_style_fonts"][1]]

    assert "NotoSans-Bold.ttf" in bold
    assert "NotoSans-Regular.ttf" not in bold


def test_a_style_with_no_face_of_its_own_borrows_the_regular(config, tmp_path):
    """Noto publishes no italic for twelve of the thirteen, so this is the
    common case and not the corner."""
    kw = _kwargs(config, tmp_path / "out", "fallbacks = yes\n")
    italic = [pathlib.Path(p).name for p in kw["fallback_style_fonts"][2]]

    assert "NotoSansMath-Regular.ttf" in italic


def test_the_panel_picks_stay_in_front_of_the_written_order(config, tmp_path):
    """The rule the feature rests on: the panel's two picks are always in
    front, and the config orders everything behind them."""
    (tmp_path / "MyIcons-Regular.ttf").write_bytes(b"x")
    kw = _kwargs(config, tmp_path / "out",
                 "fallbacks = yes\n"
                 "fallback_regular = Fallback-Regular.ttf\n"
                 "fallback_order = MyIcons\n")
    names = [pathlib.Path(p).name for p in kw["fallback_style_fonts"][0]]

    assert names[:2] == ["Fallback-Regular.ttf", "MyIcons-Regular.ttf"]


def test_a_face_reached_twice_is_taken_once(config, tmp_path):
    (tmp_path / "MyIcons-Regular.ttf").write_bytes(b"x")
    kw = _kwargs(config, tmp_path / "out",
                 "fallbacks = yes\n"
                 "fallback_order = MyIcons, MyIcons, bundled\n")
    names = [pathlib.Path(p).name for p in kw["fallback_style_fonts"][0]]

    assert names.count("MyIcons-Regular.ttf") == 1


def test_the_space_font_is_last_in_every_style(config, tmp_path):
    kw = _kwargs(config, tmp_path / "out", "fallbacks = yes\n")

    for faces in kw["fallback_style_fonts"].values():
        assert pathlib.Path(faces[-1]).name == spacefont.cache_name()


def test_the_built_in_order_stands_when_the_key_is_unset(config, tmp_path):
    parsed = _parsed(config, "fallbacks = yes\n")

    entries = fontbuild.ordered_entries(
        parsed, tmp_path / fontbuild.FALLBACK_NAME)

    assert _entry_names(entries) == _bundled_families() + \
        ["NotoSansCJKjp-Regular.otf"]


def test_a_named_family_comes_first_and_the_token_brings_the_rest(config, tmp_path):
    (tmp_path / "MyIcons-Regular.ttf").write_bytes(b"x")
    parsed = _parsed(config, "fallbacks = yes\n"
                             "fallback_order = MyIcons, bundled\n")

    names = _entry_names(fontbuild.ordered_entries(
        parsed, tmp_path / fontbuild.FALLBACK_NAME))

    assert names[0] == "MyIcons-Regular.ttf"
    assert names[1] == _bundled_families()[0]


def test_the_token_can_come_first(config, tmp_path):
    (tmp_path / "MyIcons-Regular.ttf").write_bytes(b"x")
    parsed = _parsed(config, "fallbacks = yes\n"
                             "fallback_order = bundled, MyIcons\n")

    names = _entry_names(fontbuild.ordered_entries(
        parsed, tmp_path / fontbuild.FALLBACK_NAME))

    assert names[0] == _bundled_families()[0]
    assert names[-1] == "MyIcons-Regular.ttf"


def test_an_order_without_the_token_is_the_whole_chain(config, tmp_path):
    """Dropping a bundled face you do not want, and reordering within the set,
    both need the written list to be the whole answer."""
    (tmp_path / "MyIcons-Regular.ttf").write_bytes(b"x")
    parsed = _parsed(config, "fallbacks = yes\nfallback_order = MyIcons\n")

    entries = fontbuild.ordered_entries(
        parsed, tmp_path / fontbuild.FALLBACK_NAME)

    assert _entry_names(entries) == ["MyIcons-Regular.ttf"]


def test_an_unresolvable_name_says_where_it_looked(config, tmp_path):
    parsed = _parsed(config, "fallbacks = yes\nfallback_order = Nowhere\n")

    with pytest.raises(fontconf.FontConfigError, match="Nowhere"):
        fontbuild.ordered_entries(parsed, tmp_path / fontbuild.FALLBACK_NAME)


def test_the_bundled_set_carries_the_notosans_styles():
    """NotoSans heads the chain and is the one bundled family Noto publishes an
    italic for, so it is the family worth fetching per style."""
    for name in fontbuild.NOTOSANS_STYLES:
        assert name in fontbuild.BUNDLED_FALLBACKS


def test_the_notosans_styles_come_from_the_noto_project():
    """Upstream's folder is Regular only, so these come from the project that
    publishes them, as the Arabic face does."""
    source = fontbuild.fallback_source("NotoSans-Italic.ttf")

    assert source.startswith("https://raw.githubusercontent.com/notofonts/")
    assert source.endswith("/NotoSans-Italic.ttf")


def test_a_folder_fetched_before_the_styles_still_builds(tmp_path):
    """An existing workspace has the thirteen Regulars and none of the three.
    A required new face would stop it building until it refetched."""
    faces = tmp_path / fontbuild.FALLBACK_NAME
    faces.mkdir()
    for name in fontbuild.BUNDLED_FALLBACKS:
        if name in fontbuild.NOTOSANS_STYLES:
            continue
        (faces / name).write_bytes(b"")

    wanted = [path.name for path in
              fontbuild.wanted_fallbacks("reading,cyrillic", faces)]

    assert "NotoSans-Regular.ttf" in wanted
    assert not set(wanted) & set(fontbuild.NOTOSANS_STYLES)


def test_nothing_fetched_means_the_whole_plan_is_missing(tmp_path):
    assert fontbuild.missing_fallbacks(tmp_path) == fontbuild.fetch_plan()


def test_a_folder_missing_the_new_faces_names_them(tmp_path):
    """The set grows between versions, so a folder is not either fetched or
    not. This is what puts the button back in front of somebody who fetched
    before the styles were added."""
    faces = tmp_path / fontbuild.FALLBACK_NAME
    faces.mkdir()
    for name in fontbuild.fetch_plan():
        if name in fontbuild.NOTOSANS_STYLES:
            continue
        (faces / name).write_bytes(b"")

    assert fontbuild.missing_fallbacks(tmp_path) == \
        list(fontbuild.NOTOSANS_STYLES)


def test_a_complete_folder_is_missing_nothing(tmp_path):
    faces = tmp_path / fontbuild.FALLBACK_NAME
    faces.mkdir()
    for name in fontbuild.fetch_plan():
        (faces / name).write_bytes(b"")

    assert fontbuild.missing_fallbacks(tmp_path) == []


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


def test_the_bundled_family_is_offered_beside_a_workspace_of_your_own(tmp_path):
    """Somewhere to flip to mid-tuning, at the size and knobs you are working
    at, is worth an entry whatever else is in the folder."""
    import fontsmith

    from crossglyph import fontbuild

    fontsmith.box_font(tmp_path / "Probe-Regular.ttf", [ord("A")],
                       family="Probe", style="Regular")
    names = [config.name for config in fontbuild.offered(tmp_path)[0]]
    assert names == ["Probe", "Literata"], "the bundled one comes last"


def test_a_build_with_no_arguments_builds_your_workspace_and_nothing_else(tmp_path):
    """The picker and the build differ by exactly this entry. Build all must
    not rasterize four sizes of a family nobody put in the folder."""
    import fontsmith

    from crossglyph import fontbuild

    fontsmith.box_font(tmp_path / "Probe-Regular.ttf", [ord("A")],
                       family="Probe", style="Regular")
    assert [c.name for c in fontbuild.gather(tmp_path)[0]] == ["Probe"]


def test_the_bundled_family_answers_to_its_name_whatever_else_is_there(tmp_path):
    """The picker offers it permanently, so a render has to resolve it
    permanently -- an entry that 422s when chosen is worse than no entry."""
    import fontsmith

    from crossglyph import fontbuild

    fontsmith.box_font(tmp_path / "Probe-Regular.ttf", [ord("A")],
                       family="Probe", style="Regular")
    configs, errors = fontbuild.gather(tmp_path, ["Literata"])
    assert errors == []
    assert [c.name for c in configs] == ["Literata"]
    assert configs[0].styles["regular"].parent == fontbuild.STARTER_DIR


def test_saving_the_bundled_family_makes_it_one_of_yours(tmp_path):
    """Its config is what turns a thing to look at into a thing you build. It
    is discovered as a per-font config after that, not as the bundled one."""
    import fontsmith

    from crossglyph import fontbuild, fontconf

    fontsmith.box_font(tmp_path / "Probe-Regular.ttf", [ord("A")],
                       family="Probe", style="Regular")
    conf = fontbuild.conf_dir(tmp_path)
    conf.mkdir(parents=True, exist_ok=True)
    fontconf.write_values(conf / "literata.conf",
                          {"family": "Literata", "dir": str(fontbuild.STARTER_DIR)})

    built = [config.name for config in fontbuild.gather(tmp_path)[0]]
    assert built == ["Literata", "Probe"], "a saved config joins the workspace"
    # And it is not offered twice for having a config of its own now.
    assert [c.name for c in fontbuild.offered(tmp_path)[0]] == built


def test_renaming_the_bundled_family_does_not_offer_it_again(tmp_path):
    """A config renames what it builds as, never the family it was written
    for. Asking after the name alone offered the same faces a second time,
    under the family the rename had just moved off -- and the second entry
    then held the old name against getting it back."""
    import fontsmith

    from crossglyph import fontbuild, fontconf

    fontsmith.box_font(tmp_path / "Probe-Regular.ttf", [ord("A")],
                       family="Probe", style="Regular")
    conf = fontbuild.conf_dir(tmp_path)
    conf.mkdir(parents=True, exist_ok=True)
    fontconf.write_values(conf / "literata.conf",
                          {"family": "Literata", "dir": str(fontbuild.STARTER_DIR),
                           "name": "Literata2"})

    assert [c.name for c in fontbuild.offered(tmp_path)[0]] \
        == ["Literata2", "Probe"]


def test_the_bundled_set_carries_an_arabic_face():
    assert "NotoSansArabic-Regular.ttf" in fontbuild.BUNDLED_FALLBACKS


def test_the_arabic_face_is_fetched_from_where_it_actually_lives():
    """Upstream's fallback folder has no Arabic face and 404s for one."""
    url = fontbuild.fallback_source("NotoSansArabic-Regular.ttf")
    assert url.startswith("https://")
    assert "notofonts" in url
    assert url.endswith("NotoSansArabic-Regular.ttf")


def test_every_other_face_still_comes_from_upstream():
    assert fontbuild.fallback_source("NotoSansHebrew-Regular.ttf") == \
        fontbuild.FALLBACK_URL + "NotoSansHebrew-Regular.ttf"


def test_a_missing_arabic_face_does_not_fail_a_latin_build(tmp_path):
    """The treatment CJK already gets: not fetched yet is not an error."""
    for name in fontbuild.BUNDLED_FALLBACKS:
        if name not in fontbuild.OPTIONAL_FALLBACKS:
            (tmp_path / name).write_bytes(b"")
    wanted = fontbuild.wanted_fallbacks("reading", tmp_path)
    assert all(path.name != "NotoSansArabic-Regular.ttf" for path in wanted)

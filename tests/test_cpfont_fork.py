import pathlib

from crossglyph import cpfont

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_upstream_pin_is_recorded():
    text = (ROOT / "src/crossglyph/cpfont/UPSTREAM").read_text(encoding="utf-8")
    assert "crosspoint-tools" in text
    assert len([w for w in text.split() if len(w) == 40 and w.isalnum()]) == 1


def test_the_public_api_is_importable():
    assert cpfont.CPFONT_VERSION > 0
    assert "base" in cpfont.INTERVAL_PRESETS
    assert callable(cpfont.generate_cpfont_multistyle)


def test_base_coverage_is_always_injected():
    assert (0x0000, 0x007F) in cpfont.resolve_intervals("cyrillic")


#: What our own comments point at in convert.py, by name.
#:
#: Names rather than line numbers, because the numbers rot and say nothing
#: while they do it: the converter is a pinned fork refreshed wholesale, so
#: every number in it moves under a refresh, and any edit above one moves it
#: too. A citation that has drifted onto an unrelated line is worse than none,
#: since it still reads as proof -- one here pointed at a `continue` in the
#: GPOS reader for a paragraph about FontBuildError. A name that is gone fails
#: this test instead.
CITATIONS = ["generate_cpfont_multistyle", "rasterize_font_style",
             "HEADER_SIZE", "STYLE_TOC_FORMAT"]


#: The two files UPSTREAM names, and the only ones a refresh overwrites. The
#: rest of the cpfont package is ours, so it is held to our rules like
#: everything else.
FORKED = {"convert.py", "version.py"}


def _our_sources():
    """Our own files, which is everywhere but the two forked ones."""
    for path in sorted((ROOT / "src/crossglyph").rglob("*.py")):
        if path.parts[-2] != "cpfont" or path.name not in FORKED:
            yield path
    yield from sorted((ROOT / "tests").glob("*.py"))


def test_what_we_cite_in_the_converter_is_still_called_that():
    source = (ROOT / "src/crossglyph/cpfont/convert.py").read_text(
        encoding="utf-8")
    for name in CITATIONS:
        assert name in source, f"convert.py no longer has {name}"


def test_no_comment_of_ours_cites_a_line_of_the_converter():
    import re

    for path in _our_sources():
        found = re.findall(r"convert\.py:[0-9]+(?:[-,][0-9]+)*",
                           path.read_text(encoding="utf-8"))
        assert not found, f"{path.name} cites {found}; name the function"


# --- lazy font opening ------------------------------------------------------


def _kerned_face(tmp_path):
    """A face with a GPOS kern feature, built here rather than looked for.

    Reading someone's font folder for "a face that happens to have kerning"
    made this test depend on what was in it that week, and on opening every
    file in it to find out.
    """
    from fontsmith import box_font

    codepoints = list(range(0x20, 0x7F))
    path = box_font(tmp_path / "kerned.ttf", codepoints,
                    kern={(0x41, 0x56): -80, (0x54, 0x6F): -40})
    return path, codepoints


def test_every_font_the_converter_opens_is_opened_lazily():
    """The equivalence below holds either way round, so it cannot notice the
    flag going missing -- and losing it is six times the work per face on a
    font with a real GPOS. Every open in this file reads a table or two and
    closes again; none of them mutate a font."""
    source = (ROOT / "src/crossglyph/cpfont/convert.py").read_text(encoding="utf-8")
    opens = source.count("TTFont(font_path")
    assert opens >= 4, opens
    assert source.count("TTFont(font_path, lazy=True)") == opens


def test_a_lazily_opened_font_yields_the_same_kerning(monkeypatch, tmp_path):
    """The converter opens fonts with lazy=True: fontTools otherwise decompiles
    a whole GPOS -- 136,000 objects and 180 ms a face for Calibri -- to reach
    the one kern lookup it walks. The saving is only worth having if the pairs
    that come out are the same ones, so this extracts both ways and compares.
    """
    import fontTools.ttLib as ttLib

    from crossglyph.cpfont import convert

    path, codepoints = _kerned_face(tmp_path)
    # Both lazy answers first, since the patch below takes that path away.
    lazy_pairs = convert.extract_kerning_fonttools(str(path), codepoints, 27)
    assert lazy_pairs, "the probe face carries no kerning to compare"
    lazy_ligatures = convert.extract_ligatures_fonttools(str(path), codepoints)

    class Eager(ttLib.TTFont):
        def __init__(self, *args, **kwargs):
            kwargs["lazy"] = False
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(ttLib, "TTFont", Eager)
    assert convert.extract_kerning_fonttools(
        str(path), codepoints, 27) == lazy_pairs
    assert convert.extract_ligatures_fonttools(str(path), codepoints) == \
        lazy_ligatures


# --- reasons the converter exits with ---------------------------------------


def test_a_size_the_format_cannot_hold_raises_with_its_reason(tmp_path):
    """FORK: advanceY is a byte in the .cpfont TOC, and a large size on a
    loose-hhea face runs past it. Upstream prints the reason and then exits
    with a bare code, which is fine for a command line and useless to a
    caller.

    Raised and not exited. sys.exit is a BaseException, so it went past
    `except Exception` in build_size and `except FontBuildError` in _run: one
    size over the limit ended the whole run, took every other family with it,
    and cut the preview's build stream off mid-stream. The next test is the
    one that pins that.

    150 DPI, so the pixels a line run well past a byte long before the point
    size looks unusual.
    """
    import pytest

    from crossglyph import cpfont

    path, codepoints = _kerned_face(tmp_path)
    with pytest.raises(cpfont.FontBuildError) as raised:
        cpfont.generate_cpfont_multistyle(
            {0: str(path)}, 200, [(0x41, 0x42)],
            str(tmp_path / "out.cpfont"))
    said = str(raised.value)
    assert "255" in said and "smaller" in said, said


def test_one_size_over_a_limit_does_not_take_the_run_with_it(tmp_path):
    """The failure mode the raise above exists for. A family the converter
    refuses has to come back as that family failing, with every other family
    in the run still built."""
    import fontsmith

    from crossglyph import fontbuild, fontconf

    for name in ("Big", "Small"):
        fontsmith.box_font(tmp_path / f"{name}-Regular.ttf", [0x20, 0x41],
                           family=name)
    (tmp_path / "big.conf").write_text(
        "family = Big\nsizes = 200\nintervals = base\nfallbacks = no\n",
        encoding="utf-8")
    (tmp_path / "small.conf").write_text(
        "family = Small\nsizes = 12\nintervals = base\nfallbacks = no\n",
        encoding="utf-8")
    configs = [fontconf.parse_config(tmp_path / name, root=tmp_path)
               for name in ("big.conf", "small.conf")]
    steps = list(fontbuild.build_families(configs, tmp_path / "out"))
    failed = [step for step in steps if step["event"] == "failed"]
    built = [step for step in steps if step["event"] == "size"]
    assert [step["family"] for step in failed] == ["Big"]
    assert "255" in failed[0]["error"]
    assert [step["family"] for step in built] == ["Small"], \
        "the other family still builds"


def test_the_interval_cap_is_the_one_the_reader_enforces():
    """The three limits are the firmware's policy and not the format's, so
    nothing but this test notices when the firmware moves one."""
    import re

    import pytest

    from crossglyph.cpfont import convert
    from crossglyph.render import stamp

    source = stamp.FIRMWARE / "lib" / "EpdFont" / "SdCardFont.cpp"
    if not source.is_file():
        pytest.skip(f"{source} not found (no firmware checkout beside this one)")
    said = source.read_text(encoding="utf-8", errors="replace")
    for name, ours in (("MAX_INTERVALS", convert.MAX_INTERVALS),
                       ("MAX_GLYPHS", convert.MAX_GLYPHS),
                       ("MAX_KERN_ENTRIES", convert.MAX_KERN_ENTRIES)):
        found = re.search(rf"{name}\s*=\s*(\d+)", said)
        assert found, f"{name} is not in SdCardFont.cpp any more"
        assert int(found.group(1)) == ours, \
            f"{name} is {found.group(1)} on the device and {ours} here"


def test_a_coverage_the_reader_would_refuse_stops_before_rasterizing(tmp_path,
                                                                     monkeypatch):
    """FORK: over the cap the device rejects the whole file, and shows nothing
    for it -- the family lists, drops on load, and the reader draws its own
    font at its own sizes. A build that wrote one anyway is a build that
    reported success for a font nobody can use."""
    import fontsmith
    import pytest

    from crossglyph import cpfont
    from crossglyph.cpfont import convert

    # Every other codepoint, which is one interval each.
    path = fontsmith.box_font(tmp_path / "Gappy-Regular.ttf",
                              [0x20] + list(range(0x2000, 0x2040, 2)))
    monkeypatch.setattr(convert, "MAX_INTERVALS", 8)
    out = tmp_path / "out.cpfont"
    with pytest.raises(cpfont.FontBuildError) as raised:
        cpfont.generate_cpfont_multistyle({0: str(path)}, 12,
                                          [(0x2000, 0x203F)], str(out))
    said = str(raised.value)
    assert "32 separate pieces" in said and "at most 8" in said, said
    assert "U+2000" in said, "and where they are"
    assert not out.exists(), "and nothing was written"


def test_the_count_before_a_build_is_the_count_the_converter_writes(tmp_path):
    """The panel and the command line both say what a build would carry, from
    the charmaps alone. If that ever stops agreeing with what the converter
    actually writes, the warning is worse than none: it would clear a font the
    device then refuses."""
    import fontsmith

    from crossglyph import fontbuild
    from crossglyph.cpfont import convert
    from crossglyph.cpfont.faces import open_face

    gappy = fontsmith.box_font(tmp_path / "Gappy-Regular.ttf",
                               [0x20] + list(range(0x2000, 0x2100, 2)))
    filler = fontsmith.box_font(tmp_path / "Filler-Regular.ttf",
                                [0x20] + list(range(0x2001, 0x2040, 4)),
                                family="Filler")
    asked = [(0x2000, 0x20FF)]
    runs, _sources, _per = convert.resolve_style_coverage(
        open_face(str(gappy)), [open_face(str(filler))], asked)
    mine = fontbuild.interval_runs(
        asked, fontbuild.drawable_codepoints([str(gappy), str(filler)]))
    assert mine == runs, "the same runs, and not merely the same count"


def test_a_style_with_its_own_chain_does_not_inherit_style_zero():
    """FORK: every entry is already resolved to a face for this style, so
    appending the regular chain behind it would repeat each family at its
    regular weight."""
    from crossglyph.cpfont import convert

    chains = {0: ["Sans-Regular.ttf"], 1: ["Sans-Bold.ttf"]}

    assert convert.chain_for_style(chains, 1) == ["Sans-Bold.ttf"]


def test_a_style_with_no_chain_of_its_own_takes_style_zero():
    """What a caller passing only {0: ...} has always meant by it, which is
    upstream's shape and fb2xt's."""
    from crossglyph.cpfont import convert

    assert convert.chain_for_style({0: ["Sans-Regular.ttf"]}, 2) == \
        ["Sans-Regular.ttf"]


def test_no_chains_at_all_is_an_empty_list():
    from crossglyph.cpfont import convert

    assert convert.chain_for_style(None, 0) == []


def test_an_unknown_interval_preset_exits_with_the_list(tmp_path):
    """FORK: the same, for the other exit a preview render can reach. What it
    would have taken is the answer to the reader's next question."""
    import pytest

    from crossglyph import cpfont

    with pytest.raises(SystemExit) as leaving:
        cpfont.resolve_intervals("klingon")
    said = str(leaving.value)
    assert "klingon" in said and "cyrillic" in said, said

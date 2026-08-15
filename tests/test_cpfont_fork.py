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


#: What our own comments say convert.py does, and the line each one points at.
#: The converter is a pinned fork that gets refreshed wholesale, so every one
#: of these numbers moves without anything else changing -- and a citation that
#: has drifted onto an unrelated line is worse than none, since it reads as
#: proof. Each entry is the cited range and a token the code there must carry.
CITATIONS = [
    ("1268-1271", "fallback_style_fonts.get(0, [])"),
    ("1258", "HEADER_SIZE = 32"),
    ("1302", "STYLE_TOC_FORMAT"),
    ("1303-1308", "advanceY > 255"),
    ("1131", "raise FontBuildError"),
]


def test_the_lines_we_cite_in_the_converter_are_the_ones_we_mean():
    source = (ROOT / "src/crossglyph/cpfont/convert.py").read_text(
        encoding="utf-8").splitlines()

    for where, token in CITATIONS:
        first, _, last = where.partition("-")
        lines = source[int(first) - 1:int(last or first)]
        assert any(token in line for line in lines), \
            f"convert.py:{where} no longer carries {token!r}"

    # And every citation in our own source is one of the above, so a new one
    # cannot be added without being pinned here too.
    import re

    cited = set()
    for path in sorted((ROOT / "src/crossglyph").rglob("*.py")):
        if path.parts[-2] == "cpfont":
            continue                    # the fork citing itself is upstream's
        cited |= set(re.findall(r"convert\.py:([0-9]+(?:-[0-9]+)?)",
                                path.read_text(encoding="utf-8")))
    assert cited == {where for where, _ in CITATIONS}, cited


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

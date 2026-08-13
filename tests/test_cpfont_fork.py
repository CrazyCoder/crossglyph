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

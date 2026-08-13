import pytest
from fontTools.ttLib import TTFont

from crossglyph import spacefont


def test_defaults_are_unchanged():
    widths = spacefont.resolve_widths(None)
    assert widths[0x2006] == 1 / 6
    assert widths[0x200A] == 1 / 10


def test_an_override_replaces_one_width():
    widths = spacefont.resolve_widths({0x2006: 1 / 4})
    assert widths[0x2006] == 1 / 4
    assert widths[0x2009] == 1 / 5      # the rest are untouched


def test_the_digest_tracks_overrides():
    assert spacefont.spec_digest() != spacefont.spec_digest({0x2006: 1 / 4})


def test_the_digest_is_stable_for_the_same_overrides():
    assert spacefont.spec_digest({0x2006: 0.25}) == \
        spacefont.spec_digest({0x2006: 0.25})


def test_a_codepoint_outside_the_table_is_rejected():
    """Membership is not overridable: the reader never asks a font for U+00A0
    (ChapterHtmlSlimParser rewrites it), so adding it would achieve nothing."""
    with pytest.raises(KeyError, match="00A0"):
        spacefont.resolve_widths({0x00A0: 0.5})


def test_an_override_reaches_the_generated_font(tmp_path):
    path = spacefont.build(tmp_path / "spaces.ttf", {0x2006: 1 / 2})
    hmtx = TTFont(str(path))["hmtx"]
    assert hmtx["uni2006"][0] == spacefont.UNITS_PER_EM // 2


def test_the_default_build_keeps_the_typographic_widths(tmp_path):
    path = spacefont.build(tmp_path / "spaces.ttf")
    hmtx = TTFont(str(path))["hmtx"]
    assert hmtx["uni2006"][0] == round(spacefont.UNITS_PER_EM / 6)
    assert hmtx["uni2003"][0] == spacefont.UNITS_PER_EM      # EM SPACE

"""What a built family records about how it was made.

The stamp file travels with the fonts, so what is in it is a promise to
whoever ends up holding them -- and to a later version of this tool, which is
the one reader guaranteed to disagree with today's defaults.
"""
import json

import pytest

from crossglyph import fontbuild, fontconf, fontstamp, provenance

pytest.importorskip("fontTools")


@pytest.fixture
def built(tmp_path):
    """One real family, built at one size, with its stamp beside it."""
    from fontsmith import box_font

    for style in ("Regular", "Bold"):
        box_font(tmp_path / f"Probe-{style}.ttf", [0x20, 0x41, 0x42],
                 family="Probe", style=style)
    (tmp_path / "probe.conf").write_text(
        "sizes = 12\nintervals = base\nfallbacks = no\ngamma = 1.4\n",
        encoding="utf-8")
    out = tmp_path / "out"
    config = fontconf.parse_config(tmp_path / "probe.conf")
    list(fontbuild.build_families([config], out))
    return json.loads((out / "Probe" / fontstamp.STAMP_NAME)
                      .read_text(encoding="utf-8"))


def test_the_rebuild_check_still_reads_its_own_half(built):
    """Provenance rides in the file the staleness check owns, so the half that
    decides a rebuild has to be untouched by it."""
    assert built["version"] == fontstamp.STAMP_VERSION
    assert set(built["sizes"]) == {"12"}


def test_every_setting_is_recorded_and_not_only_the_changed_ones(built):
    """Defaults move between versions. A file that recorded only departures
    from default would reproduce a different font a year later, and nobody
    would be able to say which of the two was the one that shipped."""
    settings = built["built"]["settings"]
    assert settings["gamma"] == 1.4                 # set in the config
    assert settings["kerning"] == 1.0               # never mentioned
    assert settings["hinting"] == "normal"
    assert set(fontconf.Tuning().as_dict()) <= set(settings)


def test_it_says_what_made_it(built):
    from crossglyph import version

    made = built["built"]
    assert made["by"] == f"crossglyph {version.installed()}"
    assert made["cpfont_format"] == fontbuild.cpfont.CPFONT_VERSION
    assert made["config"] == "probe.conf"
    assert made["at"].endswith("Z")


def test_each_source_face_is_identified_by_its_bytes(built):
    """A version string is a claim and a filename is a label. The hash is what
    says whether the face somebody has is the face this was made from."""
    regular = built["built"]["sources"]["regular"]
    assert regular["file"] == "Probe-Regular.ttf"
    assert len(regular["sha256"]) == 64
    assert regular["bytes"] > 0


def test_what_landed_is_listed_with_its_glyph_count(built):
    """The first question anyone asks of a shared font is what is in it."""
    one = built["built"]["files"]["12"]
    assert one["file"] == "Probe_12.cpfont"
    assert one["glyphs"] > 0 and one["bytes"] > 0


def test_a_fractional_size_is_recorded_where_the_filename_cannot_hold_it(
        tmp_path):
    """The device parses the label with strtol, so a family built at 13.5
    ships as _14 and reads back as 14 to anything that trusts the name. This
    is the only place the size it was rasterized at survives."""
    from fontsmith import box_font

    box_font(tmp_path / "Probe-Regular.ttf", [0x20, 0x41], family="Probe")
    (tmp_path / "probe.conf").write_text(
        "sizes = 13.5\nintervals = base\nfallbacks = no\n", encoding="utf-8")
    out = tmp_path / "out"
    list(fontbuild.build_families(
        [fontconf.parse_config(tmp_path / "probe.conf")], out))

    made = json.loads((out / "Probe" / fontstamp.STAMP_NAME)
                      .read_text(encoding="utf-8"))["built"]
    assert made["files"]["14"]["file"] == "Probe_14.cpfont"
    assert made["files"]["14"]["point_size"] == 13.5


def test_a_variable_slot_records_the_instance_it_was_drawn_at(tmp_path):
    """Merriweather ships Light as the file's default instance, so a family
    reproduced without this comes back visibly lighter with nothing to say
    why.

    The one face here that has to be asked directly: fontsmith builds static
    faces, and a build cannot be made to pin coordinates on one.
    """
    from fontsmith import box_font

    face = box_font(tmp_path / "Probe-Regular.ttf", [0x20, 0x41],
                    family="Probe")
    assert provenance._face(face, "hash", {"wght": 500.0})["instance"] \
        == {"wght": 500.0}
    assert "instance" not in provenance._face(face, "hash", {})
    # A static face has no design space, so there is no name to find in it and
    # none is invented.
    assert "instance_name" not in provenance._face(face, "hash", {"wght": 500.0})


def test_a_variable_face_is_named_for_the_family_not_its_default_instance():
    """Bitter's default instance is Thin, so its name record 1 reads "Bitter
    Thin" while 16 reads "Bitter". Recording the first sends somebody looking
    up the original to a weight nobody built."""
    assert provenance.NAME_IDS[0] == ("name", (16, 1))
    assert provenance.NAME_IDS[1] == ("subfamily", (17, 2))


def test_the_generated_space_face_is_not_listed_as_a_source(built):
    """It is written by this tool for this build and is nothing anybody can
    look up. That it was used is a setting, not a provenance entry."""
    assert not any("crossglyph-spaces" in name
                   for name in built["built"]["fallbacks"])


def test_a_prune_does_not_throw_the_record_away(tmp_path, built):
    """Dropping a size rewrites the stamp, and that rewrite knows nothing
    about how the family was made."""
    directory = tmp_path / "out" / "Probe"
    fontstamp.write_stamp(directory, {12: "digest-of-something"})
    kept = json.loads((directory / fontstamp.STAMP_NAME)
                      .read_text(encoding="utf-8"))
    assert kept["built"]["config"] == "probe.conf"

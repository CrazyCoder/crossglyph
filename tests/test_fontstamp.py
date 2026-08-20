import json

import pytest

from crossglyph import fontconf, fontstamp
from crossglyph.cpfont.tuning import Tuning


@pytest.fixture
def variant(tmp_path):
    fonts = tmp_path / "src"
    fonts.mkdir()
    for name in ("Alto-Medium.otf", "Alto Bold.otf", "Alto Italic.otf",
                 "Alto Bold Italic.otf"):
        (fonts / name).write_bytes(b"font-" + name.encode())
    (fonts / "alto.conf").write_text(
        "sizes = 12 14\nsizes_mod = 13\n", encoding="utf-8")
    return fontconf.parse_config(fonts / "alto.conf").variants()[0]


def _out(tmp_path, variant):
    directory = tmp_path / "out" / variant.name
    directory.mkdir(parents=True)
    return directory


def _cpfont(directory, variant, size):
    path = directory / f"{variant.name}_{size}.cpfont"
    path.write_bytes(b"CPFONT\x00\x00")
    return path


def _chained(tmp_path, text):
    """A variant in a workspace that has the bundled faces and one family of
    your own, so a chain can be reordered."""
    from crossglyph import fontbuild

    fonts = tmp_path / "src"
    fonts.mkdir(exist_ok=True)
    # All four, so the chain has a bold style to put a bold face in.
    for name in ("Alto-Medium.otf", "Alto Bold.otf", "Alto Italic.otf",
                 "Alto Bold Italic.otf"):
        (fonts / name).write_bytes(b"font-" + name.encode())
    (fonts / "MyIcons-Regular.ttf").write_bytes(b"icons")
    faces = fonts / fontbuild.FALLBACK_NAME
    faces.mkdir(exist_ok=True)
    for name in fontbuild.BUNDLED_FALLBACKS:
        (faces / name).write_bytes(b"noto-" + name.encode())
    for pair in fontbuild.CJK_FALLBACKS.values():
        for name in pair:
            (faces / name).write_bytes(b"cjk-" + name.encode())
    (fonts / "alto.conf").write_text(text, encoding="utf-8")
    return fontconf.parse_config(fonts / "alto.conf").variants()[0]


# --- digest ---------------------------------------------------------------

def test_digest_is_stable(variant):
    assert fontstamp.digest(variant, 12) == \
        fontstamp.digest(variant, 12)


def test_digest_tracks_the_size(variant):
    assert fontstamp.digest(variant, 12) != \
        fontstamp.digest(variant, 14)


def test_digest_tracks_font_content_not_mtime(variant):
    before = fontstamp.digest(variant, 12)
    (variant.config.dir / "Alto Bold.otf").write_bytes(b"different")
    assert fontstamp.digest(variant, 12) != before


def test_digest_tracks_settings(variant):
    before = fontstamp.digest(variant, 12)
    variant.config.tuning = Tuning(thresholds=Tuning.DARKEN_AA)
    assert fontstamp.digest(variant, 12) != before


def test_digest_tracks_every_tuning_knob(variant):
    """A knob absent from the stamp is a knob that silently reuses stale output."""
    before = fontstamp.digest(variant, 12)
    for tuning in (Tuning(gamma=0.8), Tuning(thresholds=(3, 6, 10)),
                   Tuning(weight=0.5), Tuning(slant=0.2),
                   Tuning(hinting="light"), Tuning(stem_darkening=True)):
        variant.config.tuning = tuning
        assert fontstamp.digest(variant, 12) != before, tuning


def test_digest_tracks_space_width_overrides(variant):
    before = fontstamp.digest(variant, 12)
    variant.config.space_widths = {0x2006: 0.25}
    assert fontstamp.digest(variant, 12) != before


def test_digest_tracks_the_converter_source(variant, monkeypatch, tmp_path):
    """The converter is our own module now, so its source is what is hashed."""
    before = fontstamp.digest(variant, 12)
    changed = tmp_path / "convert.py"
    changed.write_text("# converter, changed\n", encoding="utf-8")
    monkeypatch.setattr(fontstamp, "CONVERTER_SOURCES", (changed,))
    assert fontstamp.digest(variant, 12) != before


def test_digest_tracks_the_tuning_source_too(variant, monkeypatch, tmp_path):
    """coverage_lut() lives in tuning.py and decides the bytes of every glyph,
    so hashing only convert.py left a changed curve looking current. Inverting
    gamma's sense would have shipped stale .cpfonts to anyone with `gamma` in
    a config."""
    before = fontstamp.digest(variant, 12)
    for name in ("convert.py", "tuning.py"):
        (tmp_path / name).write_text(f"# {name}\n", encoding="utf-8")
    monkeypatch.setattr(fontstamp, "CONVERTER_SOURCES",
                        (tmp_path / "convert.py", tmp_path / "tuning.py"))
    unchanged = fontstamp.digest(variant, 12)
    assert unchanged != before

    (tmp_path / "tuning.py").write_text("# tuning, changed\n", encoding="utf-8")
    assert fontstamp.digest(variant, 12) != unchanged


def test_digest_tracks_the_cpfont_format_version(variant, monkeypatch):
    before = fontstamp.digest(variant, 12)
    monkeypatch.setattr(fontstamp.cpfont, "CPFONT_VERSION", 5)
    assert fontstamp.digest(variant, 12) != before


def test_a_reordered_chain_is_a_different_font(tmp_path):
    """Which face supplies a codepoint depends on the order, so a build under
    a new order is not the build sitting in the folder."""
    before = _chained(tmp_path, "fallbacks = yes\n")
    was = fontstamp.digest(before, 13)

    after = _chained(tmp_path, "fallbacks = yes\n"
                               "fallback_order = MyIcons, bundled\n")

    assert fontstamp.digest(after, 13) != was


def test_a_bold_face_appearing_in_the_folder_rebuilds_the_style(tmp_path):
    """The point of hashing the resolved chain and not the flag: the config
    did not move, and the font it builds did."""
    from crossglyph import fontbuild

    variant = _chained(tmp_path, "fallbacks = yes\n")
    was = fontstamp.digest(variant, 13)

    (tmp_path / "src" / fontbuild.FALLBACK_NAME
     / "NotoSans-Bold.ttf").write_bytes(b"bold")

    assert fontstamp.digest(_chained(tmp_path, "fallbacks = yes\n"), 13) != was


# --- staleness ------------------------------------------------------------

def test_everything_is_stale_without_a_stamp(tmp_path, variant):
    directory = _out(tmp_path, variant)
    assert fontstamp.stale_sizes(variant, directory) == [12, 14]


def test_nothing_is_stale_after_a_matching_build(tmp_path, variant):
    directory = _out(tmp_path, variant)
    for size in variant.sizes:
        _cpfont(directory, variant, size)
    fontstamp.write_stamp(directory, {s: fontstamp.digest(variant, s)
                                      for s in variant.sizes})
    assert fontstamp.stale_sizes(variant, directory) == []


def test_only_the_new_size_is_stale(tmp_path, variant):
    directory = _out(tmp_path, variant)
    for size in (12, 14):
        _cpfont(directory, variant, size)
    fontstamp.write_stamp(directory, {s: fontstamp.digest(variant, s)
                                      for s in (12, 14)})
    variant.sizes = [12, 14, 20]
    assert fontstamp.stale_sizes(variant, directory) == [20]


def test_a_deleted_cpfont_is_stale_even_with_a_matching_stamp(tmp_path, variant):
    directory = _out(tmp_path, variant)
    for size in variant.sizes:
        _cpfont(directory, variant, size)
    fontstamp.write_stamp(directory, {s: fontstamp.digest(variant, s)
                                      for s in variant.sizes})
    (directory / f"{variant.name}_14.cpfont").unlink()
    assert fontstamp.stale_sizes(variant, directory) == [14]


def test_force_makes_everything_stale(tmp_path, variant):
    directory = _out(tmp_path, variant)
    for size in variant.sizes:
        _cpfont(directory, variant, size)
    fontstamp.write_stamp(directory, {s: fontstamp.digest(variant, s)
                                      for s in variant.sizes})
    assert fontstamp.stale_sizes(variant, directory, force=True) == [12, 14]


def test_an_unreadable_stamp_is_treated_as_absent(tmp_path, variant):
    directory = _out(tmp_path, variant)
    (directory / fontstamp.STAMP_NAME).write_text("{not json", encoding="utf-8")
    assert fontstamp.stale_sizes(variant, directory) == [12, 14]


# --- pruning --------------------------------------------------------------

def test_dropped_sizes_are_removed(tmp_path, variant):
    directory = _out(tmp_path, variant)
    for size in (12, 14, 18):
        _cpfont(directory, variant, size)
    fontstamp.write_stamp(directory, {s: "x" for s in (12, 14, 18)})
    removed = fontstamp.prune(directory, variant)
    assert [p.name for p in removed] == [f"{variant.name}_18.cpfont"]
    assert not (directory / f"{variant.name}_18.cpfont").exists()
    stamp = json.loads((directory / fontstamp.STAMP_NAME).read_text())
    assert sorted(stamp["sizes"]) == ["12", "14"]


def test_pruning_leaves_files_from_other_families_alone(tmp_path, variant):
    directory = _out(tmp_path, variant)
    stray = directory / "Other_18.cpfont"
    stray.write_bytes(b"x")
    fontstamp.prune(directory, variant)
    assert stray.exists()


# --- fractional sizes -----------------------------------------------------


def test_a_fractional_size_is_labelled_by_canonical_rounding(tmp_path):
    """The device parses the size out of the filename with strtol into a
    uint8_t, so a fractional size cannot be named there. The label is what the
    picker shows; the glyphs are whatever was rasterized."""
    fonts = tmp_path / "src"
    fonts.mkdir()
    (fonts / "Alto-Medium.otf").write_bytes(b"font")
    (fonts / "alto.conf").write_text("sizes = 13.5\n", encoding="utf-8")
    variant = fontconf.parse_config(fonts / "alto.conf").variants()[0]

    assert variant.sizes == [13.5]
    assert fontstamp.cpfont_path(tmp_path, variant, 13.5).name == \
        f"{variant.name}_14.cpfont"


def test_the_label_rounds_half_up_not_half_to_even():
    """Python's round() is half-to-even, which would send 12.5 to 12 and 13.5
    to 14 -- an inexplicable rule on a font menu."""
    assert fontconf.size_label(12.5) == 13
    assert fontconf.size_label(13.5) == 14
    assert fontconf.size_label(13.4) == 13
    assert fontconf.size_label(13) == 13


def test_a_size_spells_back_to_the_size_it_was():
    """The spelling is not only a display: it fills the website's size boxes,
    a save writes those back, and the note under them works the filename out
    from what is in them. So a lossy spelling moves the size and misnames the
    file. %g rounded 13.4999999 to 13.5, which labels as 14 where the size
    itself labels as 13."""
    for raw in ["13", "13.5", "13.25", "13.4999999"]:
        size = fontconf.parse_sizes(raw, "sizes")[0]
        spelled = fontconf.size_spelling(size)
        assert fontconf.parse_sizes(spelled, "sizes")[0] == size, spelled
        assert fontconf.size_label(float(spelled)) == fontconf.size_label(size)
    # And a whole size is still spelled whole, which is what keeps every
    # ordinary config printing the way it always has.
    assert fontconf.size_spelling(13) == "13"
    assert fontconf.size_spelling(13.5) == "13.5"


def test_two_sizes_that_round_together_are_refused(tmp_path):
    fonts = tmp_path / "src"
    fonts.mkdir()
    (fonts / "Alto-Medium.otf").write_bytes(b"font")
    (fonts / "alto.conf").write_text("sizes = 13.5 14\n", encoding="utf-8")
    with pytest.raises(fontconf.FontConfigError, match="both land on 14"):
        fontconf.parse_config(fonts / "alto.conf")


def test_pruning_keeps_a_fractional_size_it_just_built(tmp_path):
    """The trap: the file is named for the label, so comparing the filename
    against the configured 13.5 would delete the build every run."""
    fonts = tmp_path / "src"
    fonts.mkdir()
    (fonts / "Alto-Medium.otf").write_bytes(b"font")
    (fonts / "alto.conf").write_text("sizes = 13.5\n", encoding="utf-8")
    variant = fontconf.parse_config(fonts / "alto.conf").variants()[0]

    directory = _out(tmp_path, variant)
    kept = _cpfont(directory, variant, 14)
    assert fontstamp.prune(directory, variant) == []
    assert kept.is_file()


def test_a_fractional_size_stays_current_across_runs(tmp_path):
    """The stamp is keyed by the size built, not the label, and the key has to
    spell the same way on write and on lookup or every run rebuilds."""
    fonts = tmp_path / "src"
    fonts.mkdir()
    (fonts / "Alto-Medium.otf").write_bytes(b"font")
    (fonts / "alto.conf").write_text("sizes = 13.5\n", encoding="utf-8")
    variant = fontconf.parse_config(fonts / "alto.conf").variants()[0]

    directory = _out(tmp_path, variant)
    _cpfont(directory, variant, 14)
    fontstamp.write_stamp(directory, {13.5: fontstamp.digest(variant, 13.5)})
    assert fontstamp.stale_sizes(variant, directory) == []


def test_a_whole_size_keys_the_stamp_the_way_it_always_did(tmp_path):
    """Stamps written before fractional sizes existed have to keep matching."""
    assert fontstamp.size_key(14) == "14"
    assert fontstamp.size_key(14.0) == "14"
    assert fontstamp.size_key(13.5) == "13.5"


def _config(tmp_path, sizes):
    fonts = tmp_path / "src"
    fonts.mkdir(exist_ok=True)
    (fonts / "Alto-Medium.otf").write_bytes(b"font")
    (fonts / "alto.conf").write_text(f"sizes = {sizes}\n", encoding="utf-8")
    return fonts / "alto.conf"


def test_the_same_size_twice_is_refused(tmp_path):
    """Not just sizes that round together -- one output asked for twice is
    still two jobs racing for one file, and fontcli builds sizes in a pool."""
    with pytest.raises(fontconf.FontConfigError, match="13.5 twice"):
        fontconf.parse_config(_config(tmp_path, "13.5 13.5"))


@pytest.mark.parametrize("sizes", ["nan", "inf", "1e400", "-3", "0", "0.4", "300"])
def test_a_size_that_is_not_a_usable_number_is_a_config_error(tmp_path, sizes):
    """FontConfigError, not a bare ValueError or OverflowError: fontbuild
    catches only the former per config, so anything else aborts the whole run
    with a traceback instead of reporting one bad config and carrying on.

    0.4 and 300 are refused for a different reason: their labels fall outside
    the 1..255 the device's own filename parser accepts, so the build would
    write a file nothing can load."""
    with pytest.raises(fontconf.FontConfigError):
        fontconf.parse_config(_config(tmp_path, sizes))

"""all.conf: shared settings, and families that need no config of their own."""
import pytest

from crossglyph import fontbuild, fontconf


def _fonts(directory, *names):
    for name in names:
        (directory / name).write_bytes(b"x" + name.encode())


def _conf(workspace):
    """The workspace's config folder, created on first use."""
    directory = fontbuild.conf_dir(workspace)
    directory.mkdir(exist_ok=True)
    return directory


QUILL = ["Quill-Regular.ttf", "Quill-Bold.ttf",
            "Quill-Italic.ttf", "Quill-BoldItalic.ttf"]
SAMPLE = ["sample.ttf", "sampleb.ttf", "samplei.ttf", "samplebi.ttf"]


@pytest.fixture
def source(tmp_path):
    (_conf(tmp_path) / "all.conf").write_text(
        "sizes = 12 13\nintervals = reading,cyrillic\nfallbacks = no\n"
        "thresholds = 3,6,10\n", encoding="utf-8")
    _fonts(tmp_path, *QUILL)
    return tmp_path


def _by_name(configs):
    return {c.name: c for c in configs}


# --- families with no config of their own ---------------------------------

def test_a_family_without_a_config_is_built_from_the_defaults(source):
    configs, errors = fontbuild.gather(source)
    assert errors == []
    quill = _by_name(configs)["Quill"]
    assert quill.derived is True
    assert quill.sizes == [12, 13]
    assert quill.intervals == "reading,cyrillic"
    assert quill.styles["bolditalic"].name == "Quill-BoldItalic.ttf"


def test_the_name_comes_from_the_filenames(source):
    _fonts(source, "PagePress-Regular.ttf", "PagePress-Bold.ttf")
    assert "PagePress" in _by_name(fontbuild.gather(source)[0])


def test_terse_suffixes_do_not_invent_extra_families(source):
    """sampleb/i/bi belong to sample, and must not each become a family."""
    _fonts(source, *SAMPLE)
    names = set(_by_name(fontbuild.gather(source)[0]))
    assert "sample" in names
    assert not {"sampleb", "samplei", "samplebi"} & names


def test_a_distinct_weight_keeps_its_own_family(source):
    """Quill-Light strips to itself, not to Quill."""
    _fonts(source, "Quill-Light.ttf")
    configs = _by_name(fontbuild.gather(source)[0])
    assert set(configs["Quill-Light"].styles) == {"regular"}
    assert configs["Quill"].styles["regular"].name == "Quill-Regular.ttf"


def test_a_family_with_its_own_config_is_not_duplicated(source):
    (_conf(source) / "quill.conf").write_text("name = Qui\n", encoding="utf-8")
    configs = fontbuild.gather(source)[0]
    assert [c.name for c in configs] == ["Qui"]
    assert configs[0].derived is False


def test_a_folder_of_fonts_is_a_family_list_with_no_config_at_all(source):
    """all.conf carries shared settings; it does not switch discovery on.

    What a release ships is a workspace with no `conf` in it, and the README
    tells its reader to drop four files in and run the launcher. Requiring an
    empty file first would make that first run fail with "no fonts".
    """
    (_conf(source) / "all.conf").unlink()
    configs, errors = fontbuild.gather(source)
    assert errors == []
    quill = _by_name(configs)["Quill"]
    assert quill.derived is True
    assert set(quill.styles) == {"regular", "bold", "italic", "bolditalic"}
    # Nothing is inherited any more, so it falls back to the shipped defaults
    # rather than to what the deleted all.conf used to say.
    assert quill.sizes == fontconf.DEFAULT_SIZES
    assert quill.intervals == fontconf.DEFAULT_INTERVALS


# --- inheritance ----------------------------------------------------------

def test_a_per_font_config_inherits_what_it_does_not_set(source):
    (_conf(source) / "quill.conf").write_text("sizes = 16 18\n", encoding="utf-8")
    config = _by_name(fontbuild.gather(source)[0])["Quill"]
    assert config.sizes == [16, 18]                    # its own
    assert config.intervals == "reading,cyrillic"      # inherited
    assert config.tuning.thresholds == (3, 6, 10)      # from all.conf
    assert config.fallbacks is False                   # inherited


def test_a_per_font_config_overrides_the_shared_value(source):
    (_conf(source) / "quill.conf").write_text(
        "intervals = base\nthresholds = 4,8,12\n", encoding="utf-8")
    config = _by_name(fontbuild.gather(source)[0])["Quill"]
    assert config.intervals == "base"
    assert config.tuning.thresholds == (4, 8, 12)


def test_defaults_reject_keys_that_name_one_family(source):
    (_conf(source) / "all.conf").write_text("name = Nope\n", encoding="utf-8")
    with pytest.raises(fontconf.FontConfigError, match="name"):
        fontbuild.gather(source)


def test_defaults_reject_keys_that_name_one_file(source):
    (_conf(source) / "all.conf").write_text("regular = Some.ttf\n", encoding="utf-8")
    with pytest.raises(fontconf.FontConfigError, match="regular"):
        fontbuild.gather(source)


def test_all_conf_is_not_itself_a_family(source):
    assert "all" not in _by_name(fontbuild.gather(source)[0])
    assert _conf(source) / "all.conf" not in fontbuild.discover_configs(source)


# --- selection ------------------------------------------------------------

def test_a_derived_family_can_be_named_on_the_command_line(source):
    _fonts(source, *SAMPLE)
    configs, errors = fontbuild.gather(source, ["Quill"])
    assert [c.name for c in configs] == ["Quill"]
    assert errors == []


def test_an_unknown_token_is_reported(source):
    configs, errors = fontbuild.gather(source, ["nosuchfont"])
    assert configs == []
    assert any("nosuchfont" in e for e in errors)


def test_selection_accepts_a_config_filename(source):
    (_conf(source) / "quill.conf").write_text("name = Qui\n", encoding="utf-8")
    assert [c.name for c in fontbuild.gather(source, ["quill.conf"])[0]] == ["Qui"]

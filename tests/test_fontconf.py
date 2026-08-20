import pytest

from crossglyph import fontbuild, fontconf


def _touch(directory, *names):
    for name in names:
        (directory / name).write_bytes(b"")


ALTO = [
    "Alto-Medium.otf",
    "Alto-MediumItalic.otf",
    "Alto Italic.otf",
    "Alto Bold Italic.otf",
    "Alto Bold.otf",
    "Alto.otf",
]

ROBOTO_SC = [
    "Roboto_SemiCondensed-Black.ttf",
    "Roboto_SemiCondensed-BlackItalic.ttf",
    "Roboto_SemiCondensed-Bold.ttf",
    "Roboto_SemiCondensed-BoldItalic.ttf",
    "Roboto_SemiCondensed-Italic.ttf",
    "Roboto_SemiCondensed-Light.ttf",
    "Roboto_SemiCondensed-LightItalic.ttf",
    "Roboto_SemiCondensed-Regular.ttf",
    "Roboto_SemiCondensed-SemiBold.ttf",
    "Roboto_SemiCondensed-SemiBoldItalic.ttf",
]


# --- config parsing -------------------------------------------------------

def test_reads_bare_key_value_pairs_without_a_section_header(tmp_path):
    _touch(tmp_path, *ALTO)
    (tmp_path / "alto.conf").write_text(
        "# a comment\n"
        "name = Alto\n"
        "sizes = 12 14 16 18\n"
        "; another comment\n"
        "thresholds = 3,6,10\n",
        encoding="utf-8")
    cfg = fontconf.parse_config(tmp_path / "alto.conf")
    assert cfg.name == "Alto"
    assert cfg.sizes == [12, 14, 16, 18]
    assert cfg.tuning.thresholds == fontconf.Tuning.DARKEN_AA


def test_sizes_accept_commas_as_well_as_spaces(tmp_path):
    _touch(tmp_path, *ALTO)
    (tmp_path / "alto.conf").write_text("sizes = 12, 14,16\n", encoding="utf-8")
    assert fontconf.parse_config(tmp_path / "alto.conf").sizes == [12, 14, 16]


def test_name_defaults_to_the_config_filename(tmp_path):
    _touch(tmp_path, *ALTO)
    (tmp_path / "Alto.conf").write_text("", encoding="utf-8")
    assert fontconf.parse_config(tmp_path / "Alto.conf").name == "Alto"


def test_bundled_fallbacks_are_opt_in(tmp_path):
    _touch(tmp_path, *ALTO)
    (tmp_path / "Alto.conf").write_text("", encoding="utf-8")
    assert fontconf.parse_config(tmp_path / "Alto.conf").fallbacks is False


def test_name_is_sanitised_for_use_in_filenames(tmp_path):
    _touch(tmp_path, *ALTO)
    (tmp_path / "alto.conf").write_text("name = Alto Pro!\nfamily = Alto\n",
                                          encoding="utf-8")
    assert fontconf.parse_config(tmp_path / "alto.conf").name == "AltoPro"


def test_unknown_key_is_an_error(tmp_path):
    _touch(tmp_path, *ALTO)
    (tmp_path / "alto.conf").write_text("sizez = 12\n", encoding="utf-8")
    with pytest.raises(fontconf.FontConfigError, match="sizez"):
        fontconf.parse_config(tmp_path / "alto.conf")


def test_intervals_default_to_reading_and_nothing_beside_it(tmp_path):
    """`reading` is the converter's `default` block and a good deal more, so
    naming other presets beside it mostly restates it: latin-ext and symbols
    add nothing at all, and the panel showing five ticks reads as five things
    a build needs."""
    from crossglyph.cpfont import convert

    _touch(tmp_path, *ALTO)
    (tmp_path / "alto.conf").write_text("", encoding="utf-8")
    cfg = fontconf.parse_config(tmp_path / "alto.conf")
    assert cfg.intervals == "reading"
    # base is injected by the converter itself; listing it would be redundant.
    assert "base" not in cfg.intervals

    # And the claim above, from the ranges rather than from memory.
    def points(name):
        return {code for low, high in convert.INTERVAL_PRESETS[name]
                for code in range(low, high + 1)}

    reading = points("reading") | points("base")
    for name in ("default", "latin-ext", "symbols", "vietnamese"):
        assert not points(name) - reading, f"{name} is no longer inside reading"
    # The two that are not, and why they stay tickable: the main blocks are in
    # reading, the rest of each block is not.
    assert points("greek") - reading, "polytonic Greek would have nothing to add"
    assert points("cyrillic") - reading, "the Cyrillic Supplement likewise"


def test_dir_key_points_discovery_at_another_folder(tmp_path):
    fonts = tmp_path / "elsewhere"
    fonts.mkdir()
    _touch(fonts, *ALTO)
    (tmp_path / "alto.conf").write_text("dir = elsewhere\n", encoding="utf-8")
    cfg = fontconf.parse_config(tmp_path / "alto.conf")
    assert cfg.styles["regular"].parent == fonts


# --- walking the workspace ------------------------------------------------

def test_a_face_in_a_subfolder_is_part_of_the_workspace(tmp_path):
    """A font folder arrives as a folder, and unpacking it into the root to be
    seen is busywork the tool can do itself."""
    nested = tmp_path / "serif" / "alto"
    nested.mkdir(parents=True)
    _touch(nested, *ALTO)
    assert fontconf.discover_styles(tmp_path, "Alto")["regular"].parent == nested
    assert "Alto" in fontconf.discover_families(tmp_path)


def test_a_family_split_across_folders_is_still_one_family(tmp_path):
    """Folders organize; the filename says what a face is."""
    (tmp_path / "upright").mkdir()
    (tmp_path / "sloped").mkdir()
    _touch(tmp_path / "upright", "Quill-Regular.ttf", "Quill-Bold.ttf")
    _touch(tmp_path / "sloped", "Quill-Italic.ttf")
    styles = fontconf.discover_styles(tmp_path, "Quill")
    assert set(styles) >= {"regular", "bold", "italic"}


def test_the_bundled_fallbacks_are_not_families_of_their_own(tmp_path):
    """The twelve Noto faces a fetch puts in `fallbacks` fill holes in other
    families. Walked as sources, they turn a picker of your own fonts into a
    list with NotoSansTifinagh and NotoEmoji in it, which is what recursion
    did the first time it shipped."""
    bundled = tmp_path / "fallbacks"
    bundled.mkdir()
    _touch(bundled, "NotoSans-Regular.ttf", "NotoSansTifinagh-Regular.ttf",
           "NotoEmoji-Regular.ttf")
    _touch(tmp_path, *ALTO)
    assert set(fontconf.discover_families(tmp_path)) == {"Alto"}


@pytest.mark.parametrize("folder", ["conf", "cpfonts", ".git"])
def test_the_folders_that_are_not_sources_are_not_walked(tmp_path, folder):
    """conf holds configs, cpfonts holds builds, and a dot folder is somebody
    else's. A face that turns up in one of them was not put there to be built."""
    buried = tmp_path / folder
    buried.mkdir()
    _touch(buried, *ALTO)
    assert fontconf.discover_families(tmp_path) == {}


def test_a_build_folder_named_something_else_costs_only_the_walk(tmp_path):
    """`out` can point anywhere, so the skip list cannot name every build
    folder. It does not have to: what lands in one is .cpfont, which is not a
    font suffix."""
    built = tmp_path / "somewhere-else"
    built.mkdir()
    (built / "Alto_12.cpfont").write_bytes(b"")
    assert fontconf.font_files(tmp_path) == []


def test_the_walk_is_ordered_the_same_way_everywhere(tmp_path):
    """Two files that would claim one slot are settled by path, so a folder
    does not resolve differently on another machine."""
    for folder in ("b", "a"):
        (tmp_path / folder).mkdir()
        _touch(tmp_path / folder, "Alto-Medium.otf")
    found = fontconf.font_files(tmp_path)
    assert [path.parent.name for path in found] == ["a", "b"]


# --- style discovery ------------------------------------------------------

def test_medium_is_the_regular_face(tmp_path):
    _touch(tmp_path, *ALTO)
    styles = fontconf.discover_styles(tmp_path, "Alto")
    assert styles["regular"].name == "Alto-Medium.otf"


def test_explicit_weight_beats_the_bare_stem_for_the_same_slot(tmp_path):
    """Alto.otf and Alto-Medium.otf both classify as regular."""
    _touch(tmp_path, *ALTO)
    styles = fontconf.discover_styles(tmp_path, "Alto")
    assert styles["regular"].name != "Alto.otf"


def test_regular_outranks_medium_when_a_family_ships_both(tmp_path):
    _touch(tmp_path, "Noto-Regular.ttf", "Noto-Medium.ttf", "Noto-Bold.ttf")
    styles = fontconf.discover_styles(tmp_path, "Noto")
    assert styles["regular"].name == "Noto-Regular.ttf"


def test_extra_weight_italics_lose_to_the_plain_italic(tmp_path):
    """Quill-MediumItalic must not outrank Quill-Italic when the regular
    face is Quill-Regular: the pair would be mismatched in weight."""
    _touch(tmp_path, "Quill-Regular.ttf", "Quill-Italic.ttf",
           "Quill-Medium.ttf", "Quill-MediumItalic.ttf")
    assert fontconf.discover_styles(tmp_path, "Quill")["italic"].name \
        == "Quill-Italic.ttf"


def test_the_italic_matching_a_medium_regular_wins_the_slot_back(tmp_path):
    """With Medium as the regular face, Alto Italic would be the lighter of
    the two italics; Alto-MediumItalic is the matching weight."""
    _touch(tmp_path, *ALTO)
    assert fontconf.discover_styles(tmp_path, "Alto")["italic"].name \
        == "Alto-MediumItalic.otf"


def test_all_four_alto_faces_resolve(tmp_path):
    _touch(tmp_path, *ALTO)
    styles = fontconf.discover_styles(tmp_path, "Alto")
    assert {k: v.name for k, v in styles.items()} == {
        "regular": "Alto-Medium.otf",
        "bold": "Alto Bold.otf",
        "italic": "Alto-MediumItalic.otf",
        "bolditalic": "Alto Bold Italic.otf",
    }


# --- terse suffixes -------------------------------------------------------

SAMPLE = ["sample.ttf", "sampleb.ttf", "samplebi.ttf", "samplei.ttf"]


def test_single_letter_suffixes_resolve(tmp_path):
    _touch(tmp_path, *SAMPLE)
    styles = fontconf.discover_styles(tmp_path, "sample")
    assert {k: v.name for k, v in styles.items()} == {
        "regular": "sample.ttf",
        "bold": "sampleb.ttf",
        "italic": "samplei.ttf",
        "bolditalic": "samplebi.ttf",
    }


def test_bd_suffixes_resolve(tmp_path):
    _touch(tmp_path, "arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf")
    styles = fontconf.discover_styles(tmp_path, "arial")
    assert styles["bold"].name == "arialbd.ttf"
    assert styles["italic"].name == "ariali.ttf"
    assert styles["bolditalic"].name == "arialbi.ttf"


def test_z_is_the_bold_italic_microsoft_ships(tmp_path):
    """georgiaz.ttf, verdanaz.ttf, CALIBRIZ.TTF. Without it the folder resolves
    as a family missing its bold italic, beside a one-face family called
    Georgiaz that looks like a roman and sets like an italic."""
    _touch(tmp_path, "georgia.ttf", "georgiab.ttf", "georgiai.ttf",
           "georgiaz.ttf")
    styles = fontconf.discover_styles(tmp_path, "georgia")
    assert {k: v.name for k, v in styles.items()} == {
        "regular": "georgia.ttf",
        "bold": "georgiab.ttf",
        "italic": "georgiai.ttf",
        "bolditalic": "georgiaz.ttf",
    }


def test_a_trailing_z_is_not_a_style_without_the_plain_family_file(tmp_path):
    """Quartz.ttf is a family, not the bold italic of one called Quart -- the
    same corroboration that keeps Bodoni out of the italic slot."""
    _touch(tmp_path, "Quartz.ttf", "Quartz-Bold.ttf")
    assert fontconf.discover_styles(tmp_path, "Quart") == {}
    assert fontconf.discover_styles(tmp_path, "Quartz")["regular"].name \
        == "Quartz.ttf"


def test_a_trailing_letter_is_not_a_style_without_the_plain_family_file(tmp_path):
    """Bodoni.ttf must not be read as the italic of a family called Bodon."""
    _touch(tmp_path, "Bodoni.ttf", "Bodoni-Bold.ttf")
    assert fontconf.discover_styles(tmp_path, "Bodon") == {}
    assert fontconf.discover_styles(tmp_path, "Bodoni")["regular"].name \
        == "Bodoni.ttf"


def test_a_variable_fonts_axes_are_not_part_of_its_family_name(tmp_path):
    """Google Fonts ships Merriweather[opsz,wdth,wght].ttf. The axis list is
    filename, not family: left on the stem it survives sanitize_name as
    "Merriweatheropszwdthwght", and the -Italic file -- whose suffix is no
    longer at the end -- becomes a one-face family of its own rather than that
    family's italic."""
    _touch(tmp_path, "Merriweather[opsz,wdth,wght].ttf",
           "Merriweather-Italic[opsz,wdth,wght].ttf")
    families = fontconf.discover_families(tmp_path)
    assert sorted(families) == ["Merriweather"]
    assert {k: v.name for k, v in families["Merriweather"].items()} == {
        "regular": "Merriweather[opsz,wdth,wght].ttf",
        "italic": "Merriweather-Italic[opsz,wdth,wght].ttf",
    }


GOOGLE_SANS = ["GoogleSans-VariableFont_GRAD,opsz,wght.ttf",
               "GoogleSans-Italic-VariableFont_GRAD,opsz,wght.ttf"]


def test_the_website_download_spells_the_axis_list_a_second_way(tmp_path):
    """The zip from fonts.google.com names the same thing -VariableFont_<axes>.
    The italic is the harder half: its -Italic is in the middle of the stem, so
    the two files share no prefix any style rule can pair them by."""
    _touch(tmp_path, *GOOGLE_SANS)
    families = fontconf.discover_families(tmp_path)
    assert sorted(families) == ["GoogleSans"]
    assert {k: v.name for k, v in families["GoogleSans"].items()} == {
        "regular": "GoogleSans-VariableFont_GRAD,opsz,wght.ttf",
        "italic": "GoogleSans-Italic-VariableFont_GRAD,opsz,wght.ttf",
    }


def test_one_axis_and_a_renamed_file_lose_the_suffix_too(tmp_path):
    """A single-axis download, and the same file with the list taken off by
    hand."""
    assert fontconf.font_stem(tmp_path / "Lora-VariableFont_wght.ttf") == "Lora"
    assert fontconf.font_stem(tmp_path / "Lora-VariableFont.ttf") == "Lora"


def test_a_family_that_merely_ends_in_that_word_keeps_its_name(tmp_path):
    """What marks the suffix as generated is the shape of what follows it.
    Four characters is an axis tag; a word is somebody's family name."""
    assert fontconf.font_stem(tmp_path / "Foundry-VariableFont_Display.ttf") \
        == "Foundry-VariableFont_Display"
    assert fontconf.font_stem(tmp_path / "MyVariableFont-Regular.ttf") \
        == "MyVariableFont-Regular"


def _variable(directory, name="Probe[wght].ttf", **kwargs):
    import fontsmith
    return fontsmith.variable_box_font(directory / name, [0x41, 0x42], **kwargs)


def test_a_variable_font_fills_the_bold_slot_it_has_no_file_for(tmp_path):
    """One file is several faces. The family ships a roman and an italic and
    gets four slots, because the bold ones are the same files at the weight the
    designer named Bold."""
    _variable(tmp_path)
    _variable(tmp_path, "Probe-Italic[wght].ttf", style="Italic", italic=True)
    styles = fontconf.discover_styles(tmp_path, "Probe")
    assert {k: v.name for k, v in styles.items()} == {
        "regular": "Probe[wght].ttf",
        "bold": "Probe[wght].ttf",
        "italic": "Probe-Italic[wght].ttf",
        "bolditalic": "Probe-Italic[wght].ttf",
    }


def test_a_drawn_bold_beats_an_interpolated_one(tmp_path):
    """A file for the slot is a face the designer drew; the axis is one this
    interpolates. Where both exist the drawn one is the better face."""
    _variable(tmp_path)
    _touch(tmp_path, "Probe-Bold.ttf")
    styles = fontconf.discover_styles(tmp_path, "Probe")
    assert styles["bold"].name == "Probe-Bold.ttf"


def test_a_static_font_fills_no_slot_it_has_no_file_for(tmp_path):
    _touch(tmp_path, "Probe.ttf")
    assert set(fontconf.discover_styles(tmp_path, "Probe")) == {"regular"}


def test_the_slots_are_built_at_the_instances_the_font_names(tmp_path):
    """Not at the file's default instance, which is not always the text weight:
    Merriweather defaults to Light, so taking the file as it comes builds a
    Light face and calls it Regular."""
    font = _variable(tmp_path)
    assert fontconf.slot_coords(font, "regular") == {"wght": 400.0}
    assert fontconf.slot_coords(font, "bold") == {"wght": 700.0}
    # The default this is not: the file itself says 300.
    assert fontconf.variable_font(font).axes["wght"][1] == 300.0


def test_a_font_naming_no_instance_falls_back_to_the_css_weights(tmp_path):
    font = _variable(tmp_path, instances={"Thin": 300, "Black": 900})
    assert fontconf.slot_coords(font, "regular") == {"wght": 400.0}
    assert fontconf.slot_coords(font, "bold") == {"wght": 700.0}


def test_a_weight_the_axis_does_not_reach_is_clamped_to_what_it_has(tmp_path):
    font = _variable(tmp_path, axis=("wght", 300, 400, 500),
                     instances={"Thin": 300, "Medium": 500})
    assert fontconf.slot_coords(font, "bold") == {"wght": 500.0}


def test_a_static_font_is_rasterized_at_no_coordinates_at_all(tmp_path):
    _touch(tmp_path, "Probe.ttf")
    assert fontconf.slot_coords(tmp_path / "Probe.ttf", "bold") == {}


def test_an_axis_a_font_does_not_have_is_a_config_error(tmp_path):
    _variable(tmp_path)
    (tmp_path / "probe.conf").write_text(
        "regular = Probe[wght].ttf@slnt=-12\n", encoding="utf-8")
    with pytest.raises(fontconf.FontConfigError, match="slnt"):
        fontconf.parse_config(tmp_path / "probe.conf")


def test_a_pinned_coordinate_wins_over_the_named_instance(tmp_path):
    _variable(tmp_path)
    (tmp_path / "probe.conf").write_text(
        "regular = Probe[wght].ttf@wght=500\n", encoding="utf-8")
    config = fontconf.parse_config(tmp_path / "probe.conf")
    assert config.coords("regular") == {"wght": 500.0}
    # The slot that was not pinned keeps the instance the font names.
    assert config.coords("bold") == {"wght": 700.0}


@pytest.mark.parametrize("value, filename, axes", [
    ("Probe[wght].ttf", "Probe[wght].ttf", {}),
    ("Probe[wght].ttf@wght=500", "Probe[wght].ttf", {"wght": 500.0}),
    ("Probe.ttf@wght=500,opsz=12.5", "Probe.ttf",
     {"wght": 500.0, "opsz": 12.5}),
    ("Probe.ttf@wght=-10", "Probe.ttf", {"wght": -10.0}),
    # An @ that is not a coordinate list belongs to the filename.
    ("mail@home.ttf", "mail@home.ttf", {}),
])
def test_a_style_key_splits_into_a_file_and_its_coordinates(value, filename, axes):
    assert fontconf.split_axes(value) == (filename, axes)


# The shape a foundry ships, with an invented family: what is being tested is
# the numbering, not any one typeface.
VANTAGE = [
    "Vantage_LT_65_Medium.ttf",
    "Vantage_LT_66_Medium_Italic.ttf",
    "Vantage_LT_75_Bold.ttf",
    "Vantage_LT_76_Bold_Italic.ttf",
]


def test_a_foundry_series_number_is_not_part_of_the_family(tmp_path):
    """Linotype numbers the styles: 65 Medium, 66 Medium Italic, 75 Bold, 76
    Bold Italic, where the first digit is the weight and the second says
    upright or italic. The number is in the stem, so without dropping it each
    file is a family of its own and the four never meet."""
    _touch(tmp_path, *VANTAGE)
    families = fontconf.discover_families(tmp_path)
    assert sorted(families) == ["Vantage_LT"]
    assert {k: v.name for k, v in families["Vantage_LT"].items()} == {
        "regular": "Vantage_LT_65_Medium.ttf",
        "bold": "Vantage_LT_75_Bold.ttf",
        "italic": "Vantage_LT_66_Medium_Italic.ttf",
        "bolditalic": "Vantage_LT_76_Bold_Italic.ttf",
    }


def test_the_italic_is_matched_across_a_family_name_with_a_separator(tmp_path):
    """Vantage's italic is a Medium Italic, which is parked as an extra weight
    and won back only by matching the roman's weight. That comparison drops
    separators from the filename, so it has to drop them from the family name
    too -- `Vantage_LT` never equals `vantagelt` otherwise."""
    _touch(tmp_path, *VANTAGE)
    styles = fontconf.discover_styles(tmp_path, "Vantage_LT")
    assert styles["italic"].name == "Vantage_LT_66_Medium_Italic.ttf"


def test_a_number_that_is_the_family_stays(tmp_path):
    """Only a number between the family and a tail of pure style words goes.
    A weight named as a number is the family's own and keeps it, the same way
    Roboto_SemiCondensed-Light is a family rather than a weight of one."""
    _touch(tmp_path, "Roboto_Condensed_300.ttf", "Roboto_Condensed_700.ttf")
    assert sorted(fontconf.discover_families(tmp_path)) ==         ["Roboto_Condensed_300", "Roboto_Condensed_700"]


def test_a_version_number_is_left_alone(tmp_path):
    """It is not between the family and a style, so it is none of this rule's
    business -- these still need the explicit keys."""
    _touch(tmp_path, "TerminusTTFWindows-Bold-4.49.3.ttf",
           "TerminusTTFWindows-4.49.3.ttf")
    assert fontconf.font_stem(tmp_path / "TerminusTTFWindows-Bold-4.49.3.ttf")         == "TerminusTTFWindows-Bold-4.49.3"


def test_a_spelled_out_suffix_beats_a_terse_one(tmp_path):
    _touch(tmp_path, "probe.ttf", "probeb.ttf", "probe-Bold.ttf")
    assert fontconf.discover_styles(tmp_path, "probe")["bold"].name \
        == "probe-Bold.ttf"


def test_other_weights_form_their_own_families(tmp_path):
    """A ten-file Roboto SemiCondensed folder narrows to the four real styles:
    -Light strips to Roboto_SemiCondensed-Light, a different family."""
    _touch(tmp_path, *ROBOTO_SC)
    styles = fontconf.discover_styles(tmp_path, "Roboto_SemiCondensed")
    assert {k: v.name for k, v in styles.items()} == {
        "regular": "Roboto_SemiCondensed-Regular.ttf",
        "bold": "Roboto_SemiCondensed-Bold.ttf",
        "italic": "Roboto_SemiCondensed-Italic.ttf",
        "bolditalic": "Roboto_SemiCondensed-BoldItalic.ttf",
    }


def test_optical_size_suffix_is_part_of_the_family(tmp_path):
    _touch(tmp_path, "Quill_18pt-Regular.ttf", "Quill_18pt-Bold.ttf",
           "Quill-Regular.ttf")
    assert fontconf.discover_styles(tmp_path, "Quill_18pt")["regular"].name \
        == "Quill_18pt-Regular.ttf"
    assert fontconf.discover_styles(tmp_path, "Quill")["regular"].name \
        == "Quill-Regular.ttf"


def test_explicit_style_keys_override_discovery(tmp_path):
    _touch(tmp_path, *ALTO)
    (tmp_path / "alto.conf").write_text("regular = Alto.otf\n", encoding="utf-8")
    cfg = fontconf.parse_config(tmp_path / "alto.conf")
    assert cfg.styles["regular"].name == "Alto.otf"
    assert cfg.styles["bold"].name == "Alto Bold.otf"


def test_missing_style_file_is_an_error(tmp_path):
    _touch(tmp_path, *ALTO)
    (tmp_path / "alto.conf").write_text("bold = Nope.otf\n", encoding="utf-8")
    with pytest.raises(fontconf.FontConfigError, match="Nope.otf"):
        fontconf.parse_config(tmp_path / "alto.conf")


def test_family_without_a_regular_face_is_an_error(tmp_path):
    _touch(tmp_path, "Ghost Bold.ttf")
    (tmp_path / "ghost.conf").write_text("family = Ghost\n", encoding="utf-8")
    with pytest.raises(fontconf.FontConfigError, match="regular"):
        fontconf.parse_config(tmp_path / "ghost.conf")


# --- variants -------------------------------------------------------------

def test_sizes_mod_produces_a_second_family(tmp_path):
    _touch(tmp_path, *ALTO)
    (tmp_path / "alto.conf").write_text(
        "sizes = 12 14 16 18\nsizes_mod = 13 15 17 19\n", encoding="utf-8")
    variants = fontconf.parse_config(tmp_path / "alto.conf").variants()
    assert [(v.name, v.sizes) for v in variants] == [
        ("Alto", [12, 14, 16, 18]),
        ("AltoMod", [13, 15, 17, 19]),
    ]


def test_mod_suffix_is_configurable(tmp_path):
    _touch(tmp_path, *ALTO)
    (tmp_path / "alto.conf").write_text(
        "sizes_mod = 13\nmod_suffix = Alt\n", encoding="utf-8")
    assert fontconf.parse_config(tmp_path / "alto.conf").variants()[1].name \
        == "AltoAlt"


def test_without_sizes_mod_there_is_one_variant(tmp_path):
    _touch(tmp_path, *ALTO)
    (tmp_path / "alto.conf").write_text("", encoding="utf-8")
    assert len(fontconf.parse_config(tmp_path / "alto.conf").variants()) == 1


# --- tuning ---------------------------------------------------------------

def _cfg(tmp_path, text):
    (tmp_path / "Alto-Medium.otf").write_bytes(b"x")
    (tmp_path / "alto.conf").write_text(text, encoding="utf-8")
    return fontconf.parse_config(tmp_path / "alto.conf")


def test_tuning_keys_are_parsed(tmp_path):
    cfg = _cfg(tmp_path, "gamma = 0.8\nthresholds = 3 6 10\nweight = 0.25\n"
                         "slant = 0.2\nhinting = light\nstem_darkening = yes\n")
    assert cfg.tuning.gamma == 0.8
    assert cfg.tuning.thresholds == (3, 6, 10)
    assert cfg.tuning.weight == 0.25
    assert cfg.tuning.slant == 0.2
    assert cfg.tuning.hinting == "light"
    assert cfg.tuning.stem_darkening is True


def test_tuning_defaults_to_upstream_behaviour(tmp_path):
    assert _cfg(tmp_path, "").tuning == fontconf.Tuning()


@pytest.mark.parametrize("line", ["darken_aa = yes", "force_autohint = yes"])
def test_a_key_that_is_not_a_key_is_an_error(tmp_path, line):
    """Ignoring one quietly would build a font nobody asked for."""
    with pytest.raises(fontconf.FontConfigError, match="unknown key"):
        _cfg(tmp_path, line + "\n")


def test_a_bad_threshold_order_is_rejected(tmp_path):
    with pytest.raises(fontconf.FontConfigError, match="ascending"):
        _cfg(tmp_path, "thresholds = 8 4 12\n")


def test_the_wrong_number_of_thresholds_is_rejected(tmp_path):
    with pytest.raises(fontconf.FontConfigError, match="three numbers"):
        _cfg(tmp_path, "thresholds = 4 8\n")


def test_a_non_numeric_gamma_is_rejected(tmp_path):
    with pytest.raises(fontconf.FontConfigError, match="gamma must be a number"):
        _cfg(tmp_path, "gamma = dark\n")


def test_an_unknown_hinting_mode_is_rejected(tmp_path):
    with pytest.raises(fontconf.FontConfigError, match="hinting"):
        _cfg(tmp_path, "hinting = subpixel\n")


def test_a_space_width_override_is_parsed(tmp_path):
    assert _cfg(tmp_path, "space_width_2006 = 0.25\n").space_widths == {0x2006: 0.25}


def test_a_space_width_for_a_codepoint_we_do_not_ship_is_rejected(tmp_path):
    with pytest.raises(fontconf.FontConfigError, match="00A0"):
        _cfg(tmp_path, "space_width_00A0 = 0.5\n")


def test_an_unknown_key_is_still_rejected(tmp_path):
    with pytest.raises(fontconf.FontConfigError, match="unknown key"):
        _cfg(tmp_path, "gamma_correction = 2\n")


def test_the_metric_keys_are_parsed(tmp_path):
    cfg = _cfg(tmp_path, "line_height = 1.15\nletter_spacing = 0.25\n"
                         "word_spacing = -0.5\n")
    assert cfg.tuning.line_height == fontconf.LineHeight(1.15, "em")
    assert cfg.tuning.letter_spacing == 0.25
    assert cfg.tuning.word_spacing == -0.5


def test_line_height_accepts_all_three_forms(tmp_path):
    assert _cfg(tmp_path, "line_height = 0.9x\n").tuning.line_height.mode == "scale"
    assert _cfg(tmp_path, "line_height = 26px\n").tuning.line_height.mode == "px"
    assert _cfg(tmp_path, "line_height = 1.2\n").tuning.line_height.mode == "em"


def test_line_height_defaults_to_the_fonts_own(tmp_path):
    assert _cfg(tmp_path, "").tuning.line_height is None


def test_a_nonsense_line_height_is_rejected(tmp_path):
    with pytest.raises(fontconf.FontConfigError, match="line_height"):
        _cfg(tmp_path, "line_height = wide\n")


def test_a_nonsense_letter_spacing_is_rejected(tmp_path):
    with pytest.raises(fontconf.FontConfigError,
                       match="letter_spacing must be a number"):
        _cfg(tmp_path, "letter_spacing = loose\n")


def test_kerning_accepts_yes_no_and_a_factor(tmp_path):
    assert _cfg(tmp_path, "kerning = no\n").tuning.kerning == 0.0
    assert _cfg(tmp_path, "kerning = yes\n").tuning.kerning == 1.0
    assert _cfg(tmp_path, "kerning = 0.5\n").tuning.kerning == 0.5


def test_kerning_defaults_to_the_fonts_own(tmp_path):
    assert _cfg(tmp_path, "").tuning.kerning == 1.0


def test_ligatures_are_a_plain_switch(tmp_path):
    assert _cfg(tmp_path, "ligatures = no\n").tuning.ligatures is False
    assert _cfg(tmp_path, "").tuning.ligatures is True


def test_a_negative_kerning_factor_is_rejected(tmp_path):
    with pytest.raises(fontconf.FontConfigError, match="kerning"):
        _cfg(tmp_path, "kerning = -1\n")


def test_a_nonsense_kerning_is_rejected(tmp_path):
    with pytest.raises(fontconf.FontConfigError, match="kerning"):
        _cfg(tmp_path, "kerning = tight\n")


def test_figures_selects_the_proportional_set(tmp_path):
    assert _cfg(tmp_path, "figures = proportional\n").tuning.figures == \
        "proportional"
    assert _cfg(tmp_path, "").tuning.figures == "default"


def test_an_unknown_figure_style_is_rejected(tmp_path):
    with pytest.raises(fontconf.FontConfigError, match="figures"):
        _cfg(tmp_path, "figures = oldstyle\n")


# --- writing back ---------------------------------------------------------
# These configs are written by hand and carry more comment than setting, so a
# tool that saves into one has to leave everything it did not touch alone.

WRITTEN = "gamma = 1.35"


def test_a_written_key_keeps_its_place_and_its_padding(tmp_path):
    conf = tmp_path / "alto.conf"
    conf.write_text("# Alto.\nname       = Alto\ngamma      = 1.0\n"
                    "# trailing note\n", encoding="utf-8")

    assert fontconf.write_values(conf, {"gamma": "1.35"}) == ["gamma"]
    assert conf.read_text(encoding="utf-8") == (
        "# Alto.\nname       = Alto\ngamma      = 1.35\n"
        "# trailing note\n")


def test_a_commented_out_key_is_where_the_value_goes(tmp_path):
    """The files carry their own examples commented out. Filling one in beats
    appending a second copy of the same key at the bottom."""
    conf = tmp_path / "alto.conf"
    conf.write_text("name = Alto\n# ranges =\n# sizes_mod  = 13 15 17 19\n",
                    encoding="utf-8")

    fontconf.write_values(conf, {"sizes_mod": "13 15 17 19"})
    assert conf.read_text(encoding="utf-8") == (
        "name = Alto\n# ranges =\nsizes_mod = 13 15 17 19\n")


def test_a_new_key_lands_under_a_heading_of_its_own(tmp_path):
    """Appended bare, a key reads as belonging to whatever section the file
    happened to end with -- which in these files is a block of comments."""
    conf = tmp_path / "alto.conf"
    conf.write_text("name = Alto\n\n# --- explicit files ---\n"
                    "# regular = Alto-Medium.otf\n", encoding="utf-8")

    fontconf.write_values(conf, {"gamma": "1.35"})
    fontconf.write_values(conf, {"weight": "0.2"})
    text = conf.read_text(encoding="utf-8")
    assert text.count(fontconf.WRITTEN_SECTION) == 1, text
    assert text.endswith(f"{fontconf.WRITTEN_SECTION}\ngamma = 1.35\n"
                         "weight = 0.2\n"), text


def test_a_key_set_to_none_is_removed(tmp_path):
    conf = tmp_path / "alto.conf"
    conf.write_text("name = Alto\ngamma = 1.35\nweight = 0.2\n",
                    encoding="utf-8")

    assert fontconf.write_values(conf, {"gamma": None, "kerning": None}) \
        == ["gamma"]
    assert conf.read_text(encoding="utf-8") == "name = Alto\nweight = 0.2\n"


def test_writing_what_is_already_there_touches_nothing(tmp_path):
    """Saving twice must not rewrite the file, or every save is a change to
    anything watching it -- and the second one would have nothing to say."""
    conf = tmp_path / "alto.conf"
    original = "name = Alto\ngamma      = 1.35\n"
    conf.write_text(original, encoding="utf-8")

    assert fontconf.write_values(conf, {"gamma": "1.35", "weight": None}) == []
    assert conf.read_text(encoding="utf-8") == original


def test_writing_leaves_no_half_written_file_behind(tmp_path):
    conf = tmp_path / "alto.conf"
    conf.write_text("name = Alto\n", encoding="utf-8")
    fontconf.write_values(conf, {"gamma": "1.35"})
    assert [p.name for p in tmp_path.iterdir()] == ["alto.conf"]


def test_a_config_that_does_not_exist_yet_is_created(tmp_path):
    """The family that all.conf covers without naming has no file of its own
    until something saves one."""
    conf = tmp_path / "ledger.conf"
    fontconf.write_values(conf, {"gamma": "1.35", "kerning": None})
    assert conf.read_text(encoding="utf-8") == \
        f"{fontconf.WRITTEN_SECTION}\ngamma = 1.35\n"


def test_a_tuning_round_trips_through_the_files_own_spelling(tmp_path):
    """tuning_values is the inverse of the parser, and the pair has to close:
    what a save writes must read back as the tuning that was saved."""
    from crossglyph.cpfont.tuning import LineHeight, Tuning

    tuning = Tuning(gamma=1.35, weight=0.2, slant=-0.1, hinting="light",
                    grayscale_hinting=True, mono=True, stem_darkening=True,
                    line_height=LineHeight.parse("1.15x"),
                    letter_spacing=0.25, word_spacing=-0.5, kerning=0.5,
                    ligatures=False, figures="proportional")
    values = {key: value
              for key, value in fontconf.tuning_values(tuning).items()
              if value is not None}
    assert fontconf.tuning_from(values, "test.conf") == tuning


def test_the_fallback_order_is_read_as_written(tmp_path):
    (tmp_path / "Alto-Regular.ttf").write_bytes(b"")
    conf = tmp_path / "alto.conf"
    conf.write_text("fallback_order = NotoSerif, bundled\n", encoding="utf-8")

    parsed = fontconf.parse_config(conf)

    assert parsed.fallback_order == "NotoSerif, bundled"


def test_the_fallback_order_defaults_to_empty(tmp_path):
    (tmp_path / "Alto-Regular.ttf").write_bytes(b"")
    conf = tmp_path / "alto.conf"
    conf.write_text("", encoding="utf-8")

    assert fontconf.parse_config(conf).fallback_order == ""


def test_all_conf_may_carry_the_fallback_order():
    """It names families and not one specific file, so it is shareable. That is
    the useful place for it: one order for the workspace."""
    assert "fallback_order" in fontbuild.DEFAULTS_KEYS


def test_an_empty_coverage_is_not_the_default_coverage(tmp_path):
    """Unticking every preset is a choice, and the narrowest one. Only an
    absent key means the default."""
    (tmp_path / "Probe-Regular.ttf").write_bytes(b"")

    absent = tmp_path / "absent.conf"
    absent.write_text("family = Probe\n", encoding="utf-8")
    empty = tmp_path / "empty.conf"
    empty.write_text("family = Probe\nintervals =\n", encoding="utf-8")

    assert fontconf.parse_config(absent).intervals == fontconf.DEFAULT_INTERVALS
    assert fontconf.parse_config(empty).intervals == ""

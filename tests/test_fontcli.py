"""crossglyph build, run the way the command line runs it.

Through `main`, because what is here is the difference between this surface and
the preview. Both build, but they do it down two separate paths, and each of
these was fixed on one of them and missed on the other.
"""
import fontsmith
import pytest

from crossglyph import fontcli, spacefont


@pytest.fixture
def workspace(tmp_path):
    """A workspace one synthetic face wide, with its config where the command
    line looks for it."""
    source = tmp_path / "fonts"
    (source / "conf").mkdir(parents=True)
    fontsmith.box_font(source / "Probe-Regular.ttf", range(0x41, 0x5B))
    (source / "conf" / "probe.conf").write_text(
        "sizes = 12\nintervals = base\nfallbacks = no\n", encoding="utf-8")
    return source


def build(workspace, out, jobs="1"):
    return fontcli.main(["--fonts", str(workspace), "-o", str(out),
                         "-j", jobs])


def test_the_stray_space_face_is_swept_from_the_command_line_too(workspace,
                                                                 tmp_path):
    """An install only ever built from a terminal is the one most likely to
    still carry the file, since it never reaches the preview's build."""
    out = tmp_path / "out"
    out.mkdir()
    (out / spacefont.STRAY_NAME).write_bytes(b"")
    assert build(workspace, out) == 0
    assert not (out / spacefont.STRAY_NAME).exists()


def test_missing_fallbacks_are_reported_rather_than_raised(workspace, tmp_path,
                                                           capsys):
    """A workspace without them is a thing to fix, and fetching them is the
    only thing that fixes it. Stopping builds nothing and leaves the family
    that would have been fine unbuilt."""
    (workspace / "conf" / "probe.conf").write_text(
        "sizes = 12\nintervals = base\nfallbacks = yes\n", encoding="utf-8")
    assert build(workspace, tmp_path / "out") == 0
    said = capsys.readouterr()
    assert "crossglyph fetch-fallbacks" in said.err
    assert (tmp_path / "out" / "Probe" / "Probe_12.cpfont").is_file(), \
        "and the font it could build is built"


def test_it_is_said_once_however_many_sizes_wanted_them(workspace, tmp_path,
                                                        capsys):
    """It is the workspace's failing and not each size's, so a family of four
    must not say it four times."""
    (workspace / "conf" / "probe.conf").write_text(
        "sizes = 12 14 16 18\nintervals = base\nfallbacks = yes\n",
        encoding="utf-8")
    assert build(workspace, tmp_path / "out", jobs="4") == 0
    assert capsys.readouterr().err.count("crossglyph fetch-fallbacks") == 1


def test_a_fractional_size_names_the_file_it_will_write(workspace, tmp_path,
                                                        capsys):
    """`--list` is what you read before copying a build to a card, and a size
    of 13.25 writes Probe_13.cpfont. Saying only 13.25 leaves the one number
    the device will show unstated."""
    (workspace / "conf" / "probe.conf").write_text(
        "sizes = 13.25 16\nintervals = base\nfallbacks = no\n",
        encoding="utf-8")
    fontcli.main(["--fonts", str(workspace), "-o", str(tmp_path / "out"),
                  "--list"])
    said = capsys.readouterr().out
    assert "13.25 (ships as 13)" in said
    # A whole size is its own label, and a parenthesis after every one of them
    # would be noise on the line this is meant to make readable.
    assert "16 (ships as" not in said


def test_the_up_to_date_line_names_it_as_well(workspace, tmp_path, capsys):
    """The third line asking the same question. A run that built nothing still
    says what is already on the card, and it is no more able to say which file
    that is than the other two were."""
    (workspace / "conf" / "probe.conf").write_text(
        "sizes = 13.25\nintervals = base\nfallbacks = no\n", encoding="utf-8")
    out = tmp_path / "out"
    assert build(workspace, out) == 0
    capsys.readouterr()
    assert build(workspace, out) == 0
    assert "up to date 13.25 (ships as 13)" in capsys.readouterr().out


def test_the_built_line_names_it_too(workspace, tmp_path, capsys):
    """The same question at the other end: which file did that just write."""
    (workspace / "conf" / "probe.conf").write_text(
        "sizes = 13.25\nintervals = base\nfallbacks = no\n", encoding="utf-8")
    out = tmp_path / "out"
    assert build(workspace, out) == 0
    assert "Probe 13.25 (ships as 13)" in capsys.readouterr().out
    assert (out / "Probe" / "Probe_13.cpfont").is_file()


# --- a tick that came to nothing -----------------------------------------

def _ticking_thai(workspace, *, face=False):
    """The workspace with thai ticked, and optionally a face that draws it
    sitting unused in the fallbacks folder."""
    (workspace / "conf" / "probe.conf").write_text(
        "sizes = 12\nintervals = thai\nfallbacks = no\n", encoding="utf-8")
    if face:
        faces = workspace / "fallbacks"
        faces.mkdir(exist_ok=True)
        fontsmith.box_font(faces / "NotoSans-Regular.ttf", [0x20, 0x41],
                           family="NotoSans")
        fontsmith.box_font(faces / "NotoSansThai-Regular.ttf", [0x20, 0x0E01],
                           family="NotoSansThai")
    return workspace


def test_a_range_nothing_draws_is_named_under_its_family(workspace, tmp_path,
                                                         capsys):
    assert build(_ticking_thai(workspace), tmp_path / "out") == 0
    assert "nothing in this build draws thai" in capsys.readouterr().err


def test_the_face_that_would_draw_it_is_named(workspace, tmp_path, capsys):
    assert build(_ticking_thai(workspace, face=True), tmp_path / "out") == 0
    said = capsys.readouterr().err
    assert "NotoSansThai-Regular.ttf" in said
    assert "fallbacks = yes" in said


def test_a_range_the_build_draws_is_not_mentioned(workspace, tmp_path, capsys):
    assert build(workspace, tmp_path / "out") == 0
    assert "nothing in this build draws" not in capsys.readouterr().err


def test_fail_on_warning_exits_one_and_still_writes_the_fonts(workspace,
                                                              tmp_path):
    out = tmp_path / "out"
    code = fontcli.main(["--fonts", str(_ticking_thai(workspace)),
                         "-o", str(out), "-j", "1", "--fail-on-warning"])
    assert code == 1
    assert list(out.rglob("*.cpfont")), \
        "a gate that skipped the writing would be a different feature"


def test_a_clean_build_under_the_flag_still_exits_zero(workspace, tmp_path):
    assert fontcli.main(["--fonts", str(workspace), "-o", str(tmp_path / "out"),
                         "-j", "1", "--fail-on-warning"]) == 0


def test_fetching_is_half_an_answer_while_the_set_is_switched_off(workspace,
                                                                  tmp_path,
                                                                  capsys):
    """The faces would land in a folder this build does not read, so a line
    that said only "fetch" sends somebody through a download to the same empty
    range."""
    _ticking_thai(workspace)
    assert build(workspace, tmp_path / "out") == 0
    said = capsys.readouterr().err
    assert "fetch-fallbacks" in said and "fallbacks = yes" in said


def test_with_the_set_switched_on_a_fetch_is_the_whole_answer(workspace,
                                                              tmp_path,
                                                              capsys):
    _ticking_thai(workspace)
    (workspace / "conf" / "probe.conf").write_text(
        "sizes = 12\nintervals = thai\nfallbacks = yes\n", encoding="utf-8")
    assert build(workspace, tmp_path / "out") == 0
    said = capsys.readouterr().err
    assert "fetch-fallbacks" in said
    assert "fallbacks = yes" not in said, "it already is"


def test_fail_on_warning_gates_on_the_folder_being_short(workspace, tmp_path):
    """That line is printed as a warning, and a flag that says it fails on any
    warning has to mean it."""
    (workspace / "conf" / "probe.conf").write_text(
        "sizes = 12\nintervals = base\nfallbacks = yes\n", encoding="utf-8")
    out = tmp_path / "out"
    assert fontcli.main(["--fonts", str(workspace), "-o", str(out),
                         "-j", "1"]) == 0
    assert fontcli.main(["--fonts", str(workspace), "-o", str(out), "-j", "1",
                         "--force", "--fail-on-warning"]) == 1
    assert list(out.rglob("*.cpfont"))

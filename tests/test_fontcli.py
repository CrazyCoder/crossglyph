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
    """A workspace without them is a thing to fix, not a crash. The sizes are
    rasterized in worker processes, so nothing catching this leaves the
    sentence that says what to do at the bottom of two tracebacks."""
    (workspace / "conf" / "probe.conf").write_text(
        "sizes = 12\nintervals = base\nfallbacks = yes\n", encoding="utf-8")
    assert build(workspace, tmp_path / "out") == 2
    said = capsys.readouterr().err
    assert "crossglyph fetch-fallbacks" in said


def test_it_is_said_once_however_many_sizes_wanted_them(workspace, tmp_path,
                                                        capsys):
    """It is the workspace's failing and not each size's, so a family of four
    must not say it four times."""
    (workspace / "conf" / "probe.conf").write_text(
        "sizes = 12 14 16 18\nintervals = base\nfallbacks = yes\n",
        encoding="utf-8")
    assert build(workspace, tmp_path / "out", jobs="4") == 2
    assert capsys.readouterr().err.count("crossglyph fetch-fallbacks") == 1

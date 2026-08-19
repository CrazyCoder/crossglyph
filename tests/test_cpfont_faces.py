"""Opening a face from a path FreeType cannot name itself."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: A user name, which the whole install then sits under. Any character
#: outside ASCII does it; this is the one people actually hit.
CYRILLIC = "Сергей"


def test_a_face_opens_from_a_path_freetype_cannot_encode(tmp_path):
    """freetype-py sends FT_New_Face the path as UTF-8 and FreeType opens it
    with the C library's `fopen`, which on Windows reads bytes in the ANSI
    code page. The two disagree over every character above ASCII, so the face
    fails with "cannot open resource" over a file Python reads happily."""
    from fontsmith import box_font

    from crossglyph.cpfont.faces import open_face

    folder = tmp_path / CYRILLIC
    folder.mkdir()
    path = box_font(folder / "Probe-Regular.ttf", [0x20, 0x41], family="Probe")
    assert open_face(path).family_name == b"Probe"


def test_an_ascii_path_opens_too(tmp_path):
    """The plain route, which is what almost every install takes."""
    from fontsmith import box_font

    from crossglyph.cpfont.faces import open_face

    path = box_font(tmp_path / "Probe-Regular.ttf", [0x20, 0x41],
                    family="Probe")
    assert open_face(path).family_name == b"Probe"


def test_nothing_else_opens_a_face_by_path():
    """The converter is a fork merged by hand, and upstream's own line is
    `freetype.Face(fontfile)`. A refresh that took it back would restore the
    bug without failing anything that reads a font, since every suite runs
    under an ASCII path unless it builds one of its own. The two tests above
    cover the helper; this covers everyone who has to reach it.
    """
    offenders = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src/crossglyph").rglob("*.py")
        if "freetype.Face(" in path.read_text(encoding="utf-8")
    }
    assert offenders == {"src/crossglyph/cpfont/faces.py"}, \
        "open a face with cpfont.faces.open_face, not freetype.Face"

"""One real rasterization, end to end. Slow, and skips without the clones."""
import shutil
import struct

import pytest

from crossglyph import fontbuild, fontconf


@pytest.fixture
def project(tmp_path, noto_or_skip):
    source = tmp_path / "src"
    source.mkdir()
    shutil.copy(noto_or_skip, source / "Probe-Regular.ttf")
    # ascii only, one small size: enough to exercise the whole pipeline without
    # spending a minute on Cyrillic and Greek coverage.
    (source / "probe.conf").write_text(
        "sizes = 12\nintervals = base\nfallbacks = no\n", encoding="utf-8")
    return fontconf.parse_config(source / "probe.conf").variants()[0]


def _build(variant, tmp_path, force=False):
    return fontbuild.build_variant(variant, tmp_path / "out", force=force)


def test_produces_a_version_4_cpfont(project, tmp_path):
    report = _build(project, tmp_path)
    assert report.built == [12]
    out = tmp_path / "out" / "Probe" / "Probe_12.cpfont"
    blob = out.read_bytes()
    assert blob[:8] == b"CPFONT\x00\x00"
    assert struct.unpack_from("<H", blob, 8)[0] == 4


def test_second_run_rebuilds_nothing(project, tmp_path):
    _build(project, tmp_path)
    report = _build(project, tmp_path)
    assert report.built == []
    assert report.skipped == [12]


def test_a_deleted_output_is_rebuilt(project, tmp_path):
    _build(project, tmp_path)
    (tmp_path / "out" / "Probe" / "Probe_12.cpfont").unlink()
    assert _build(project, tmp_path).built == [12]


def test_changing_the_font_rebuilds(project, tmp_path, noto_or_skip):
    _build(project, tmp_path)
    # Same bytes, new mtime: content hashing must see no reason to rebuild.
    shutil.copy(noto_or_skip, project.config.styles["regular"])
    assert _build(project, tmp_path).built == []


def test_the_pool_really_builds_in_other_processes(tmp_path):
    """The one thing only a real pool can show: a Job survives the trip to a
    spawned interpreter and back. Everything else about a build is tested
    against a stubbed run_jobs, which would never notice a Config that had
    stopped pickling."""
    import fontsmith

    source = tmp_path / "src"
    source.mkdir()
    fontsmith.box_font(source / "Probe-Regular.ttf", range(0x41, 0x5B))
    (source / "probe.conf").write_text(
        "sizes = 10 12\nintervals = base\nfallbacks = no\n", encoding="utf-8")
    variant = fontconf.parse_config(source / "probe.conf").variants()[0]
    out = tmp_path / "out"
    jobs = fontbuild.plan_variant(variant, out)[1]
    assert len(jobs) == 2

    landed = list(fontbuild.run_jobs(jobs, out, workers=2))
    assert sorted(one.job.size for one in landed) == [10, 12]
    assert [one.error for one in landed] == [None, None], landed
    assert all(one.built.bytes > 0 for one in landed)
    for size in (10, 12):
        assert (out / "Probe" / f"Probe_{size}.cpfont").is_file()


# --- variable fonts -------------------------------------------------------
# These build a synthetic variable face rather than a real one, so they run
# without the clones the fixture above needs.

def _variable_project(tmp_path, extra=""):
    import fontsmith

    source = tmp_path / "src"
    source.mkdir(exist_ok=True)
    fontsmith.variable_box_font(source / "Probe[wght].ttf", range(0x41, 0x5B))
    (source / "probe.conf").write_text(
        "sizes = 12\nintervals = base\nfallbacks = no\nspace_glyphs = no\n" + extra,
        encoding="utf-8")
    return fontconf.parse_config(source / "probe.conf").variants()[0]


def test_one_variable_file_builds_the_bold_slot_too(tmp_path):
    """The family ships one file and the .cpfont carries two styles: the second
    is the same outlines at the weight the font calls Bold."""
    variant = _variable_project(tmp_path)
    assert sorted(variant.config.styles) == ["bold", "regular"]
    _build(variant, tmp_path)
    blob = (tmp_path / "out" / "Probe" / "Probe_12.cpfont").read_bytes()
    assert struct.unpack_from("<I", blob, 12)[0] == 2


def test_the_slots_are_rasterized_at_their_own_weights(tmp_path):
    """The whole point: the coordinates reach FreeType. Built with the bold slot
    pinned back to the regular's weight, the file is a different one -- if the
    coordinates were ignored, both builds would be the same bytes."""
    at_bold = _variable_project(tmp_path)
    _build(at_bold, tmp_path)
    bold = (tmp_path / "out" / "Probe" / "Probe_12.cpfont").read_bytes()

    pinned = _variable_project(tmp_path, "bold = Probe[wght].ttf@wght=400\n")
    _build(pinned, tmp_path)
    light = (tmp_path / "out" / "Probe" / "Probe_12.cpfont").read_bytes()
    assert bold != light


def test_moving_a_coordinate_restales_the_size(tmp_path):
    """The file's hash cannot say which face a slot is when both slots share
    it, so the coordinates are in the stamp."""
    from crossglyph import fontstamp

    variant = _variable_project(tmp_path)
    _build(variant, tmp_path)
    assert _build(variant, tmp_path).built == []

    moved = _variable_project(tmp_path, "bold = Probe[wght].ttf@wght=900\n")
    assert fontstamp.stale_sizes(moved, tmp_path / "out" / "Probe") == [12]

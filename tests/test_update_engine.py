"""Where the render core is built from, and how that checkout is updated.

The engine comes from a firmware checkout kept for it and nothing else, so
that a working checkout can be on any branch without moving what the preview
draws. Two files have to agree about which directory that is: build.sh, which
compiles from it, and stamp.py, which judges the module against it.
"""
import importlib.util
import json
import pathlib
import re

import pytest

from crossglyph.render import stamp

REPO = pathlib.Path(__file__).resolve().parents[1]
BUILD = REPO / "src" / "render" / "build.sh"

_spec = importlib.util.spec_from_file_location(
    "update_engine", REPO / "tools" / "update-engine.py")
assert _spec and _spec.loader
update_engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(update_engine)


def build_candidates() -> list[str]:
    """The directory names build.sh tries, in its own order."""
    text = BUILD.read_text(encoding="utf-8")
    match = re.search(r"for candidate in ([^\n;]+); do", text)
    assert match, "build.sh no longer resolves $FW from a candidate list"
    return match.group(1).split()


def test_the_build_and_the_staleness_check_look_in_the_same_places():
    """One decides what the module is built from and the other decides whether
    it is out of date. Disagreeing makes both answers wrong."""
    assert build_candidates() == list(stamp.ENGINE_DIRS)


def test_the_engine_checkout_is_preferred_over_a_working_one(tmp_path,
                                                             monkeypatch):
    monkeypatch.delenv("CROSSGLYPH_FIRMWARE", raising=False)
    monkeypatch.setattr(stamp, "ROOT", tmp_path / "crossglyph")
    for name in stamp.ENGINE_DIRS:
        (tmp_path / name).mkdir()
    assert stamp._firmware() == tmp_path / stamp.ENGINE_DIRS[0]


def test_a_lone_working_checkout_still_answers(tmp_path, monkeypatch):
    """One checkout is the whole setup for a contributor, and for CI."""
    monkeypatch.delenv("CROSSGLYPH_FIRMWARE", raising=False)
    monkeypatch.setattr(stamp, "ROOT", tmp_path / "crossglyph")
    (tmp_path / "crosspoint-reader").mkdir()
    assert stamp._firmware() == tmp_path / "crosspoint-reader"


def test_naming_a_firmware_beats_both(tmp_path, monkeypatch):
    """Which is how a fork is built from, without anything knowing of forks."""
    monkeypatch.setenv("CROSSGLYPH_FIRMWARE", str(tmp_path / "elsewhere"))
    monkeypatch.setattr(stamp, "ROOT", tmp_path / "crossglyph")
    (tmp_path / stamp.ENGINE_DIRS[0]).mkdir()
    assert stamp._firmware() == tmp_path / "elsewhere"


def test_with_nothing_beside_it_the_last_name_is_what_is_reported(
        tmp_path, monkeypatch):
    """There is no checkout, so nothing is compared. The path is only there
    for the message that says which one was looked for."""
    monkeypatch.delenv("CROSSGLYPH_FIRMWARE", raising=False)
    monkeypatch.setattr(stamp, "ROOT", tmp_path / "crossglyph")
    assert stamp._firmware() == tmp_path / stamp.ENGINE_DIRS[-1]


# --- what the stamp says ---------------------------------------------------


@pytest.fixture
def stamped(tmp_path, monkeypatch):
    """A stamp file this test owns, in place of the committed one."""
    path = tmp_path / "render.built-from.json"
    monkeypatch.setattr(stamp, "STAMP_PATH", path)
    return path


def test_the_module_says_which_firmware_and_which_branch(stamped):
    stamped.write_text(json.dumps({"firmware": "a" * 40,
                                   "source": "crosspoint-reader",
                                   "ref": "develop"}), encoding="utf-8")
    assert stamp.describe() == f"crosspoint-reader develop {'a' * 12}"


def test_a_stamp_from_before_the_source_was_recorded_still_reads(stamped):
    """The commit is the field that has always been there."""
    stamped.write_text(json.dumps({"firmware": "b" * 40}), encoding="utf-8")
    assert stamp.describe() == f"{stamp.FIRMWARE.name} {'b' * 12}"


def test_no_stamp_at_all_says_so(stamped):
    assert stamp.describe() == "sources it kept no record of"


def test_the_build_records_the_three_fields_the_stamp_reads():
    """A grep, because running the build needs emsdk and a firmware clone."""
    text = BUILD.read_text(encoding="utf-8")
    written = re.search(r'printf \'(\{.*?\})\\n\'', text, re.S)
    assert written, "build.sh no longer writes the stamp with printf"
    for field in ("firmware", "source", "ref"):
        assert f'"{field}"' in written.group(1)


# --- the update script -----------------------------------------------------


def test_the_report_reads_what_the_build_compiles_from_the_build():
    """A source added to build.sh has to reach the report, so the list is
    parsed out of the script rather than repeated in it."""
    paths = update_engine.compiled_paths()
    for source in ("lib/EpdFont/EpdFont.cpp",
                   "lib/GfxRenderer/GfxRenderer.cpp",
                   "lib/Epub/Epub/ParsedText.cpp",
                   "lib/uzlib/src/tinflate.c"):
        assert source in paths
    # The include directories too: a header change is a change to what the
    # module compiles, even when no .cpp of ours moved.
    assert "lib/Memory" in paths and "lib/Serialization" in paths
    assert not any(path.startswith("$") for path in paths)


def test_the_script_tracks_one_branch_of_one_repository():
    assert update_engine.BRANCH == "develop"
    assert update_engine.DIRECTORY.name == stamp.ENGINE_DIRS[0]
    assert update_engine.URL.endswith("crosspoint-reader.git")


def test_the_render_tests_gate_on_a_missing_core_not_a_stale_one():
    """A core built from older firmware draws what that firmware drew, and is
    the one a release ships. Skipping on staleness dropped a hundred tests the
    moment upstream moved, and said so only in a count nobody reads."""
    for name in ("test_preview.py", "test_preview_server.py",
                 "test_daemon.py"):
        text = (REPO / "tests" / name).read_text(encoding="utf-8")
        assert "is_stale" not in text, f"{name} gates on staleness"
    # Except where staleness itself is what is under test.
    core = (REPO / "tests" / "test_render_core.py").read_text(encoding="utf-8")
    for line in core.splitlines():
        if "is_stale" in line:
            assert line.lstrip().startswith(("assert", "#", '"')), line

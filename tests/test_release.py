"""Where each tracked file lands in the release tree.

The release is the same artifact for a first install and for an update: the
updater takes the versions/<v> subtree and ignores the rest. What belongs to
the install rather than to any one version has to stay outside it, or an
update would replace the launcher and the workspace along with the code.
"""
import importlib.util
import pathlib
import subprocess
import zipfile

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "make_release", REPO / "tools" / "make-release.py")
assert _spec and _spec.loader
make_release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_release)


@pytest.mark.parametrize("path", [
    "crossglyph.cmd", "crossglyph.sh",
    "fonts/README.md", "fonts/conf/all.conf",
])
def test_what_outlives_a_version_stays_at_the_root(path):
    assert make_release.release_path(path, "0.2.0") == path


@pytest.mark.parametrize("path", [
    "pyproject.toml", "uv.lock", "LICENSE", "README.md",
    "src/crossglyph/cli.py", "src/crossglyph/render/render.wasm",
    "docs/fonts.md",
])
def test_everything_else_is_the_version(path):
    assert make_release.release_path(path, "0.2.0") == f"versions/0.2.0/{path}"


def test_the_version_directory_carries_its_own_uv():
    """The shim execs <version>/tools/uv.cmd, so a release that left uv at the
    root would go on running the old one after every update."""
    assert make_release.release_path("tools/uv.cmd", "0.2.0") \
        == "versions/0.2.0/tools/uv.cmd"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """A real release archive, packed the way make-release.py packs one.

    Built here rather than by running the script, which refuses on a dirty
    tree: the archive comes from HEAD either way, so what it says about the
    repack holds while the working tree is mid-edit. That matters because
    these are the assertions that catch a release nobody can run, and a test
    that skips through every working day is one that catches it after release.
    """
    version = make_release.version()
    name = f"crossglyph-{version}"
    work = tmp_path_factory.mktemp("release")
    flat, out = work / "flat.zip", work / f"{name}.zip"
    subprocess.run(["git", "-C", str(REPO), "archive", "--format=zip",
                    f"--prefix={name}/", "-o", str(flat), "HEAD"], check=True)
    with zipfile.ZipFile(flat) as source:
        make_release.repack(source, out, name, version)
    return version, name, out


@pytest.fixture(scope="module")
def members(built):
    """Every member of the archive, keyed by its path inside the release."""
    _, name, path = built
    with zipfile.ZipFile(path) as archive:
        return {i.filename[len(name) + 1:]: i for i in archive.infolist()}


def test_the_archive_holds_both_halves_of_the_release(built, members):
    version, name, path = built
    with zipfile.ZipFile(path) as archive:
        assert archive.read(f"{name}/current").decode().strip() == version
    assert "crossglyph.cmd" in members and "crossglyph.sh" in members
    assert "fonts/conf/all.conf" in members
    assert f"versions/{version}/pyproject.toml" in members
    assert f"versions/{version}/src/crossglyph/cli.py" in members
    assert f"versions/{version}/tools/uv.cmd" in members


def test_neither_half_leaks_into_the_other(built, members):
    """An update replaces versions/<v> wholesale. Anything of the install's
    that ended up in there would be replaced with it."""
    version, _, _ = built
    assert "src/crossglyph/cli.py" not in members
    assert f"versions/{version}/crossglyph.cmd" not in members
    assert f"versions/{version}/fonts/conf/all.conf" not in members


def test_the_executables_extract_executable(built, members):
    """crossglyph.sh is run directly and uv.cmd is exec'd by it.

    create_system as well as the bits, and that is the half easy to lose: a
    POSIX unzip applies a mode only when the entry says Unix, so an archive
    that kept 0755 and dropped that field extracts unrunnable while every
    assertion about the bits still passes. That shipped once.
    """
    version, _, _ = built
    for member in ("crossglyph.sh", f"versions/{version}/tools/uv.cmd"):
        info = members[member]
        assert (info.external_attr >> 16) & 0o111, \
            f"not executable after the repack: {member}"
        assert info.create_system == make_release.UNIX, \
            f"executable but not marked Unix, so the bit is ignored: {member}"


def test_no_entry_is_left_without_a_mode(members):
    """zipfile fills a blank one in as 0600: readable by whoever unpacked the
    release and by nobody else."""
    blank = sorted(path for path, info in members.items()
                   if make_release.unusable_mode(info))
    assert not blank, f"{len(blank)} entries with no usable mode: {blank[:5]}"


def test_the_polyglot_wrapper_keeps_its_mixed_line_endings(built):
    """A repack that went through text mode would quietly normalise them, and
    uniform endings break one of the two interpreters that read this file."""
    version, name, path = built
    with zipfile.ZipFile(path) as archive:
        uv = archive.read(f"{name}/versions/{version}/tools/uv.cmd")
    assert not make_release.check_polyglot(uv, "tools/uv.cmd")


# --- the manifest ---------------------------------------------------------


def test_the_manifest_describes_the_release():
    said = make_release.manifest("0.2.0", "b" * 64, 1656832,
                                 "CrazyCoder/crossglyph")
    assert said["version"] == "0.2.0"
    assert said["url"].startswith("https://github.com/CrazyCoder/crossglyph/")
    assert said["url"].endswith("/v0.2.0/crossglyph-0.2.0.zip")
    assert said["notes_url"].endswith("/tag/v0.2.0")
    assert said["sha256"] == "b" * 64
    assert said["size"] == 1656832
    assert said["signature"] is None


def test_the_manifest_is_what_the_client_accepts():
    """The two halves are written apart and have to agree. Parsing the real
    thing with the real parser is the only assertion that says they do."""
    import json

    from crossglyph import updates

    said = make_release.manifest("0.2.0", "c" * 64, 10, "CrazyCoder/crossglyph")
    parsed = updates.parse(json.dumps(said).encode("utf-8"))
    assert parsed.version == "0.2.0"
    assert parsed.launcher_changed is False


def test_a_release_writes_the_manifest_beside_the_zip(built, tmp_path):
    """Whatever the workflow uploads has to come from the run that produced
    the zip, or the hash in it describes a different file."""
    import hashlib
    import json

    version, _, path = built
    out = tmp_path / "latest.json"
    make_release.write_manifest(path, version, out, "CrazyCoder/crossglyph")

    said = json.loads(out.read_text(encoding="utf-8"))
    assert said["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert said["size"] == path.stat().st_size


def test_the_users_own_files_stay_at_the_root():
    """update.conf is theirs, like fonts/. An update replaces versions/<v>
    wholesale, so anything of theirs in there would go with it."""
    assert make_release.release_path("update.conf", "0.2.0") == "update.conf"


def test_the_release_carries_no_state_of_its_own(members):
    """A state file in a release would tell a fresh install it had already
    checked, on the clock of whoever built it."""
    assert not [path for path in members if "update-state" in path]

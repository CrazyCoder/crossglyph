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


def test_the_built_archive_has_the_release_shape():
    """Runs the real packer, so the properties that only exist in the zip --
    the layout, the executable bits, the polyglot bytes -- are asserted on the
    bytes somebody would download rather than on the plan for them."""
    if subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"],
                      capture_output=True, text=True).stdout.strip():
        pytest.skip("the archive is built from HEAD; commit first")

    done = subprocess.run(["uv", "run", "tools/make-release.py"], cwd=REPO,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr

    version = make_release.version()
    name = f"crossglyph-{version}"
    with zipfile.ZipFile(REPO / "dist" / f"{name}.zip") as archive:
        members = {i.filename[len(name) + 1:]: i for i in archive.infolist()}

        assert archive.read(f"{name}/current").decode().strip() == version
        assert "crossglyph.cmd" in members and "crossglyph.sh" in members
        assert "fonts/conf/all.conf" in members
        assert f"versions/{version}/pyproject.toml" in members
        assert f"versions/{version}/src/crossglyph/cli.py" in members
        assert f"versions/{version}/tools/uv.cmd" in members

        # Nothing of the version's outside its directory, and nothing of the
        # install's inside it.
        assert "src/crossglyph/cli.py" not in members
        assert f"versions/{version}/crossglyph.cmd" not in members
        assert f"versions/{version}/fonts/conf/all.conf" not in members

        # The bit survives the repack. crossglyph.sh is executed directly and
        # uv.cmd is exec'd by it, so both matter.
        for path in ("crossglyph.sh", f"versions/{version}/tools/uv.cmd"):
            assert (members[path].external_attr >> 16) & 0o111, \
                f"not executable after the repack: {path}"

        # And so do the mixed line endings, which a repack that went through
        # text mode would quietly normalise.
        uv = archive.read(f"{name}/versions/{version}/tools/uv.cmd")
        assert not make_release.check_polyglot(uv, "tools/uv.cmd")

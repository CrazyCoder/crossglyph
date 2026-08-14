"""Installing a release: fetch, verify, stage, swap, and go back again.

Everything here runs against a zip built in the test, through the one network
seam, so nothing reaches the internet and the whole path is exercised rather
than mocked out in the middle.
"""
import hashlib
import io
import json
import os
import pathlib
import zipfile

import pytest

from crossglyph import install, layout, updates, upgrade

NEW = "0.2.0"
OLD = "0.1.0"

#: What a release carries at the root of the archive, above versions/.
PREFIX = f"crossglyph-{NEW}"

TEMPLATE = b"# out = \n"


def make_zip(version=NEW, *, template=TEMPLATE, escape=False,
             executable=False) -> bytes:
    """A release zip shaped the way tools/make-release.py builds one."""
    body = io.BytesIO()
    with zipfile.ZipFile(body, "w") as archive:
        inside = f"{PREFIX}/versions/{version}"
        archive.writestr(f"{PREFIX}/crossglyph.sh", "#!/bin/sh\n")
        archive.writestr(f"{PREFIX}/current", f"{version}\n")
        archive.writestr(f"{PREFIX}/fonts/conf/all.conf", template)
        archive.writestr(f"{inside}/pyproject.toml", f'version = "{version}"\n')
        archive.writestr(f"{inside}/src/crossglyph/cli.py", "print()\n")
        archive.writestr(f"{inside}/fonts/conf/all.conf", template)
        if executable:
            info = zipfile.ZipInfo(f"{inside}/tools/uv.cmd")
            info.create_system = upgrade.UNIX
            info.external_attr = 0o100755 << 16
            archive.writestr(info, ":<<\"::CMDLITERAL\"\n")
        if escape:
            archive.writestr(f"{inside}/../../../escaped.txt", "no\n")
    return body.getvalue()


def manifest(raw: bytes, version=NEW, **over) -> bytes:
    body = {
        "version": version,
        "url": f"https://example.invalid/crossglyph-{version}.zip",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size": len(raw),
        "notes_url": f"https://example.invalid/releases/tag/v{version}",
        "launcher_changed": False,
    }
    return json.dumps({**body, **over}).encode("utf-8")


class Served:
    """The manifest and the zip, over the one seam the package opens."""

    def __init__(self, raw, said):
        self.raw, self.said, self.opened = raw, said, []

    def fetch(self, url, timeout=2.0):
        self.opened.append(url)
        return self.said

    def open_stream(self, url, timeout=2.0):
        self.opened.append(url)
        return io.BytesIO(self.raw)


@pytest.fixture
def served(monkeypatch):
    raw = make_zip()
    serving = Served(raw, manifest(raw))
    monkeypatch.setattr(updates, "fetch", serving.fetch)
    monkeypatch.setattr(updates, "open_stream", serving.open_stream)
    monkeypatch.setattr(upgrade.version, "installed", lambda: OLD)
    return serving


@pytest.fixture
def release(tmp_path):
    """An unpacked release sitting on the old version."""
    (tmp_path / "versions" / OLD / "fonts" / "conf").mkdir(parents=True)
    (tmp_path / "versions" / OLD / "fonts" / "conf" / "all.conf").write_bytes(
        TEMPLATE)
    (tmp_path / "fonts" / "conf").mkdir(parents=True)
    (tmp_path / "fonts" / "conf" / "all.conf").write_bytes(TEMPLATE)
    layout.write_current(tmp_path, OLD)
    return tmp_path


def run(root, kind=install.ZIP):
    return list(upgrade.steps(root, kind))


def last(steps):
    return steps[-1]


# --- refusing, before anything is downloaded ------------------------------


@pytest.mark.parametrize("kind", [install.CONTAINER, install.CHECKOUT,
                                  install.UNKNOWN])
def test_a_kind_that_does_not_own_its_files_refuses_first(release, served,
                                                          kind):
    """Nothing is fetched: in a container the download would be written to a
    filesystem that goes away on restart, and say nothing at the time."""
    said = last(run(release, kind))
    assert said["event"] == "error"
    assert install.instruction(kind) in said["error"]
    assert served.opened == []


def test_nothing_newer_is_not_an_error(release, served, monkeypatch):
    monkeypatch.setattr(upgrade.version, "installed", lambda: NEW)
    assert last(run(release))["event"] == "current"
    assert layout.current(release) == OLD


def test_an_unreachable_server_says_so(release, monkeypatch):
    def boom(url, timeout=2.0):
        raise OSError("no route to host")

    monkeypatch.setattr(updates, "fetch", boom)
    monkeypatch.setattr(upgrade.version, "installed", lambda: OLD)
    assert "could not reach" in last(run(release))["error"]


def test_a_release_that_changes_the_launcher_refuses(release, served,
                                                     monkeypatch):
    """cmd.exe is holding the launcher open at the line that started this."""
    monkeypatch.setattr(
        updates, "fetch",
        lambda url, timeout=2.0: manifest(served.raw, launcher_changed=True))
    said = last(run(release))
    assert said["event"] == "error"
    assert "launcher" in said["error"]
    assert layout.current(release) == OLD


# --- the whole path -------------------------------------------------------


def test_a_release_is_installed_and_becomes_current(release, served):
    said = last(run(release))
    assert said["event"] == "done", said
    assert said["version"] == NEW
    assert layout.current(release) == NEW
    assert (release / "versions" / NEW / "pyproject.toml").is_file()


def test_only_the_version_subtree_is_taken(release, served):
    """One artifact serves a first install and an update, so most of what is
    in it belongs to a root that already exists."""
    run(release)
    landed = release / "versions" / NEW
    assert not (landed / "crossglyph.sh").exists()
    assert not (landed / "versions").exists()


def test_the_previous_version_is_left_where_it_is(release, served):
    """Pruning is a launch-time job. The version being replaced is the one
    running this, and deleting its files now is how Windows locks one."""
    run(release)
    assert (release / "versions" / OLD).is_dir()


def test_the_download_counts_its_way_up(release, served):
    counted = [step for step in run(release) if step["event"] == "step"]
    assert counted
    assert counted[-1]["got"] == counted[-1]["bytes"]


def test_the_plan_says_what_is_coming(release, served):
    plan = next(step for step in run(release) if step["event"] == "plan")
    assert plan["version"] == NEW
    assert plan["bytes"] > 0
    assert plan["converting"] is False


def test_nothing_is_left_in_versions_afterwards(release, served):
    run(release)
    assert sorted(path.name for path in (release / "versions").iterdir()) == \
        [OLD, NEW]


# --- when it goes wrong ---------------------------------------------------


def test_a_hash_that_does_not_match_installs_nothing(release, served,
                                                     monkeypatch):
    monkeypatch.setattr(updates, "fetch",
                        lambda url, timeout=2.0: manifest(served.raw,
                                                          sha256="b" * 64))
    said = last(run(release))
    assert said["event"] == "error"
    assert "hash" in said["error"]
    assert layout.current(release) == OLD
    assert not (release / "versions" / NEW).exists()
    assert list((release / "versions").iterdir()) == [release / "versions" / OLD]


def test_a_zip_that_names_a_path_outside_itself_is_refused(release, served,
                                                           monkeypatch):
    raw = make_zip(escape=True)
    monkeypatch.setattr(updates, "open_stream",
                        lambda url, timeout=2.0: io.BytesIO(raw))
    monkeypatch.setattr(updates, "fetch",
                        lambda url, timeout=2.0: manifest(raw))
    assert "outside itself" in last(run(release))["error"]
    assert not (release.parent / "escaped.txt").exists()


def test_a_zip_with_no_version_directory_is_refused(release, served,
                                                    monkeypatch):
    raw = make_zip(version="0.9.9")          # not the version it claims to be
    monkeypatch.setattr(updates, "open_stream",
                        lambda url, timeout=2.0: io.BytesIO(raw))
    monkeypatch.setattr(updates, "fetch",
                        lambda url, timeout=2.0: manifest(raw))
    assert "carries no versions" in last(run(release))["error"]
    assert layout.current(release) == OLD


def test_an_interrupted_extract_leaves_nothing_launchable(release, served,
                                                          monkeypatch):
    def half(*args, **kwargs):
        raise OSError("the disk filled up")

    monkeypatch.setattr(upgrade, "extract", half)
    assert last(run(release))["event"] == "error"
    assert layout.current(release) == OLD
    assert not (release / "versions" / NEW).exists()
    assert not any(path.name.startswith(layout.INCOMING_PREFIX)
                   for path in (release / "versions").iterdir())


@pytest.mark.skipif(os.name == "nt", reason="no executable bit on Windows")
def test_an_executable_member_lands_executable(tmp_path):
    """tools/uv.cmd is what the launcher execs. Python's own extract drops the
    mode, and the failure is at the next launch rather than here."""
    archive = tmp_path / "release.zip"
    archive.write_bytes(make_zip(executable=True))
    upgrade.extract(archive, tmp_path / "out", NEW)
    assert os.access(tmp_path / "out" / "tools" / "uv.cmd", os.X_OK)


# --- the workspace --------------------------------------------------------


def test_a_template_nobody_has_is_written(tmp_path):
    incoming = tmp_path / "incoming"
    (incoming / "fonts" / "conf").mkdir(parents=True)
    (incoming / "fonts" / "conf" / "all.conf").write_bytes(b"new\n")
    assert upgrade.seed_workspace(tmp_path, incoming, None) == []
    assert (tmp_path / "fonts" / "conf" / "all.conf").read_bytes() == b"new\n"


def test_a_template_nobody_edited_is_replaced(release, served):
    """Identical to what this version shipped, so it is ours to update."""
    shipped = release / "versions" / OLD / "fonts" / "conf" / "all.conf"
    shipped.write_bytes(b"old\n")
    (release / "fonts" / "conf" / "all.conf").write_bytes(b"old\n")
    assert last(run(release))["kept"] == []
    assert (release / "fonts" / "conf" / "all.conf").read_bytes() == TEMPLATE


def test_a_template_somebody_edited_is_kept(release, served):
    (release / "fonts" / "conf" / "all.conf").write_bytes(b"out = D:/mine\n")
    said = last(run(release))
    assert said["kept"] == ["conf/all.conf"]
    assert (release / "fonts" / "conf" / "all.conf").read_bytes() == \
        b"out = D:/mine\n"
    assert (release / "fonts" / "conf" / "all.conf.new").read_bytes() == \
        TEMPLATE


def test_a_workspace_file_that_did_not_change_is_left_alone(release, served):
    """Identical to what is arriving. Writing it would be a no-op with a
    timestamp on it."""
    assert last(run(release))["kept"] == []


def test_nothing_else_in_the_workspace_is_touched(release, served):
    (release / "fonts" / "Alto.ttf").write_bytes(b"a font")
    run(release)
    assert (release / "fonts" / "Alto.ttf").read_bytes() == b"a font"


# --- converting a source download -----------------------------------------


@pytest.fixture
def source(tmp_path):
    """What Code > Download ZIP gives: the tree, with no versions/, no
    current, and fonts/ already beside src/."""
    (tmp_path / "src" / "crossglyph").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "crossglyph.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "fonts" / "conf").mkdir(parents=True)
    (tmp_path / "fonts" / "conf" / "all.conf").write_bytes(TEMPLATE)
    return tmp_path


def test_a_source_download_gains_a_version_and_a_current(source, served):
    said = last(run(source, install.SOURCE))
    assert said["event"] == "done"
    assert said["converting"] is True
    assert layout.current(source) == NEW
    assert (source / "versions" / NEW / "pyproject.toml").is_file()


def test_the_old_flat_tree_is_left_alone(source, served):
    """It is inert once current exists, and deleting files inside a folder
    somebody unpacked themselves is a larger act than adding two."""
    run(source, install.SOURCE)
    assert (source / "pyproject.toml").is_file()
    assert (source / "src" / "crossglyph").is_dir()
    assert (source / "crossglyph.sh").read_text(encoding="utf-8") == "#!/bin/sh\n"


def test_a_converted_tree_then_detects_as_a_release(source, served):
    run(source, install.SOURCE)
    assert install.detect(source, {}, pathlib.Path("/nonexistent")) == \
        install.ZIP


def test_a_source_download_on_the_newest_version_converts_nothing(
        source, served, monkeypatch):
    """Gated on the same comparison as everything else. A snapshot taken from
    master after the last tag still reports that tag, and installing it over
    the top would be a downgrade."""
    monkeypatch.setattr(upgrade.version, "installed", lambda: NEW)
    assert last(run(source, install.SOURCE))["event"] == "current"
    assert not (source / "versions").exists()
    assert layout.current(source) is None


# --- rolling back ---------------------------------------------------------


def test_rollback_goes_to_the_version_below(release):
    (release / "versions" / NEW).mkdir()
    layout.write_current(release, NEW)
    assert upgrade.rollback(release) == OLD
    assert layout.current(release) == OLD


def test_rollback_records_what_it_rejected(release):
    (release / "versions" / NEW).mkdir()
    layout.write_current(release, NEW)
    upgrade.rollback(release)
    assert updates.load_state(release).rejected == NEW


def test_the_check_stays_quiet_about_a_rejected_version(release, monkeypatch):
    """Otherwise the next check offers the release somebody just escaped, and
    goes on offering it every day."""
    monkeypatch.setattr(updates.version, "installed", lambda: OLD)
    state = updates.State(1000.0, NEW, None, rejected=NEW)
    assert updates.available(state) is None


def test_but_speaks_up_for_something_newer_than_it(release, monkeypatch):
    monkeypatch.setattr(updates.version, "installed", lambda: OLD)
    state = updates.State(1000.0, "0.3.0", None, rejected=NEW)
    assert updates.available(state) == "0.3.0"


def test_a_rejection_survives_the_next_check(release, served):
    updates.save_state(release, updates.State(0.0, None, None, rejected=NEW))
    updates.check(release, force=True, now=1000.0, environ={})
    assert updates.load_state(release).rejected == NEW


def test_there_is_nothing_to_roll_back_to_on_a_first_release(release):
    with pytest.raises(upgrade.Refused):
        upgrade.rollback(release)


def test_a_tree_with_no_current_cannot_roll_back(tmp_path):
    with pytest.raises(upgrade.Refused):
        upgrade.rollback(tmp_path)

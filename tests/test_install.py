"""Which kind of install this is, which decides how it can be updated."""
import pathlib

import pytest

from crossglyph import install


def _release(root: pathlib.Path) -> pathlib.Path:
    (root / "versions" / "0.1.0").mkdir(parents=True)
    (root / "current").write_text("0.1.0\n", encoding="utf-8")
    return root


def _tree(root: pathlib.Path) -> pathlib.Path:
    (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    return root


#: A path that is never there, so detection cannot see the real one.
NO_DOCKER = pathlib.Path("/nonexistent/.dockerenv")


def test_a_release_layout_is_the_zip_kind(tmp_path):
    assert install.detect(_release(tmp_path), {}, NO_DOCKER) == install.ZIP


def test_a_clone_is_a_checkout(tmp_path):
    (_tree(tmp_path) / ".git").mkdir()
    assert install.detect(tmp_path, {}, NO_DOCKER) == install.CHECKOUT


def test_the_same_tree_without_git_is_a_source_download(tmp_path):
    """What the GitHub Code button gives you: the repo, with no versions/ and
    no .git. It updates by being converted into a release install."""
    assert install.detect(_tree(tmp_path), {}, NO_DOCKER) == install.SOURCE


def test_a_dockerenv_marker_makes_it_a_container(tmp_path):
    marker = tmp_path / "dockerenv"
    marker.touch()
    assert install.detect(_tree(tmp_path), {}, marker) == install.CONTAINER


def test_a_container_wins_over_a_release_layout(tmp_path):
    """An image built by unpacking a release has the layout, and self-updating
    inside one writes to a filesystem that goes away on restart. Being in a
    container is a fact about where this runs; a directory cannot outvote it."""
    marker = tmp_path / "dockerenv"
    marker.touch()
    assert install.detect(_release(tmp_path), {}, marker) == install.CONTAINER


def test_an_empty_directory_is_unknown(tmp_path):
    assert install.detect(tmp_path, {}, NO_DOCKER) == install.UNKNOWN


def test_the_environment_variable_wins_over_detection(tmp_path):
    """The image sets it. Detecting a container from the inside is unreliable
    across runtimes, so what the packager says is taken over what we sniff."""
    env = {"CROSSGLYPH_INSTALL_KIND": install.CONTAINER}
    assert install.detect(_release(tmp_path), env, NO_DOCKER) == install.CONTAINER


def test_an_unrecognised_kind_in_the_environment_is_ignored(tmp_path):
    """A typo should not silently disable updating."""
    env = {"CROSSGLYPH_INSTALL_KIND": "zipp"}
    assert install.detect(_release(tmp_path), env, NO_DOCKER) == install.ZIP


def test_a_release_layout_that_cannot_be_written_is_unknown(tmp_path,
                                                            monkeypatch):
    """Not a special failure: an install nobody can write to simply is not a
    kind that can replace its own files."""
    monkeypatch.setattr(install.os, "access", lambda path, mode: False)
    assert install.detect(_release(tmp_path), {}, NO_DOCKER) == install.UNKNOWN


def test_the_kinds_that_own_their_own_files_can_update_themselves():
    """A source download does, once: the conversion only adds versions/ and
    current beside a tree it never touches."""
    assert install.can_self_update(install.ZIP) is True
    assert install.can_self_update(install.SOURCE) is True
    for kind in (install.CONTAINER, install.CHECKOUT, install.UNKNOWN):
        assert install.can_self_update(kind) is False


@pytest.mark.parametrize("kind", list(install.KINDS))
def test_every_kind_has_an_instruction(kind):
    said = install.instruction(kind)
    assert said and said[0].isupper() and said.endswith(".")
    # The prose standard: no em dash, and no double hyphen standing in for one.
    assert "—" not in said and "--" not in said


def test_the_root_follows_the_environment_when_the_shim_names_it(monkeypatch):
    """A release runs from versions/<v>/src/crossglyph, which is four parents
    from the install root and two from a checkout's. The shim knows which
    layout it is, so it says rather than leaving this to inference."""
    monkeypatch.setenv("CROSSGLYPH_HOME", str(pathlib.Path("/somewhere/CG")))
    assert install.root() == pathlib.Path("/somewhere/CG")


def test_without_it_the_root_is_the_project_directory(monkeypatch):
    monkeypatch.delenv("CROSSGLYPH_HOME", raising=False)
    assert (install.root() / "pyproject.toml").is_file()


def test_a_release_is_the_kind_with_nothing_to_say_about_itself():
    """The ordinary case. A note on every run is noise, so label() is empty
    and the caller leaves it out rather than printing an empty bracket."""
    assert install.label(install.ZIP) == ""


@pytest.mark.parametrize("kind", [install.CONTAINER, install.CHECKOUT,
                                  install.SOURCE, install.UNKNOWN])
def test_every_other_kind_says_which_it_is(kind):
    assert install.label(kind)


@pytest.mark.parametrize("kind", list(install.KINDS))
def test_a_kind_with_an_update_waiting_says_what_to_do_about_it(kind):
    assert install.notice(kind, True) == install.instruction(kind)


def test_a_release_with_nothing_to_update_to_says_nothing():
    assert install.notice(install.ZIP, False) == ""


def test_a_source_download_says_so_whether_or_not_there_is_an_update():
    """Standing and passive: its version is whatever the last release set, so
    a tree taken from master after that reports the release and compares as up
    to date while holding something else."""
    said = install.notice(install.SOURCE, False)
    assert said.startswith("This is a source download")


@pytest.mark.parametrize("kind", [install.CONTAINER, install.CHECKOUT,
                                  install.UNKNOWN])
def test_a_kind_that_cannot_update_itself_says_so_standing(kind):
    """Worth saying when there is nothing to act on: what somebody can do here
    is not what the buttons on this page do."""
    assert install.notice(kind, False) == install.instruction(kind)


def test_a_kind_nobody_declared_is_named_rather_than_hidden():
    """A route added to the instructions and forgotten here should still
    report something, not silently look like an ordinary release."""
    assert install.label("flatpak") == "flatpak"

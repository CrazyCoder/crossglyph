"""The versioned tree: what is installed, what is live, and what goes."""
import pytest

from crossglyph import layout


def make(root, names, live=None):
    for name in names:
        (root / "versions" / name / "src").mkdir(parents=True)
    if live:
        layout.write_current(root, live)
    return root


def test_current_is_the_first_line(tmp_path):
    (tmp_path / "current").write_text("0.2.0\n", encoding="utf-8")
    assert layout.current(tmp_path) == "0.2.0"


def test_no_current_is_no_version(tmp_path):
    assert layout.current(tmp_path) is None


def test_an_empty_current_is_no_version(tmp_path):
    """What an interrupted write leaves. It names versions/ itself, which is a
    directory that exists, so reading it as a name is how the launcher ends up
    running the folder the versions live in."""
    (tmp_path / "current").write_text("\n", encoding="utf-8")
    assert layout.current(tmp_path) is None


def test_writing_current_survives_a_round_trip(tmp_path):
    layout.write_current(tmp_path, "0.3.0")
    assert layout.current(tmp_path) == "0.3.0"
    assert not (tmp_path / "current.tmp").exists()


def test_present_is_in_version_order(tmp_path):
    make(tmp_path, ["0.9.0", "0.10.0", "0.2.0"])
    assert layout.present(tmp_path) == ["0.2.0", "0.9.0", "0.10.0"]


def test_a_directory_that_is_not_a_version_is_not_ours(tmp_path):
    make(tmp_path, ["0.1.0"])
    (tmp_path / "versions" / "notes").mkdir()
    assert layout.present(tmp_path) == ["0.1.0"]


def test_present_on_a_tree_with_no_versions(tmp_path):
    assert layout.present(tmp_path) == []


# --- retention ------------------------------------------------------------


def test_the_previous_version_is_kept_and_the_one_before_it_is_not(tmp_path):
    make(tmp_path, ["0.1.0", "0.2.0", "0.3.0"], live="0.3.0")
    assert layout.prune(tmp_path, keep=1) == ["0.1.0"]
    assert layout.present(tmp_path) == ["0.2.0", "0.3.0"]


def test_keeping_none_leaves_only_the_live_one(tmp_path):
    make(tmp_path, ["0.1.0", "0.2.0"], live="0.2.0")
    layout.prune(tmp_path, keep=0)
    assert layout.present(tmp_path) == ["0.2.0"]


def test_a_rollback_keeps_the_version_it_rolled_back_from(tmp_path):
    """Retention is by version order, not by age against current. Removing the
    newer one would mean downloading it again to roll forward."""
    make(tmp_path, ["0.1.0", "0.2.0"], live="0.1.0")
    assert layout.prune(tmp_path, keep=1) == []
    assert layout.present(tmp_path) == ["0.1.0", "0.2.0"]


def test_the_running_version_is_never_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(layout, "running", lambda: "0.1.0")
    make(tmp_path, ["0.1.0", "0.2.0", "0.3.0"], live="0.3.0")
    assert layout.prune(tmp_path, keep=0) == ["0.2.0"]
    assert layout.present(tmp_path) == ["0.1.0", "0.3.0"]


def test_running_reads_the_directory_it_is_executing_from(tmp_path,
                                                          monkeypatch):
    where = tmp_path / "versions" / "1.2.3" / "src" / "crossglyph"
    where.mkdir(parents=True)
    monkeypatch.setattr(layout, "__file__", str(where / "layout.py"))
    assert layout.running() == "1.2.3"


def test_running_in_a_checkout_is_no_version(tmp_path, monkeypatch):
    where = tmp_path / "src" / "crossglyph"
    where.mkdir(parents=True)
    monkeypatch.setattr(layout, "__file__", str(where / "layout.py"))
    assert layout.running() is None


def test_a_directory_that_will_not_go_does_not_fail_the_pass(tmp_path,
                                                             monkeypatch):
    """Windows locks a directory somebody has open. That is a reason to try
    again at the next launch, not a reason to fail what was asked for."""
    make(tmp_path, ["0.1.0", "0.2.0"], live="0.2.0")
    monkeypatch.setattr(layout.shutil, "rmtree",
                        lambda *args, **kwargs: None)
    assert layout.prune(tmp_path, keep=0) == []
    assert layout.present(tmp_path) == ["0.1.0", "0.2.0"]


def test_pruning_a_tree_with_no_versions_does_nothing(tmp_path):
    assert layout.prune(tmp_path, keep=1) == []


# --- what an interrupted update leaves ------------------------------------


@pytest.fixture
def littered(tmp_path):
    make(tmp_path, ["0.1.0"], live="0.1.0")
    (tmp_path / "versions" / ".incoming-0.2.0" / "src").mkdir(parents=True)
    (tmp_path / "versions" / ".tmp-0.2.0.zip").write_bytes(b"half")
    return tmp_path


def test_sweep_clears_what_a_crashed_update_left(littered):
    layout.sweep(littered)
    assert [path.name for path in (littered / "versions").iterdir()] == \
        ["0.1.0"]


def test_sweep_leaves_the_versions_alone(littered):
    layout.tidy(littered, keep=1)
    assert layout.present(littered) == ["0.1.0"]

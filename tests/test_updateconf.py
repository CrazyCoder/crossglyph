"""What the user asked for about checking, and the four ways to say no."""
import pathlib

import pytest

from crossglyph import updateconf


def _conf(root: pathlib.Path, text: str) -> pathlib.Path:
    (root / updateconf.PATH_NAME).write_text(text, encoding="utf-8")
    return root


def test_no_file_at_all_means_the_defaults():
    said = updateconf.settings(pathlib.Path("/nonexistent"), {})
    assert said.check is True
    assert said.interval_hours == 24


def test_a_commented_template_sets_nothing(tmp_path):
    """The file ships fully commented, exactly as fonts/conf/all.conf does, so
    uncommenting a line changes something and having the file does not."""
    root = _conf(tmp_path, "# check          = no\n# interval_hours = 1\n")
    said = updateconf.settings(root, {})
    assert said.check is True and said.interval_hours == 24


def test_keys_are_read(tmp_path):
    root = _conf(tmp_path, "check = no\ninterval_hours = 6\n")
    said = updateconf.settings(root, {})
    assert said.check is False
    assert said.interval_hours == 6


@pytest.mark.parametrize("text,expected", [
    ("check = no", False), ("check = No", False), ("check = false", False),
    ("check = off", False), ("check = 0", False),
    ("check = yes", True), ("check = true", True), ("check = 1", True),
])
def test_the_spellings_of_no(tmp_path, text, expected):
    assert updateconf.settings(_conf(tmp_path, text), {}).check is expected


def test_a_value_that_makes_no_sense_leaves_the_default(tmp_path):
    """A typo should not silently turn checking off, nor set an interval of
    zero that would check on every run."""
    root = _conf(tmp_path, "check = maybe\ninterval_hours = soon\n")
    said = updateconf.settings(root, {})
    assert said.check is True and said.interval_hours == 24


def test_a_negative_interval_is_refused(tmp_path):
    assert updateconf.settings(_conf(tmp_path, "interval_hours = -1"),
                               {}).interval_hours == 24


def test_the_environment_can_say_no(tmp_path):
    env = {"CROSSGLYPH_NO_UPDATE_CHECK": "1"}
    assert updateconf.settings(tmp_path, env).check is False


def test_any_value_of_it_counts(tmp_path):
    """Set to anything at all, including 0: it exists to be set, and somebody
    who exported it meant it."""
    assert updateconf.settings(tmp_path, {"CROSSGLYPH_NO_UPDATE_CHECK": "0"}
                               ).check is False


def test_ci_is_silent_without_being_asked(tmp_path):
    assert updateconf.settings(tmp_path, {"CI": "true"}).check is False


def test_the_flag_says_no_for_one_run(tmp_path):
    assert updateconf.settings(tmp_path, {}, flag_off=True).check is False


def test_any_one_of_them_is_enough(tmp_path):
    """Not a precedence chain: each is a way of saying no, and one is enough.
    A config that says yes does not overrule an environment that says no."""
    root = _conf(tmp_path, "check = yes\n")
    assert updateconf.settings(root, {"CI": "1"}).check is False


def test_a_key_the_reader_does_not_know_is_ignored(tmp_path):
    """update.conf grows a key in the next phase. A file written for a newer
    version should not stop an older one running."""
    root = _conf(tmp_path, "keep_versions = 2\ncheck = no\n")
    assert updateconf.settings(root, {}).check is False

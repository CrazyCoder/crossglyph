"""What version this is, and which of two is the greater."""
import subprocess
import sys

import pytest

from crossglyph import version


def test_the_installed_version_is_three_numbers():
    assert version.parse(version.installed()) is not None


@pytest.mark.parametrize("text,expected", [
    ("0.1.0", (0, 1, 0)),
    ("1.2.3", (1, 2, 3)),
    ("10.20.30", (10, 20, 30)),
    ("  0.1.0  ", (0, 1, 0)),
])
def test_a_plain_version_parses(text, expected):
    assert version.parse(text) == expected


@pytest.mark.parametrize("text", [
    "1.2", "1.2.3.4", "v1.2.3", "1.2.3a", "1.2.3-rc.1", "", "latest",
    # PEP 440 spellings that are not plain semver. Refusing them is the point:
    # the release tags are three numbers, and anything else means the manifest
    # is not what this code thinks it is.
    "1.2.3rc1", "1.2.3.post1",
    # Unicode digits. int() would accept these and \d would match them, so a
    # naive parser silently orders versions nobody typed.
    "١.٢.٣",
])
def test_anything_else_is_refused_rather_than_guessed(text):
    assert version.parse(text) is None


def test_ordering_is_numeric_and_not_lexical():
    """The bug this exists to prevent: "0.10.0" < "0.9.0" as strings."""
    assert version.is_newer("0.10.0", "0.9.0") is True
    assert version.is_newer("0.9.0", "0.10.0") is False


def test_the_same_version_is_not_newer():
    assert version.is_newer("1.2.3", "1.2.3") is False


def test_an_unparseable_version_is_never_newer():
    """Either side. A version nobody can order is not grounds for acting."""
    assert version.is_newer("garbage", "1.2.3") is False
    assert version.is_newer("1.2.3", "garbage") is False


def test_the_version_path_does_not_pay_for_a_wasm_runtime():
    """`crossglyph --version` should not load a wasm runtime to print a string.

    In-process this cannot be asked -- the rest of the suite has imported
    wasmtime already -- so ask a fresh interpreter.
    """
    done = subprocess.run(
        [sys.executable, "-c",
         "import sys; from crossglyph import version;"
         " from crossglyph.render import stamp;"
         " version.installed(); stamp.build_stamp();"
         " print('wasmtime' in sys.modules)"],
        capture_output=True, text=True, check=True)
    assert done.stdout.strip() == "False", \
        "reading the version or the stamp pulled in wasmtime"

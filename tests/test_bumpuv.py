"""Rewriting the pinned uv without touching anything else in the wrapper.

tools/uv.cmd is read by two interpreters, each of which needs its own line
endings, and it holds the same version and the same six hashes twice over.
Everything here is about a rewrite that cannot quietly get either wrong. None
of it reaches the network: what does is the fetching, which these tests do not
call.
"""
import importlib.util
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
WRAPPER = REPO / "tools" / "uv.cmd"

_spec = importlib.util.spec_from_file_location(
    "bump_uv", REPO / "tools" / "bump-uv.py")
assert _spec and _spec.loader
bump_uv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bump_uv)

NEW = "9.9.9"
#: Six hashes that are obviously not real, and all different, so a rewrite
#: that put one platform's hash on another would show.
FRESH = {platform: f"{index}" * 64
         for index, platform in enumerate(bump_uv.PLATFORMS)}


@pytest.fixture
def wrapper():
    return WRAPPER.read_bytes()


@pytest.fixture
def bumped(wrapper):
    version, _, sums = bump_uv.read_wrapper(wrapper.decode("utf-8"))
    return bump_uv.bump(
        wrapper, bump_uv.replacements(version, NEW, sums, FRESH))


def test_the_pin_is_read_out_of_the_bash_half(wrapper):
    version, urls, sums = bump_uv.read_wrapper(wrapper.decode("utf-8"))

    assert re.fullmatch(r"\d+(\.\d+)+", version)
    for platform in bump_uv.PLATFORMS:
        # The template, not a resolved URL: interpolating one version is what
        # lets a bump rewrite a single string instead of six addresses.
        assert "${TOOL_VERSION}" in urls[platform]
        assert re.fullmatch(r"[a-f0-9]{64}", sums[platform])


def test_both_halves_are_rewritten(wrapper, bumped):
    """cmd.exe reads one and bash the other, so a bump that reached only one
    of them would work on the machine it was run from and nowhere else."""
    text = bumped.decode("utf-8")
    old, _, sums = bump_uv.read_wrapper(wrapper.decode("utf-8"))

    assert f'TOOL_VERSION="{NEW}"' in text        # bash
    assert f'TOOL_VERSION={NEW}"' in text         # batch
    assert old not in text
    for platform in bump_uv.PLATFORMS:
        assert text.count(FRESH[platform]) == 2
        assert sums[platform] not in text


def test_the_rewrite_leaves_every_line_ending_where_it_was(wrapper, bumped):
    """The one thing the wrapper cannot survive. It is mixed on purpose, most
    editors flatten it silently, and a flattened one breaks whichever half
    the person who did it does not run."""
    endings = bump_uv.line_endings(wrapper)

    assert True in endings and False in endings   # the fixture really is mixed
    assert bump_uv.line_endings(bumped) == endings


def test_nothing_else_in_the_file_moves(wrapper, bumped):
    """Comments, URLs and the invocation are not the bump's business. What is
    left after the version and the hashes are put back is the same bytes."""
    old, _, sums = bump_uv.read_wrapper(wrapper.decode("utf-8"))
    back = bump_uv.bump(
        bumped, bump_uv.replacements(NEW, old, FRESH, sums))

    assert back == wrapper


def test_halves_that_disagree_are_refused_rather_than_half_written(wrapper):
    """A hash that is not in both halves means the file is not the one this
    script knows how to read. Rewriting the copy it can find would leave a
    wrapper that verifies on one platform and fails on the others."""
    version, _, sums = bump_uv.read_wrapper(wrapper.decode("utf-8"))
    drifted = wrapper.replace(sums["LINUX_X64"].encode(), b"f" * 64, 1)

    with pytest.raises(SystemExit, match="occurs 1 times"):
        bump_uv.bump(drifted,
                     bump_uv.replacements(version, NEW, sums, FRESH))


def test_windows_runs_the_batch_half_and_everyone_else_the_bash_one(
        monkeypatch):
    """The bash half dies on Git Bash with an unsupported OS, so a bump run
    from one on Windows still has to take the cmd branch. `call` is there
    because cmd strips the quotes off a command that opens with one, which is
    how an install path with a space in it arrives in pieces."""
    seen = {}

    def capture(command, **kwargs):
        seen["command"] = command
        seen["env"] = kwargs["env"]
        return type("Done", (), {"returncode": 0})()

    monkeypatch.setattr(bump_uv.subprocess, "run", capture)

    monkeypatch.setattr(bump_uv.os, "name", "nt")
    bump_uv.run_wrapper(["--version"])
    assert seen["command"] == ["cmd", "/c", "call", str(WRAPPER), "--version"]

    monkeypatch.setattr(bump_uv.os, "name", "posix")
    bump_uv.run_wrapper([], {"TOOL_VERIFY_ALL_PLATFORMS": "1"})
    assert seen["command"] == ["bash", str(WRAPPER)]
    assert seen["env"]["TOOL_VERIFY_ALL_PLATFORMS"] == "1"

"""Whether to check for a new release, and how often.

Its own reader rather than fontconf's: that one is about font keys, and
bending it to a file with nothing to do with fonts would tie two unrelated
formats together. The syntax is the same `key = value` with `#` comments,
because it is the one already in the workspace and there is no reason for a
second.
"""
from __future__ import annotations

import dataclasses
import os
import pathlib
from collections.abc import Mapping

PATH_NAME = "update.conf"

#: Long enough that nobody meets the network twice in a day, short enough that
#: a release is noticed the day after it lands.
DEFAULT_INTERVAL_HOURS = 24.0

#: Versions kept besides the live one. One is what a rollback needs, and a
#: version that has been run costs about 80 MB once uv has built its venv: a
#: second one buys a rollback to a release nobody is on.
DEFAULT_KEEP = 1

_NO = {"no", "false", "off", "0"}
_YES = {"yes", "true", "on", "1"}


@dataclasses.dataclass(frozen=True)
class Settings:
    check: bool
    interval_hours: float
    keep_versions: int


def read(root: pathlib.Path) -> dict[str, str]:
    """The keys the file sets, which for the shipped template is none.

    A key this version does not know is kept rather than refused: the file
    grows, and one written for a newer version should not stop an older one
    running.
    """
    found: dict[str, str] = {}
    try:
        text = (root / PATH_NAME).read_text(encoding="utf-8")
    except OSError:
        return found
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        found[key.strip().lower()] = value.strip()
    return found


def _flag(value: str | None, default: bool) -> bool:
    """A written yes or no, or the default for anything else.

    Anything else rather than a guess: a typo that turns checking off says
    nothing at the time, and is then never noticed.
    """
    if value is None:
        return default
    lowered = value.strip().lower()
    if lowered in _NO:
        return False
    if lowered in _YES:
        return True
    return default


def _hours(value: str | None) -> float:
    """A positive number of hours, or the default.

    Zero and below are refused along with nonsense: an interval of none would
    put the network on every single run, which is the thing the throttle is
    there to prevent.
    """
    if value is None:
        return DEFAULT_INTERVAL_HOURS
    try:
        hours = float(value)
    except ValueError:
        return DEFAULT_INTERVAL_HOURS
    return hours if hours > 0 else DEFAULT_INTERVAL_HOURS


def _count(value: str | None) -> int:
    """A whole number of versions to keep, or the default.

    Zero is allowed and means the live one only. Below zero is not a smaller
    number of versions, it is a typo, and it gets the default rather than a
    reading of its own.
    """
    if value is None:
        return DEFAULT_KEEP
    try:
        kept = int(value)
    except ValueError:
        return DEFAULT_KEEP
    return kept if kept >= 0 else DEFAULT_KEEP


def settings(root: pathlib.Path, environ: Mapping[str, str] | None = None,
             flag_off: bool = False) -> Settings:
    """What this install wants, from the file and the environment together.

    The four ways to say no are not a precedence chain: each silences the
    automatic check on its own, and a file saying yes does not overrule an
    environment that says no. None of them touches a check somebody asked for
    by hand, which is the whole use of the button.
    """
    environ = os.environ if environ is None else environ
    keys = read(root)
    quiet = (flag_off
             or "CROSSGLYPH_NO_UPDATE_CHECK" in environ
             or "CI" in environ
             or not _flag(keys.get("check"), True))
    return Settings(check=not quiet,
                    interval_hours=_hours(keys.get("interval_hours")),
                    keep_versions=_count(keys.get("keep_versions")))

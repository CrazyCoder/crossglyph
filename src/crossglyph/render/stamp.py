"""What the render core on disk says about itself.

Split from the module loader so that reading it costs nothing: `render`
imports wasmtime at module scope, and `crossglyph --version` wants the
firmware commit without a wasm runtime behind it. Nothing here touches the
module, only the two files beside it.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[3]
WASM_PATH = pathlib.Path(__file__).resolve().parent / "render.wasm"
STAMP_PATH = WASM_PATH.with_name("render.built-from.json")

#: Where the firmware comes from, first that exists: a checkout that belongs to
#: the engine build and is on one branch for that reason, then a shared one.
#: $CROSSGLYPH_FIRMWARE beats both, which is also how a fork of the firmware is
#: built from without anything here knowing about forks.
#:
#: src/render/build.sh resolves $FW from the same list, and a test asserts they
#: agree: one decides what the module is built from, this decides whether it is
#: out of date, and a disagreement makes both answers wrong.
ENGINE_DIRS = ("crosspoint-reader-engine", "crosspoint-reader")


def _firmware() -> pathlib.Path:
    named = os.environ.get("CROSSGLYPH_FIRMWARE")
    if named:
        return pathlib.Path(named)
    beside = (ROOT.parent / name for name in ENGINE_DIRS)
    return next((path for path in beside if path.is_dir()),
                ROOT.parent / ENGINE_DIRS[-1])


#: Only a checkout has this. Without one there is nothing to compare the
#: module against, and is_stale() says so rather than guessing.
FIRMWARE = _firmware()


def short(commit: str | None) -> str:
    return commit[:12] if commit else "an unknown commit"


def describe() -> str:
    """What the module was built from, as a sentence fragment.

    The firmware the stamp names, not the directory found beside this repo:
    those differ as soon as the engine is built from a checkout of its own,
    and they would differ again for a second firmware.
    """
    stamp = _stamp()
    commit = stamp.get("firmware")
    if not commit:
        return "sources it kept no record of"
    where = " ".join(part for part in (stamp.get("source") or FIRMWARE.name,
                                       stamp.get("ref")) if part)
    return f"{where} {short(commit)}"


def _stamp() -> dict:
    """What build.sh recorded beside the module, or nothing."""
    try:
        stamp = json.loads(STAMP_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return stamp if isinstance(stamp, dict) else {}


def firmware_commit(source: str | pathlib.Path | None = None) -> str | None:
    """HEAD of the firmware clone the core would be built from, or None."""
    try:
        return subprocess.run(
            ["git", "-C", str(source or FIRMWARE), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def build_stamp() -> str | None:
    """The firmware commit the module on disk was built from, if it says."""
    return _stamp().get("firmware") or None


def current_firmware() -> tuple[str | None, str | pathlib.Path]:
    """The commit to compare against, and the checkout it came from.

    The stamp records a commit and not a path, so this is the sibling checkout
    or whatever $CROSSGLYPH_FIRMWARE names. Returns which one answered, so
    the warning can name it rather than guessing.
    """
    return firmware_commit(FIRMWARE), FIRMWARE


def is_stale() -> bool:
    """True when the module is missing, or the firmware has moved past it.

    A module with no record of where it came from counts as not matching, so a
    checkout that has never rebuilt pays one rebuild and is accurate from then
    on.
    """
    if not WASM_PATH.is_file():
        return True
    current, _ = current_firmware()
    if current is None:
        # Nothing to compare against: a release, a firmware exported as a
        # tarball, or no git on PATH. "Cannot check" is not "does not match" --
        # calling it stale would advise a rebuild the caller has no way to
        # run, on every single run.
        return False
    return build_stamp() != current

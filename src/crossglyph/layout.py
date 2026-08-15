"""The versioned tree an unpacked release keeps, and how it is tidied.

A release holds one directory per version under `versions/`, with `current`
naming the live one, so an update adds a directory and rewrites one line rather
than overwriting anything that is running. Nothing here reaches the network or
knows what an update is: this is the shape on disk, and `upgrade.py` is what
changes it.
"""
from __future__ import annotations

import pathlib
import shutil

from . import version

CURRENT_NAME = "current"
VERSIONS_NAME = "versions"

#: What an interrupted update leaves behind: a tree that was being extracted
#: and a zip that was being written. Neither is ever named as a version, so the
#: launcher cannot pick one up, and both are swept at the next launch.
INCOMING_PREFIX = ".incoming-"
TMP_PREFIX = ".tmp-"

#: A version directory an update moved out of its own way. It is left rather
#: than deleted because deleting it can be impossible while the tool runs, for
#: the reason `upgrade.swap` gives; the next launch sweeps it.
OLD_PREFIX = ".old-"


def versions_dir(root: pathlib.Path) -> pathlib.Path:
    return root / VERSIONS_NAME


def version_dir(root: pathlib.Path, name: str) -> pathlib.Path:
    return root / VERSIONS_NAME / name


def current(root: pathlib.Path) -> str | None:
    """The version the launcher runs, or None when there is no release here."""
    try:
        first = (root / CURRENT_NAME).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return None
    return first[0].strip() if first and first[0].strip() else None


def write_current(root: pathlib.Path, name: str) -> None:
    """Name the live version, in a way that cannot land half written.

    The launcher reads this file on every run, and a truncated write would
    leave it naming a directory that is not there. Written aside and moved,
    which on both platforms is atomic within a directory.
    """
    beside = root / (CURRENT_NAME + ".tmp")
    beside.write_text(f"{name}\n", encoding="utf-8")
    beside.replace(root / CURRENT_NAME)


def present(root: pathlib.Path) -> list[str]:
    """The versions installed here, oldest first.

    A directory whose name is not a version is somebody else's and is left out
    of every answer this module gives, so nothing here can remove it.
    """
    try:
        found = list(versions_dir(root).iterdir())
    except OSError:
        return []
    named = [path.name for path in found
             if path.is_dir() and version.parse(path.name)]
    return sorted(named, key=lambda name: version.parse(name))


def running() -> str | None:
    """The version directory this code is executing from, if it is in one.

    Read off __file__ rather than off the installed metadata, because what must
    survive a prune is the directory whose files are open, whatever any
    metadata says about which version they are.
    """
    here = pathlib.Path(__file__).resolve()
    # .../versions/<v>/src/crossglyph/layout.py
    if len(here.parents) > 3 and here.parents[3].name == VERSIONS_NAME:
        return here.parents[2].name
    return None


def keep_set(installed: list[str], live: str | None, here: str | None,
             keep: int) -> set[str]:
    """Which of `installed` survives a prune.

    Retention is by version order rather than "older than current". After a
    rollback the current version is the older one, and the newer has to stay or
    rolling forward means downloading it again.
    """
    kept = {name for name in (live, here) if name}
    rest = [name for name in installed if name not in kept]
    return kept | set(rest[len(rest) - keep:] if keep > 0 else [])


def prune(root: pathlib.Path, keep: int) -> list[str]:
    """Remove the versions past the retention count. Returns what went.

    Never the live version and never the one this process is running from. A
    removal that fails is left for the next launch: a directory Windows has
    locked is a reason to try again later, not a reason to fail anything the
    user asked for.
    """
    installed = present(root)
    survivors = keep_set(installed, current(root), running(), keep)
    gone = []
    for name in installed:
        if name in survivors:
            continue
        shutil.rmtree(version_dir(root, name), ignore_errors=True)
        if not version_dir(root, name).exists():
            gone.append(name)
    return gone


def sweep(root: pathlib.Path) -> None:
    """Clear what an interrupted update, or one that could not tidy up, left.

    Nothing in here is ever named as a version, so none of it is launchable and
    a sweep that fails costs only the space until the next one.
    """
    try:
        leftovers = list(versions_dir(root).iterdir())
    except OSError:
        return
    for path in leftovers:
        if path.name.startswith((INCOMING_PREFIX, OLD_PREFIX)):
            shutil.rmtree(path, ignore_errors=True)
        elif path.name.startswith(TMP_PREFIX):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                # A locked file, or a directory where a zip was expected.
                # This runs at launch, so nothing it meets is worth failing a
                # build over: the next launch tries again.
                pass


def tidy(root: pathlib.Path, keep: int) -> None:
    """Housekeeping, run at launch and never on a path anybody is waiting on.

    Not part of applying an update: at the moment the button is pressed, the
    version being replaced is the one serving the page the press came from, and
    deleting its files then is how a locked-file failure is invited.
    """
    sweep(root)
    prune(root, keep)

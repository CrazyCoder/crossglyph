"""Installing a newer release, and going back to the last one.

One code path, driven from `crossglyph update` and from the Update button, so
the two cannot come to behave differently. It is a generator of steps rather
than a function that returns at the end: the download is a megabyte and a half
and the page shows a bar for it, and the command line prints the same steps as
lines. That is the shape `fontbuild.fetch_steps` already has, and the page
already reads.

Nothing is ever overwritten in place. A new version lands in a directory of
its own, and `current` is rewritten last, after the tree it names is whole.
Two facts make that not an optimisation but the only way it can work:

- cmd.exe reads a batch file by byte offset while it runs it, so the launcher
  is being read as this executes and cannot be replaced from here;
- the package imports lazily, so replacing src/ under a running process would
  load new code into one that already holds old code.
"""
from __future__ import annotations

import dataclasses
import hashlib
import os
import pathlib
import shutil
import zipfile
from collections.abc import Iterator

from . import install, layout, updates, version

#: A megabyte and a half over a link that may be slow. The manifest's two
#: seconds is a wait nobody asked for; this one is a download somebody pressed
#: a button for and is watching.
DOWNLOAD_TIMEOUT = 120.0

CHUNK = 262144

#: The user's, and never written over: the update seeds files into it under
#: the conffile rule below and touches nothing else in it.
WORKSPACE = "fonts"

#: Written beside a file the user has edited, rather than over it.
SUFFIX = ".new"

#: The launcher, which is the one file an update cannot write over: it is open
#: and being read by cmd.exe or by a shell as this runs. The new one is left
#: beside it with this suffix, and the launcher itself applies it at the next
#: launch, before it has done anything else. See the comment at the top of
#: crossglyph.cmd for what happens when that rule is broken.
STAGED = ".staged"

LAUNCHERS = ("crossglyph.cmd", "crossglyph.sh")

#: "Version made by" saying Unix, which is what makes a mode in the archive
#: mean anything. zipfile does not apply either, so this module does.
UNIX = 3


class Refused(Exception):
    """This install will not do that, and here is the sentence saying why."""


def _safe(name: str) -> bool:
    """Whether a member name may be written under the directory we chose.

    A zip can name ../../anything, and Python's extract is the one that guards
    against it. This module writes members itself, so it guards for itself.

    A backslash is refused rather than interpreted. The format says separators
    are forward slashes, so a name carrying one is malformed at best; and it
    is the way past a check like this one, since `..\\..\\x` is a single
    innocent-looking component to a POSIX path and three to Windows.
    """
    if not name or name[0] in "/\\" or "\\" in name:
        return False
    parts = pathlib.PurePosixPath(name).parts
    return ".." not in parts and not any(":" in part for part in parts)


def extract(archive: pathlib.Path, into: pathlib.Path, wanted: str) -> None:
    """The versions/<wanted>/ subtree of a release zip, and nothing else.

    One artifact serves a first install and an update, so most of what is in
    it belongs to the root of an install that already has a root.

    Modes are written back on POSIX. zipfile drops them, and tools/uv.cmd
    without its executable bit is an install that cannot start: the failure is
    at the next launch, nowhere near the update that caused it.
    """
    inside = f"/{layout.VERSIONS_NAME}/{wanted}/"
    found = 0
    with zipfile.ZipFile(archive) as source:
        for info in source.infolist():
            if info.is_dir() or inside not in info.filename:
                continue
            rest = info.filename.split(inside, 1)[1]
            if not _safe(rest):
                raise ValueError(f"the release names a file outside itself: "
                                 f"{info.filename}")
            target = into / rest
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(info) as member, target.open("wb") as out:
                shutil.copyfileobj(member, out)
            mode = info.external_attr >> 16
            if os.name != "nt" and info.create_system == UNIX and mode:
                target.chmod(mode & 0o777)
            found += 1
    if not found:
        raise ValueError(f"the release zip carries no {layout.VERSIONS_NAME}/"
                         f"{wanted} to install")


def seed_workspace(root: pathlib.Path, incoming: pathlib.Path,
                   shipped: pathlib.Path | None) -> list[str]:
    """Put the new version's workspace templates where the user's workspace is.

    The conffile rule, which is Debian's and exists because these are files a
    tool ships and a user then edits:

        absent               -> write it
        as it shipped        -> write it, since they never touched it
        anything else        -> keep theirs, and write <name>.new beside it

    `shipped` is the copy that came with the version being replaced, which is
    what tells an edited file from one that has simply changed between
    releases. A source download has none, so a file that differs is kept and
    gets a .new rather than being assumed untouched. That errs towards leaving
    what somebody wrote where they wrote it.

    Returns the files kept, so whoever asked for the update can be told a .new
    is sitting there.
    """
    source = incoming / WORKSPACE
    kept = []
    for path in sorted(source.rglob("*")) if source.is_dir() else []:
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        live = root / WORKSPACE / relative
        arriving = path.read_bytes()
        if live.is_file():
            theirs = live.read_bytes()
            if theirs == arriving:
                continue
            was = shipped / WORKSPACE / relative if shipped else None
            if not (was and was.is_file() and was.read_bytes() == theirs):
                live.with_name(live.name + SUFFIX).write_bytes(arriving)
                kept.append(str(relative).replace("\\", "/"))
                continue
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_bytes(arriving)
    return kept


def stage_launchers(root: pathlib.Path, incoming: pathlib.Path) -> list[str]:
    """Leave the new launcher beside the running one. Returns what was staged.

    Only where it differs, so an install whose launcher has not changed gets
    no file it has to notice. The live one is never written: it is open, and
    the platforms differ only in how badly that ends.
    """
    staged = []
    for name in LAUNCHERS:
        arriving = incoming / name
        live = root / name
        if not arriving.is_file() or (live.is_file()
                                      and live.read_bytes()
                                      == arriving.read_bytes()):
            continue
        beside = root / (name + STAGED)
        beside.write_bytes(arriving.read_bytes())
        # The one it replaces was executable, and the one that replaces it has
        # to be, or the next launch is the last one.
        if os.name != "nt":
            beside.chmod(arriving.stat().st_mode & 0o777 or 0o755)
        staged.append(name)
    return staged


def _download(url: str, into: pathlib.Path, sha256: str,
              size: int) -> Iterator[dict]:
    """Stream the release to disk, hashing it on the way past.

    Hashed as it arrives rather than read back afterwards: it is the same
    bytes, one pass instead of two, and there is nothing else the file is for.
    """
    got = 0
    digest = hashlib.sha256()
    with updates.open_stream(url, DOWNLOAD_TIMEOUT) as answer:
        with into.open("wb") as out:
            while chunk := answer.read(CHUNK):
                out.write(chunk)
                digest.update(chunk)
                got += len(chunk)
                yield {"event": "step", "got": got, "bytes": max(size, got)}
    if digest.hexdigest() != sha256:
        # Deleted rather than kept for inspection: what is on disk is an
        # unknown archive from the internet, and leaving it invites somebody
        # to unpack it by hand and find out.
        into.unlink(missing_ok=True)
        raise ValueError("the download does not match the hash the manifest "
                         "gave, so it was thrown away")


def steps(root: pathlib.Path, kind: str | None = None) -> Iterator[dict]:
    """Fetch, verify, stage and swap, saying how far it has got.

    The terminal step is one of three. `done` installed something, `current`
    found nothing worth installing, and `error` explains why it stopped, which
    includes an install that was never going to be able to do this.
    """
    kind = install.detect(root) if kind is None else kind
    # Before anything is fetched: an image or a package manager owns these
    # files, and downloading a release to find that out wastes the download
    # and, in a container, writes it to a filesystem that goes away.
    if not install.can_self_update(kind):
        yield {"event": "error",
               "error": f"this install cannot update itself. "
                        f"{install.instruction(kind)}"}
        return

    try:
        found = updates.parse(updates.fetch(updates.MANIFEST_URL))
    except (OSError, ValueError) as exc:
        yield {"event": "error",
               "error": f"could not reach the update server: {exc}"}
        return

    here = version.installed()
    if not version.is_newer(found.version, here):
        yield {"event": "current", "version": here}
        return

    versions = layout.versions_dir(root)
    archive = versions / f"{layout.TMP_PREFIX}{found.version}.zip"
    incoming = versions / f"{layout.INCOMING_PREFIX}{found.version}"
    landing = layout.version_dir(root, found.version)
    live = layout.current(root)
    converting = live is None
    yield {"event": "plan", "version": found.version, "bytes": found.size,
           "notes_url": found.notes_url, "converting": converting}
    try:
        # A source download has neither, and this is the whole of what
        # converting it into a release install amounts to.
        versions.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(incoming, ignore_errors=True)
        yield from _download(found.url, archive, found.sha256, found.size)
        extract(archive, incoming, found.version)
        # The copy the version being replaced shipped, which is what tells an
        # edited file from one that changed between releases.
        kept = seed_workspace(root, incoming,
                              layout.version_dir(root, live) if live else None)
        # Named as a version only once it is whole, so an update interrupted
        # anywhere before this leaves nothing the launcher could pick up.
        shutil.rmtree(landing, ignore_errors=True)
        incoming.replace(landing)
        layout.write_current(root, found.version)
        # After current, so an install interrupted before this still starts:
        # the old launcher understands the new layout, which is what keeping
        # it thin is for.
        staged = stage_launchers(root, landing)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        shutil.rmtree(incoming, ignore_errors=True)
        yield {"event": "error", "error": str(exc)}
        return
    finally:
        archive.unlink(missing_ok=True)

    yield {"event": "done", "version": found.version, "kept": kept,
           "staged": staged, "converting": converting, "where": str(landing)}


def rollback(root: pathlib.Path) -> str:
    """Go back to the highest retained version below the live one.

    The version left behind is recorded as rejected, and the check stays quiet
    about it until something newer than it exists. A rollback that the next
    check undoes by nagging is not a safety net.
    """
    live = layout.current(root)
    on = version.parse(live or "")
    if on is None:
        raise Refused("this install has no versions to roll back through")
    # present() answers in version order and only with names that parse, so
    # the last one below the live version is the one to go back to.
    older = [name for name in layout.present(root)
             if version.parse(name) < on]
    if not older:
        raise Refused(f"there is no version older than {live} to go back to")
    target = older[-1]
    try:
        layout.write_current(root, target)
    except OSError as exc:
        raise Refused(f"could not write which version to run: {exc}") from exc
    known = updates.load_state(root)
    updates.save_state(root, dataclasses.replace(known, rejected=live))
    return target

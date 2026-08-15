"""Which kind of install this is, and therefore how it can be updated.

An unpacked release, a container image, a clone and a source download all
answer "is there a newer version" the same way and "how do you get it"
differently. Resolving one kind here is what keeps that difference in one
place, rather than having the notice, the button and the apply path each work
it out and eventually disagree.
"""
from __future__ import annotations

import os
import pathlib
from collections.abc import Mapping

ZIP = "zip"
CONTAINER = "container"
CHECKOUT = "checkout"
SOURCE = "source"
UNKNOWN = "unknown"

#: The second sentence of the notice, and the set of kinds there are. One row
#: per packaging route, so adding one is a row here rather than a branch at
#: every call site.
INSTRUCTIONS = {
    ZIP: "Run crossglyph update to install it.",
    CONTAINER: "Pull the new image to update.",
    CHECKOUT: "Run git pull to update.",
    SOURCE: "Run crossglyph update to convert this into a release install.",
    UNKNOWN: "Open the release page to update.",
}

KINDS = tuple(INSTRUCTIONS)

#: What a kind says when there is nothing to update to. A source download is
#: the one with something worth saying: its version is whatever the last
#: release set, so a tree taken from master days later reports that release and
#: compares as up to date while holding something else entirely.
STANDING = {
    SOURCE: "This is a source download, so its version may not describe what "
            "is in the tree.",
}

#: Kinds whose instruction says only what an Update button already does, so a
#: surface carrying that button says nothing at all. A source download can
#: self-update too and is deliberately not here: its instruction says the
#: update converts the install, which is a thing to know before pressing
#: rather than after.
BUTTON_SAYS_IT = (ZIP,)

#: How a kind is named when something has to say which one it is. Beside the
#: instructions rather than at the call site, so a new packaging route is one
#: place to edit and not two that can drift. A release is absent on purpose:
#: it is the ordinary case, and naming it on every run is noise.
LABELS = {
    CONTAINER: "container",
    CHECKOUT: "checkout",
    SOURCE: "source download",
    UNKNOWN: "will not update itself",
}

#: Docker writes this; other runtimes do not, which is why it is only a hint.
#: What the image says in CROSSGLYPH_INSTALL_KIND is the signal that counts.
DOCKERENV = pathlib.Path("/.dockerenv")


def root() -> pathlib.Path:
    """The install root: what holds the launcher, the workspace and versions/.

    A release runs from versions/<v>/src/crossglyph and a checkout from
    src/crossglyph, so this cannot be counted off __file__ without guessing
    which layout it is in. The shim knows, so it exports CROSSGLYPH_HOME.
    Unset means run in place, where two parents up has always been right.
    """
    named = os.environ.get("CROSSGLYPH_HOME")
    return pathlib.Path(named) if named \
        else pathlib.Path(__file__).resolve().parents[2]


def detect(directory: pathlib.Path,
           environ: Mapping[str, str] | None = None,
           dockerenv: pathlib.Path | None = None) -> str:
    """The kind of install `directory` holds. First match wins."""
    environ = os.environ if environ is None else environ
    dockerenv = DOCKERENV if dockerenv is None else dockerenv

    named = environ.get("CROSSGLYPH_INSTALL_KIND", "").strip()
    if named in INSTRUCTIONS:
        return named
    # Before the layout, not after it. Being in a container is a fact about
    # where this is running, which no arrangement of directories overrides: an
    # image built by unpacking a release has the layout, and self-updating
    # inside one writes to a filesystem that goes away on restart. That
    # failure is silent, which is what makes it worth the ordering.
    if dockerenv.exists():
        return CONTAINER
    if (directory / "current").is_file() and (directory / "versions").is_dir():
        # An install nobody can write to is not a special failure, it is
        # simply not a kind that can replace its own files. On Windows this
        # sees only the read-only attribute, so a directory that is unwritable
        # for another reason still resolves to ZIP and fails at apply time.
        return ZIP if os.access(directory, os.W_OK) else UNKNOWN
    if (directory / ".git").exists():
        return CHECKOUT
    if (directory / "pyproject.toml").is_file():
        return SOURCE
    return UNKNOWN


def can_self_update(kind: str) -> bool:
    """Which kinds own the files an update would write.

    A source download does, once: converting it only adds versions/ and
    current beside a tree it never touches, and after that it is a release
    like any other. Everything else belongs to an image or a package manager.
    """
    return kind in (ZIP, SOURCE)


def instruction(kind: str) -> str:
    return INSTRUCTIONS.get(kind, INSTRUCTIONS[UNKNOWN])


def notice(kind: str, available: bool, *, offering: bool = False) -> str:
    """The sentence a surface shows about updating, or nothing.

    One place decides this, so the page and the command line cannot come to
    disagree and neither has to work out for itself when there is something to
    say. An install with nothing to update to says nothing at all, whichever
    kind it is: what a clone would have to do about a release it is not behind
    is nothing, and standing there telling it to pull is an instruction to
    fetch what it already has.

    The comparison behind `available` is a version against the published one,
    so a clone whose pyproject is behind that release is told and one that is
    not is left alone. What that cannot see is a clone level with the release
    and behind it in commits, which is the caveat a source download carries
    below and a clone is expected to know about itself.

    `offering` is a surface that is itself offering to do it: the preview,
    which puts an Update button on this very line. Telling somebody to run a
    command beside a button that runs it is noise, so the kinds in
    BUTTON_SAYS_IT say nothing there. Every other kind is told, including the
    two the button cannot help -- a container still has to be sent to pull the
    image, and that is the one thing the page cannot do for it.
    """
    if available:
        return "" if offering and kind in BUTTON_SAYS_IT else instruction(kind)
    return STANDING.get(kind, "")


def label(kind: str) -> str:
    """What to call this kind, or nothing when there is nothing to say."""
    return LABELS.get(kind, "" if kind == ZIP else kind)

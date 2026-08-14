"""Is there a newer release, and when did we last ask.

The check never sits on a path anybody is waiting for: the CLI runs it after
its work is done and the preview runs it on a thread at startup, so the only
cost anyone meets is a bounded wait once per throttle window. That is why
there is no detached child process here, which is the machinery npm's
update-notifier needs because an npm CLI is too short lived to afford even a
fast check.

Nothing here downloads or installs a release.
"""
from __future__ import annotations

import dataclasses
import json
import pathlib
import re
import time
import urllib.request
from collections.abc import Mapping

from . import updateconf, version

#: Published to Pages by the release workflow. Pages is CDN served and
#: unmetered, unlike the REST API, which is 60 requests an hour per address
#: and shared by everyone behind one.
MANIFEST_URL = "https://crazycoder.github.io/crossglyph/latest.json"

#: Written by the tool, beside the launcher. Not a config: nothing in it is a
#: decision somebody made.
STATE_NAME = ".update-state.json"

#: Long enough not to delay a font build anybody is watching, short enough
#: that an install with no network is not left sitting there.
TIMEOUT = 2.0

#: A manifest is small. Reading a bounded amount means a server answering with
#: something enormous costs a page of memory rather than all of it.
MAX_BYTES = 1 << 16

_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclasses.dataclass(frozen=True)
class Manifest:
    version: str
    url: str
    sha256: str
    size: int
    notes_url: str
    launcher_changed: bool


@dataclasses.dataclass(frozen=True)
class State:
    checked_at: float
    latest: str | None
    error: str | None


def parse(raw: bytes) -> Manifest:
    """The manifest, or ValueError saying why it is not one.

    Every field is checked, because this is what a download is verified
    against later: a manifest nobody validated is a hash nobody can trust.
    """
    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"the manifest is not JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise ValueError("the manifest is not an object")

    declared = str(body.get("version", "")).strip()
    if version.parse(declared) is None:
        raise ValueError(f"the manifest version is not three numbers: "
                         f"{body.get('version')!r}")
    url = str(body.get("url", ""))
    if not url.startswith("https://"):
        raise ValueError("the manifest does not serve the release over HTTPS")
    sha256 = str(body.get("sha256", "")).lower()
    if not _SHA256.fullmatch(sha256):
        raise ValueError("the manifest carries no SHA-256")
    notes = str(body.get("notes_url", ""))
    if not notes.startswith("https://"):
        raise ValueError("the manifest has no release page")
    try:
        size = int(body.get("size", 0))
    except (TypeError, ValueError):
        raise ValueError("the manifest size is not a number") from None
    # Unknown keys are ignored on purpose: the format has to be able to grow
    # without every install already out there refusing to read it.
    return Manifest(version=declared, url=url, sha256=sha256, size=size,
                    notes_url=notes,
                    launcher_changed=bool(body.get("launcher_changed", False)))


def fetch(url: str, timeout: float = TIMEOUT) -> bytes:
    """The one place this package talks to the network.

    A single seam, so the tests can be sure they never do.
    """
    with urllib.request.urlopen(url, timeout=timeout) as answer:  # noqa: S310
        return answer.read(MAX_BYTES)


def load_state(root: pathlib.Path) -> State:
    """What the last check found, or a state that has never checked."""
    try:
        body = json.loads((root / STATE_NAME).read_text(encoding="utf-8"))
        return State(checked_at=float(body.get("checked_at", 0)),
                     latest=body.get("latest") or None,
                     error=body.get("error") or None)
    except (OSError, ValueError, TypeError, AttributeError):
        return State(checked_at=0.0, latest=None, error=None)


def save_state(root: pathlib.Path, state: State) -> None:
    """Best effort. A read-only install still runs, it just asks every time."""
    try:
        (root / STATE_NAME).write_text(
            json.dumps(dataclasses.asdict(state)), encoding="utf-8")
    except OSError:
        pass


def check(root: pathlib.Path, *, force: bool = False,
          now: float | None = None, environ: Mapping[str, str] | None = None,
          flag_off: bool = False) -> State:
    """Ask if the throttle allows it, and record what came back.

    A forced check ignores both the throttle and the opt-outs: those exist to
    stop it asking on its own, and a button that honoured them would have
    nothing to do.
    """
    now = time.time() if now is None else now
    wanted = updateconf.settings(root, environ, flag_off)
    known = load_state(root)
    if not force:
        if not wanted.check:
            return known
        waited = now - known.checked_at
        # Never checked is due whatever the clock says. Comparing a stored
        # zero against the clock would make that depend on how far the clock
        # happens to be from the epoch, which is true today and is not a
        # reason. A stored time in the future is due too: a clock that moved
        # back would otherwise wedge the throttle shut for as long as it takes
        # to catch up.
        if 0 < known.checked_at and 0 <= waited < wanted.interval_hours * 3600:
            return known

    try:
        found = parse(fetch(MANIFEST_URL))
        state = State(checked_at=now, latest=found.version, error=None)
    except (OSError, ValueError) as exc:
        # The time is recorded even on a failure, or an install with no
        # network meets the timeout on every single run.
        state = State(checked_at=now, latest=None, error=str(exc))
    save_state(root, state)
    return state


def available(state: State) -> str | None:
    """The release worth moving to, or None.

    Strictly newer, so a tree already past the last release is never told to
    move backwards. That is the ordinary case for a clone of master, whose
    version is only bumped when a release is cut.
    """
    if not state.latest:
        return None
    return state.latest if version.is_newer(state.latest,
                                            version.installed()) else None

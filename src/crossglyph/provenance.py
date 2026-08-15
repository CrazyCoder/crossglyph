"""What a built family was made from, written beside it.

A family folder is a thing people copy: onto a card, into a zip, to somebody
who liked how it looked. What travels with it is four .cpfont files whose only
metadata is a name and a size, and everything that decided how they draw --
which face, which weight of it, which knobs, which converter -- stays behind
on the machine that ran the build. This is that, in the stamp file already in
the folder.

It is written to be read by a person and by a later version of this tool, so
it records what a build *resolved* rather than what a config happened to say.
Defaults move between versions; a value that was the default when this ran is
still the value it ran with, and a file that recorded only the departures from
default would reproduce a different font a year later.

Nothing here is read back yet. It is written because the moment to record how
something was made is while you still know, and by the time a reader wants it
the machine that knew is long gone.
"""
from __future__ import annotations

import datetime
import pathlib

from . import cpfont, version
from .fontconf import STYLES, Config, Variant, size_label

#: Name table records worth keeping, each with the ids to try in order. Enough
#: to find the original again and to know what may be done with it -- which is
#: the question a shared font raises first and answers least.
#:
#: The typographic names (16, 17) come before the basic pair (1, 2) because a
#: variable font's basic pair describes its *default instance*, and that is
#: routinely not the face you built: Bitter's default is Thin, so its name
#: record 1 reads "Bitter Thin" while 16 reads "Bitter". Recording the first
#: would send somebody looking up the original to the wrong weight.
#:
#: 13 is left out on purpose: a licence *description* is frequently the entire
#: OFL, several times the size of everything else here. The URL says the same
#: thing and stays a line.
NAME_IDS = (("name", (16, 1)), ("subfamily", (17, 2)), ("version", (5,)),
            ("manufacturer", (8,)), ("designer", (9,)),
            ("vendor_url", (11,)), ("designer_url", (12,)),
            ("licence_url", (14,)))


def _face(path: pathlib.Path, sha256: str, coords: dict[str, float]) -> dict:
    """One source face: which file, which bytes, and what it says it is.

    The filename and not the path. Where a font sat belongs to one machine,
    and this file is meant to leave that machine -- the same reason the render
    core's stamp records a commit and no directory.
    """
    from fontTools.ttLib import TTFont, TTLibError

    face: dict = {"file": path.name, "sha256": sha256}
    try:
        face["bytes"] = path.stat().st_size
    except OSError:
        pass
    try:
        with TTFont(path, lazy=True, fontNumber=0) as font:
            names = font["name"]
            for key, numbers in NAME_IDS:
                said = next((found for found in map(names.getDebugName, numbers)
                             if found), None)
                if said:
                    face[key] = said
    except (OSError, TTLibError, KeyError):
        # A face that will not open still gets its name and its hash, which is
        # what identifies it. Nothing here is worth failing a finished build.
        pass
    if coords:
        # Which face of a variable file this slot actually is. Without it a
        # rebuild from this record takes the file's own default instance --
        # Merriweather ships Light as its default, so a family reproduced
        # without this is visibly lighter and nothing says why.
        face["instance"] = dict(sorted(coords.items()))
        # And what its designer calls that point, when they named it. The
        # subfamily above cannot say: on a variable file it describes the
        # default instance, which is routinely not the one built -- Bitter's
        # is Thin. "Medium" is what somebody looking the face up would search
        # for; wght 500 is what they would have to translate first.
        named = _instance_name(path, coords)
        if named:
            face["instance_name"] = named
    return face


def _instance_name(path: pathlib.Path, coords: dict[str, float]) -> str | None:
    """The designer's name for this point in the design space, if it has one.

    An unnamed point is ordinary -- a weight pinned between two instances has
    no name to find -- so this answers None rather than inventing one.
    """
    from .fontconf import variable_font

    found = variable_font(path)
    if not found:
        return None
    wanted = {tag: float(value) for tag, value in coords.items()}
    for label, at in found.named:
        if {tag: float(value) for tag, value in at.items()} == wanted:
            return label
    return None


def _sources(variant: Variant) -> dict:
    from .fontstamp import source_digest

    config: Config = variant.config
    return {style: _face(config.styles[style], source_digest(config.styles[style]),
                         config.coords(style))
            for style in STYLES if style in config.styles}


def _settings(variant: Variant) -> dict:
    """Every value the build resolved, knobs and shape both.

    All of them, including the ones nobody set. What reproduces a font is what
    it was built with, and "the default" is not a value a later version can be
    trusted to still agree on.

    The sizes are this variant's, not the config's: a second size list builds a
    folder of its own with a stamp of its own, and each says what is in it.
    """
    config: Config = variant.config
    settings: dict = dict(config.tuning.as_dict())
    settings.update({
        "intervals": config.intervals,
        "ranges": config.ranges,
        "fallbacks": config.fallbacks,
        "space_glyphs": config.space_glyphs,
        "sizes": list(variant.sizes),
    })
    if config.space_widths:
        settings["space_widths"] = {f"{cp:04X}": width for cp, width
                                    in sorted(config.space_widths.items())}
    if config.user_fallbacks:
        settings["user_fallbacks"] = {key: path.name for key, path
                                      in sorted(config.user_fallbacks.items())}
    return settings


def _files(variant: Variant, directory: pathlib.Path) -> dict:
    """What landed, per size, keyed as the filename spells it.

    `point_size` is here because the filename cannot hold it: the device parses
    the label with strtol into a uint8_t, so a family built at 13.5 ships as
    _14 and reads back as 14 to anything that trusts the name. This is the only
    place the size it was actually rasterized at survives.
    """
    from .fontbuild import style_metrics

    found = {}
    for size in variant.sizes:
        path = directory / f"{variant.name}_{size_label(size)}.cpfont"
        if not path.is_file():
            continue
        entry = {"file": path.name, "bytes": path.stat().st_size,
                 "glyphs": style_metrics(path).glyphs}
        if float(size) != float(size_label(size)):
            entry["point_size"] = size
        found[size_label(size)] = entry
    return found


def describe(variant: Variant, directory: pathlib.Path,
             fallbacks: list[str] | None = None,
             now: datetime.datetime | None = None) -> dict:
    """The provenance block for one built family."""
    config: Config = variant.config
    stamped = (now or datetime.datetime.now(datetime.timezone.utc))
    return {
        "at": stamped.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "by": f"crossglyph {version.installed()}",
        "cpfont_format": cpfont.CPFONT_VERSION,
        "config": config.path.name,
        "settings": _settings(variant),
        "sources": _sources(variant),
        "fallbacks": list(fallbacks or []),
        "files": _files(variant, directory),
    }

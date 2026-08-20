"""Decide which sizes of a family actually need rebuilding.

Rasterizing a full Cyrillic+Greek family at four sizes takes minutes, so the
loop is only pleasant if repeat runs are free. Each output directory keeps a
stamp of what produced its files; a size is rebuilt when its inputs changed or
its .cpfont went missing.

Content hashes rather than mtimes: these fonts arrive by copy, download and
rsync, and all three hand back a fresh mtime for bytes that did not change.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re

from . import cpfont, spacefont
from .fontconf import STYLES, Variant, size_label

STAMP_NAME = ".crossglyph.json"
STAMP_VERSION = 1

# The converter is our own module now, so its source is hashed directly rather
# than a referenced script's path being resolved and read.
#
# tuning.py counts as converter source: coverage_lut() decides the bytes of
# every glyph, and hashing only convert.py meant a change to that curve left
# every built family looking current. It bit exactly once -- inverting gamma's
# sense would have shipped stale .cpfonts for anyone with `gamma` in a config,
# and only escaped notice because convert.py happened to change too.
CONVERTER_SOURCES = (pathlib.Path(cpfont.convert.__file__),
                     pathlib.Path(cpfont.tuning.__file__))


def source_digest(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _chain_digests(config) -> dict[int, list[str]]:
    """Every fallback face each style would open, hashed, in order.

    The generated space font is left out. It is not on disk until a build
    makes it, and its bytes differ run to run whatever its widths are, which
    is why `space_glyphs` hashes the spec instead.
    """
    from . import fontbuild

    space = fontbuild.space_font_path(config.space_widths)
    return {style_id: [source_digest(path) for face in faces
                       for path in [pathlib.Path(face)] if path != space]
            for style_id, faces in sorted(
                fontbuild.fallback_chain(config).items())}


def digest(variant: Variant, size: float) -> str:
    """Everything that can change the bytes of one .cpfont, hashed."""
    config = variant.config
    payload = {
        "name": variant.name,
        "size": size,
        "intervals": config.coverage,
        "fallbacks": config.fallbacks,
        "tuning": config.tuning.as_dict(),
        "styles": {s: source_digest(config.styles[s]) for s in STYLES if s in config.styles},
        # A variable font's slots share a file, so the hash of that file says
        # nothing about which face each one is: without the coordinates, moving
        # the bold slot's weight leaves every size looking current.
        "axes": {style: coords for style in STYLES if style in config.styles
                 for coords in [config.coords(style, size)] if coords},
        # Per style, in order. Which face supplies a codepoint is the chain's
        # answer, so a reorder, or a bold face newly dropped in the folder,
        # is a different font at settings that did not move.
        #
        # fontbuild imports this module, so the import is here rather than at
        # the top.
        "chain": _chain_digests(config),
        "converter": [source_digest(path) for path in CONVERTER_SOURCES],
        # The generated file is not hashed: fontTools stamps head.created, so
        # its bytes differ run to run while the font does not.
        "space_glyphs": (spacefont.spec_digest(config.space_widths)
                         if config.space_glyphs else False),
        "cpfont_version": cpfont.CPFONT_VERSION,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def size_key(size: float) -> str:
    """How a size is spelled in the stamp.

    One function so the three places that touch it cannot disagree: writing,
    looking up, and filtering on prune. Whole sizes lose the `.0` so that a
    stamp written before fractional sizes existed still matches.
    """
    return str(int(size)) if float(size).is_integer() else str(size)


def _read(directory: pathlib.Path) -> dict:
    """The stamp file as it stands, or an empty one.

    Missing, half-written, or not an object at all: there is one thing to do
    with a note this tool left itself and cannot read, which is write it again.
    """
    try:
        data = json.loads((directory / STAMP_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def read_stamp(directory: pathlib.Path) -> dict[str, str]:
    """Recorded size -> digest, empty when missing, unreadable or stale-schema."""
    data = _read(directory)
    if data.get("version") != STAMP_VERSION:
        return {}
    return {str(k): str(v) for k, v in (data.get("sizes") or {}).items()}


def read_built(directory: pathlib.Path) -> dict:
    """The provenance block, or nothing. Kept across a rewrite that has none.

    A prune rewrites the stamp to drop a size, and it knows nothing about what
    the family was made from. Reading it back means one removed size does not
    throw away the record of the build.

    No version check, unlike the digests: those are only meaningful to the
    schema that wrote them, while a record of how a family was made is worth
    keeping across whatever this file becomes.
    """
    return _read(directory).get("built") or {}


def write_stamp(directory: pathlib.Path, sizes: dict[float, str],
                built: dict | None = None) -> None:
    """Record what is current, and what made it.

    `built` is provenance, written when a build has just produced something.
    It is not part of what decides a rebuild -- `version` and the digests are
    -- so a stamp from before it existed goes on matching, and adding this
    rebuilds nothing.
    """
    directory.mkdir(parents=True, exist_ok=True)
    body: dict = {"version": STAMP_VERSION,
                  "sizes": {size_key(k): v for k, v in sorted(sizes.items())}}
    keep = built or read_built(directory)
    if keep:
        body["built"] = keep
    (directory / STAMP_NAME).write_text(json.dumps(body, indent=2,
                                                   ensure_ascii=False),
                                        encoding="utf-8")


def cpfont_path(directory: pathlib.Path, variant: Variant,
                size: float) -> pathlib.Path:
    """Where one size lands on the card.

    The filename carries the *label*, not the size it was rasterized at: the
    device parses it with strtol into a uint8_t, so a fractional size could not
    be named there at all. Nothing reads a point size out of the file, so a
    13.5 pt build shipped as `_14` renders 13.5 pt glyphs under a "14" in the
    menu. See fontconf.size_label.
    """
    return directory / f"{variant.name}_{size_label(size)}.cpfont"


def stale_sizes(variant: Variant, directory: pathlib.Path,
                force: bool = False) -> list[float]:
    if force:
        return list(variant.sizes)
    stamp = read_stamp(directory)
    stale = []
    for size in variant.sizes:
        if stamp.get(size_key(size)) != digest(variant, size):
            stale.append(size)
        elif not cpfont_path(directory, variant, size).is_file():
            stale.append(size)
    return stale


def prune(directory: pathlib.Path, variant: Variant) -> list[pathlib.Path]:
    """Drop .cpfont files for sizes no longer in the config.

    Only files this variant would itself produce are considered, so a family
    directory shared with anything else is left alone.
    """
    # Labels, not sizes: the filename carries the rounded label, so a variant
    # built at 13.5 owns Name_14.cpfont and comparing against 13.5 would delete
    # the file it just wrote.
    keep = {size_label(size) for size in variant.sizes}
    pattern = re.compile(rf"^{re.escape(variant.name)}_(\d+)\.cpfont$")
    removed = []
    for path in sorted(directory.glob("*.cpfont")):
        match = pattern.match(path.name)
        if match and int(match.group(1)) not in keep:
            path.unlink()
            removed.append(path)
    if removed:
        # The stamp is keyed by the size that was built, which may be
        # fractional -- so it is the label of each key that has to be kept.
        stamp = read_stamp(directory)
        write_stamp(directory, {float(k): v for k, v in stamp.items()
                                if size_label(float(k)) in keep})
    return removed

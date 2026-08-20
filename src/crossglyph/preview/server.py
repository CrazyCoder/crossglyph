"""The preview server: knobs in as JSON, a page of type out as a PNG.

A shim over the preview package and nothing more. All the behaviour is a layer
down, so this file is the one to delete when the static web version can call
the wasm module directly from the browser. See docs/preview.md.
"""
from __future__ import annotations

import argparse
import contextlib
import functools
import io
import ipaddress
import json
import os
import pathlib
import sys
import threading
import time

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import (
        FileResponse,
        JSONResponse,
        Response,
        StreamingResponse,
    )
    from pydantic import BaseModel, Field
    from starlette.background import BackgroundTask
except ModuleNotFoundError as exc:      # pragma: no cover - install guidance
    raise SystemExit(
        f"the preview needs its web dependencies ({exc.name}). Install them "
        f"with:\n  uv sync") from exc

import freetype
from fontTools.ttLib import TTFont, TTLibError
from PIL import Image

from .. import (
    daemon,
    fontbuild,
    fontconf,
    install,
    layout,
    updateconf,
    updates,
    upgrade,
    version,
)
from ..cpfont.convert import (
    BASE_INTERVALS,
    INTERVAL_PRESETS,
    MAX_INTERVALS,
    FontBuildError,
    figure_glyph_overrides,
    gsub_ligature_sequences,
)
from ..cpfont.faces import open_face
from ..cpfont.tuning import LineHeight, Tuning
from ..fontconf import STYLES, Config, FontConfigError
from ..render import RenderCoreMissing, image, stamp
from . import (
    BOLD,
    BOLD_ITALIC,
    ITALIC,
    REGULAR,
    SAMPLE_TEXT,
    SAMPLES,
    Drawable,
    PageSpec,
    build_font,
    built_coverage,
    coverage_for,
    faces_for,
    fallback_split,
    narrowed,
    page_codepoints,
    presets_covering,
    preview_page,
)

app = FastAPI(title="CrossGlyph font preview")

#: What to call each face when reporting which ones are loaded.
FACE_NAMES = {REGULAR: "regular", BOLD: "bold", ITALIC: "italic",
              BOLD_ITALIC: "bold italic"}

STATIC = pathlib.Path(__file__).parent / "static"

#: fontconf's style names, which is what family_faces returns, to ours.
STYLE_IDS = {"regular": REGULAR, "bold": BOLD, "italic": ITALIC,
             "bolditalic": BOLD_ITALIC}
STYLE_NAMES = {style: name for name, style in STYLE_IDS.items()}

_sources: dict[int, pathlib.Path] = {}
_family: str | None = None

#: Presentation metadata sits above the simulated framebuffer. Keep the label
#: process-stable: an update only changes the version after the preview restarts.
WATERMARK = f"CrossGlyph {version.installed()}"
WATERMARK_INSET = 5

#: The glyphs needed by `WATERMARK`, including any MAJOR.MINOR.PATCH version.
#: Each byte is one six-pixel row from Spleen 6x12 2.2.0. This is a true bitmap
#: font, not a thresholded outline, so every stroke lands on the pixel grid.
#: Spleen is BSD-2-Clause; THIRD-PARTY-NOTICES.md carries its notice.
_SPLEEN_6X12 = {
    " ": bytes.fromhex("00 00 00 00 00 00 00 00 00 00 00 00"),
    ".": bytes.fromhex("00 00 00 00 00 00 00 00 20 00 00 00"),
    "0": bytes.fromhex("00 70 88 98 a8 c8 88 88 70 00 00 00"),
    "1": bytes.fromhex("00 20 60 20 20 20 20 20 70 00 00 00"),
    "2": bytes.fromhex("00 70 88 08 08 70 80 80 f8 00 00 00"),
    "3": bytes.fromhex("00 70 88 08 30 08 08 88 70 00 00 00"),
    "4": bytes.fromhex("00 80 80 90 90 90 f8 10 10 00 00 00"),
    "5": bytes.fromhex("00 f8 80 80 f0 08 08 08 f0 00 00 00"),
    "6": bytes.fromhex("00 70 80 80 f0 88 88 88 70 00 00 00"),
    "7": bytes.fromhex("00 f8 88 08 10 20 20 20 20 00 00 00"),
    "8": bytes.fromhex("00 70 88 88 70 88 88 88 70 00 00 00"),
    "9": bytes.fromhex("00 70 88 88 88 78 08 08 70 00 00 00"),
    "C": bytes.fromhex("00 78 80 80 80 80 80 80 78 00 00 00"),
    "G": bytes.fromhex("00 78 80 80 b8 88 88 88 78 00 00 00"),
    "h": bytes.fromhex("00 80 80 f0 88 88 88 88 88 00 00 00"),
    "l": bytes.fromhex("00 40 40 40 40 40 40 40 30 00 00 00"),
    "o": bytes.fromhex("00 00 00 70 88 88 88 88 70 00 00 00"),
    "p": bytes.fromhex("00 00 00 f0 88 88 88 88 f0 80 80 80"),
    "r": bytes.fromhex("00 00 00 78 88 80 80 80 80 00 00 00"),
    "s": bytes.fromhex("00 00 00 78 80 70 08 08 f0 00 00 00"),
    "y": bytes.fromhex("00 00 00 88 88 88 88 88 78 08 08 f0"),
}
_SPLEEN_SIZE = (6, 12)


def _watermark_mask(text: str) -> Image.Image:
    """Compose Spleen glyph rows into one reusable one-bit label."""
    width, height = _SPLEEN_SIZE
    mask = Image.new("1", (width * len(text), height))
    for index, char in enumerate(text):
        glyph = Image.frombytes("1", _SPLEEN_SIZE, _SPLEEN_6X12[char])
        mask.paste(glyph, (index * width, 0))
    return mask


WATERMARK_MASK = _watermark_mask(WATERMARK)


def _watermark(page: Image.Image, *, inverted: bool = False) -> Image.Image:
    """Add the generator and version to the bottom-right of a rendered page."""
    left = page.width - WATERMARK_INSET - WATERMARK_MASK.width
    top = page.height - WATERMARK_INSET - WATERMARK_MASK.height
    page.paste(image.LIGHT if inverted else image.DARK, (left, top),
               WATERMARK_MASK)
    return page


def set_font_source(path: pathlib.Path | str | None, *,
                    family: str | None = None, **faces) -> None:
    """The faces a render uses when the request names no family.

    `path` is the regular face; bold, italic and bold_italic are optional and
    fall back to regular when absent, exactly as they would on the device.
    `family` is the name these faces came from, when they came from one -- the
    picker shows it as the current choice rather than as a fifth entry.
    """
    global _sources, _family
    _family = family
    if path is None:
        _sources = {}
        return
    _sources = {REGULAR: pathlib.Path(path)}
    for name, style in (("bold", BOLD), ("italic", ITALIC),
                        ("bold_italic", BOLD_ITALIC)):
        if faces.get(name):
            _sources[style] = pathlib.Path(faces[name])


def _family_styles(family: str) -> tuple[tuple[int, str], ...]:
    """sources_for's answer in a form that is safe to hand out twice.

    Cached because resolving a family walks the whole source folder -- see
    family_config -- and the answer only moves when the files do.
    """
    return _styles_cached(str(fontbuild.SOURCE_DIR), family)


@functools.lru_cache(maxsize=16)
def _styles_cached(source: str, family: str) -> tuple[tuple[int, str], ...]:
    del source                          # in the key, not the body
    return tuple(sorted((STYLE_IDS[name], str(path))
                        for name, path in family_faces(family).items()
                        if name in STYLE_IDS))


def sources_for(family: str) -> dict[int, pathlib.Path]:
    """The faces of a family, keyed as the preview keys them.

    A fresh dict per call rather than a cached one: sync endpoints run in a
    threadpool, so a cached mapping would be shared between requests in flight.
    """
    return {style: pathlib.Path(path) for style, path in _family_styles(family)}


def axes_for(family: str, size: float,
             panel: dict | None = None) -> tuple[tuple[int, tuple], ...]:
    """A family's per-style design coordinates, keyed and shaped for a cache.

    Empty for a static family. The optical size axis follows the size on the
    page, which is why this takes one -- the page is a build like any other,
    and a preview at 13 pt that showed the 18 pt optical cut would be showing
    a face the card will never carry.
    """
    if family:
        config = family_config(family)
        pairs = [(STYLE_IDS[style], panel_coords(config, style, size, panel))
                 for style in fontconf.STYLES if style in config.styles]
    else:
        # Started on files rather than on a family, so there is no config to
        # consult and no panel to lay over it: each face is asked for its own
        # slot's instance directly. Without this a variable file named with
        # --font draws at its default instance, which for Merriweather is Light.
        pairs = [(style, fontconf.slot_coords(path, STYLE_NAMES[style], size))
                 for style, path in _sources.items()]
    return tuple((style, tuple(sorted(coords.items())))
                 for style, coords in pairs if coords)


#: The coverage presets the panel offers, in the website's own order and
#: wording (crosspointreader.com/fonts, "Additional Unicode Coverage"). `base`
#: is not among them: the converter adds it to every build itself.
COVERAGE_PRESETS = [
    ("reading", "Reading", "Fiction"), ("default", "Default", "CrossPoint"),
    ("latin-ext", "Latin Extended", ""), ("greek", "Greek", ""),
    ("cyrillic", "Cyrillic", ""), ("vietnamese", "Vietnamese", ""),
    ("hebrew", "Hebrew", ""), ("arabic", "Arabic", "Farsi, Urdu"),
    ("armenian", "Armenian", ""), ("georgian", "Georgian", ""),
    ("ethiopic", "Ethiopic", ""), ("cherokee", "Cherokee", ""),
    ("tifinagh", "Tifinagh", ""), ("bengali", "Bengali", ""),
    ("thai", "Thai", ""), ("hangul", "Hangul", "Korean"),
    ("cjk-sc", "Chinese", "Simplified"), ("cjk-tc", "Chinese", "Traditional"),
    ("cjk-jp", "Japanese", ""), ("symbols", "Symbols & Arrows", ""),
    ("ipa-chars", "IPA characters", ""),
]


def _fallback_family(path: pathlib.Path | None,
                     regulars: dict[str, str]) -> str:
    """Which family a fallback file belongs to, for the picker.

    The config stores a file, since that is what the converter takes; the panel
    offers families, because picking "the regular of Noto Sans Symbols" is the
    only sane way to choose one. This is the trip back.
    """
    return regulars.get(str(path), "") if path else ""


#: The two slots the panel drives, and which style keys each one covers. The
#: italic slots follow their roman: a family's italic is its text weight in
#: italic, not a weight of its own.
WEIGHT_SLOTS = {"text": ("regular", "italic"), "bold": ("bold", "bolditalic")}

#: Not offered on the page: it follows the size being previewed, so a control
#: for it would be a second, disagreeing way to say what size this is.
FOLLOWS_SIZE = "opsz"


def variable_entry(config: Config) -> dict | None:
    """What the panel needs to offer a variable family's instances, or None.

    Read from the regular slot's file, which is the one whose named instances
    the pickers list. The italic file is asked for the same coordinates rather
    than for its own names -- a family whose text weight is SemiBold is
    SemiBold in italic too.
    """
    regular = config.styles.get("regular")
    font = fontconf.variable_font(regular) if regular else None
    if font is None:
        return None
    # Every axis the font has, minus the one that follows the size. These are
    # the sliders, less the weight, which is the two pickers instead.
    axes = [{"tag": tag, "min": low, "default": default, "max": high}
            for tag, (low, default, high) in font.axes.items()
            if tag != FOLLOWS_SIZE]
    weights = {slot: config.coords(styles[0]).get("wght")
               for slot, styles in WEIGHT_SLOTS.items()
               if styles[0] in config.styles}
    coords = config.coords("regular")
    # Where each slider sits, which is the config's coordinate or, for an axis
    # it says nothing about, the font's own default -- the value the row is
    # built at either way. A slider whose position the panel could not name
    # would read as an unsaved change on a page nobody had touched.
    other = {axis["tag"]: coords.get(axis["tag"], axis["default"])
             for axis in axes if axis["tag"] != "wght"}
    # A face whose only axis is optical size has nothing to offer here, and an
    # empty panel section is worse than none.
    if not other and not any(value is not None for value in weights.values()):
        return None
    return {
        "axes": axes,
        # Name and weight per named instance, in the font's own order.
        "instances": [{"name": name, "wght": coords.get("wght")}
                      for name, coords in font.named if "wght" in coords],
        "weights": weights,
        "other": other,
    }


def panel_coords(config: Config, style: str, size: float | None,
                 panel: dict | None) -> dict[str, float]:
    """One slot's coordinates with the panel's choices laid over the config's.

    The page is the only thing saying what this font looks like right now, so
    what it shows wins over what the file was left saying -- the same rule the
    knobs follow. An empty panel leaves the config's own answer alone.
    """
    coords = config.coords(style, size)
    if not coords or not panel:
        return coords
    font = fontconf.variable_font(config.styles[style])
    axes = font.axes if font else {}
    for slot, styles in WEIGHT_SLOTS.items():
        if style in styles and panel.get(slot) is not None and "wght" in axes:
            coords["wght"] = float(panel[slot])
    # Only axes this face actually has. A tag it does not carry would reach the
    # rasterizer, which ignores it, and then a save would write a config that
    # will not parse -- an error about a font that is fine.
    for tag, value in panel.items():
        if tag not in WEIGHT_SLOTS and tag != FOLLOWS_SIZE and tag in axes:
            coords[tag] = float(value)
    # Clamped here as well as in the config, because this arrives from a page.
    for tag in list(coords):
        if tag in axes:
            low, _, high = axes[tag]
            coords[tag] = max(low, min(high, coords[tag]))
    return coords


def _axis_note(config: Config, style: str) -> str:
    """A slot's design coordinates, for the badge that names its file.

    Automatic `opsz` follows the size on the page and says nothing about which
    face this slot is. An explicit pin identifies the face and is shown.
    """
    pinned = config.axis_overrides.get(style, {})
    coords = {
        tag: value for tag, value in config.coords(style).items()
        if tag != FOLLOWS_SIZE or tag in pinned
    }
    if not coords:
        return ""
    return " at " + ", ".join(f"{tag} {value:g}"
                              for tag, value in sorted(coords.items()))


#: What a request can get wrong, as opposed to what the server can. A family
#: name the folder does not have, a size that will not parse, a coordinate off
#: an axis: every one of them is something the page sent, so every one is a 422
#: with the reason in it rather than a traceback.
CLIENT_ERRORS = (ValueError, TypeError, LookupError, FontConfigError)

#: Which kind of failure a render hit, for the page to headline. One status
#: cannot say this: a knob the converter would not take, a family whose files
#: have moved and a font file nobody can read are all 422, and a single
#: headline over the three of them names the wrong thing twice.
#:
#: A response header rather than a field in the body, following x-undrawn and
#: x-coverage-fix below. The body of a failed request is FastAPI's
#: {"detail": ...} and /save reads that same shape, so widening it here would
#: reach a panel that has nothing to do with rendering.
FAULT_HEADER = "x-fault"


def _freetype_said(exc: BaseException) -> str:
    """FreeType's own words, without freetype-py's wrapper around them.

    Its __str__ is `FT_Exception:  (cannot open resource)` -- the class name,
    two spaces, and the message in brackets. The class name means nothing to
    a reader and the brackets are not punctuation they can act on.

    One bracket off each end and only a matched pair, so a message carrying
    brackets of its own comes through whole. str.strip() takes characters
    rather than an affix and would eat both of a trailing `(x))`.
    """
    inside = str(exc).partition(":")[2].strip()
    if inside.startswith("(") and inside.endswith(")"):
        inside = inside[1:-1].strip()
    return inside or str(exc)


def _fault(exc: BaseException, faces: dict | None) -> tuple[str, str]:
    """Which kind of failure this render hit, and the sentence to show for it.

    `faces` is the style-to-path mapping the render had resolved, or None when
    it failed before there was one. It is where the file name in a font fault
    comes from: FreeType says what went wrong and never which file it was
    reading, so without this the reader is told "cannot open resource" about
    nothing in particular.
    """
    detail = str(exc).strip()
    if isinstance(exc, SystemExit):
        # sys.exit("reason") carries one; sys.exit(1) does not, and str() of
        # an int code is the digit, which would reach the panel as the whole
        # message. Both exits this path can reach carry their reason.
        reason = "" if isinstance(exc.code, int) else detail
        return "converter", reason or ("the converter rejected this "
                                       "combination; see the server log")
    if isinstance(exc, freetype.FT_Exception):
        return "font", _unreadable(faces, _freetype_said(exc))
    # Already names the file it was reading, and says what to do about it.
    if isinstance(exc, FontBuildError):
        return "font", detail
    if isinstance(exc, LookupError):
        return "family", detail
    if isinstance(exc, FontConfigError):
        return "config", detail
    return "setting", detail or f"{type(exc).__name__} from the converter"


def _unreadable(faces: dict | None, said: str) -> str:
    """A font fault with the files named, since FreeType's message is not.

    Every face the build was given, and "one of" them where there is more
    than one: a fallback in the chain is as likely to be the unreadable one
    as the family's own face, and the error cannot say which. Sharing a
    folder is the ordinary case, so that is named once after the files
    instead of repeated down a column of paths.
    """
    paths = sorted({pathlib.Path(path) for path in (faces or {}).values()})
    if not paths:
        return said
    folders = {path.parent for path in paths}
    if len(folders) == 1:
        what, where = ", ".join(p.name for p in paths), f" in {folders.pop()}"
    else:
        what, where = ", ".join(str(p) for p in paths), ""
    if len(paths) > 1:
        what = f"one of {what}"
    return f"{said}. Reading {what}{where}."


#: The knobs that only do something when the font has the feature behind them.
#: Each answers with what the converter would actually apply, rather than with
#: the feature tag: a font can declare `liga` over rules whose glyphs have no
#: cmap entry, and those are dropped on the way into a .cpfont.
FEATURE_KNOBS = {"ligatures": gsub_ligature_sequences,
                 "figures": figure_glyph_overrides}


def file_stamp(path: pathlib.Path) -> tuple[str, int, int] | None:
    """A file's identity for a cache key, or None when it is not there.

    Everything asked about a face here is cached, because every family in the
    folder is asked on the way to the picker. Keyed on the stamp rather than
    on the path alone, as fontconf.variable_font is and for the same reason:
    a file replaced under a running preview is a new key, so it is read again
    rather than answered for out of the old one.
    """
    try:
        stat = path.stat()
    except OSError:
        return None
    return str(path), stat.st_mtime_ns, stat.st_size


def face_features(path: pathlib.Path) -> frozenset[str]:
    """Which of the feature knobs one face can answer."""
    known = file_stamp(path)
    return _face_features(*known) if known else frozenset(FEATURE_KNOBS)


@functools.lru_cache(maxsize=128)
def _face_features(path: str, mtime: int, size: int) -> frozenset[str]:
    """A face that will not open makes no claim either way, so it answers with
    all of them: greying a knob says the font cannot act on it, and that is
    not something to say about a file nobody could read. Whatever is wrong
    with it will be said properly by the build.
    """
    del mtime, size                 # in the key, not the body
    try:
        # The ligature walk names the rules it drops on stderr, which is worth
        # having during a build and is noise when the question is only whether
        # there are any.
        with contextlib.redirect_stderr(io.StringIO()):
            return frozenset(name for name, carries in FEATURE_KNOBS.items()
                             if carries(path))
    except (OSError, TTLibError):
        return frozenset(FEATURE_KNOBS)


def face_outlines(path: pathlib.Path) -> str:
    """What kind of outlines a face carries, lowercased: truetype, cff, ...

    Empty when FreeType will not say, which is what keeps a file nobody can
    read from being described. Stated per face because it decides which of
    FreeType's engines draws it, and only some of them darken stems.
    """
    known = file_stamp(path)
    return _face_outlines(*known) if known else ""


@functools.lru_cache(maxsize=128)
def _face_outlines(path: str, mtime: int, size: int) -> str:
    del mtime, size                 # in the key, not the body
    try:
        return open_face(path).get_format().decode().casefold()
    except (OSError, freetype.FT_Exception):
        return ""


def face_hinting(path: pathlib.Path) -> tuple[bool, bool]:
    """Whether the TrueType interpreter draws this face: (bytecode, tricky).

    `bytecode` is FreeType's own test for it, which is not "has a `prep`": a
    face with no glyph instructions, no `fpgm` and a `prep` of 7 bytes or fewer
    goes to the auto-hinter whatever the interpreter is set to (base/ftobjs.c,
    the `num_locations` clause). `tricky` is the face flag that exempts a font
    from that dispatch entirely, so its bytecode runs under `light` and `auto`
    too.

    The 7 is FreeType's own threshold and the reason this is not simply
    "non-empty": a `prep` that short is a stub that cannot do anything, and the
    bundled Literata is exactly that case. 2.13.2, which the wheel links, still
    hands such a face to the interpreter and gets an identical page out of both
    versions; a later FreeType skips it outright. Taking the newer rule greys
    the switch on the one family every new user opens, which is where a switch
    that draws the same page twice is least welcome.

    Both true when the face will not open, since greying is a claim and there
    is nothing to claim about a font nobody could read.
    """
    known = file_stamp(path)
    return _face_hinting(*known) if known else (True, True)


@functools.lru_cache(maxsize=128)
def _face_hinting(path: str, mtime: int, size: int) -> tuple[bool, bool]:
    del mtime, size                 # in the key, not the body
    try:
        tricky = open_face(path).is_tricky
    except (OSError, freetype.FT_Exception):
        return (True, True)
    try:
        with TTFont(path, lazy=True) as font:
            reader = font.reader
            if "glyf" not in reader:
                return (False, tricky)      # CFF: no interpreter involved
            bytecode = bool(font["maxp"].maxSizeOfInstructions
                            or len(reader["fpgm"] if "fpgm" in reader else b"")
                            or len(reader["prep"] if "prep" in reader else b"") > 7)
    except (OSError, TTLibError, KeyError):
        return (True, tricky)
    return (bytecode, tricky)


def family_outlines(config: Config) -> str:
    """The one format every face in the family carries, or "mixed".

    A family drawn by two engines is one the stem darkening rule cannot speak
    for, so it says so rather than picking the first face's answer.
    """
    kinds = {face_outlines(path) for path in set(config.styles.values())}
    return kinds.pop() if len(kinds) == 1 else "mixed"


def family_hinting(config: Config) -> dict[str, bool]:
    """face_hinting over a whole family, as the panel needs it.

    Any face counts, for the reason family_features gives: a family whose
    regular carries bytecode and whose bold does not still draws a different
    page when the interpreter changes.
    """
    flags = [face_hinting(path) for path in set(config.styles.values())]
    return {"bytecode": any(bytecode for bytecode, _ in flags),
            "tricky": any(tricky for _, tricky in flags)}


def family_features(config: Config) -> dict[str, bool]:
    """Which feature knobs this family's faces can answer, by knob name.

    Any face counts: a family whose bold has no ligatures but whose regular
    does still draws a different page with the switch off, and a knob greyed
    on the strength of one face would be a lie about the other three.
    """
    have: frozenset[str] = frozenset()
    for path in set(config.styles.values()):
        have |= face_features(path)
    return {name: name in have for name in FEATURE_KNOBS}


def family_entry(config: Config, regulars: dict[str, str] | None = None) -> dict:
    """One family as the picker and the panel need it.

    `tuning` is what the family is set to today: all.conf underneath its own
    .conf. That is the build the card would get, so it is where the knobs start
    and what the arrows compare against.

    `conf` is the file a save would write. For a family all.conf covers without
    naming, that file does not exist yet -- `derived` says so, because writing
    to all.conf instead would retune every family in the folder.
    """
    return {"name": config.name,
            "faces": sorted(FACE_NAMES[STYLE_IDS[style]]
                            for style in config.styles if style in STYLE_IDS),
            # By style rather than sorted by name, because the page shows one
            # badge per style and has to say which file is behind each. A
            # variable font puts the same file behind two of them, so the badge
            # carries the coordinates that tell those two apart -- otherwise it
            # reads as the same face listed twice.
            "files": {FACE_NAMES[STYLE_IDS[style]]: path.name + _axis_note(config, style)
                      for style, path in config.styles.items()
                      if style in STYLE_IDS},
            "tuning": config.tuning.as_dict(),
            # Which knobs this family can answer. A font with no ligature rules
            # and no `pnum` draws the same page whichever way those two are
            # set, and a control that cannot do anything should say so rather
            # than invite an experiment with no result.
            "features": family_features(config),
            # Which of FreeType's engines draws this family, since stem
            # darkening is not in all of them. Not a knob the font either has
            # or lacks: the hinting mode decides too, so the page is given the
            # fact and works the rule out for itself.
            "outlines": family_outlines(config),
            # The same shape again, for the interpreter knob: whether any face
            # carries bytecode for it to run, and whether any is tricky, which
            # is what keeps that face off the auto-hinter in every mode.
            **family_hinting(config),
            # None for a static family, which is what hides the axis controls.
            "variable": variable_entry(config),
            "conf": (config.path.name if not config.derived
                     else f"{config.name.lower()}.conf"),
            "derived": config.derived,
            # Whether this is the family that ships with the tool rather than
            # one of yours. It is in the picker whatever else is there, so
            # saying so is what stops it looking like a font you put in the
            # folder and forgot -- and what explains why Build all leaves it.
            "bundled": (config.styles.get("regular", config.path).parent
                        == fontbuild.STARTER_DIR),
            # What the family builds as, which is the export panel's half of
            # the same file. `sizes` is what the reader's Font Size setting
            # lists, one entry each, not the size on screen.
            "export": {
                # What the family is called on the device and in the folder a
                # build writes, which is the picker's own label: a source file
                # can be named MerriweatherSansCondensed and a reader's Font
                # list is a phone-sized screen.
                "name": config.name,
                "sizes": " ".join(fontconf.size_spelling(size)
                                  for size in config.sizes),
                # The second family the same faces build, if the config asks
                # for one: <name><mod_suffix> at its own sizes.
                "sizes_mod": " ".join(fontconf.size_spelling(size)
                                      for size in config.sizes_mod),
                "mod_suffix": config.mod_suffix,
                "intervals": config.intervals,
                "ranges": config.ranges,
                "fallbacks": config.fallbacks,
                "fallback1": _fallback_family(
                    config.user_fallbacks.get("fallback_regular"),
                    regulars or {}),
                "fallback2": _fallback_family(
                    config.user_fallbacks.get("fallback2_regular"),
                    regulars or {}),
            }}


def families() -> list[dict]:
    """Every family the font source folder offers, with what each is set to.

    One walk of the folder answers all of it, so the picker can say what
    changing to a family will load without a round trip per entry.
    """
    configs = fontbuild.offered(fontbuild.SOURCE_DIR)[0]
    # Every family's regular face, so a fallback file can be reported as the
    # family it belongs to without a second walk per entry.
    regulars = {str(config.styles["regular"]): config.name
                for config in configs if "regular" in config.styles}
    return [family_entry(config, regulars) for config in configs]


class PageKnobs(BaseModel):
    device: str = "x4"
    margin: int = 5
    alignment: str = "justify"
    hyphenation: bool = False
    extra_paragraph_spacing: bool = True
    line_spacing: str = "normal"
    language: str = "en"
    antialiased: bool = True
    inverted: bool = False


class RenderRequest(BaseModel):
    # Fractional: FreeType's char size is 26.6 fixed point, and the integer
    # step is 2.08 px/em at 150 DPI -- too coarse to tune against.
    size: float = Field(13, ge=6, le=64)
    text: str = SAMPLE_TEXT
    #: A family from the font source folder. Empty means the one the app was
    #: started on, which is the only choice when it was started on a file.
    family: str = ""
    tuning: dict = Field(default_factory=dict)
    page: PageKnobs = Field(default_factory=PageKnobs)
    #: The export panel's fallback settings, as it currently shows them rather
    #: than as the config has them: turning the checkbox on is a change you
    #: want to see. They only reach a build when the text asks for a codepoint
    #: the family lacks, which on most pages is never.
    fallbacks: bool = False
    fallback1: str = ""
    fallback2: str = ""
    #: The coverage the build would carry. It decides whether the 15.7 MB CJK
    #: face is among the bundled ones, and it narrows what the page draws: the
    #: preview rasterizes the text, less anything this coverage would leave out
    #: of the built font, so what is on screen is what the device would show.
    #: None means the panel has not said yet, which is not the same as nothing
    #: ticked and must not blank the page.
    intervals: str | None = None
    #: Raw `(0xAAAA-0xBBBB)` ranges from the same panel, added to `intervals`.
    ranges: str | None = None
    #: A variable family's axis controls as the panel shows them: `text` and
    #: `bold` are weights, anything else is an axis tag. Empty for a static
    #: family, and for a variable one it means "whatever the config says".
    axes: dict[str, float] = Field(default_factory=dict)


def _cache_key(tuning: dict) -> tuple:
    """A hashable form of the posted tuning, for the build cache.

    JSON has no tuples, so `thresholds` arrives as a list -- and a list in an
    lru_cache key raises TypeError, which the caller turns into a 422 saying
    "unhashable type". thresholds is a documented knob and Tuning.as_dict()
    emits it as a list, so the round trip has to work.
    """
    return tuple(sorted(
        (name, tuple(value) if isinstance(value, list) else value)
        for name, value in tuning.items()))


def _tuning(items: tuple) -> Tuning:
    """A Tuning from the wire form, where line_height arrives as a number.

    Everything else on Tuning is a plain scalar, but line_height is a value
    with a unit -- a bare number is a multiple of the em, and `x` and `px`
    suffixes mean the font's own height and literal pixels. The panel sends
    the bare number; the .conf parser sends the same strings through the same
    LineHeight.parse, so the two agree.
    """
    fields = dict(items)
    # The panel spells the three cut points as one string, because they are one
    # choice and a <select> holds one value. A config spells them the same way.
    raw = fields.get("thresholds")
    if isinstance(raw, str):
        try:
            raw = tuple(int(part) for part in raw.replace(",", " ").split())
        except ValueError as exc:
            raise ValueError(f"thresholds must be three numbers, "
                             f"got {fields['thresholds']!r}") from exc
        fields["thresholds"] = raw
    # Its own check rather than Tuning's, which unpacks the triple and reports
    # "not enough values to unpack" -- true, and no help at all in a panel.
    if raw is not None and len(raw) != 3:
        raise ValueError(f"thresholds must be three numbers, got {raw!r}")
    raw = fields.get("line_height")
    if raw is None or raw == "":
        fields.pop("line_height", None)
    elif not isinstance(raw, LineHeight):
        fields["line_height"] = LineHeight.parse(str(raw))
    return Tuning(**fields)


# Keyed by family as well as coverage, since a family's `fallback_order` can
# reorder the set, so a workspace of them needs more than a handful of entries.
@functools.lru_cache(maxsize=32)
def _bundled_faces(source: str, intervals: str, family: str = "") -> tuple:
    """The families a build with this coverage would fill from, in its order.

    One entry per family, each a style map as fontbuild.pinned_faces returns,
    flattened to pairs so an lru_cache key can hold it.

    The family's own `fallback_order` decides the order where it sets one. It
    is a config key with no control on the page, so a render that ignored it
    would draw a chain the build does not use.

    Cached: this reads all.conf and stats a dozen files, and a render must not
    do that on every keystroke. Nothing here reads a font -- which of them is
    opened is build_font's decision, and only when the text needs one.

    Keyed on the source folder as well as the coverage, though only one folder
    is ever live: the alternative is a cache that answers for the folder the
    *last* caller had, which is a trap for anything that repoints SOURCE_DIR --
    the tests do, and a session that switched folders would too.
    """
    directory = fontbuild.fallback_dir(source)
    if directory is None:
        # Not fetched. The page draws with the family's own faces rather than
        # refusing: what the family covers is exactly what is being tuned, and
        # a blank page teaches nothing. The panel already says they are not
        # here, and has the button, a few rows under the box that asked.
        return ()
    entries = None
    if family:
        # LookupError alone: a name the folder no longer has is the picker
        # holding a remembered choice, and the render says so elsewhere. A
        # `fallback_order` this cannot resolve is a config the build would
        # refuse, so it travels to the panel rather than being drawn around.
        with contextlib.suppress(LookupError):
            config = family_config(family)
            if config.fallback_order.strip():
                entries = fontbuild.ordered_entries(config, intervals)
    if entries is None:
        entries = fontbuild.bundled_entries(intervals, directory)
    return tuple(tuple(sorted(entry.items())) for entry in entries)


@functools.lru_cache(maxsize=64)
def _worst_intervals(coverage: str, faces: tuple) -> int:
    """The most intervals any style of this family would carry, once built.

    CrossPoint refuses a style with more than MAX_INTERVALS of them and says
    nothing a reader can see, so the panel is where this belongs: the count is
    settled by the charmaps and the coverage, both of which are on screen
    before anybody presses Build.

    Kept, because a render runs on every keystroke in the sample text and the
    answer moves only when a box is ticked or a fallback picked.
    """
    asked = fontbuild.asked_intervals(coverage)
    return max((len(fontbuild.interval_runs(
                    asked, fontbuild.chain_codepoints(chain, asked)))
                for _style, chain in faces), default=0)


def _bundled_load_or_zero(request: RenderRequest) -> int:
    """What this coverage would cost with the bundled faces on, or 0.

    0 when they are already on, when they would not bring it under the cap, or
    when anything about the question could not be answered. The panel offers
    the number only where it is an answer.
    """
    if request.fallbacks:
        return 0
    try:
        under = interval_load(request.model_copy(update={"fallbacks": True}))
    except (LookupError, OSError, FontConfigError, SystemExit):
        return 0
    return under if 0 < under <= MAX_INTERVALS else 0


def _interval_load_or_zero(request: RenderRequest) -> int:
    """interval_load, and 0 for anything that stops it answering.

    This rides on a response the page already has, and a page that drew is
    worth more than a count of what a build of it would carry. A family whose
    faces have moved since, a fallback pick that no longer resolves: the
    render got its own picture from somewhere, and this says nothing rather
    than turning that into an error.

    SystemExit among them, and named rather than implied: `resolve_intervals`
    exits on a token it does not know, and a raw range half typed into the
    field is one of those on every keystroke until the bracket closes. It is a
    BaseException, so `except Exception` here would let it past and out of the
    app.
    """
    try:
        return interval_load(request)
    except (LookupError, OSError, FontConfigError, SystemExit):
        return 0


def interval_load(request: RenderRequest) -> int:
    """What a build of the panel as it stands would write, at its worst style.

    From the request and not from the .conf. A build writes the panel to the
    file before it runs, so what is on screen is what would be built, and a
    count read from the saved file would be one save behind the boxes being
    ticked.

    Every style the family has, rather than the ones this page happens to set:
    the cap is per style, and one style over it is a file the device refuses
    whole.
    """
    if request.intervals is None and request.ranges is None:
        return 0                     # the panel said nothing about coverage
    # An empty string is the narrowest build there is and not an absent one:
    # every box clear still carries `base`, so it still has a count.
    coverage = ",".join(part for part in (request.intervals, request.ranges)
                        if part)
    styles = sources_for(request.family) if request.family else _sources
    offered = fallbacks_for(request)
    return _worst_intervals(coverage, tuple(sorted(
        (style, (str(path), *offered.get(style, ())))
        for style, path in styles.items())))


def fallbacks_for(request: RenderRequest) -> dict[int, tuple[str, ...]]:
    """The faces this request would fall back to, per style, in order.

    The two chosen families first, then the bundled set -- the same order
    fontbuild.fallback_chain assembles, so a codepoint the family lacks is
    drawn from the face the build would have drawn it from, in the style it is
    set in. An entry lends its own face for a style where it has one, and its
    regular face otherwise.
    """
    entries: list[dict[str, pathlib.Path]] = []
    for name in (request.fallback1, request.fallback2):
        if not name:
            continue
        regular = sources_for(name).get(REGULAR)
        if regular is None:
            raise LookupError(f"the {name!r} family has no regular face to "
                              f"fall back to")
        # Through pinned_faces, because a save keeps this pick as one filename
        # and the build finds the other three beside it. A family whose config
        # names a bold discovery would not have found is where the two answers
        # part, and the build's is the one the page has to show.
        entries.append(fontbuild.pinned_faces(regular))
    if request.fallbacks:
        # Not said and nothing ticked pick the same faces here: the coverage
        # only decides whether a CJK script was asked for, and neither answers
        # yes. The distinction the render draws on belongs to built_coverage,
        # which is the only place it means anything -- and a None reaching the
        # split below is an AttributeError out of a request nobody has to send
        # wrongly to make.
        entries += [dict(entry) for entry in
                    _bundled_faces(str(fontbuild.SOURCE_DIR),
                                   request.intervals or "", request.family)]

    return {style_id: tuple(fontbuild.chain_for(entries, style))
            for style_id, style in enumerate(STYLES)}


# One entry per style rather than per render, so the depth is four times the
# renders it holds.
@functools.lru_cache(maxsize=128)
def resolved_fallbacks(sources: tuple, coverage: tuple,
                       fallbacks: tuple) -> Drawable:
    """The faces worth opening and the codepoints none of them has.

    Both come out of one walk of the list and both are wanted on every render:
    the faces to build with, and the leftovers to say the page cannot draw.

    Cached because which face supplies a missing codepoint depends on the
    family and the text, not on the knobs -- so asking once and remembering is
    what keeps tuning responsive on a page that does need a fallback. Without
    it every turn of gamma reopens the whole bundled set to find the same one
    face.
    """
    return fallback_split(dict(sources), coverage, fallbacks)


@functools.lru_cache(maxsize=32)
def build_font_cached(sources: tuple, size: float, coverage: tuple,
                      tuning_items: tuple, fallbacks: tuple = (),
                      axes: tuple = ()) -> bytes:
    """A knob that does not touch the font should not pay for a build.

    Keyed on the coverage rather than the text it came from, so editing the
    sample text only rebuilds when it brings in a character the last build did
    not have -- which most edits do not. Every key is a tuple because an
    lru_cache key has to hash, which is why the chains arrive as pairs."""
    return build_font(dict(sources), size, tuning=_tuning(tuning_items),
                      coverage=coverage, fallbacks=dict(fallbacks),
                      axes={style: dict(coords) for style, coords in axes})


@app.post("/render")
def render(request: RenderRequest) -> Response:
    if not _sources and not request.family:
        raise HTTPException(503, "no font source; start with --font")
    # Named in a font fault below, and set before the try because the failure
    # can land before there is anything to name.
    sources: dict | None = None
    try:
        spec = PageSpec(**request.page.model_dump())
        spec.to_call_args()                      # validate before rasterizing
        sources = sources_for(request.family) if request.family else _sources
        # Only the styles the text is actually set in. Every style in the build
        # is a full rasterization of the coverage, so a plain paragraph would
        # otherwise pay four times over for three faces nothing on the page
        # wears -- and with a fallback in the list, four GPOS reads of it.
        sources = faces_for(request.text, sources)
        keyed = tuple(sorted((style, str(path))
                             for style, path in sources.items()))
        # What the text needs, then what this coverage would actually build of
        # it. Narrowed before the faces are asked, so a character the build
        # would drop is drawn the way the device draws it: not at all.
        wanted = coverage_for(request.text, sources)
        built = built_coverage(request.intervals, request.ranges)
        coverage = narrowed(wanted, built)
        uncovered: frozenset[int] = frozenset() if built is None else (
            frozenset(page_codepoints(request.text)) - built)
        # Per style, because a chain can hold a bold face the regular one does
        # not, and because what a style cannot draw is that style's own face
        # measured against that style's own chain.
        offered = fallbacks_for(request)
        drawable = {style: resolved_fallbacks(((style, str(path)),), coverage,
                                              offered.get(style, ()))
                    for style, path in sources.items()}
        font = build_font_cached(
            keyed, request.size, coverage, _cache_key(request.tuning),
            tuple(sorted((style, tuple(str(path) for path in resolved.faces))
                         for style, resolved in drawable.items())),
            axes_for(request.family, request.size, request.axes))
        # What nothing can draw, narrowed to what is actually on the page: the
        # build's coverage carries the output codepoint of every ligature the
        # faces could form, and a face whose GSUB names an `ff` it has no cmap
        # entry for is not a page with a hole in it (see page_codepoints).
        #
        # Narrowed rather than asked again, because asking again is a second
        # walk of every fallback face. The page's codepoints are a subset of
        # the coverage, and whether a face supplies one does not depend on what
        # else was asked for, so the two agree over the codepoints they share.
        #
        # Across the styles on the page. A style that exists and has no glyph
        # draws nothing there, so a codepoint the bold style cannot reach is a
        # hole whatever the regular one has -- asking the faces together, as
        # one call for all of them did, answers only whether *some* style has
        # it. Coverage is the text's and not each run's, so this can name a
        # character the page happens to set only in the style that has it.
        # Faces of one family rarely differ that way, and the reverse silence
        # is the worse of the two.
        undrawn = frozenset().union(
            *(resolved.undrawn for resolved in drawable.values())
        ) & page_codepoints(request.text)
        page = _watermark(preview_page(font, request.text, spec),
                          inverted=spec.inverted)
    # SystemExit is deliberate and not paranoia: the converter is a script at
    # heart and calls sys.exit() on bad input rather than raising -- an
    # advanceY the .cpfont format cannot hold, which generate_cpfont_multistyle
    # exits on above 255 and a large `size` can reach on a loose-hhea face.
    # SystemExit is a
    # BaseException, so a bare `except ValueError` lets it past the handler and
    # out of the app entirely.
    except SystemExit as exc:
        kind, why = _fault(exc, sources)
        raise HTTPException(422, why, {FAULT_HEADER: kind}) from exc
    # FontBuildError from cpfont, not fontbuild: two classes share the name,
    # and the one this path can raise is the converter's, from
    # rasterize_font_style on a malformed face. The fontbuild one comes
    # from the family builder, which the preview never calls.
    #
    # FT_Exception comes from freetype-py itself and arrives first for a file
    # that is not a font at all -- the --font path is user input like any
    # other knob, so a face FreeType cannot parse is a 422 and not a 500.
    # LookupError is a family name the source folder does not have -- from the
    # picker that means a remembered choice whose files have since moved, which
    # is the reader's problem to see rather than a 500.
    except (*CLIENT_ERRORS, FontBuildError,
            freetype.FT_Exception) as exc:
        kind, why = _fault(exc, sources)
        raise HTTPException(422, why, {FAULT_HEADER: kind}) from exc
    # A workspace condition, not bad input -- the same class as having no font
    # source, which is already a 503. As a 422 it shows up in the panel's
    # status line as though the knob had been rejected.
    except RenderCoreMissing as exc:
        raise HTTPException(503, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc)) from exc

    buffer = io.BytesIO()
    page.save(buffer, format="PNG")
    # How many characters drew nothing, so the page can say so. A header rather
    # than a second request: it belongs to this page and not to the next one,
    # and the body is a PNG with nowhere to put it. Latin-1 is all a header
    # may carry, which is the other reason this is a count and not the
    # characters themselves.
    # Two ways a character comes out blank, and they have different answers:
    # no face on the list has it, or the coverage would not have built it.
    # The second names the presets that would carry it, so a blank page says
    # which box to tick rather than leaving it to be worked out.
    # And what a fetch would still bring *this* page. The count the panel got
    # at load speaks for the folder alone, which cannot answer for the CJK
    # face: that one comes only when something asks for it, so a folder can
    # hold every other face and be short of it. Without this the button hides
    # itself on a Japanese page and the note goes on to advise a family of
    # your own, with the face that would have drawn it a press away.
    return Response(buffer.getvalue(), media_type="image/png",
                    headers={"x-undrawn": str(len(undrawn)),
                             "x-uncovered": str(len(uncovered)),
                             "x-fallbacks-missing": str(len(
                                 fontbuild.missing_fallbacks(
                                     fontbuild.SOURCE_DIR,
                                     request.intervals or "", request.text))),
                             "x-coverage-fix":
                                 ",".join(presets_covering(uncovered)),
                             # What the device would refuse, before a build
                             # rather than after four of them. 0 when the
                             # count could not be worked out.
                             "x-intervals": str(_interval_load_or_zero(request)),
                             "x-interval-cap": str(MAX_INTERVALS),
                             # What the same coverage would cost with the
                             # bundled set on, when that is under the cap. The
                             # measured answer beats a general one: dropping a
                             # preset moves the count by too little to help,
                             # and nothing on screen says so.
                             "x-intervals-bundled":
                                 str(_bundled_load_or_zero(request))})


#: What the panel is allowed to write back, in the .conf's own spelling.
#: `size` is not among them: the conf's `sizes` is what the family ships, not
#: which one you are working at.
SAVED_KEYS = ("gamma", "thresholds", "weight", "slant", "letter_spacing",
              "word_spacing", "kerning", "ligatures", "hinting",
              "grayscale_hinting", "mono", "stem_darkening", "figures",
              "line_height")


#: The export keys, which are not tuning: they decide what a build contains
#: rather than how a glyph looks. `fallback_regular` and `fallback2_regular`
#: name one specific file, so they can only ever live in a family's own config.
EXPORT_KEYS = ("name", "sizes", "sizes_mod", "mod_suffix", "intervals",
               "ranges", "fallbacks", "fallback_regular", "fallback2_regular")


def axis_changes(panel: dict, config: Config) -> dict[str, str | None]:
    """The four style keys a save writes for a variable family.

    A slot whose coordinates are the ones discovery would pick anyway has its
    line removed rather than restated -- the same rule the knobs follow, and
    what keeps a config from freezing an automatic answer that should go on
    following the font.
    """
    changes: dict[str, str | None] = {}
    for style in fontconf.STYLES:
        path = config.styles.get(style)
        if path is None:
            continue
        wanted = panel_coords(config, style, None, panel)
        pinned = config.axis_overrides.get(style, {})
        # Against the automatic pick, which is this config with nothing pinned.
        plain = fontconf.slot_coords(path, style)
        if not wanted or (wanted == plain and FOLLOWS_SIZE not in pinned):
            changes[style] = None
            continue
        # The file relative to the config's own folder, so it stays portable --
        # the same form the fallback keys are written in.
        name = os.path.relpath(path, config.dir).replace("\\", "/")
        # Only the axes that differ from the automatic pick. A coordinate is an
        # override laid over the font's own instance, so restating the rest
        # says nothing -- and freezes a value that should go on following the
        # font if its designer ever moves that instance. An explicit optical
        # size remains a pin even at the font's default: automatic optical size
        # would move away from it for another build size.
        axes = ",".join(
            f"{tag}={value:g}" for tag, value in sorted(wanted.items())
            if plain.get(tag) != value or
            (tag == FOLLOWS_SIZE and tag in pinned))
        changes[style] = f"{name}@{axes}" if axes else name
    return changes


class SaveRequest(BaseModel):
    family: str
    tuning: dict = Field(default_factory=dict)
    #: A variable family's axis controls, as /render takes them. Absent leaves
    #: whatever the config says about them alone.
    axes: dict | None = None
    #: sizes, intervals, ranges, fallbacks, fallback1, fallback2 -- the last
    #: two as family names, which is how the panel offers them. Absent leaves
    #: that half of the config alone.
    export: dict | None = None


def _name_taken(names: set[str], config: Config) -> tuple[str, str] | None:
    """The family already building under one of `names`, and which one.

    Two families with one output name write over each other in the build
    folder, size by size, and which of them wins is whichever the walk reached
    last. Nothing downstream can tell them apart afterwards, so a name already
    taken is refused here rather than found later.

    Names rather than a name on both sides: a config carrying `sizes_mod`
    builds a second family called after the first, and landing on one of those
    is the same overwrite as landing on a family's own name.
    """
    folded = {name.casefold() for name in names}
    for other in fontbuild.offered(fontbuild.SOURCE_DIR)[0]:
        # The same family, reached twice: every family all.conf covers without
        # naming shares its path, so the family it was discovered under is what
        # tells those apart.
        if (other.path, other.family.casefold()) == (config.path,
                                                     config.family.casefold()):
            continue
        for variant in other.variants():
            if variant.name.casefold() in folded:
                return other.family, variant.name
    return None


def export_changes(request_export: dict, config: Config,
                   shared: dict[str, str]) -> dict[str, str | None]:
    """The export half of a save, as .conf keys.

    Fallbacks arrive as family names and go in as the file the converter
    takes: its regular face, relative to the config's own folder so the file
    stays portable.
    """
    wanted: dict[str, str | None] = {}

    # What the build calls this family, which is a name of its own rather than
    # the one the files happen to carry. It reaches a filename, so the same
    # strip the converter does is applied here and the page is told what it
    # got: sanitize_name answers "CustomFont" for a string with nothing usable
    # in it, which makes an empty field mean "whatever the files are called"
    # rather than a name.
    plain = fontconf.sanitize_name(config.family)
    raw_name = str(request_export.get("name", "")).strip()
    chosen = fontconf.sanitize_name(raw_name) if raw_name else plain
    wanted["name"] = chosen if chosen != plain else None

    sizes = str(request_export.get("sizes", "")).strip()
    if sizes:
        # Validated by the same parser the config uses, so a typo is a 422
        # here rather than a family that silently builds nothing.
        fontconf.parse_sizes(sizes, "sizes")
    wanted["sizes"] = sizes or None

    # The second family: its own sizes, and the suffix its name ends with. The
    # suffix means nothing without them, so it is written only alongside them --
    # and only when it differs from what the family would be called anyway.
    sizes_mod = str(request_export.get("sizes_mod", "")).strip()
    if sizes_mod:
        fontconf.parse_sizes(sizes_mod, "sizes_mod")
    wanted["sizes_mod"] = sizes_mod or None
    # sanitize_name answers "CustomFont" for a string with nothing usable in it,
    # which is right for a family name and wrong for a suffix: empty here means
    # "whatever the family would be called anyway", not a name of its own.
    raw_suffix = str(request_export.get("mod_suffix", "")).strip()
    suffix = fontconf.sanitize_name(raw_suffix) if raw_suffix else ""
    inherited_suffix = fontconf.sanitize_name(shared.get("mod_suffix", "Mod"))
    # `and suffix`, because an empty one is the absence of a key and not a key
    # set to nothing: written down, it comes back through sanitize_name as
    # "CustomFont" and the second family builds under that.
    wanted["mod_suffix"] = (
        suffix if sizes_mod and suffix and suffix != inherited_suffix else None)

    # Written even when it is empty, where every other key here is dropped at
    # that point. Nothing ticked is a coverage the panel can show and a build
    # can make, and a key that is absent hands the family the default instead.
    wanted["intervals"] = str(request_export.get("intervals", "")).strip()
    wanted["ranges"] = str(request_export.get("ranges", "")).strip() or None
    wanted["fallbacks"] = "yes" if request_export.get("fallbacks") else "no"

    for key, field in (("fallback_regular", "fallback1"),
                       ("fallback2_regular", "fallback2")):
        name = str(request_export.get(field, "")).strip()
        if not name:
            wanted[key] = None
            continue
        face = family_config(name).styles.get("regular")
        if face is None:
            raise LookupError(f"the {name!r} family has no regular face to "
                              f"fall back to")
        wanted[key] = os.path.relpath(face, config.dir).replace("\\", "/")

    # What this save would have the family build, now that the second one is
    # known too. Against what it builds today rather than always: the answer
    # costs a walk of the folder, and it can only have moved when one of these
    # three did.
    built = {chosen}
    if wanted["sizes_mod"]:
        built.add(chosen + (wanted["mod_suffix"] or inherited_suffix))
    if built != {variant.name for variant in config.variants()}:
        taken = _name_taken(built, config)
        if taken:
            raise ValueError(f"the {taken[0]} family already builds as "
                             f"{taken[1]}, and two of them would write over "
                             f"each other")

    # Only what differs from all.conf, the same rule the tuning half follows --
    # except for the two file keys, which all.conf cannot carry at all.
    return {key: (value if value != shared.get(key) else None)
            if key not in fontconf.PATH_KEYS else value
            for key, value in wanted.items()}


@app.post("/save")
def save(request: SaveRequest) -> dict:
    """Write the knobs into the family's own .conf, and say what moved.

    Only what differs from all.conf goes in the file, and a knob that returns
    to the shared value has its line removed rather than restated: the point of
    all.conf is that changing it moves every family, which stops being true the
    moment each family repeats its values back.
    """
    # Every knob, or none: this saves the state of a panel, and a partial post
    # would quietly write the converter's default over each knob it left out.
    missing = [key for key in SAVED_KEYS
               if key not in request.tuning and key != "line_height"]
    if missing:
        raise HTTPException(
            422, f"a save carries the whole panel; missing {', '.join(missing)}"
                 f" (line_height is the exception: absent is the font's own)")
    try:
        config = family_config(request.family)
        shared = fontconf.tuning_from(
            fontbuild.load_defaults(fontbuild.SOURCE_DIR), fontbuild.DEFAULTS_NAME)
        wanted = fontconf.tuning_values(_tuning(_cache_key(request.tuning)))
        inherited = fontconf.tuning_values(shared)
        changes = {key: (wanted[key] if wanted[key] != inherited[key] else None)
                   for key in SAVED_KEYS}
        # A family all.conf covers without naming has no file of its own, and
        # config.path is all.conf itself -- writing there would retune every
        # family in the folder. It gets its own, and the file names the family
        # outright rather than leaning on its filename, which cannot spell one
        # with a space in it.
        path = config.path
        if config.derived:
            path = fontbuild.conf_dir() / f"{config.name.lower()}.conf"
            path.parent.mkdir(parents=True, exist_ok=True)
            changes = {"family": config.family, **changes}
            # The bundled family's faces are in the package rather than the
            # folder. Saying where they are is what turns this from something
            # to look at into a family of yours: with `dir` written down it
            # resolves like any other config, and builds with the rest.
            folder = config.styles["regular"].parent
            if folder != fontbuild.SOURCE_DIR:
                changes = {"dir": str(folder), **changes}
        if request.export is not None:
            changes.update(export_changes(
                request.export, config,
                fontbuild.load_defaults(fontbuild.SOURCE_DIR)))
        if request.axes is not None:
            changes.update(axis_changes(request.axes, config))
        moved = fontconf.write_values(path, changes)
        # The folder just changed under us, so what was resolved from it is
        # no longer what it says -- including the read-back below.
        forget_families()
    except CLIENT_ERRORS as exc:
        raise HTTPException(422, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, f"could not write {exc.filename}: {exc}") from exc

    # Read back rather than echo: what the next build will use is what the file
    # now says, which is the only answer worth putting in front of anyone.
    #
    # By what the file now calls it, not by the name the page arrived with: a
    # rename is the one save after which the old output name addresses nothing,
    # and looking it up again would fail on the family that had just been
    # written. The `family` key never moves, so it is what a rename falls back
    # to once its own name is gone.
    asked = request.family
    if request.export is not None:
        asked = changes["name"] or config.family
    saved = family_config(asked)
    return {"conf": path.name, "moved": sorted(moved),
            # What the strip above made of the name, so the page shows the one
            # that landed rather than the one that was typed.
            "name": saved.name,
            "tuning": saved.tuning.as_dict()}


@app.get("/defaults")
def defaults() -> JSONResponse:
    """What the page starts from, so the sample text lives in one place.

    `families` is the picker's list and `family` the entry to select. When the
    app was started on a bare file there is no entry to select: `font` names
    it, and the page keeps it as a choice of its own at the top of the list.

    The page asks for this again whenever its tab comes back, so this is where
    a font dropped into the folder, or a config edited beside it, is noticed.
    """
    rescan()
    payload = {"text": SAMPLE_TEXT,
            # Every preset, in picker order, so switching between them is a
            # dropdown rather than a round trip. The page picks one of these
            # from the browser's own languages the first time it is opened.
            "samples": {tag: {"name": sample.name, "text": sample.text}
                        for tag, sample in SAMPLES.items()},
            "source": str(fontbuild.SOURCE_DIR),
            # What all.conf says, which is usually nothing, and where that
            # lands. The field holds the first so that leaving it empty goes
            # on meaning "wherever the default is" rather than freezing
            # today's answer into the file.
            "out": fontbuild.load_defaults(fontbuild.SOURCE_DIR)
                            .get("out", "").strip(),
            "out_resolved": str(fontbuild.output_dir()),
            # The ranges travel with each preset so the panel can work out for
            # itself which ticks another tick has already made. `reading` is
            # the converter's `default` and a good deal more, and a row of
            # boxes with nothing to say about that reads as five independent
            # choices. Every build carries `base` whatever is ticked, so it is
            # part of the answer and is sent alongside.
            "presets": [{"name": name, "label": label, "note": note,
                         "ranges": INTERVAL_PRESETS.get(name, [])}
                        for name, label, note in COVERAGE_PRESETS],
            "base": BASE_INTERVALS,
            # Whether the bundled faces are anywhere, so the panel can offer to
            # fetch them rather than let a build fail on them.
            "fallbacks": str(fontbuild.fallback_dir() or ""),
            # How many a fetch would still add. A folder can hold every face an
            # older version wanted and lack what this one added, so presence is
            # not the question the button asks.
            "fallbacks_missing": len(fontbuild.missing_fallbacks()),
            "font": _sources[REGULAR].name if _sources else None,
            "faces": sorted(FACE_NAMES[style] for style in _sources),
            "families": families(),
            "family": _family}
    # Explicitly uncacheable, like the page and its modules: this is the
    # answer to "what is in the folder", the page asks it again precisely
    # because that changes, and a browser holding a copy from before a font
    # arrived would keep answering the old way through every reload.
    return JSONResponse(payload, headers=NO_STORE)


def _about(asked: bool = False, state: updates.State | None = None) -> dict:
    """What this install is, and what the last check found.

    Reading only. The page renders what is already known; the thread at
    startup and the button are the two things that ask, which is what keeps a
    page load off the network.

    `asked` is the button rather than a page load, and it is what decides
    whether a release somebody rolled back from is named. A load is the tool
    raising the subject, which is the nagging the rejection exists to stop;
    the button is a person asking, and they get an answer.
    """
    root = install.root()
    kind = install.detect(root)
    state = updates.load_state(root) if state is None else state
    found = updates.available(state, asked=asked)
    running = version.installed()
    # What a restart would run. It differs from what is running only after an
    # update or a rollback, and saying so is the only way this process can:
    # it goes on being the old version for as long as it lives, so every check
    # it makes finds the release already on the disk and calls it new. On disk
    # rather than remembered, so a reload, a second browser and an update done
    # from the command line all get the same answer.
    live = layout.current(root)
    pending = live if live and live != running else None
    return {"version": running,
            "firmware": stamp.build_stamp(),
            # The process actually serving, which is not always the one a
            # background start spawned: a launcher, and uv's own venv python
            # on Windows, both hand off to a child. Killing the wrapper would
            # leave this one holding the port.
            "pid": os.getpid(),
            # Which workspace this one is serving, since --fonts and
            # $CROSSGLYPH_FONTS both move it and a background server is not
            # somewhere you can see the command that started it.
            "workspace": str(fontbuild.SOURCE_DIR),
            # Sent rather than written into the page, so the link and the
            # place the updater fetches from cannot come to disagree.
            "home": updates.HOME,
            "kind": kind,
            "pending": pending,
            "handoff": _handoff_status(),
            "can_self_update": install.can_self_update(kind),
            # The sentence, already decided. The page renders what it is given
            # rather than working out for itself when there is one, which is
            # the rule that keeps it and the command line saying the same
            # thing about the same install. Nothing to say once the release is
            # installed and waiting: telling somebody how to fetch what they
            # have already fetched is the nag this exists to avoid.
            "notice": install.notice(kind, bool(found) and not pending,
                                     offering=True),
            "latest": state.latest,
            "available": found,
            # Named, so the island can say why it is offering a release the
            # page load before it did not. Silently reappearing on a button
            # press reads as a bug in the button.
            "turned_down": updates.was_turned_down(state, found),
            "checked_at": state.checked_at or None,
            "checking_off": not updateconf.settings(root).check,
            "error": state.error}


@app.get("/update")
def update_state() -> dict:
    """What this install is, and how it would be updated.

    Separate from /defaults, which carries facts about the workspace that the
    page reads once. This one grows fields as the update work lands, and the
    page renders whatever it is given rather than deciding anything itself.
    """
    return _about()


@app.post("/update/check")
def update_check() -> dict:
    """Ask now, ignoring the throttle and the opt-outs.

    A failure travels in the body rather than as a 500: the page has to be
    able to say what went wrong, and a status code is not a sentence. Kept
    apart from applying, so a forced check is never one mis-wired handler away
    from installing something.
    """
    state = updates.check(install.root(), force=True)
    return _about(asked=True, state=state)


def _startup(root: pathlib.Path) -> None:
    """What a launch does for itself, off the path the page is waiting on.

    The check first: it is bounded by a two second timeout, and the page shows
    what it found. Pruning after, because it can be thousands of files.
    """
    updates.check(root)
    layout.tidy(root, updateconf.settings(root).keep_versions)


#: The running uvicorn and the command that can replace it. Both exist only
#: while main() is inside Server.run(), not under the test client or in --png.
_server = None
_restart_state: daemon.State | None = None
_handoff_process = None
_handoff_failed = False

#: Applying and installed are both exclusive. The latter lasts until this
#: process exits: another request from a stale tab must not reinstall the same
#: version or launch a second restart while the first one is taking over.
_update_guard = threading.Lock()
_update_phase = "idle"


def _begin_update() -> bool:
    global _update_phase
    with _update_guard:
        if _update_phase != "idle":
            return False
        _update_phase = "applying"
        return True


def _finish_update(installed: bool) -> None:
    global _update_phase
    with _update_guard:
        _update_phase = "installed" if installed else "idle"


def _handoff_status() -> str | None:
    if _handoff_failed:
        return "failed"
    if _handoff_process is None:
        return None
    return "starting" if _handoff_process.poll() is None else "failed"


def _loopback(client: str) -> bool:
    try:
        return ipaddress.ip_address(client).is_loopback
    except ValueError:
        return False


@app.post("/shutdown")
def shutdown(request: Request) -> dict:
    """Stop serving, which is how `crossglyph stop` stops this.

    Loopback only, and no token. A token could not do the job anyway: a
    browser on another machine can only learn one if the page carries it, and
    a page that carries it hands it to everyone who can load the page. Where
    the request comes from is a fact the server already has, so a preview
    bound to 0.0.0.0 serves its pages to the network and takes this from
    nobody but the machine it runs on.

    An endpoint rather than a signal because of Windows: a detached child has
    no console for a Ctrl+Break to reach it through, and everything else
    there is a kill rather than a shutdown.
    """
    client = request.client.host if request.client else ""
    if not _loopback(client):
        raise HTTPException(
            status_code=403,
            detail="the preview only takes a shutdown from the machine it "
                   "runs on")
    if _server is None:
        raise HTTPException(
            status_code=409,
            detail="this preview was not started as a server")
    # uvicorn finishes the response and then leaves its loop, so the answer to
    # this request is the last thing it serves.
    _server.should_exit = True
    return {"stopping": True}


class UpdateRequest(BaseModel):
    """The JSON object that makes a browser update an intentional request."""


@app.post("/update")
def update_apply(request: Request,
                 _body: UpdateRequest) -> StreamingResponse:
    """Install the newest release, then hand a local preview to that release.

    A line of JSON at a time, the way /build and /fallbacks answer, so the
    page reads it with the reader it already has and draws the bar it already
    has. upgrade.steps remains the one place that decides whether the update
    is allowed. Restart is separate: it is offered only to a loopback browser
    while a real server has enough state to reproduce itself.
    """
    root = install.root()
    if not _begin_update():
        line = json.dumps({
            "event": "error",
            "error": "an update is already running or waiting for CrossGlyph "
                     "to restart.",
        }) + "\n"
        return StreamingResponse(iter((line,)),
                                 media_type="application/x-ndjson")

    state = _restart_state
    local = _loopback(request.client.host if request.client else "")
    target = None
    installed = False

    def lines():
        nonlocal installed, target
        try:
            for original in upgrade.steps(root):
                step = original
                if original.get("event") == "done":
                    version_name = original["version"]
                    can_restart = (local and state is not None
                                   and daemon.handoff_command(
                                       root, version_name) is not None)
                    if can_restart:
                        target = version_name
                    step = {
                        **original,
                        "restarting": can_restart,
                        "restart_log": (
                            str(root / daemon.LOG_NAME) if can_restart else None),
                    }
                    installed = True
                yield json.dumps(step) + "\n"
        finally:
            _finish_update(installed)

    def restart() -> None:
        global _handoff_failed, _handoff_process
        if target is not None and state is not None:
            _handoff_process = daemon.handoff(root, target, state)
            _handoff_failed = _handoff_process is None

    return StreamingResponse(
        lines(), media_type="application/x-ndjson",
        background=BackgroundTask(restart))


class OutRequest(BaseModel):
    out: str


@app.post("/out")
def set_out(request: OutRequest) -> dict:
    """Where builds go, which is all.conf's business rather than a family's.

    Empty clears the key, which puts it back to $CROSSGLYPH_OUT or the cpfonts
    folder beside the sources.
    """
    path = fontbuild.conf_dir() / fontbuild.DEFAULTS_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fontconf.write_values(path, {"out": request.out.strip() or None})
        forget_families()
    except OSError as exc:
        raise HTTPException(500, f"could not write {path.name}: {exc}") from exc
    return {"out": str(fontbuild.output_dir())}


class FetchRequest(BaseModel):
    #: The coverage to fetch for, which decides whether a CJK face comes too.
    intervals: str = ""
    #: And what is on the page, which decides the same thing: text that cannot
    #: be drawn without a CJK face is a request for one, whatever the coverage
    #: boxes say. Pressing Fetch when the page says characters are missing is
    #: then enough on its own.
    text: str = ""


@app.post("/fallbacks")
def fetch(request: FetchRequest) -> StreamingResponse:
    """Put the bundled faces in the font source folder, saying how far it got.

    Downloaded from the OFL files the website's own converter ships, which is
    the only thing here that reaches the network -- and it happens because
    somebody pressed a button asking for it.

    A line of JSON per step rather than one answer at the end: the CJK face
    alone is 15.7 MB, and a button that sits there for a minute with nothing to
    show is one people press again.
    """
    def lines():
        try:
            for step in fontbuild.fetch_steps(
                    fontbuild.SOURCE_DIR, request.intervals, request.text):
                if step["event"] == "done":
                    # Before the page is told, so the render it draws next
                    # fills from what has just landed rather than from the
                    # answer worked out when there was nothing there.
                    forget_families()
                    step["where"] = str(fontbuild.fallback_dir() or "")
                yield json.dumps(step) + "\n"
        # The headers are long gone by here, so a failure travels as the last
        # line rather than as a status. A network that went away mid-download
        # is the likely one, and the part file it leaves is not moved into
        # place, so pressing Fetch again resumes from whole files.
        except OSError as exc:
            yield json.dumps({
                "event": "error",
                "error": f"could not fetch the fallback faces: {exc}"}) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


class BuildRequest(BaseModel):
    #: One family, or empty for every family in the folder.
    family: str = ""
    force: bool = False


@app.post("/build")
def build(request: BuildRequest) -> StreamingResponse:
    """Build .cpfont families, exactly as crossglyph build would, saying where it
    has got to.

    A line of JSON per step rather than one answer at the end: four families at
    four sizes with fallbacks on is minutes, and a button that says "building"
    for two of them and nothing else is indistinguishable from a hung one.

    Streaming rather than a job id and a poll: the progress belongs to the
    request that caused it, so there is no state to keep, nothing to expire and
    no second build to confuse it with. Nothing here touches the render core,
    so the page goes on drawing while it runs.
    """
    out = fontbuild.output_dir()
    # Resolved before the response starts: once a byte is out, a failure can
    # only be a line in the stream, and "no such family" deserves a 422.
    try:
        if request.family:
            configs = [family_config(request.family)]
        else:
            configs, errors = fontbuild.gather(fontbuild.SOURCE_DIR)
            if errors and not configs:
                raise LookupError("; ".join(errors))
    except CLIENT_ERRORS as exc:
        raise HTTPException(422, str(exc)) from exc

    # Against the whole workspace rather than against this build: renaming a
    # family and pressing Build leaves the directory it used to have, and the
    # simulator would go on staging it. Read before the response starts, since
    # it walks the folder.
    keep = fontbuild.wanted_families(fontbuild.SOURCE_DIR)

    def lines():
        try:
            for step in fontbuild.build_families(
                    configs, out, force=request.force, keep=keep):
                yield json.dumps(step) + "\n"
        # Every one of these means the build stopped, and the headers are long
        # gone, so they travel as the last line rather than as a status.
        except (*CLIENT_ERRORS, OSError, FontBuildError,
                fontbuild.FontBuildError) as exc:
            yield json.dumps({"event": "error", "error": str(exc)}) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


#: This is a tool you edit while it is running, and the page is a folder of
#: module files a browser is free to keep. Kept, they are served after the edit that
#: was supposed to fix them: the page runs the old code, the change looks like
#: it did nothing, and the next hour goes to the wrong question. Nothing here
#: is worth a cache -- it is one process serving one reader off local disk.
NO_STORE = {"cache-control": "no-store"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers=NO_STORE)


#: What the page is allowed to ask for beside itself. A whitelist of suffixes
#: rather than a static mount: this serves one directory of hand-written files,
#: and a path that escapes it is a bug worth a 404 rather than a file.
ASSET_SUFFIXES = {".css", ".js", ".png", ".svg"}


@app.get("/{asset:path}")
def asset(asset: str) -> FileResponse:
    path = (STATIC / asset).resolve()
    if (path.suffix not in ASSET_SUFFIXES
            or not path.is_file()
            or STATIC.resolve() not in path.parents):
        raise HTTPException(404, f"no such asset: {asset}")
    return FileResponse(path, headers=NO_STORE)


def family_config(name: str) -> Config:
    """The crossglyph build config for a family, by any name that addresses it.

    Cached, because resolving one family parses every config in the folder and
    walks it once per family it finds -- half a second on a folder of ninety
    fonts, which every render would otherwise pay before drawing anything. The
    answer only moves when a file does, and the one thing that moves a file
    under a running app is a save, which drops it.

    What comes back is shared, so treat it as read-only: `coords()` and the
    rest hand back fresh dicts, and nothing here writes to a Config.

    The source folder is in the key as well as the name. Only one folder is
    ever in play at a time, but it is a global the tests move -- and a cache
    keyed on the name alone answers for whichever folder asked first.

    crossglyph build already resolves a family to its four files -- from the
    family's own .conf, or from all.conf and the filenames -- so previewing one
    should not mean typing four paths that the build knows by heart. This is
    that same resolution, and a face pinned in the .conf is honoured here too.

    The config rather than just the faces, because `--family alto` and
    `--family alto.conf` both address a family the picker calls Alto, and
    the picker has to be told the name it uses itself.
    """
    return _config_cached(str(fontbuild.SOURCE_DIR), name)


@functools.lru_cache(maxsize=16)
def _config_cached(source: str, name: str) -> Config:
    del source                          # in the key, not the body
    configs, errors = fontbuild.gather(fontbuild.SOURCE_DIR, [name])
    if not configs:
        # offered() rather than gather(): the roll call has to name everything
        # that can be asked for, and the bundled family can be whatever else
        # is in the folder.
        known = ", ".join(sorted(config.name for config
                                 in fontbuild.offered(fontbuild.SOURCE_DIR)[0]))
        # gather() says which token missed and where it looked; the roll call
        # of what is there is what turns that into the next command to type.
        raise LookupError("\n".join(
            (errors or [f"no font family {name!r} under {fontbuild.SOURCE_DIR}"])
            + [f"there is: {known or 'nothing'}"]))
    return configs[0]


def forget_families() -> None:
    """Drop what was resolved from the folder, after it changed underneath us.

    A family can be addressed by several names and all.conf reaches every one
    of them, so the whole lot goes rather than one entry.

    The bundled faces with them. They are not families and never show in the
    picker, but which of them a build would fill from is worked out once and
    kept, so a set fetched under a running app stayed invisible to every
    render after it until the process was restarted.
    """
    _config_cached.cache_clear()
    _styles_cached.cache_clear()
    _bundled_faces.cache_clear()


_workspace: tuple | None = None


def workspace_stamp() -> tuple:
    """Every source file in the workspace, with what says it has been edited.

    The question file_stamp asks of one face, asked of the folder: fonts and
    configs together, since a .conf decides which faces a family resolves to
    and all.conf reaches all of them.

    A fingerprint rather than a watcher. There is nothing to keep running and
    nothing to miss -- a volume mounted after the process started, an editor
    writing through a rename, a file copied in with an old mtime but a new
    size all just look different the next time this is asked.
    """
    source = fontbuild.SOURCE_DIR
    files = fontconf.font_files(source)
    files += sorted(fontbuild.conf_dir(source).glob("*.conf"))
    # The bundled faces too, which discovery skips on purpose and a build
    # reads all the same: fetched, replaced or removed, they change what a
    # page is drawn with while no font and no config has moved.
    bundled = fontbuild.fallback_dir(source)
    if bundled and bundled.is_dir():
        files += sorted(path for path in bundled.iterdir()
                        if path.suffix.lower() in fontconf.FONT_SUFFIXES)
    return tuple(stamp for stamp in map(file_stamp, files) if stamp)


def rescan() -> bool:
    """Forget the resolved families if the folder has moved on. True when it had.

    The list a picker shows is read from the folder every time and was never
    the stale part. What goes stale is what a family *resolves to* -- which
    files its four slots hold, and what its config sets them to -- because
    that is what is cached, and it is what the next render draws with.

    Called from /defaults alone, which the page asks for on load and whenever
    its tab comes back. That is the whole of it on purpose: reaching the
    folder means leaving the window, so coming back is when it can have
    changed, and an app nobody is looking at does no work at all -- which is
    most of what a background one does. One fingerprint costs 14ms over 69
    files and 350ms over 2000: nothing once, and a great deal on every frame
    of a dragged slider.

    The first call counts as a change, since nothing is known yet. That clears
    caches that are cold, which costs nothing, and it is worth more than the
    branch it replaces: skipping it rests on nothing having resolved a family
    before the page's first ask, which is true today and is not something
    anything states or checks.
    """
    global _workspace
    seen, _workspace = _workspace, workspace_stamp()
    if seen == _workspace:
        return False
    forget_families()
    return True


def family_faces(name: str) -> dict[str, pathlib.Path]:
    """The faces of a family in the font source folder, keyed by style name."""
    return dict(family_config(name).styles)


def _first_family() -> str | None:
    """What the preview opens on when nothing says otherwise."""
    if not fontbuild.SOURCE_DIR.is_dir():
        return None
    configs, _ = fontbuild.gather(fontbuild.SOURCE_DIR)
    return configs[0].name if configs else None


def _restart_rest(opts, source: pathlib.Path,
                  family: str | None) -> list[str]:
    """Preview arguments that remain valid from the install root."""
    rest = ["--fonts", str(fontbuild.SOURCE_DIR.resolve())]
    if family:
        rest.extend(("--family", family))
    else:
        rest.extend(("--font", str(source.resolve())))
    for name, flag in (("bold", "--bold"), ("italic", "--italic"),
                       ("bold_italic", "--bold-italic")):
        if value := getattr(opts, name):
            rest.extend((flag, str(pathlib.Path(value).expanduser().resolve())))
    return rest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="crossglyph preview",
        description="Tune a font against the device's own renderer.")
    # Neither is required: started with no arguments at all, the preview opens
    # on the first family in the workspace, which is the whole of what a
    # tester has to do after unpacking.
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--font", help="the regular face to preview")
    where.add_argument("--family",
                       help="a family in the workspace, by name -- its four "
                            "faces are resolved the way crossglyph build "
                            "resolves them")
    parser.add_argument("--bold", help="the bold face, if the family has one")
    parser.add_argument("--italic", help="the italic face")
    parser.add_argument("--bold-italic", dest="bold_italic",
                        help="the bold italic face")
    # float, like every other size in the tool: FreeType takes 26.6 fixed
    # point and the slider steps a quarter point.
    parser.add_argument("--size", type=float, default=13,
                        help="point size for --png (default: %(default)s)")
    parser.add_argument("--device", choices=("x4", "x3"), default="x4",
                        help="reader geometry for --png (default: %(default)s)")
    parser.add_argument("--png", metavar="PATH",
                        help="write one page and exit, instead of serving")
    parser.add_argument("--fonts", default=None,
                        help=f"the workspace to read families from "
                             f"(default: {fontbuild.SOURCE_DIR}, or "
                             f"$CROSSGLYPH_FONTS)")
    parser.add_argument(
        "--host", default=os.environ.get("CROSSGLYPH_HOST", "127.0.0.1"),
        help="address to serve on (default: %(default)s, or "
             "$CROSSGLYPH_HOST)")
    parser.add_argument("--port", type=int, default=daemon.DEFAULT_PORT,
                        metavar="PORT",
                        help="port to serve on (default: %(default)s)")
    parser.add_argument("--no-open", dest="open_browser", action="store_false",
                        help="serve without opening a browser")
    opts = parser.parse_args(argv)

    if opts.fonts:
        workspace = pathlib.Path(opts.fonts).expanduser().resolve()
        if not workspace.is_dir():
            print(f"no such workspace: {opts.fonts}", file=sys.stderr)
            return 2
        # The module attribute rather than a value threaded through: every
        # reader here looks it up on fontbuild at the time it asks, which is
        # what lets the picker, a build and a save all follow one move.
        fontbuild.SOURCE_DIR = workspace

    if not opts.font and not opts.family:
        opts.family = _first_family()
        if opts.family is None:
            # The bundled family answers an empty workspace, so getting here
            # means this copy of the tool has lost its own faces too.
            print(f"no fonts in {fontbuild.SOURCE_DIR}, and none bundled in "
                  f"{fontbuild.STARTER_DIR}\n"
                  f"Drop TTF or OTF files in, or pass --font or --family.",
                  file=sys.stderr)
            return 2

    faces = {"bold": opts.bold, "italic": opts.italic,
             "bold_italic": opts.bold_italic}
    font = opts.font
    family = None
    if opts.family:
        try:
            config = family_config(opts.family)
        except LookupError as exc:
            print(exc, file=sys.stderr)
            return 2
        # Its own name, not the token that found it: the picker lists families
        # by name, and it has to be able to select the one already showing.
        family, resolved = config.name, dict(config.styles)
        # An explicit --bold beside --family still wins, so one face can be
        # swapped out without naming the other three.
        font = resolved.get("regular")
        for option, style in (("bold", "bold"), ("italic", "italic"),
                              ("bold_italic", "bolditalic")):
            faces[option] = faces[option] or resolved.get(style)
        if font is None:
            print(f"the {opts.family!r} family has no regular face",
                  file=sys.stderr)
            return 2

    for label, path in [("font", font)] + list(faces.items()):
        if path and not pathlib.Path(path).is_file():
            print(f"{label} face not found: {path}", file=sys.stderr)
            return 2
    source = pathlib.Path(font)
    set_font_source(source, family=family, **faces)

    if opts.png:
        page = preview_page(build_font(
            _sources, opts.size,
            axes={style: dict(coords) for style, coords
                  in axes_for(_family or "", opts.size)}),
            spec=PageSpec(device=opts.device))
        _watermark(page).save(opts.png)
        print(f"wrote {opts.png}")
        return 0

    import webbrowser

    import uvicorn

    root = install.root()
    held = daemon.busy(root, opts.host, opts.port, "preview")
    if held is not None:
        print(held, file=sys.stderr)
        return 1
    # On a thread, so a slow or absent network and a large directory removal
    # delay nothing anybody is waiting on. The page reads whatever the check
    # has written by the time it asks, and picks the answer up on the next
    # load if it has not landed yet. Pruning is here rather than in the update
    # itself: at the moment the button is pressed, the version being replaced
    # is the one serving the page the press came from.
    threading.Thread(target=_startup, args=(root,), daemon=True).start()
    address = f"http://{opts.host}:{opts.port}"
    loaded = ", ".join(FACE_NAMES[style] for style in sorted(_sources))
    print(f"preview on {address}  ({source.name}: {loaded})")
    if opts.open_browser:
        # On a timer, so the browser asks for the page after uvicorn is
        # listening rather than racing it.
        threading.Timer(0.5, webbrowser.open, [address]).start()
    # Config and Server rather than uvicorn.run, which is the two of them and
    # keeps neither: /shutdown needs the object to ask. The restart state also
    # makes a foreground preview reproducible by the detached update handoff.
    global _server, _restart_state, _handoff_process, _handoff_failed
    _finish_update(False)
    _handoff_process = None
    _handoff_failed = False
    _server = uvicorn.Server(uvicorn.Config(
        app, host=opts.host, port=opts.port, log_level="warning"))
    _restart_state = daemon.State(
        pid=os.getpid(), host=opts.host, port=opts.port,
        rest=_restart_rest(opts, source, family),
        version=version.installed(), started=time.time())
    try:
        _server.run()
    except KeyboardInterrupt:
        # Server.capture_signals deliberately re-raises SIGINT after its
        # graceful shutdown. uvicorn.run() catches it, but constructing the
        # Server here is what lets /shutdown address the live instance.
        pass
    finally:
        _server = None
        _restart_state = None
        _handoff_process = None
        _handoff_failed = False
        _finish_update(False)
    return 0

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
import json
import os
import pathlib
import sys

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, Response, StreamingResponse
    from pydantic import BaseModel, Field
except ModuleNotFoundError as exc:      # pragma: no cover - install guidance
    raise SystemExit(
        f"the preview needs its web dependencies ({exc.name}). Install them "
        f"with:\n  uv sync") from exc

import freetype
from fontTools.ttLib import TTFont, TTLibError

from .. import (fontbuild, fontconf, install, layout, updateconf, updates,
                upgrade, version)
from ..cpfont.convert import (BASE_INTERVALS, INTERVAL_PRESETS,
                              FontBuildError, figure_glyph_overrides,
                              gsub_ligature_sequences)
from ..cpfont.tuning import LineHeight, Tuning
from ..fontconf import Config, FontConfigError
from ..render import RenderCoreMissing, stamp
from . import (BOLD, BOLD_ITALIC, ITALIC, REGULAR, SAMPLE_TEXT, SAMPLES,
               Drawable, PageSpec, build_font, coverage_for, faces_for,
               fallback_split, page_codepoints, preview_page)

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

    Empty for a static face. `opsz` is left out: it follows the size on the
    page rather than saying anything about which face this slot is.
    """
    coords = {tag: value for tag, value in config.coords(style).items()
              if tag != "opsz"}
    if not coords:
        return ""
    return " at " + ", ".join(f"{tag} {value:g}"
                              for tag, value in sorted(coords.items()))


#: What a request can get wrong, as opposed to what the server can. A family
#: name the folder does not have, a size that will not parse, a coordinate off
#: an axis: every one of them is something the page sent, so every one is a 422
#: with the reason in it rather than a traceback.
CLIENT_ERRORS = (ValueError, TypeError, LookupError, FontConfigError)


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
        return freetype.Face(path).get_format().decode().casefold()
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
        tricky = freetype.Face(path).is_tricky
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
    #: The coverage the build would carry, which decides whether the 15.7 MB
    #: CJK face is among the bundled ones. Not what the preview rasterizes --
    #: that is the text, always.
    intervals: str = ""
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


@functools.lru_cache(maxsize=8)
def _bundled_faces(source: str, intervals: str) -> tuple[str, ...]:
    """The bundled Noto faces a build with this coverage would fill from.

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
    return tuple(str(path)
                 for path in fontbuild.wanted_fallbacks(intervals, directory))


def fallbacks_for(request: RenderRequest) -> tuple[str, ...]:
    """The faces this request would fall back to, in the converter's order.

    The two chosen families first, then the bundled set -- the same order
    fontbuild.build_kwargs assembles, so a codepoint the family lacks is drawn
    from the face the build would have drawn it from.
    """
    faces = []
    for name in (request.fallback1, request.fallback2):
        if not name:
            continue
        regular = sources_for(name).get(REGULAR)
        if regular is None:
            raise LookupError(f"the {name!r} family has no regular face to "
                              f"fall back to")
        faces.append(str(regular))
    if request.fallbacks:
        faces.extend(_bundled_faces(str(fontbuild.SOURCE_DIR), request.intervals))
    return tuple(faces)


@functools.lru_cache(maxsize=32)
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


def _with_the_button(exc: Exception) -> str:
    """The fallbacks message as the panel should tell it.

    The command in it is right for a terminal, and the reader of this one is
    looking at a page with the button on it. Kept out of fontbuild for that
    reason: the same words on the command line would name something that is
    not there.
    """
    return f"{exc}\nOr press Fetch, beside 'bundled fallback faces' above."


@functools.lru_cache(maxsize=32)
def build_font_cached(sources: tuple, size: float, coverage: tuple,
                      tuning_items: tuple, fallbacks: tuple = (),
                      axes: tuple = ()) -> bytes:
    """A knob that does not touch the font should not pay for a build.

    Keyed on the coverage rather than the text it came from, so editing the
    sample text only rebuilds when it brings in a character the last build did
    not have -- which most edits do not. Every key is a tuple because an
    lru_cache key has to hash."""
    return build_font(dict(sources), size, tuning=_tuning(tuning_items),
                      coverage=coverage, fallbacks=fallbacks,
                      axes={style: dict(coords) for style, coords in axes})


@app.post("/render")
def render(request: RenderRequest) -> Response:
    if not _sources and not request.family:
        raise HTTPException(503, "no font source; start with --font")
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
        coverage = coverage_for(request.text, sources)
        offered = fallbacks_for(request)
        drawable = resolved_fallbacks(keyed, coverage, offered)
        font = build_font_cached(
            keyed, request.size, coverage, _cache_key(request.tuning),
            tuple(str(path) for path in drawable.faces),
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
        undrawn = drawable.undrawn & page_codepoints(request.text)
        page = preview_page(font, request.text, spec)
    # SystemExit is deliberate and not paranoia: the converter is a script at
    # heart and calls sys.exit() on bad input rather than raising -- an
    # advanceY the .cpfont format cannot hold (convert.py:1292-1297), which a
    # large `size` can reach on a loose-hhea face. SystemExit is a
    # BaseException, so a bare `except ValueError` lets it past the handler and
    # out of the app entirely.
    except SystemExit as exc:
        # sys.exit("reason") carries one; sys.exit(1) does not, and str() of it
        # is "1", which would reach the panel as the whole error message.
        reason = str(exc) if not isinstance(exc.code, int) else ""
        raise HTTPException(
            422, reason or "the converter rejected this combination; "
                           "see the server log") from exc
    # FontBuildError from cpfont, not fontbuild: two classes share the name,
    # and the one this path can raise is the converter's (convert.py:1120,
    # from rasterize_font_style on a malformed face). The fontbuild one comes
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
        raise HTTPException(
            422, str(exc) or f"{type(exc).__name__} from the converter") from exc
    # A workspace condition, not bad input -- the same class as having no font
    # source, which is already a 503. As a 422 it shows up in the panel's
    # status line as though the knob had been rejected.
    except RenderCoreMissing as exc:
        raise HTTPException(503, str(exc)) from exc
    # Fallbacks ticked and not fetched. The same class again, and this is the
    # one missing file the reader can fix without leaving the page.
    except fontbuild.FallbacksMissing as exc:
        raise HTTPException(503, _with_the_button(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc)) from exc

    buffer = io.BytesIO()
    page.save(buffer, format="PNG")
    # How many characters drew nothing, so the page can say so. A header rather
    # than a second request: it belongs to this page and not to the next one,
    # and the body is a PNG with nowhere to put it. Latin-1 is all a header
    # may carry, which is the other reason this is a count and not the
    # characters themselves.
    return Response(buffer.getvalue(), media_type="image/png",
                    headers={"x-undrawn": str(len(undrawn))})


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
        # Against the automatic pick, which is this config with nothing pinned.
        plain = fontconf.slot_coords(path, style)
        if not wanted or wanted == plain:
            changes[style] = None
            continue
        # The file relative to the config's own folder, so it stays portable --
        # the same form the fallback keys are written in.
        name = os.path.relpath(path, config.dir).replace("\\", "/")
        # Only the axes that differ from the automatic pick. A coordinate is an
        # override laid over the font's own instance, so restating the rest
        # says nothing -- and freezes a value that should go on following the
        # font if its designer ever moves that instance.
        axes = ",".join(f"{tag}={value:g}" for tag, value in sorted(wanted.items())
                        if tag != FOLLOWS_SIZE and plain.get(tag) != value)
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

    wanted["intervals"] = str(request_export.get("intervals", "")).strip() or None
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
def defaults() -> dict:
    """What the page starts from, so the sample text lives in one place.

    `families` is the picker's list and `family` the entry to select. When the
    app was started on a bare file there is no entry to select: `font` names
    it, and the page keeps it as a choice of its own at the top of the list.
    """
    return {"text": SAMPLE_TEXT,
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
            "font": _sources[REGULAR].name if _sources else None,
            "faces": sorted(FACE_NAMES[style] for style in _sources),
            "families": families(),
            "family": _family}


def _about() -> dict:
    """What this install is, and what the last check found.

    Reading only. The page renders what is already known; the thread at
    startup and the button are the two things that ask, which is what keeps a
    page load off the network.
    """
    root = install.root()
    kind = install.detect(root)
    state = updates.load_state(root)
    found = updates.available(state)
    return {"version": version.installed(),
            "firmware": stamp.build_stamp(),
            "kind": kind,
            "can_self_update": install.can_self_update(kind),
            # The sentence, already decided. The page renders what it is given
            # rather than working out for itself when there is one, which is
            # the rule that keeps it and the command line saying the same
            # thing about the same install.
            "notice": install.notice(kind, bool(found)),
            "latest": state.latest,
            "available": found,
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
    updates.check(install.root(), force=True)
    return _about()


def _startup(root: pathlib.Path) -> None:
    """What a launch does for itself, off the path the page is waiting on.

    The check first: it is bounded by a two second timeout, and the page shows
    what it found. Pruning after, because it can be thousands of files.
    """
    updates.check(root)
    layout.tidy(root, updateconf.settings(root).keep_versions)


@app.post("/update")
def update_apply() -> StreamingResponse:
    """Install the newest release, saying how far it has got.

    A line of JSON at a time, the way /build and /fallbacks answer, so the
    page reads it with the reader it already has and draws the bar it already
    has. Nothing here decides whether the update is allowed: upgrade.steps
    resolves the install kind and refuses as its first step, before it opens
    the network.
    """
    def lines():
        for step in upgrade.steps(install.root()):
            yield json.dumps(step) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


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
        # Fallbacks that were asked for and never fetched are the one of them
        # this page can offer to fix, so that one says how.
        except fontbuild.FallbacksMissing as exc:
            yield json.dumps(
                {"event": "error", "error": _with_the_button(exc)}) + "\n"
        except (*CLIENT_ERRORS, OSError, FontBuildError,
                fontbuild.FontBuildError) as exc:
            yield json.dumps({"event": "error", "error": str(exc)}) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


#: This is a tool you edit while it is running, and the page is fourteen module
#: files a browser is free to keep. Kept, they are served after the edit that
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
ASSET_SUFFIXES = {".css", ".js", ".svg"}


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
    """Drop what was resolved from the folder, after something wrote to it.

    A save is the only thing that changes a config under a running app, and it
    changes exactly the family it named -- but a family can be addressed by
    several names and all.conf reaches every one of them, so the whole lot goes
    rather than one entry.
    """
    _config_cached.cache_clear()
    _styles_cached.cache_clear()


def family_faces(name: str) -> dict[str, pathlib.Path]:
    """The faces of a family in the font source folder, keyed by style name."""
    return dict(family_config(name).styles)


def _first_family() -> str | None:
    """What the preview opens on when nothing says otherwise."""
    if not fontbuild.SOURCE_DIR.is_dir():
        return None
    configs, _ = fontbuild.gather(fontbuild.SOURCE_DIR)
    return configs[0].name if configs else None


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
    parser.add_argument("--png", metavar="PATH",
                        help="write one page and exit, instead of serving")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-open", dest="open_browser", action="store_false",
                        help="serve without opening a browser")
    opts = parser.parse_args(argv)

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
        preview_page(build_font(
            _sources, opts.size,
            axes={style: dict(coords) for style, coords
                  in axes_for(_family or "", opts.size)})).save(opts.png)
        print(f"wrote {opts.png}")
        return 0

    import threading
    import webbrowser

    import uvicorn

    # On a thread, so a slow or absent network and a large directory removal
    # delay nothing anybody is waiting for. The page reads whatever the check
    # has written by the time it asks, and picks the answer up on the next
    # load if it has not landed yet. Pruning is here rather than in the update
    # itself: at the moment the button is pressed, the version being replaced
    # is the one serving the page the press came from.
    threading.Thread(target=_startup, args=(install.root(),),
                     daemon=True).start()
    address = f"http://{opts.host}:{opts.port}"
    loaded = ", ".join(FACE_NAMES[style] for style in sorted(_sources))
    print(f"preview on {address}  ({source.name}: {loaded})")
    if opts.open_browser:
        # On a timer, so the browser asks for the page after uvicorn is
        # listening rather than racing it.
        threading.Timer(0.5, webbrowser.open, [address]).start()
    uvicorn.run(app, host=opts.host, port=opts.port, log_level="warning")
    return 0

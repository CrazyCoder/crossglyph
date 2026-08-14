"""Read a font family's build config and work out which file is which style.

The style rules are a port of crosspoint-tools/src/pages/fonts/fontBuilder.js,
the folder picker on https://crosspointreader.com/fonts. Matching it matters:
a folder that the website resolves to Medium/Bold/Italic/BoldItalic has to
resolve the same way here, or a font that was checked on the device would build
differently at home.
"""
from __future__ import annotations

import configparser
import dataclasses
import functools
import math
import pathlib
import re
import struct
import typing

from . import spacefont
from .cpfont.tuning import LineHeight, Tuning

FONT_SUFFIXES = (".ttf", ".otf")

# fontBuilder.js STYLE_PATTERNS, in order. First match wins, and the same list
# is used in reverse to strip the suffix back off and recover the family stem.
STYLE_PATTERNS = [
    ("bolditalic", re.compile(
        r"[-_ ]?(bold[-_ ]?italic|bold[-_ ]?oblique|bolditalic|boldoblique|BdIt|bi)$",
        re.IGNORECASE)),
    ("bold", re.compile(r"[-_ ]?(bold|Bd)$", re.IGNORECASE)),
    ("italic", re.compile(r"[-_ ]?(italic|It|oblique)$", re.IGNORECASE)),
    ("regular", re.compile(r"[-_ ]?(regular|normal|book|roman|medium|Rg)$",
                           re.IGNORECASE)),
]

# fontBuilder.js EXTRA_WEIGHT_RE. Files matching it are dropped before anything
# else, which is what keeps Alto-MediumItalic from fighting Alto Italic for
# the italic slot -- both classify as italic, and only one can win.
EXTRA_WEIGHT_RE = re.compile(
    r"(thin|hairline|extra[-_ ]?light|ultra[-_ ]?light|light|medium|semi[-_ ]?bold"
    r"|demi[-_ ]?bold|extra[-_ ]?bold|ultra[-_ ]?bold|black|heavy)[-_ ]?(italic|oblique)",
    re.IGNORECASE)

STYLES = ("regular", "bold", "italic", "bolditalic")

# Terse suffixes from the old Windows/foundry convention: sample.ttf,
# sampleb.ttf, samplei.ttf, samplebi.ttf. Longest first.
#
# A bare trailing "b" or "i" is far too eager to match on its own -- it would
# read Bodoni.ttf as the italic of a family called Bodon -- so these are only
# consulted when the plain family file exists in the same folder to corroborate
# them. STYLE_PATTERNS already covers the longer spellings (Bd, BdIt, bi).
#
# "z" is bold italic in the same convention -- Microsoft's own core fonts ship
# georgiaz.ttf, verdanaz.ttf and CALIBRIZ.TTF, and a folder of them otherwise
# resolves as a family missing its bold italic beside a one-face family called
# Georgiaz. It is as eager as "b" and "i" and rides on the same corroboration.
SHORT_SUFFIXES = [
    ("bolditalic", "bdit"), ("bolditalic", "bdi"), ("bolditalic", "bi"),
    ("bolditalic", "z"),
    ("bold", "bd"), ("bold", "b"),
    ("italic", "it"), ("italic", "i"),
]

# Preferred keyword per slot, best first. Only the regular slot really needs
# this -- a family shipping both Regular and Medium should use Regular, but
# Alto ships only Medium and must fall through to it.
KEYWORD_RANK = {
    "regular": ["regular", "normal", "roman", "book", "medium", "rg"],
    "bold": ["bold", "bd"],
    "italic": ["italic", "oblique", "it"],
    "bolditalic": ["bolditalic", "boldoblique", "bdit", "bi"],
}

# What the user ticks on the website: Reading (Fiction), Latin Extended, Greek,
# Cyrillic, Symbols & Arrows. `base` is injected by the converter itself.
#: `reading` is not a peer of the other presets: it is the converter's own
#: `default` block plus a good deal more, so it already carries Latin Extended,
#: Cyrillic U+0400-04FF, monotonic Greek, the currency and arrow and maths
#: blocks, and Vietnamese. Naming those beside it added 3431 codepoints where
#: `reading` alone gives 3127, and the 304 between them are polytonic Greek and
#: the Cyrillic Supplement -- neither of which a book wants and most faces do
#: not draw. Listing them made the panel look as though five ticks were needed.
DEFAULT_INTERVALS = "reading"
DEFAULT_SIZES = [12, 14, 16, 18]

BOOL_KEYS = {"fallbacks", "space_glyphs", "stem_darkening", "ligatures"}
TUNING_KEYS = {"gamma", "thresholds", "weight", "slant", "hinting",
               "line_height", "letter_spacing", "word_spacing", "kerning",
               "figures"}
PATH_KEYS = {"regular", "bold", "italic", "bolditalic",
             "fallback_regular", "fallback2_regular"}
# `out` is not a property of a family at all -- it is where builds go, which
# belongs in all.conf. It is listed here so that file may carry it; parse_config
# ignores it, and fontbuild.output_dir is what reads it.
KNOWN_KEYS = ({"name", "family", "dir", "out", "fallback_dir", "sizes",
               "sizes_mod", "mod_suffix", "intervals", "ranges"}
              | BOOL_KEYS | TUNING_KEYS | PATH_KEYS)

# space_width_2006 = 0.25 -- one key per overridable space, so they cannot be
# enumerated in KNOWN_KEYS and are matched instead.
_SPACE_WIDTH_RE = re.compile(r"^space_width_([0-9A-Fa-f]{4})$")

_TRUE = {"yes", "true", "on", "1"}
_FALSE = {"no", "false", "off", "0"}


class FontConfigError(RuntimeError):
    """A config that cannot be built as written."""


def sanitize_name(name: str) -> str:
    """fontBuilder.js sanitizeFamilyName: the name reaches a filename and the
    reader's family list, so anything outside [A-Za-z0-9_-] is dropped."""
    return re.sub(r"[^A-Za-z0-9_-]+", "", name) or "CustomFont"


# A variable font carries its axes in the filename, and Google Fonts' own
# spelling is a bracketed list: Merriweather[opsz,wdth,wght].ttf, with the
# italic as Merriweather-Italic[opsz,wdth,wght].ttf. The axes are not part of
# the family name and nothing here varies an axis, so they come off the stem
# before it is matched. Left on, the brackets and commas survive as far as
# sanitize_name and the family arrives called "Merriweatheropszwdthwght" -- and
# the italic, whose suffix is no longer at the end of the stem, is a second
# one-face family rather than that family's italic.
_AXES_RE = re.compile(r"\[[^\[\]]*\]$")


# Every word a style suffix can be spelled with, for recognising a tail that is
# nothing but style. Wider than STYLE_PATTERNS on purpose: this is only used to
# decide whether what follows a number is a style, and a weight that is its own
# family (Light, Black) still has to count as one there.
_STYLE_WORD = (r"bold|italic|oblique|regular|normal|book|roman|medium|light"
               r"|thin|hairline|black|heavy|semi|demi|extra|ultra|semibold"
               r"|demibold|extrabold|ultrabold|extralight|ultralight|bd|it|rg")

# Linotype's series numbers: 65 Medium, 66 Medium Italic, 75 Bold, 76 Bold
# Italic, where the first digit is the weight and the second says upright or
# italic, and the word after it says the same thing again. The number is what
# makes each file its own family stem, so the four never meet.
#
# Only a whole number between the family and a tail that is nothing but style
# words goes. That is what keeps it off a name where the number IS the family:
# `Roboto_Condensed_300` has no style tail, so its 300 stays and it remains a
# family of its own, exactly as `Roboto_SemiCondensed-Light` does.
_SERIES_RE = re.compile(
    rf"[-_ ]\d+(?=(?:[-_ ](?:{_STYLE_WORD}))+$)", re.IGNORECASE)


def font_stem(path: pathlib.Path) -> str:
    """A font file's stem, as the style and family rules should see it.

    Without a variable font's axis list, and without a foundry's series number.
    """
    stem = _AXES_RE.sub("", path.stem)
    return re.sub(r"[-_ ]+$", "", _SERIES_RE.sub("", stem))


class VariableFont(typing.NamedTuple):
    """A variable font's axes and the instances its designer named.

    axes maps tag -> (minimum, default, maximum); instances maps a weight --
    "roman" or "bold" -- to the design coordinates the font itself gives it.
    `named` is every instance in the font's own order, which is what a picker
    offers: those two are the ones a slot is built at by default.
    """
    axes: dict[str, tuple[float, float, float]]
    instances: dict[str, dict[str, float]]
    named: tuple[tuple[str, dict[str, float]], ...] = ()


#: Instance names that mean "the text weight" once any italic is taken off.
#: An italic file names its own upright-equivalent instance "Italic", which
#: comes to nothing at all, so the empty string belongs here too.
ROMAN_NAMES = {"", "regular", "book", "roman", "normal"}

#: What a slot asks the weight axis for when no named instance claims it.
#: The CSS numbers, which is what a variable font's wght axis is scaled in.
SLOT_WEIGHT = {"roman": 400.0, "bold": 700.0}

#: Which weight each style slot is built from. The italic slots differ by the
#: file they come from, not by the coordinates asked of it.
SLOT_KIND = {"regular": "roman", "italic": "roman",
             "bold": "bold", "bolditalic": "bold"}


def _instance_kind(name: str) -> str | None:
    """Which weight a named instance is, or None if it is neither.

    Merriweather names seven -- Light, Regular, Medium, SemiBold, Bold,
    ExtraBold, Black -- and only two of them are slots here.
    """
    key = re.sub(r"[-_ ]", "",
                 re.sub(r"(italic|oblique)", "", name, flags=re.IGNORECASE))
    key = key.casefold()
    if key in ROMAN_NAMES:
        return "roman"
    return "bold" if key == "bold" else None


def _has_fvar(path: pathlib.Path) -> bool:
    """Whether a font file carries an fvar table, from its table directory.

    A sniff rather than an open: discovery runs over every file in the folder
    on every gather(), and all but a handful of them are static. This reads the
    12-byte header and the directory that follows it, where opening the font
    properly would parse tables nothing here looks at.
    """
    try:
        with path.open("rb") as handle:
            header = handle.read(12)
            if len(header) < 12 or header[:4] not in (
                    b"\x00\x01\x00\x00", b"OTTO", b"true"):
                return False        # a collection (ttcf) is not one font
            count = struct.unpack(">H", header[4:6])[0]
            directory = handle.read(16 * count)
    except OSError:
        return False
    return any(directory[at:at + 4] == b"fvar"
               for at in range(0, len(directory) - 3, 16))


@functools.lru_cache(maxsize=1024)
def _variable_font(path: str, mtime: int, size: int) -> VariableFont | None:
    """Cached by identity, since a font is read once and asked about often.

    The stamp is in the key rather than checked against a stored one: a file
    that is replaced under a running preview gets a new key and is read again.

    The sniff is inside the cache rather than in front of it, and that is the
    whole cost of this: discovery asks every candidate family about every file
    in the folder, so a folder of 90 fonts is some 2600 questions per walk.
    Answering each with an open and a read costs a quarter of a second, which
    is more than the render it holds up.
    """
    del mtime, size                 # in the key, not the body
    from fontTools.ttLib import TTFont

    if not _has_fvar(pathlib.Path(path)):
        return None
    with TTFont(path, lazy=True) as font:
        axes = {axis.axisTag: (axis.minValue, axis.defaultValue, axis.maxValue)
                for axis in font["fvar"].axes}
        names = font["name"]
        instances: dict[str, dict[str, float]] = {}
        named: list[tuple[str, dict[str, float]]] = []
        for instance in font["fvar"].instances:
            label = names.getDebugName(instance.subfamilyNameID) or ""
            named.append((label, dict(instance.coordinates)))
            kind = _instance_kind(label)
            # First wins: the list is in the designer's order, and a font that
            # names two things "Regular" means the first of them.
            if kind and kind not in instances:
                instances[kind] = dict(instance.coordinates)
    return VariableFont(axes, instances, tuple(named))


def variable_font(path: pathlib.Path) -> VariableFont | None:
    """A font file's axes and named instances, or None if it is not variable.

    One stat per call and nothing else once the answer is known -- see
    _variable_font for why that matters.
    """
    try:
        stat = path.stat()
    except OSError:
        return None
    return _variable_font(str(path), stat.st_mtime_ns, stat.st_size)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def slot_coords(path: pathlib.Path, style: str, size: float | None = None,
                override: dict[str, float] | None = None) -> dict[str, float]:
    """The design coordinates one style slot is rasterized at.

    Empty for a static font, which is nearly all of them.

    The font's own named instance wins, because the designer chose those
    coordinates: Merriweather's default instance is Light, so taking the file
    as it comes builds a Light face and calls it Regular. A font that names no
    instance for the slot falls back to the CSS weights, clamped to what its
    axis actually offers.

    `opsz` is the exception and is not a slot's business at all: the axis
    exists to be set to the size being rendered, so it follows `size` -- again
    clamped, since a face whose optical range starts at 18 pt has nothing
    finer to give a 13 pt build.

    An override from the config is applied last and wins outright, including
    over opsz.
    """
    font = variable_font(path)
    if font is None:
        return {}
    kind = SLOT_KIND.get(style, "roman")
    coords = dict(font.instances.get(kind) or {})
    if not coords and "wght" in font.axes:
        low, _, high = font.axes["wght"]
        coords["wght"] = _clamp(SLOT_WEIGHT[kind], low, high)
    if size is not None and "opsz" in font.axes:
        low, _, high = font.axes["opsz"]
        coords["opsz"] = _clamp(float(size), low, high)
    for tag, value in (override or {}).items():
        if tag in font.axes:
            low, _, high = font.axes[tag]
            coords[tag] = _clamp(value, low, high)
    return coords


#: `regular = Merriweather[opsz,wdth,wght].ttf@wght=500`. Anchored at the end
#: and shaped like a coordinate list, so a filename with an @ in it is only
#: mistaken for one if it also ends in `tag=number`.
_AXIS_SUFFIX_RE = re.compile(
    r"@(?P<axes>[A-Za-z0-9]{1,4}\s*=\s*-?\d+(?:\.\d+)?"
    r"(?:\s*,\s*[A-Za-z0-9]{1,4}\s*=\s*-?\d+(?:\.\d+)?)*)\s*$")


def split_axes(value: str, key: str = "regular",
               where: str = "") -> tuple[str, dict[str, float]]:
    """A style key's filename and the design coordinates pinned after it.

    The automatic pick is right for a family whose text weight is the one its
    designer called Regular, which is most of them. This is for the rest: a
    face whose text weight is SemiBold has no other way to ask.
    """
    match = _AXIS_SUFFIX_RE.search(value)
    if not match:
        return value, {}
    axes = {}
    for pair in match.group("axes").split(","):
        tag, _, number = pair.partition("=")
        tag = tag.strip()
        if len(tag) > 4:
            raise FontConfigError(
                f"{where}: {key} names an axis {tag!r}, but an axis tag is at "
                f"most four characters")
        axes[tag] = float(number)
    return value[:match.start()].strip(), axes


def can_synthesize(path: pathlib.Path, style: str) -> bool:
    """Whether this file can stand in for a slot it has no file of its own for.

    Only a real difference counts: a variable font whose weight axis stops at
    its default has no bold in it, and pointing the bold slot at the same
    coordinates as the regular would ship the same glyphs twice.
    """
    coords = slot_coords(path, style)
    return bool(coords) and coords != slot_coords(path, "regular")


def classify(stem: str) -> str:
    for style, pattern in STYLE_PATTERNS:
        if pattern.search(stem):
            return style
    return "regular"


def family_of(stem: str) -> str:
    """Strip every style suffix, as extractFamily does."""
    for _, pattern in STYLE_PATTERNS:
        stem = pattern.sub("", stem, count=1)
    return re.sub(r"[-_ ]+$", "", stem)


def _rank(stem: str, style: str) -> int:
    """Position of this file's style keyword in the slot's preference list.

    A file whose classification came from the fallback rather than a real
    suffix (`Alto.otf`) ranks last, so an explicit weight always wins.
    """
    for _, pattern in STYLE_PATTERNS:
        match = pattern.search(stem)
        if match:
            keyword = re.sub(r"[-_ ]", "", match.group(1)).lower()
            ranks = KEYWORD_RANK[style]
            return ranks.index(keyword) if keyword in ranks else len(ranks)
    return len(KEYWORD_RANK[style]) + 1


def _squash(name: str) -> str:
    """A name with its separators gone, for comparing spellings of one thing."""
    return re.sub(r"[-_ ]", "", name).casefold()


def _weight_keyword(stem: str) -> str | None:
    """The style keyword a stem ends with, e.g. 'medium' for Alto-Medium."""
    for _, pattern in STYLE_PATTERNS:
        match = pattern.search(stem)
        if match:
            return re.sub(r"[-_ ]", "", match.group(1)).lower()
    return None


def _weight_matched_italic(parked: list[pathlib.Path], family: str,
                           regular: pathlib.Path) -> pathlib.Path | None:
    """The italic belonging to a non-standard regular weight, if there is one.

    The website drops every extra-weight italic, which is right when it would
    fight a plain Italic for the slot, but wrong when the family's regular face
    IS an extra weight: pairing Alto-Medium with the lighter Alto Italic
    leaves the italic visibly thinner than its roman. Here the file whose weight
    matches the chosen regular wins the slot back.
    """
    weight = _weight_keyword(font_stem(regular))
    if not weight:
        return None
    # Separators come off both sides. They come off the file either way, so a
    # family whose own name carries one -- Vantage_LT, PT_Serif-Web -- would
    # otherwise never match its own italic.
    wanted = {_squash(f"{family}{weight}{suffix}")
              for suffix in ("italic", "oblique")}
    for path in parked:
        if _squash(font_stem(path)) in wanted:
            return path
    return None


def _short_style(stem: str, wanted: str) -> str | None:
    """Style for a terse suffix on the wanted family, e.g. sampleb -> bold."""
    normalized = _squash(stem)
    wanted = _squash(wanted)
    if not normalized.startswith(wanted):
        return None
    rest = normalized[len(wanted):]
    for style, suffix in SHORT_SUFFIXES:
        if rest == suffix:
            return style
    return None


def discover_styles(directory: pathlib.Path, family: str) -> dict[str, pathlib.Path]:
    """Map style -> font file for one family in one directory.

    The family is matched case-insensitively, so a config named alto.conf
    finds Alto-Medium.otf without having to spell the family out.
    """
    found: dict[str, tuple[int, str, pathlib.Path]] = {}
    parked: list[pathlib.Path] = []
    wanted = family.casefold()
    fonts = sorted(p for p in (directory.iterdir() if directory.is_dir() else [])
                   if p.suffix.lower() in FONT_SUFFIXES and p.is_file())
    # Only then is a bare "b"/"i" suffix trustworthy (see SHORT_SUFFIXES).
    terse = any(font_stem(p).casefold() == wanted for p in fonts)

    for path in fonts:
        if EXTRA_WEIGHT_RE.search(font_stem(path)):
            parked.append(path)
            continue
        style: str | None = None
        rank = 0
        if family_of(font_stem(path)).casefold() == wanted:
            style = classify(font_stem(path))
            rank = _rank(font_stem(path), style)
        elif terse:
            style = _short_style(font_stem(path), wanted)
            # Worse than any spelled-out suffix, better than the bare stem, so
            # Family-Bold.ttf still beats familyb.ttf if a folder has both.
            rank = len(KEYWORD_RANK[style]) if style else 0
        if style is None:
            continue
        candidate = (rank, path.name, path)
        if style not in found or candidate < found[style]:
            found[style] = candidate

    styles = {style: entry[2] for style, entry in found.items()}
    if "regular" in styles:
        matched = _weight_matched_italic(parked, family, styles["regular"])
        if matched is not None:
            styles["italic"] = matched
    # A variable font is several faces in one file, so a family that ships two
    # of them ships four: the bold slots are the same files at the weight the
    # designer named Bold. A file that already holds the slot keeps it -- a
    # drawn bold beats an interpolated one.
    for style, source in (("bold", "regular"), ("bolditalic", "italic")):
        if style not in styles and source in styles \
                and can_synthesize(styles[source], style):
            styles[style] = styles[source]
    return styles


def discover_families(directory: pathlib.Path) -> dict[str, dict[str, pathlib.Path]]:
    """Every font family in a directory, as family -> {style: file}.

    Candidates are tried shortest-stem first and each claims its files, so a
    terse variant cannot invent a family of its own: `sample` claims
    sampleb/i/bi, and the leftover candidates `sampleb`, `samplei` and
    `samplebi` are dropped because every file they would use is taken.

    A weight that is genuinely its own family keeps one -- `Quill-Light`
    strips to itself, not to `Quill`, so it is built separately.
    """
    fonts = sorted(p for p in (directory.iterdir() if directory.is_dir() else [])
                   if p.suffix.lower() in FONT_SUFFIXES and p.is_file())
    candidates = sorted(
        {family_of(font_stem(p)) for p in fonts
         if not EXTRA_WEIGHT_RE.search(font_stem(p))},
        key=lambda stem: (len(stem), stem))

    found: dict[str, dict[str, pathlib.Path]] = {}
    claimed: set[pathlib.Path] = set()
    for family in candidates:
        if not family:
            continue
        styles = discover_styles(directory, family)
        if "regular" not in styles:
            continue
        files = set(styles.values())
        if files <= claimed:
            continue
        found[family] = styles
        claimed |= files
    return found


@dataclasses.dataclass
class Variant:
    """One output family: a name, a size list, and the config it came from."""
    name: str
    sizes: list[float]
    config: "Config"


@dataclasses.dataclass
class Config:
    path: pathlib.Path
    # True when the settings came from all.conf and the identity from filenames.
    derived: bool
    name: str
    family: str
    dir: pathlib.Path
    sizes: list[float]
    sizes_mod: list[float]
    mod_suffix: str
    intervals: str
    ranges: str
    fallbacks: bool
    space_glyphs: bool
    tuning: Tuning
    space_widths: dict[int, float]
    styles: dict[str, pathlib.Path]
    user_fallbacks: dict[str, pathlib.Path]
    #: Design coordinates a config pinned per slot, from `regular = f.ttf@wght=500`.
    #: Empty for every static family, which is nearly all of them.
    axis_overrides: dict[str, dict[str, float]] = dataclasses.field(
        default_factory=dict)
    #: The workspace this config belongs to, which is where its fallbacks and
    #: its builds live. `dir` may point somewhere else for the font files.
    root: pathlib.Path = pathlib.Path()

    def coords(self, style: str, size: float | None = None) -> dict[str, float]:
        """The design coordinates one slot is rasterized at, for one size.

        Empty unless that slot's file is a variable font. `size` is what the
        optical size axis follows, so this is per build rather than per family.
        """
        path = self.styles.get(style)
        if path is None:
            return {}
        return slot_coords(path, style, size, self.axis_overrides.get(style))

    @property
    def coverage(self) -> str:
        """intervals plus any raw ranges, as one --intervals argument."""
        parts = [self.intervals.strip(), self.ranges.strip()]
        return ",".join(p for p in parts if p)

    def variants(self) -> list[Variant]:
        out = []
        if self.sizes:
            out.append(Variant(self.name, self.sizes, self))
        if self.sizes_mod:
            out.append(Variant(self.name + self.mod_suffix, self.sizes_mod, self))
        return out

    def sources(self) -> list[pathlib.Path]:
        """Every font file that feeds the build, for hashing."""
        return [self.styles[s] for s in STYLES if s in self.styles] + \
            [self.user_fallbacks[k] for k in sorted(self.user_fallbacks)]


def size_label(size: float) -> int:
    """The integer a .cpfont filename carries for this point size.

    The device parses the size out of the filename with strtol and keeps it in
    a uint8_t (SdCardFontRegistry.cpp:85, CrossPointSettings.h:239), so a
    fractional size cannot be named or selected there. Nothing reads a point
    size out of the file itself, though -- it is a label for the picker, not a
    layout input -- so 13.5 pt shipped as `_14` renders 13.5 pt glyphs under a
    "14" in the menu.

    Half-up rather than Python's round(), which is half-to-even: a rule that
    turned 12.5 into 12 and 13.5 into 14 would be a puzzle on a font menu.
    """
    return math.floor(size + 0.5)


def size_spelling(size: float) -> str:
    """A size as a config writes it: 13, or 13.5 when it really is fractional."""
    return f"{size:g}"


def parse_sizes(raw: str, where: str) -> list[float]:
    tokens = [t for t in re.split(r"[,\s]+", raw.strip()) if t]
    # int() has to be inside the try as well: float() happily returns nan and
    # inf, and int(nan) raises ValueError while int(1e400) raises OverflowError
    # -- neither of which fontbuild catches, so one bad config would abort the
    # whole run with a traceback instead of being reported and skipped.
    try:
        # Keep whole sizes as ints so the common case prints and stamps as it
        # always did.
        sizes = [int(v) if v == int(v) else v
                 for v in (float(t) for t in tokens)]
    except (ValueError, OverflowError) as exc:
        raise FontConfigError(
            f"{where}: sizes must be numbers, got {raw!r}") from exc

    for size in sizes:
        # The label is what reaches the card, and the device's own parser
        # rejects anything outside 1..255 (SdCardFontRegistry.cpp:85), so a
        # size whose label falls outside it would build a file nothing loads.
        if not 1 <= size_label(size) <= 255:
            raise FontConfigError(
                f"{where}: size {size} labels as {size_label(size)}, and the "
                f"device only reads 1..255")

    # Two sizes that land on the same label would write the same .cpfont, and
    # since fontcli builds sizes in a pool they would race for the file. Equal
    # sizes count too: `13.5 13.5` is one output asked for twice.
    seen: dict[int, float] = {}
    for size in sizes:
        label = size_label(size)
        if label in seen:
            both = (f"{seen[label]} and {size}" if seen[label] != size
                    else f"{size} twice")
            raise FontConfigError(
                f"{where}: sizes {both} both land on {label}, so they would "
                f"write the same .cpfont")
        seen[label] = size
    return sizes


def _bool(raw: str, key: str, where: str) -> bool:
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise FontConfigError(f"{where}: {key} must be yes or no, got {raw!r}")


def tuning_from(values: dict[str, str], where: str) -> Tuning:
    """One Tuning from the config's keys."""
    raw = values.get("thresholds", "").strip()
    if raw:
        parts = [t for t in re.split(r"[,\s]+", raw) if t]
        if len(parts) != 3:
            raise FontConfigError(
                f"{where}: thresholds needs three numbers, got {raw!r}")
        try:
            thresholds = tuple(int(p) for p in parts)
        except ValueError as exc:
            raise FontConfigError(
                f"{where}: thresholds must be numbers, got {raw!r}") from exc
    else:
        thresholds = Tuning().thresholds

    hinting = values.get("hinting", "").strip().lower() or "normal"

    def number(key: str, default: str) -> float:
        try:
            return float(values.get(key, default))
        except ValueError as exc:
            raise FontConfigError(
                f"{where}: {key} must be a number, got {values[key]!r}") from exc

    # A factor rather than only a switch: the useful setting is usually
    # partial, so `yes` and `no` are spellings of 1.0 and 0.0.
    raw_kerning = values.get("kerning", "").strip().lower()
    if raw_kerning == "" or raw_kerning in _TRUE:
        kerning = 1.0
    elif raw_kerning in _FALSE:
        kerning = 0.0
    else:
        try:
            kerning = float(raw_kerning)
        except ValueError as exc:
            raise FontConfigError(
                f"{where}: kerning must be yes, no or a factor, "
                f"got {values['kerning']!r}") from exc

    raw_line_height = values.get("line_height", "").strip()
    try:
        line_height = LineHeight.parse(raw_line_height) if raw_line_height else None
    except ValueError as exc:
        raise FontConfigError(f"{where}: {exc}") from exc

    try:
        return Tuning(
            gamma=number("gamma", "1.0"),
            thresholds=thresholds,
            weight=number("weight", "0"),
            slant=number("slant", "0"),
            hinting=hinting,
            stem_darkening=_bool(values.get("stem_darkening", "no"),
                                 "stem_darkening", where),
            line_height=line_height,
            letter_spacing=number("letter_spacing", "0"),
            word_spacing=number("word_spacing", "0"),
            kerning=kerning,
            ligatures=_bool(values.get("ligatures", "yes"), "ligatures", where),
            figures=values.get("figures", "default").strip().lower() or "default")
    except ValueError as exc:
        raise FontConfigError(f"{where}: {exc}") from exc


def _space_widths(values: dict[str, str], where: str) -> dict[int, float]:
    """Per-codepoint space width overrides, from space_width_XXXX keys."""
    out = {}
    for key, raw in values.items():
        match = _SPACE_WIDTH_RE.match(key)
        if not match:
            continue
        try:
            out[int(match.group(1), 16)] = float(raw)
        except ValueError as exc:
            raise FontConfigError(
                f"{where}: {key} must be a number, got {raw!r}") from exc
    try:
        spacefont.resolve_widths(out)
    except KeyError as exc:
        raise FontConfigError(f"{where}: {exc.args[0]}") from exc
    return out


def read_values(path: pathlib.Path, allowed: set[str] | None = None) -> dict[str, str]:
    """Parse one .conf into a plain key -> value dict, rejecting unknown keys."""
    parser = configparser.ConfigParser()
    # The configs are a flat list of key = value pairs, as asked for. A section
    # header would be noise in a five-line file, so one is injected here.
    try:
        parser.read_string("[font]\n" + path.read_text(encoding="utf-8"),
                           source=str(path))
    except configparser.Error as exc:
        raise FontConfigError(f"{path.name}: {exc}") from exc

    values = dict(parser["font"])
    allowed = KNOWN_KEYS if allowed is None else allowed
    unknown = sorted(k for k in set(values) - allowed
                     if not _SPACE_WIDTH_RE.match(k))
    if unknown:
        raise FontConfigError(
            f"{path.name}: unknown key(s) {', '.join(unknown)}. "
            f"Known keys: {', '.join(sorted(allowed))}")
    return values


def tuning_values(tuning: Tuning) -> dict[str, str | None]:
    """A Tuning back as .conf keys -- the inverse of _tuning.

    None is "this key is not set", which is what a writer needs to know to
    remove a line rather than write one.
    """
    def number(value: float) -> str:
        return f"{value:g}"

    return {
        "gamma": number(tuning.gamma),
        "thresholds": ",".join(str(t) for t in tuning.thresholds),
        "weight": number(tuning.weight),
        "slant": number(tuning.slant),
        "hinting": tuning.hinting,
        "stem_darkening": "yes" if tuning.stem_darkening else "no",
        "line_height": str(tuning.line_height) if tuning.line_height else None,
        "letter_spacing": number(tuning.letter_spacing),
        "word_spacing": number(tuning.word_spacing),
        "kerning": number(tuning.kerning),
        "ligatures": "yes" if tuning.ligatures else "no",
        "figures": tuning.figures,
    }


#: Heading for keys a tool appends to a hand-written config, so they do not
#: read as belonging to whatever section the file happened to end with.
WRITTEN_SECTION = "# --- set from the preview -----------------------------------"


def write_values(path: pathlib.Path, changes: dict[str, str | None],
                 section: str = WRITTEN_SECTION) -> list[str]:
    """Set or remove keys in a .conf, leaving every other byte where it is.

    A value of None removes the key. Returns the keys that actually moved.

    These files are written by hand and documented in their own comments --
    alto.conf is sixty lines of them around eight settings -- so this is a
    line editor rather than a configparser round trip, which would flatten the
    lot. A key already in the file keeps its place and its padding; a key that
    is only there commented out is uncommented in place, which is where the
    file's own examples are; anything else is appended.

    The write is atomic: a half-written config is one the builder cannot read,
    and it would be the file holding the settings you had just tuned.
    """
    lines = (path.read_text(encoding="utf-8").splitlines(keepends=True)
             if path.is_file() else [])
    moved: list[str] = []

    def find(pattern: re.Pattern) -> int | None:
        return next((i for i, line in enumerate(lines) if pattern.match(line)),
                    None)

    for key, value in changes.items():
        live = re.compile(rf"^(\s*){re.escape(key)}(\s*)=", re.IGNORECASE)
        commented = re.compile(rf"^\s*#\s*{re.escape(key)}\s*=", re.IGNORECASE)
        at = find(live)
        if value is None:
            if at is None:
                continue                        # not set here; nothing to do
            del lines[at]
            moved.append(key)
            continue

        if at is not None:
            if lines[at].split("=", 1)[1].strip() == value:
                continue                        # already what it should be
            match = live.match(lines[at])
            lines[at] = f"{match[1]}{key}{match[2]}= {value}\n"
        else:
            spot = find(commented)
            if spot is not None:
                lines[spot] = f"{key} = {value}\n"
            else:
                if lines and not lines[-1].endswith("\n"):
                    lines[-1] += "\n"
                if section and not any(line.startswith(section)
                                       for line in lines):
                    # A blank line to stand it off from what is above, unless
                    # the heading *is* the top of a file being created.
                    lines += (["\n"] if lines else []) + [section + "\n"]
                lines.append(f"{key} = {value}\n")
        moved.append(key)

    if not moved:
        return []
    temporary = path.with_name(path.name + ".writing")
    temporary.write_text("".join(lines), encoding="utf-8")
    temporary.replace(path)
    return moved


def parse_config(path: pathlib.Path, values: dict[str, str] | None = None,
                 family: str | None = None, derived: bool = False,
                 root: pathlib.Path | str | None = None) -> Config:
    """Resolve one .conf into a buildable Config.

    `values` carries the already-merged settings (all.conf underneath the file's
    own keys). `family` and `derived` are for families all.conf covers without
    naming: the settings come from the shared file, the identity from the font
    filenames. `root` is the workspace the font files sit in, which is one
    level up from the configs.
    """
    path = pathlib.Path(path)
    if values is None:
        values = read_values(path)

    where = path.name
    if family is None:
        # Falls back to the config's filename, not to `name`: the file is named
        # after the family, while `name` only renames the output. Otherwise
        # `name = Qui` in quill.conf would send discovery looking for a
        # family called "Qui".
        family = values.get("family", "").strip() or path.stem
    # `dir` resolves against the workspace rather than against the config's own
    # folder, because the configs live in conf/ and the fonts one level up.
    root = pathlib.Path(root) if root is not None else path.parent
    directory = (root / values.get("dir", ".").strip()).resolve()

    styles = discover_styles(directory, family)
    # Take the family's real capitalisation from the files rather than from the
    # config's filename, so alto.conf produces Alto and not alto.
    if "regular" in styles:
        family = family_of(font_stem(styles["regular"]))
    name = family if derived else values.get("name", family)
    name = sanitize_name(name)
    fallbacks: dict[str, pathlib.Path] = {}
    overrides: dict[str, dict[str, float]] = {}
    for key in PATH_KEYS:
        if key not in values:
            continue
        filename, axes = split_axes(values[key].strip(), key, where)
        candidate = (directory / filename).resolve()
        if not candidate.is_file():
            raise FontConfigError(f"{where}: {key} = {values[key].strip()} not found "
                                  f"in {directory}")
        if key in STYLES:
            styles[key] = candidate
            if axes:
                overrides[key] = axes
        elif axes:
            raise FontConfigError(
                f"{where}: {key} takes a filename, not design coordinates. Only "
                f"the four style keys are rasterized at a chosen instance.")
        else:
            fallbacks[key] = candidate
    for key, axes in overrides.items():
        font = variable_font(styles[key])
        unknown = sorted(set(axes) - set(font.axes if font else ()))
        if unknown:
            have = (", ".join(sorted(font.axes)) if font
                    else "none, since it is not variable")
            raise FontConfigError(
                f"{where}: {key} asks for {', '.join(unknown)}, which "
                f"{styles[key].name} does not have. Its axes: {have}.")

    if "regular" not in styles:
        raise FontConfigError(
            f"{where}: no regular face found for family {family!r} in {directory}. "
            f"Set 'family' to the shared part of the filenames, or name the files "
            f"explicitly with 'regular = ...'.")

    return Config(
        path=path,
        derived=derived,
        name=name,
        family=family,
        dir=directory,
        sizes=parse_sizes(values.get("sizes", ""), where) or DEFAULT_SIZES,
        sizes_mod=parse_sizes(values.get("sizes_mod", ""), where),
        mod_suffix=sanitize_name(values.get("mod_suffix", "Mod")),
        intervals=values.get("intervals", DEFAULT_INTERVALS).strip() or DEFAULT_INTERVALS,
        ranges=values.get("ranges", "").strip(),
        fallbacks=_bool(values.get("fallbacks", "yes"), "fallbacks", where),
        space_glyphs=_bool(values.get("space_glyphs", "yes"), "space_glyphs", where),
        tuning=tuning_from(values, where),
        space_widths=_space_widths(values, where),
        styles=styles,
        user_fallbacks=fallbacks,
        axis_overrides=overrides,
        root=root,
    )

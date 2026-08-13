"""Drive the .cpfont converter over a folder of font configs.

The converter is src/crossglyph/cpfont/, a fork of the script behind
https://crosspointreader.com/fonts. See that package's UPSTREAM for the pin and
the refresh procedure.

It is imported and called, not run as a subprocess: a preview cannot afford an
interpreter start per keystroke, and once the script is our own code there is
nothing to sandbox. Parallelism comes from the process pool in the CLI instead.
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import os
import pathlib
import struct
import typing

from . import cpfont, fontconf, fontstamp, spacefont
from .fontconf import STYLES, Config, FontConfigError, Variant, parse_config

#: The tool's own root, which is where an unpacked release keeps its workspace.
ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Where fetch_fallbacks puts them, and the first place fallback_dir looks:
#: beside the fonts they fill in, so one folder holds a family's sources, its
#: config, its builds and this. `fallback_dir` in all.conf overrides it.
FALLBACK_NAME = "fallbacks"

#: The face every set has, used to tell a real fallback folder from an empty
#: one somebody happened to create.
ANCHOR_FACE = "NotoSans-Regular.ttf"

#: Where a fetch downloads from. The faces are OFL, and this is the copy the
#: website's own converter ships.
FALLBACK_URL = ("https://raw.githubusercontent.com/crosspoint-reader/"
                "crosspoint-tools/master/scripts/font-builder/"
                "default-fallback-fonts/")

#: Carried along so the licence travels with the fonts, as the OFL requires.
FALLBACK_LICENCE = "OFL.txt"

#: The workspace: font files at its root, configs in conf/, builds in cpfonts/.
#: A release keeps one beside the launcher, which is what a tester fills in.
SOURCE_DIR = pathlib.Path(os.environ.get("CROSSGLYPH_FONTS") or ROOT / "fonts")

#: The family that ships with the tool, inside the package rather than in the
#: workspace, which belongs to whoever unpacked it. An empty folder and an
#: error is a poor first five minutes, so this stands in until there is a font
#: to prefer. Literata is OFL, and one variable file per posture fills all four
#: style slots with its opsz axis following the size being built -- so the
#: family it opens on exercises the knobs rather than just filling the picker.
STARTER_DIR = pathlib.Path(__file__).resolve().parent / "starter"

#: Where built families go when nothing says otherwise: beside their sources,
#: so a family's files, its config and its builds sit in one place. That also
#: gives a copy of this tool somewhere to write that it certainly owns.
OUTPUT_NAME = "cpfonts"

# .github/workflows/build-fonts.yml, in order. These fill holes the chosen
# family does not cover, on every style: the converter appends the style-0 list
# to all four (cpfont/convert.py:882).
BUNDLED_FALLBACKS = (
    "NotoSans-Regular.ttf",
    "NotoSansHebrew-Regular.ttf",
    "NotoSansArmenian-Regular.ttf",
    "NotoSansGeorgian-Regular.ttf",
    "NotoSansEthiopic-Regular.ttf",
    "NotoSansCherokee-Regular.ttf",
    "NotoSansTifinagh-Regular.ttf",
    "NotoSansCoptic-Regular.ttf",
    "NotoSansMath-Regular.ttf",
    "NotoSansSymbols-Regular.ttf",
    "NotoSansSymbols2-Regular.ttf",
    "NotoEmoji-Regular.ttf",
)

# Same workflow: which CJK faces get appended, chosen by the requested script.
CJK_FALLBACKS = {
    "cjk-jp": ("NotoSansCJKjp-Regular.otf", "NotoSansCJKsc-Regular.otf"),
    "cjk-tc": ("NotoSansCJKtc-Regular.otf", "NotoSansCJKsc-Regular.otf"),
    "cjk-sc": ("NotoSansCJKsc-Regular.otf", "NotoSansCJKjp-Regular.otf"),
}
DEFAULT_CJK_FALLBACK = ("NotoSansCJKjp-Regular.otf",)


class FontBuildError(RuntimeError):
    """The converter failed for one family."""


class FallbacksMissing(FileNotFoundError):
    """The bundled Noto faces are not in the workspace.

    A type of its own because it is the one missing file a caller can offer to
    go and get: the message below names the command, and the preview adds its
    own button to it. Anything else that is not there is not that.
    """


def output_dir(source: pathlib.Path | str | None = None) -> pathlib.Path:
    """Where this source folder's builds go.

    all.conf's `out` wins, so a folder can say where its own families belong
    and every tool that reads it agrees -- the builder, the preview's Build
    button and the launcher's install step. A relative path resolves against
    the source folder, which is the useful form: `out = ../cpfonts-built`
    moves them without naming a drive.

    Then $CROSSGLYPH_OUT, then a `cpfonts` folder beside the sources.
    """
    source = pathlib.Path(source) if source else SOURCE_DIR
    declared = load_defaults(source).get("out", "").strip()
    if declared:
        return pathlib.Path(source, declared).resolve()
    if os.environ.get("CROSSGLYPH_OUT"):
        return pathlib.Path(os.environ["CROSSGLYPH_OUT"])
    return source / OUTPUT_NAME


def fallback_candidates(source: pathlib.Path | str | None = None) -> list[pathlib.Path]:
    """Every place the bundled faces might be, best first.

    `fallback_dir` in all.conf, then a `fallbacks` folder in the workspace,
    which is where a fetch puts them.
    """
    source = pathlib.Path(source) if source else SOURCE_DIR
    declared = load_defaults(source).get("fallback_dir", "").strip()
    return ([pathlib.Path(source, declared).resolve()] if declared else []) + [
        source / FALLBACK_NAME]


def fallback_dir(source: pathlib.Path | str | None = None) -> pathlib.Path | None:
    """The first candidate that actually holds the faces, or None.

    Judged by the one face every set has rather than by the folder existing:
    an empty `fallbacks/` somebody created must not shadow a real set.
    """
    for path in fallback_candidates(source):
        if (path / ANCHOR_FACE).is_file():
            return path
    return None


def require_bundled_fallbacks(source: pathlib.Path | str | None = None) -> pathlib.Path:
    """Where the bundled Noto faces are, or how to get them.

    These fonts are large, unmodified and OFL, so they are neither vendored in
    this repo nor rewritten: they are fetched once into the font source folder,
    or read from a checkout that already has them.
    """
    found = fallback_dir(source)
    if found is not None:
        return found
    looked = "\n".join(f"  {path}" for path in fallback_candidates(source))
    raise FallbacksMissing(
        "the bundled fallback fonts were not found. Looked in:\n"
        f"{looked}\n"
        "Fetch them with `crossglyph fetch-fallbacks` (3.4 MB, or 19 MB "
        "with a CJK script), or set 'fallbacks = no' in the font config.")


def bundled_fallbacks(intervals: str) -> list[str]:
    """Bundled fallback filenames for a coverage string, workflow order."""
    requested = {token.strip().lower() for token in intervals.split(",")}
    for preset, files in CJK_FALLBACKS.items():
        if preset in requested:
            return list(BUNDLED_FALLBACKS) + list(files)
    return list(BUNDLED_FALLBACKS) + list(DEFAULT_CJK_FALLBACK)


def wanted_fallbacks(intervals: str, directory: pathlib.Path) -> list[pathlib.Path]:
    """The bundled faces this coverage needs, in workflow order.

    A CJK face is 15.7 MB and only earns that when a CJK script was asked for.
    The one appended to every build is a catch-all, so it is skipped when it is
    not there rather than failing a Latin family over it; anything else missing
    was requested outright, and that is an error with the fetch in it.
    """
    asked_for_cjk = any(preset in intervals.lower() for preset in CJK_FALLBACKS)
    paths, missing = [], []
    for name in bundled_fallbacks(intervals):
        path = directory / name
        if path.is_file():
            paths.append(path)
        elif not asked_for_cjk and name in DEFAULT_CJK_FALLBACK:
            continue                    # nobody asked for CJK; carry on
        else:
            missing.append(name)
    if missing:
        raise FallbacksMissing(
            f"{directory} is missing {', '.join(missing)}. Fetch the set with "
            f"`crossglyph fetch-fallbacks`, or set 'fallbacks = no'.")
    return paths


#: What a pan-CJK face is for. Han and the two kana blocks, hangul and its
#: jamo, the CJK punctuation those are written with, and the compatibility and
#: fullwidth blocks a book picks up from its source. Nothing in the twelve
#: faces above has a glyph in any of them, so text that needs one of these
#: draws as blank space until a CJK face is fetched.
CJK_RANGES = (
    (0x2E80, 0x2FDF),                   # radicals
    (0x3000, 0x303F),                   # CJK punctuation
    (0x3040, 0x30FF),                   # hiragana and katakana
    (0x3130, 0x318F),                   # hangul compatibility jamo
    (0x3400, 0x4DBF), (0x4E00, 0x9FFF),  # han
    (0xAC00, 0xD7A3),                   # hangul syllables
    (0xF900, 0xFAFF),                   # compatibility ideographs
    (0xFF00, 0xFFEF),                   # halfwidth and fullwidth forms
)


def needs_cjk(text: str) -> bool:
    """Whether this text wants one of the pan-CJK faces.

    One of them answers all four languages rather than one each:
    NotoSansCJKjp carries 20,976 han, 11,172 hangul and both kana, so Korean is
    covered by it as well, which is just as well since no Korean face is
    published beside the others.
    """
    return any(low <= code <= high
               for code in map(ord, text) for low, high in CJK_RANGES)


def fetch_plan(intervals: str = "", text: str = "") -> list[str]:
    """Which files a fetch would put in the workspace, in order.

    A CJK face is 15.7 MB against 3.4 MB for everything else, so it comes only
    when something has asked for it: a coverage that names a script, or text
    that cannot be drawn without one. The second is what makes pressing Fetch
    enough when the page says characters are missing, rather than sending
    somebody off to find the right coverage box first.
    """
    names = list(BUNDLED_FALLBACKS) + [FALLBACK_LICENCE]
    asked = any(preset in intervals.lower() for preset in CJK_FALLBACKS)
    if asked or needs_cjk(text):
        names += [name for name in bundled_fallbacks(intervals)
                  if name not in BUNDLED_FALLBACKS]
    return names


def fetch_steps(source: pathlib.Path | str | None = None, intervals: str = "",
                text: str = "") -> typing.Iterator[dict]:
    """Fetch the bundled faces, saying how far it has got.

    Downloaded from the same OFL files the website's own converter ships. The
    licence travels with them.

    Sizes are read first so the progress is in bytes rather than in files. One
    file is usually four fifths of the download, so counting files would race
    to the last one and then look stalled for a minute.
    """
    import urllib.request

    source = pathlib.Path(source) if source else SOURCE_DIR
    target = source / FALLBACK_NAME
    target.mkdir(parents=True, exist_ok=True)

    landed, wanted = [], []
    for name in fetch_plan(intervals, text):
        path = target / name
        if path.is_file():
            landed.append(path)
        else:
            wanted.append((name, path))

    # Asked for up front so the progress can be in bytes. A server that does
    # not say is not an error: the download still works, the bar just has less
    # to go on, so an absent length counts as nothing rather than stopping.
    total = 0
    for name, _ in wanted:
        ask = urllib.request.Request(FALLBACK_URL + name, method="HEAD")
        with urllib.request.urlopen(ask, timeout=30) as answer:
            headers = getattr(answer, "headers", None)
            total += int((headers.get("content-length") if headers else 0) or 0)
    yield {"event": "plan", "files": len(wanted), "bytes": total}

    got = 0
    for name, path in wanted:
        yield {"event": "start", "name": name, "got": got, "bytes": total}
        # Written aside and moved into place, so an interrupted fetch cannot
        # leave a half a font that every later run treats as present.
        part = path.with_name(path.name + ".part")
        with urllib.request.urlopen(FALLBACK_URL + name, timeout=60) as answer:
            with part.open("wb") as out:
                while chunk := answer.read(262144):
                    out.write(chunk)
                    got += len(chunk)
                    yield {"event": "step", "name": name,
                           "got": got, "bytes": total}
        part.replace(path)
        landed.append(path)
    yield {"event": "done", "where": str(target), "faces": len(landed)}


def fetch_fallbacks(source: pathlib.Path | str | None = None,
                    intervals: str = "", text: str = "",
                    *, say=print) -> list[pathlib.Path]:
    """fetch_steps for a caller with nothing to show progress on."""
    source = pathlib.Path(source) if source else SOURCE_DIR
    for step in fetch_steps(source, intervals, text):
        if step["event"] == "start":
            say(f"  downloading {step['name']}")
    target = source / FALLBACK_NAME
    say(f"fallback faces in {target}")
    return [target / name for name in fetch_plan(intervals, text)
            if (target / name).is_file()]


def space_font_path(out_dir: pathlib.Path) -> pathlib.Path:
    return out_dir / spacefont.FILENAME


def ensure_space_font(out_dir: pathlib.Path,
                      widths: dict[int, float] | None = None) -> pathlib.Path:
    """Generate the space-only fallback font if it is not already there."""
    path = space_font_path(out_dir)
    if not path.is_file():
        spacefont.build(path, widths)
    return path


STYLE_IDS = {"regular": 0, "bold": 1, "italic": 2, "bolditalic": 3}


def build_kwargs(variant: Variant, size: int, out_dir: pathlib.Path) -> dict:
    """Arguments for one generate_cpfont_multistyle call: one family, one size.

    The converter takes every fallback for style 0 and appends that list to all
    four styles itself (cpfont/convert.py:882), which is why the user, bundled
    and space faces all go into one ordered list.
    """
    config: Config = variant.config
    style_fonts = {STYLE_IDS[style]: str(config.styles[style])
                   for style in STYLES if style in config.styles}

    fallbacks: list[str] = []
    for key in ("fallback_regular", "fallback2_regular"):
        if key in config.user_fallbacks:
            fallbacks.append(str(config.user_fallbacks[key]))
    if config.fallbacks:
        bundled = require_bundled_fallbacks(config.root)
        fallbacks += [str(path)
                      for path in wanted_fallbacks(config.coverage, bundled)]
    # Independent of `fallbacks`: this one supplies nothing but the fixed-width
    # spaces, so it cannot pad the build, and without it U+2006 and friends are
    # simply not drawn (see spacefont). Last, so a real face keeps its own.
    if config.space_glyphs:
        fallbacks.append(str(space_font_path(out_dir)))

    # A variable file fills several slots, each at its own coordinates, and the
    # optical size axis follows the size being built -- so this is per size and
    # not per family. Empty for a static family, which is nearly all of them.
    style_axes = {STYLE_IDS[style]: coords
                  for style in STYLES if style in config.styles
                  for coords in [config.coords(style, size)] if coords}

    return {
        "style_fonts": style_fonts,
        "style_axes": style_axes or None,
        "size": size,
        "intervals": cpfont.resolve_intervals(config.coverage),
        "output_path": str(fontstamp.cpfont_path(out_dir / variant.name,
                                                 variant, size)),
        "fallback_style_fonts": {0: fallbacks} if fallbacks else None,
        "tuning": config.tuning,
    }


@dataclasses.dataclass
class Report:
    variant: str
    built: list[int] = dataclasses.field(default_factory=list)
    skipped: list[int] = dataclasses.field(default_factory=list)
    failed: list[int] = dataclasses.field(default_factory=list)
    removed: list[pathlib.Path] = dataclasses.field(default_factory=list)
    error: str | None = None


@dataclasses.dataclass
class Job:
    """One size of one family: the unit of work, and of parallelism."""
    variant: Variant
    size: int

    @property
    def label(self) -> str:
        return f"{self.variant.name} {self.size}"


def default_jobs() -> int:
    """Worker count. Rasterizing is CPU-bound and each job is its own process,
    so this scales with cores; the cap keeps a big family from opening a dozen
    copies of a CJK font at once."""
    return max(1, min(os.cpu_count() or 4, 12))


class Metrics(typing.NamedTuple):
    glyphs: int
    advance_y: int
    ascender: int
    descender: int


def style_metrics(path: pathlib.Path) -> Metrics:
    """The first style's counts and line metrics, from the .cpfont TOC.

    Worth surfacing: the glyph count is what explains an unexpectedly large
    file -- 300 codepoints building to 3000 glyphs means the bundled fallbacks
    are padding it, which the byte size alone does not say. The line metrics are
    what a too-tight line_height has to be checked against.

    Layout, from cpfont/convert.py:971-979 -- a 32-byte header, then 32-byte
    style TOC entries: glyphCount at +8, advanceY +12, ascender +13, descender
    +15.
    """
    with path.open("rb") as handle:
        header = handle.read(32 + 32)
    if len(header) < 64 or header[:8] != b"CPFONT\x00\x00":
        return Metrics(0, 0, 0, 0)
    glyphs, advance_y = struct.unpack_from("<IB", header, 32 + 8)
    ascender, descender = struct.unpack_from("<hh", header, 32 + 13)
    return Metrics(glyphs, advance_y, ascender, descender)


def glyph_count(path: pathlib.Path) -> int:
    return style_metrics(path).glyphs


class Built(typing.NamedTuple):
    bytes: int
    glyphs: int
    warnings: tuple[str, ...] = ()


def build_size(job: Job, out_dir: pathlib.Path) -> Built:
    """Build one .cpfont. Returns its size in bytes and its glyph count."""
    if job.variant.config.space_glyphs:
        ensure_space_font(out_dir, job.variant.config.space_widths)
    kwargs = build_kwargs(job.variant, job.size, out_dir)
    path = pathlib.Path(kwargs["output_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    # The converter prints progress to stderr; the CLI runs several of these at
    # once and interleaved lines are nonsense, so it is silenced and only the
    # exception survives to be reported.
    with contextlib.redirect_stderr(io.StringIO()) as captured:
        try:
            cpfont.generate_cpfont_multistyle(**kwargs)
        except cpfont.FontBuildError as exc:
            raise FontBuildError(str(exc)) from exc
        except Exception as exc:
            tail = "\n".join(captured.getvalue().splitlines()[-10:])
            raise FontBuildError(f"{type(exc).__name__}: {exc}\n{tail}") from exc
    if not path.is_file():
        raise FontBuildError("converter reported success but wrote no file")

    # Warnings travel back in the result rather than being printed: the
    # converter's own stderr is captured above and thrown away on success, and
    # several of these run at once.
    metrics = style_metrics(path)
    warnings = []
    band = metrics.ascender - metrics.descender
    # Only about a pitch that was asked for. Plenty of fonts declare a band
    # wider than their own line height -- NotoSans has a negative lineGap, so
    # its ascender and descender span 35px against a 34px pitch -- and those
    # are worst-case bounds that real adjacent lines rarely both reach.
    if (job.variant.config.tuning.line_height is not None
            and metrics.advance_y and band > metrics.advance_y):
        warnings.append(
            f"line_height {metrics.advance_y}px is under the {band}px this "
            f"font's ascender and descender span, so consecutive lines may "
            f"overlap")
    return Built(path.stat().st_size, metrics.glyphs, tuple(warnings))


def plan_variant(variant: Variant, out_dir: pathlib.Path,
                 force: bool = False) -> tuple[Report, list[Job]]:
    """Prune dropped sizes and work out what still needs building."""
    directory = out_dir / variant.name
    directory.mkdir(parents=True, exist_ok=True)
    report = Report(variant.name)
    report.removed = fontstamp.prune(directory, variant)
    stale = fontstamp.stale_sizes(variant, directory, force=force)
    report.skipped = [s for s in variant.sizes if s not in stale]
    return report, [Job(variant, size) for size in stale]


def finalize_variant(variant: Variant, out_dir: pathlib.Path,
                     failed: set[int]) -> None:
    """Record what is now current.

    Sizes that failed are left out, so the next run retries exactly those and
    nothing else. Skipped sizes keep their entry because they are still valid.
    """
    directory = out_dir / variant.name
    fontstamp.write_stamp(directory, {
        size: fontstamp.digest(variant, size)
        for size in variant.sizes
        if size not in failed
        and fontstamp.cpfont_path(directory, variant, size).is_file()})


def build_variant(variant: Variant, out_dir: pathlib.Path,
                  force: bool = False) -> Report:
    """Build one variant serially. The CLI parallelizes across variants; this
    is the single-variant path used by tests and by callers with one family."""
    report, jobs = plan_variant(variant, out_dir, force=force)
    for job in jobs:
        build_size(job, out_dir)
        report.built.append(job.size)
    if jobs:
        finalize_variant(variant, out_dir, failed=set())
    return report


def build_families(configs, out_dir: pathlib.Path, force: bool = False,
                   prune: bool = False):
    """Build every variant of every config, saying where it has got to.

    Yields a dict per step: one `plan` first, then a `size` as each .cpfont
    lands, then `done`. The plan comes first because it costs a stamp read per
    size and answers "how many is this going to be" -- without which a progress
    line can only count upwards and hope.

    Serial on purpose: the CLI parallelises across a process pool, which cannot
    report until a whole family is finished, and this exists to report.

    A size that fails is recorded and the rest of that family is skipped -- the
    next one usually fails the same way -- but the other families carry on, so
    a folder-wide build is not lost to one bad face.

    `prune` is for a build of everything, and only that: a family that no
    config produces any more leaves a whole directory behind that per-size
    pruning never looks at, and the simulator would go on staging it. With a
    chosen config the families that were not asked for are absent from the
    plan rather than orphaned, so pruning then would delete the folder.
    """
    import shutil

    plans = []
    for config in configs:
        for variant in config.variants():
            report, jobs = plan_variant(variant, out_dir, force=force)
            plans.append((variant, report, jobs))

    removed = []
    if prune:
        for path in orphan_dirs(out_dir, {variant.name for variant, _, _ in plans}):
            shutil.rmtree(path)
            removed.append(path.name)

    total = sum(len(jobs) for _, _, jobs in plans)
    yield {"event": "plan", "total": total, "out": str(out_dir),
           "families": [variant.name for variant, _, _ in plans],
           "removed": removed}

    done = 0
    for variant, report, jobs in plans:
        for job in jobs:
            try:
                build_size(job, out_dir)
            except FontBuildError as exc:
                report.error = str(exc)
                report.failed = [size for size in variant.sizes
                                 if size not in report.built
                                 and size not in report.skipped]
                done += len(jobs) - len(report.built)
                yield {"event": "failed", "family": variant.name,
                       "size": job.size, "done": done, "total": total,
                       "error": str(exc)}
                break
            report.built.append(job.size)
            done += 1
            yield {"event": "size", "family": variant.name, "size": job.size,
                   "done": done, "total": total}
        if jobs:
            finalize_variant(variant, out_dir, failed=set(report.failed))

    yield {"event": "done", "out": str(out_dir), "removed": removed,
           "families": [{"name": variant.name,
                         "sizes": sorted(variant.sizes),
                         "built": sorted(report.built),
                         "skipped": sorted(report.skipped),
                         "failed": sorted(report.failed),
                         "removed": sorted(str(path) for path in report.removed),
                         "error": report.error}
                        for variant, report, _ in plans]}


def orphan_dirs(out_dir: pathlib.Path, wanted: set[str]) -> list[pathlib.Path]:
    """Family directories we built that no config produces any more.

    Dropping `sizes_mod`, or renaming a family, leaves a whole directory behind
    that per-size pruning never looks at -- and the simulator would go on
    staging it. Only directories carrying our own stamp file are considered, so
    a family that was put there by hand is never touched.
    """
    if not out_dir.is_dir():
        return []
    return [path for path in sorted(out_dir.iterdir())
            if path.is_dir() and path.name not in wanted
            and (path / fontstamp.STAMP_NAME).is_file()]


# The shared defaults file. Not a family of its own: it supplies values that
# per-font configs inherit, and covers every family that has no config at all.
DEFAULTS_NAME = "all.conf"

#: Configs sit in their own folder, so the workspace root holds font files and
#: nothing else.
CONF_NAME = "conf"

# Keys that cannot be shared, because they name one specific family or file.
PER_FONT_ONLY = {"name", "family"} | fontconf.PATH_KEYS
DEFAULTS_KEYS = fontconf.KNOWN_KEYS - PER_FONT_ONLY


def conf_dir(source: pathlib.Path | str | None = None) -> pathlib.Path:
    """Where a workspace keeps its configs."""
    source = pathlib.Path(source) if source else SOURCE_DIR
    return source / CONF_NAME


def discover_configs(source: pathlib.Path) -> list[pathlib.Path]:
    """Per-font configs, which is every *.conf except the shared defaults."""
    return [p for p in sorted(conf_dir(source).glob("*.conf"))
            if p.name.lower() != DEFAULTS_NAME]


def load_defaults(source: pathlib.Path) -> dict[str, str]:
    """Values from all.conf, or an empty dict when there is none."""
    path = conf_dir(source) / DEFAULTS_NAME
    if not path.is_file():
        return {}
    return fontconf.read_values(path, allowed=DEFAULTS_KEYS)


def load(paths: list[pathlib.Path], defaults: dict[str, str] | None = None,
         root: pathlib.Path | None = None) -> tuple[list[Config], list[str]]:
    """Parse configs, collecting failures instead of stopping at the first.

    Each file's own keys sit on top of the shared defaults, so a per-font config
    only has to state what it does differently.
    """
    configs, errors = [], []
    for path in paths:
        try:
            values = {**(defaults or {}), **fontconf.read_values(path)}
            configs.append(parse_config(path, values=values, root=root))
        except FontConfigError as exc:
            errors.append(str(exc))
    return configs, errors


def derived_configs(source: pathlib.Path, defaults: dict[str, str],
                    covered: set[str]) -> tuple[list[Config], list[str]]:
    """One config per family in the folder that no per-font config claims."""
    path = conf_dir(source) / DEFAULTS_NAME
    directory = (source / defaults.get("dir", ".").strip()).resolve()
    configs, errors = [], []
    for family in fontconf.discover_families(directory):
        if family.casefold() in covered:
            continue
        try:
            configs.append(parse_config(path, values=defaults, family=family,
                                        derived=True, root=source))
        except FontConfigError as exc:
            errors.append(str(exc))
    return configs, errors


def starter_configs(source: pathlib.Path,
                    defaults: dict[str, str]) -> tuple[list[Config], list[str]]:
    """The bundled family, for a workspace that has nothing of its own yet.

    Read where it is installed rather than copied into the workspace: that
    folder is the reader's, and a tool that drops files in it unasked is one
    you have to clean up after. `dir` is what a Save writes so the config goes
    on resolving once the folder has a font of its own and this steps aside.
    """
    if not STARTER_DIR.is_dir():
        return [], []                   # an install missing its own faces
    path = conf_dir(source) / DEFAULTS_NAME
    values = {**defaults, "dir": str(STARTER_DIR)}
    configs, errors = [], []
    for family in fontconf.discover_families(STARTER_DIR):
        try:
            configs.append(parse_config(path, values=values, family=family,
                                        derived=True, root=source))
        except FontConfigError as exc:
            errors.append(str(exc))
    return configs, errors


def gather(source: pathlib.Path,
           tokens: list[str] | None = None) -> tuple[list[Config], list[str]]:
    """Everything to build: per-font configs first, then the folder's families.

    Selection by token matches a config filename, a family name or an output
    name, so a family no config names is still addressable by name.

    A folder with fonts in it and no config at all is a family list, which is
    what `fonts/README.md` promises and what somebody who has just unpacked a
    release has. all.conf carries shared settings; it is not the switch that
    turns discovery on.
    """
    defaults = load_defaults(source)
    configs, errors = load(discover_configs(source), defaults, root=source)
    covered = {c.family.casefold() for c in configs}
    covered |= {c.name.casefold() for c in configs}

    more, more_errors = derived_configs(source, defaults, covered)
    configs += sorted(more, key=lambda c: c.name.casefold())
    errors += more_errors

    # Last, and only when the folder came up empty, so a workspace with fonts
    # in it never has the bundled family competing with them.
    if not configs:
        more, more_errors = starter_configs(source, defaults)
        configs += more
        errors += more_errors

    if not tokens:
        return configs, errors

    wanted = {t.casefold().removesuffix(".conf") for t in tokens}
    chosen = [c for c in configs
              if {c.name.casefold(), c.family.casefold(), c.path.stem.casefold()}
              & wanted]
    missed = wanted - {v for c in chosen
                       for v in (c.name.casefold(), c.family.casefold(),
                                 c.path.stem.casefold())}
    for token in sorted(missed):
        errors.append(f"no config or font family matching {token!r} in {source}")
    return chosen, errors

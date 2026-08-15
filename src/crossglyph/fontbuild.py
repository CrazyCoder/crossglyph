"""Drive the .cpfont converter over a folder of font configs.

The converter is src/crossglyph/cpfont/, a fork of the script behind
https://crosspointreader.com/fonts. See that package's UPSTREAM for the pin and
the refresh procedure.

It is imported and called, not run as a subprocess: a preview cannot afford an
interpreter start per keystroke, and once the script is our own code there is
nothing to sandbox. A build is the other case, and gets a process pool: one
size of one family is the unit of work, and there are usually more of those
than there are cores.
"""
from __future__ import annotations

import concurrent.futures
import contextlib
import dataclasses
import io
import os
import pathlib
import struct
import tempfile
import time
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
#: to prefer, and stays in the picker after that as something to compare
#: against. Literata is OFL, and one variable file per posture fills all four
#: style slots with its opsz axis following the size being built -- so the
#: family it opens on exercises the knobs rather than just filling the picker.
STARTER_DIR = pathlib.Path(__file__).resolve().parent / "starter"

#: Where built families go when nothing says otherwise: beside their sources,
#: so a family's files, its config and its builds sit in one place. That also
#: gives a copy of this tool somewhere to write that it certainly owns.
OUTPUT_NAME = "cpfonts"

# .github/workflows/build-fonts.yml, in order. These fill holes the chosen
# family does not cover, on every style: generate_cpfont_multistyle appends
# the style-0 list to all four itself.
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


def space_font_path(widths: dict[int, float] | None = None) -> pathlib.Path:
    """Where the space-only face for these widths lives.

    Not the output folder, which is the one folder here whose whole purpose is
    to be copied onto a card: this is an input to a build and not a font to
    read with, and a reader who copies it gains a face with fourteen invisible
    glyphs in it. Not the workspace either, which can be mounted read-only
    while the output is not. The temporary directory is writable wherever this
    runs, it is nobody's to tidy, and a face that is swept from under a build
    is written again by the worker that wants it.
    """
    return pathlib.Path(tempfile.gettempdir(), spacefont.cache_name(widths))


def ensure_space_font(widths: dict[int, float] | None = None) -> pathlib.Path:
    """Generate the space-only fallback font if it is not already there.

    Written under a name of this process's own and moved into place, because
    "is it there yet" and "write it" are two steps and several builds reach
    them together: every worker finds the file missing, and the second to open
    it for writing gets an OSError from Windows while the first still has it.

    That race is wider than it used to be. The file is keyed on the widths and
    kept where any build on the machine can find it, so the builds sharing it
    are no longer only the ones writing to one output folder -- a command line
    build and the preview's are two processes reaching this at once. Both ways
    out end with the same bytes on disk, since the name is a digest of what is
    in them.
    """
    path = space_font_path(widths)
    if path.is_file():
        return path
    temporary = path.with_name(f"{path.name}.{os.getpid()}")
    spacefont.build(temporary, widths)
    try:
        if path.is_file():
            # Somebody else finished first. Theirs is as good as this one, and
            # replacing a file the converter may already have open would only
            # trade this race for another.
            temporary.unlink(missing_ok=True)
        else:
            os.replace(temporary, path)
    except OSError:
        # It appeared between the question and the answer, and on Windows it
        # cannot be replaced while whoever wrote it still has it open. Theirs
        # will do.
        temporary.unlink(missing_ok=True)
    return path


STYLE_IDS = {"regular": 0, "bold": 1, "italic": 2, "bolditalic": 3}


def build_kwargs(variant: Variant, size: int, out_dir: pathlib.Path) -> dict:
    """Arguments for one generate_cpfont_multistyle call: one family, one size.

    generate_cpfont_multistyle takes every fallback for style 0 and appends
    that list to all four styles itself, which is why the user, bundled and
    space faces all go into one ordered list.
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
        fallbacks.append(str(space_font_path(config.space_widths)))

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
    #: Bytes written this run: the sizes in `built`, and not the ones already
    #: current, which nothing wrote. What a build costs on the card is the
    #: question behind "4 built", and it was being computed and dropped.
    written: int = 0
    #: And what the sizes in `skipped` already take up. A run that wrote
    #: nothing still put something on the card last time, and "already current"
    #: with no number beside it is the one case where the size is missing
    #: because there was no work rather than because there is no font.
    current: int = 0


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
    so this scales with cores; one is left for whatever asked for the build,
    and the cap keeps a big family from opening a dozen copies of a CJK font
    at once."""
    return max(1, min((os.cpu_count() or 4) - 1, 12))


def worker_count(job_count: int, workers: int | None = None) -> int:
    """How many processes a run of `job_count` sizes will use.

    Shared so that the count a caller announces is the count it gets: there is
    no sense in opening more workers than there are sizes to give them.
    """
    return max(1, min(workers or default_jobs(), job_count))


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

    Layout, both from generate_cpfont_multistyle: HEADER_SIZE is 32 and
    STYLE_TOC_FORMAT packs each 32-byte style entry, with glyphCount at +8,
    advanceY +12, ascender +13 and descender +15.
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
        ensure_space_font(job.variant.config.space_widths)
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
    # Off the files rather than remembered from a run that may never have
    # happened on this machine: "already current" means the .cpfont is there
    # and matches, so it is there to be measured.
    for size in report.skipped:
        path = fontstamp.cpfont_path(directory, variant, size)
        if path.is_file():
            report.current += path.stat().st_size
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


class Plan(typing.NamedTuple):
    """One variant, what is already current, and the sizes still to build."""
    variant: Variant
    report: Report
    jobs: list[Job]


def plan_families(configs, out_dir: pathlib.Path,
                  force: bool = False) -> list[Plan]:
    """Every variant of every config, and the sizes each still owes.

    Planning the lot before building any of it is what lets one pool cover
    them all: a family with fewer stale sizes than there are cores would
    otherwise leave workers idle while it finished.
    """
    return [Plan(variant, *plan_variant(variant, out_dir, force=force))
            for config in configs for variant in config.variants()]


def all_jobs(plans: list[Plan]) -> list[Job]:
    """Every outstanding size across the plans, for one pool to cover."""
    return [job for plan in plans for job in plan.jobs]


def reports_by_variant(plans: list[Plan]) -> dict[int, Report]:
    """Each plan's report, addressed by the variant a finished job carries.

    By identity rather than by name: nothing stops two hand-written configs
    from producing one output name, and a map keyed on that would file both
    families' sizes under whichever of them was planned last. A job holds the
    very Variant its plan was built from, on the way out to a worker and back,
    so identity is exact here in a way the name is not.
    """
    return {id(plan.variant): plan.report for plan in plans}


class Landed(typing.NamedTuple):
    """One job's outcome. `error` is None when it built."""
    job: Job
    seconds: float
    error: str | None
    built: Built


def _run(job: Job, out_dir: pathlib.Path) -> tuple[float, str | None, Built]:
    """Run one job, returning (seconds, error or None, Built).

    Module-level and picklable, because the pool spawns processes on Windows.
    """
    started = time.monotonic()
    try:
        built = build_size(job, out_dir)
    except FontBuildError as exc:
        return time.monotonic() - started, str(exc), Built(0, 0)
    return time.monotonic() - started, None, built


def run_jobs(jobs: list[Job], out_dir: pathlib.Path,
             workers: int | None = None) -> typing.Iterator[Landed]:
    """Rasterize every job, yielding each as it lands.

    In the order they finish, which is what lets a caller report a long run
    rather than going quiet until the last size is done.

    Processes, not threads: rasterizing is CPU-bound Python, so threads would
    serialize on the GIL. One size alone skips the pool, since spawning an
    interpreter to do a job this process could have done costs more than the
    job.
    """
    if not jobs:
        return
    # Here rather than in each worker. build_size() asks for it too, and that
    # is the call several workers reach together on a fresh output folder --
    # doing it once up front means they all find it already written.
    for job in jobs:
        if job.variant.config.space_glyphs:
            ensure_space_font(job.variant.config.space_widths)

    count = worker_count(len(jobs), workers)
    if count == 1:
        for job in jobs:
            seconds, error, built = _run(job, out_dir)
            yield Landed(job, seconds, error, built)
        return

    with concurrent.futures.ProcessPoolExecutor(max_workers=count) as pool:
        futures = {pool.submit(_run, job, out_dir): job for job in jobs}
        try:
            for future in concurrent.futures.as_completed(futures):
                seconds, error, built = future.result()
                yield Landed(futures[future], seconds, error, built)
        finally:
            # A caller that stops reading -- a browser that went away
            # mid-build -- would otherwise hold the pool open until every
            # queued size had been rasterized for nobody.
            for future in futures:
                future.cancel()


def build_variant(variant: Variant, out_dir: pathlib.Path,
                  force: bool = False) -> Report:
    """Build one variant here, in this process, and let a failure out.

    The path the end-to-end tests take: one size, no pool, and an exception
    rather than an error field, so a broken build fails the test where it
    broke rather than being reported as data.
    """
    report, jobs = plan_variant(variant, out_dir, force=force)
    for job in jobs:
        build_size(job, out_dir)
        report.built.append(job.size)
    if jobs:
        finalize_variant(variant, out_dir, failed=set())
    return report


def build_families(configs, out_dir: pathlib.Path, force: bool = False,
                   keep: set[str] | None = None):
    """Build every variant of every config, saying where it has got to.

    Yields a dict per step: one `plan` first, then a `size` as each .cpfont
    lands, then `done`. The plan comes first because it costs a stamp read per
    size and answers "how many is this going to be" -- without which a progress
    line can only count upwards and hope.

    Every outstanding size of every family goes through one pool, so a family
    with fewer stale sizes than there are cores does not leave workers idle.
    They land in whatever order they finish, which is what the step events are
    for: the bar counts completions rather than assuming an order.

    A size that fails is recorded and the rest of that family is written off --
    the next one usually fails the same way -- but the other families carry on,
    so a folder-wide build is not lost to one bad face.

    `keep` is every family the workspace accounts for, from
    `wanted_families()`. Anything else under the output folder that we put
    there is left behind by a family that has been renamed, dropped, or had
    its second size list removed, and per-size pruning never looks at a whole
    directory -- the simulator would go on staging it. It is the workspace and
    not this run, because a build of one family says nothing about the others.
    None leaves the folder alone.
    """
    import shutil

    plans = plan_families(configs, out_dir, force=force)

    removed = []
    if keep is not None:
        for path in orphan_dirs(out_dir, keep):
            shutil.rmtree(path)
            removed.append(path.name)
    # The space face that builds up to now left in here, which is ours and not
    # a font to read with. Unreported: a line saying a hidden file went would
    # need more explaining than the file was ever worth. Whatever the folder is
    # on, a build that cannot delete from it is not a build worth failing.
    with contextlib.suppress(OSError):
        (out_dir / spacefont.STRAY_NAME).unlink(missing_ok=True)

    total = sum(len(plan.jobs) for plan in plans)
    yield {"event": "plan", "total": total, "out": str(out_dir),
           "families": [plan.variant.name for plan in plans],
           "removed": removed}

    done = 0
    reports = reports_by_variant(plans)
    written_off = set()
    for job, _seconds, error, made in run_jobs(all_jobs(plans), out_dir):
        variant = job.variant
        report = reports[id(variant)]
        # A family whose first failure has already been reported. Its other
        # sizes were counted then, so whatever they came back with here is a
        # result nobody is waiting for.
        if id(variant) in written_off:
            continue
        if error:
            written_off.add(id(variant))
            report.error = error
            report.failed = [size for size in variant.sizes
                             if size not in report.built
                             and size not in report.skipped]
            done += len(report.failed)
            yield {"event": "failed", "family": variant.name,
                   "size": job.size, "done": done, "total": total,
                   "error": error}
            continue
        report.built.append(job.size)
        report.written += made.bytes
        done += 1
        yield {"event": "size", "family": variant.name, "size": job.size,
               "done": done, "total": total, "bytes": made.bytes}

    for plan in plans:
        if plan.jobs:
            finalize_variant(plan.variant, out_dir, failed=set(plan.report.failed))

    yield {"event": "done", "out": str(out_dir), "removed": removed,
           # What this run wrote, and what the sizes it left alone already take
           # up. Both, because a run that wrote nothing still put something on
           # the card the last time it ran.
           "bytes": sum(plan.report.written for plan in plans),
           "current_bytes": sum(plan.report.current for plan in plans),
           "families": [{"name": plan.variant.name,
                         "bytes": plan.report.written,
                         "current_bytes": plan.report.current,
                         "sizes": sorted(plan.variant.sizes),
                         "built": sorted(plan.report.built),
                         "skipped": sorted(plan.report.skipped),
                         "failed": sorted(plan.report.failed),
                         "removed": sorted(str(p) for p in plan.report.removed),
                         "error": plan.report.error}
                        for plan in plans]}


def orphan_dirs(out_dir: pathlib.Path, wanted: set[str]) -> list[pathlib.Path]:
    """Family directories we built that no config produces any more.

    Dropping `sizes_mod`, or renaming a family, leaves a whole directory behind
    that per-size pruning never looks at -- and the simulator would go on
    staging it. Only directories carrying our own stamp file are considered, so
    a family that was put there by hand is never touched.

    Matched without regard to case, which is how the workspace addresses a
    family everywhere else -- and on the filesystem this runs on, `Alto` and
    `alto` are one directory anyway.
    """
    if not out_dir.is_dir():
        return []
    folded = {name.casefold() for name in wanted}
    return [path for path in sorted(out_dir.iterdir())
            if path.is_dir() and path.name.casefold() not in folded
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


def families_in(source: pathlib.Path, defaults: dict[str, str],
                directory: pathlib.Path,
                covered: frozenset[str] = frozenset(),
                ) -> tuple[list[Config], list[str]]:
    """A config per family in `directory`, from the shared defaults.

    `directory` is where the files are looked for and `defaults["dir"]` is what
    the config says about that, which are the same thing for the workspace and
    are not for the bundled family. Failures are collected rather than raised:
    one unreadable face must not cost you the rest of the folder.
    """
    path = conf_dir(source) / DEFAULTS_NAME
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


def derived_configs(source: pathlib.Path, defaults: dict[str, str],
                    covered: set[str]) -> tuple[list[Config], list[str]]:
    """One config per family in the folder that no per-font config claims."""
    directory = (source / defaults.get("dir", ".").strip()).resolve()
    return families_in(source, defaults, directory, frozenset(covered))


def starter_configs(source: pathlib.Path,
                    defaults: dict[str, str]) -> tuple[list[Config], list[str]]:
    """The bundled family, for a workspace that has nothing of its own yet.

    Read where it is installed rather than copied into the workspace: that
    folder is the reader's, and a tool that drops files in it unasked is one
    you have to clean up after. `dir` is what a Save writes, so the config goes
    on resolving once this is a family of theirs rather than one of ours.

    gather() takes these only when the workspace has nothing; offered() takes
    them always, and the difference between the two is what a build builds.
    """
    if not STARTER_DIR.is_dir():
        return [], []                   # an install missing its own faces
    return families_in(source, {**defaults, "dir": str(STARTER_DIR)},
                       STARTER_DIR)


def unclaimed_starter(source: pathlib.Path, defaults: dict[str, str],
                      configs: list[Config]) -> tuple[list[Config], list[str]]:
    """The bundled family, unless one of `configs` already answers for it.

    Which happens two ways: the workspace was empty so gather() already took
    it, or a Save wrote it a config of its own and it is a family like any
    other now. Either way it belongs in the list once.

    By family as well as by name, the pair discovery matches on everywhere
    else. A config renames only what it builds as, so one that has been given
    a name of its own still answers for the family it was written for -- and
    asking after the name alone would offer the same faces a second time, as
    the family the rename had just moved off.
    """
    known = {value for config in configs
             for value in (config.name.casefold(), config.family.casefold())}
    more, errors = starter_configs(source, defaults)
    return [c for c in more
            if not {c.name.casefold(), c.family.casefold()} & known], errors


def offered(source: pathlib.Path | str | None = None,
            ) -> tuple[list[Config], list[str]]:
    """Every family to offer for looking at: the workspace, then the bundled one.

    A build takes gather() and a picker takes this, and the one entry between
    them is the point. What a build with no arguments does is build your
    workspace, and the family that came with the tool is not part of it until
    you save a config for it. Somewhere to flip to mid-tuning, though -- a face
    you know is good, at the size and the knobs you are working at -- is worth
    a permanent entry whatever else is in the folder.
    """
    source = pathlib.Path(source) if source else SOURCE_DIR
    configs, errors = gather(source)
    more, more_errors = unclaimed_starter(source, load_defaults(source), configs)
    return configs + more, errors + more_errors


def claimed_names(source: pathlib.Path) -> set[str]:
    """The output names the workspace's config files ask for, resolvable or not.

    Read from the files rather than from parsed configs, because a config whose
    faces have gone missing produces nothing and would otherwise look like a
    family nobody wants: its output would be swept up as an orphan for the one
    reason it cannot be rebuilt. A name it claims is a name it keeps.

    Spelled as the config spells it, which is not always how the directory is:
    a resolved family takes its capitals from the font file, and an unresolved
    one has no file to take them from. Only orphan_dirs consumes this, and it
    compares without case for exactly that reason.
    """
    names = set()
    # all.conf underneath each file, because a second family can be declared
    # there: `sizes_mod` shared across the folder means every family has one,
    # and a config that says nothing about it still builds the directory.
    defaults = load_defaults(source)
    for path in discover_configs(source):
        try:
            values = {**defaults, **fontconf.read_values(path)}
        except FontConfigError:
            # Unreadable, so it claims whatever it is called. A file nobody can
            # parse is a worse reason still to delete something.
            names.add(path.stem)
            continue
        family = values.get("family", "").strip() or path.stem
        name = fontconf.sanitize_name(values.get("name", "").strip() or family)
        names.add(name)
        if values.get("sizes_mod", "").strip():
            names.add(name + fontconf.sanitize_name(
                values.get("mod_suffix", "Mod").strip() or "Mod"))
    return names


def wanted_families(source: pathlib.Path | str | None = None) -> set[str]:
    """Every family directory the workspace accounts for.

    What a build compares the output folder against: anything else under it
    that we put there is left over from a family that has been renamed,
    dropped, or had its second size list removed.

    `offered` rather than `gather`, so the bundled family keeps the output a
    preview build gave it -- the command line would not produce that directory
    and would otherwise delete it.
    """
    source = pathlib.Path(source) if source else SOURCE_DIR
    return ({variant.name for config in offered(source)[0]
             for variant in config.variants()}
            | claimed_names(source))


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

    # Named outright, the bundled family is addressable whatever else is in the
    # workspace. The picker offers it permanently and a render has to be able
    # to resolve what the picker offers -- but it stays out of the list above,
    # so a build with no arguments still builds your workspace and not the
    # family that came with the tool.
    pool = configs + unclaimed_starter(source, defaults, configs)[0]
    wanted = {t.casefold().removesuffix(".conf") for t in tokens}
    chosen = [c for c in pool
              if {c.name.casefold(), c.family.casefold(), c.path.stem.casefold()}
              & wanted]
    missed = wanted - {v for c in chosen
                       for v in (c.name.casefold(), c.family.casefold(),
                                 c.path.stem.casefold())}
    for token in sorted(missed):
        errors.append(f"no config or font family matching {token!r} in {source}")
    return chosen, errors

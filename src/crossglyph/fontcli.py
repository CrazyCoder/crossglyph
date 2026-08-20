"""crossglyph build - build .cpfont families from a folder of fonts and configs."""
from __future__ import annotations

import argparse
import pathlib
import shutil
import sys
import time

from . import fontbuild
from .cpfont.tuning import Tuning
from .fontconf import STYLES, Config, FontConfigError, size_with_label


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crossglyph build",
        description="Build CrossPoint .cpfont families from TTF/OTF sources.")
    parser.add_argument("configs", nargs="*",
                        help="config files or family names; default is every "
                             "*.conf in the workspace")
    parser.add_argument("--fonts", default=str(fontbuild.SOURCE_DIR),
                        help="workspace holding the font files, with the "
                             "configs in its conf/ folder "
                             "(default: %(default)s, or $CROSSGLYPH_FONTS)")
    parser.add_argument("-o", "--out", default=str(fontbuild.output_dir()),
                        help="output folder (default: %(default)s, or $CROSSGLYPH_OUT)")
    parser.add_argument("-j", "--jobs", type=int, default=fontbuild.default_jobs(),
                        help="sizes to rasterize in parallel (default: %(default)s)")
    parser.add_argument("--force", action="store_true",
                        help="rebuild even when nothing changed")
    parser.add_argument("--list", dest="list_only", action="store_true",
                        help="show what each config resolves to, and build nothing")
    parser.add_argument("--fail-on-warning", dest="fail_on_warning",
                        action="store_true",
                        help="return 1 when the build warns about anything, "
                             "after every file is written; without it a build "
                             "that produced fonts returns 0 whatever it said")
    parser.add_argument("--fetch-fallbacks", dest="fetch_fallbacks",
                        action="store_true",
                        help="put the bundled Noto fallback faces in the "
                             "workspace and build nothing (3.4 MB; a CJK "
                             "face is 15.7 MB more and comes only when a "
                             "config asks for one)")
    return parser


def _listed(names: tuple[str, ...] | list[str]) -> str:
    """`a`, `a or b`, `a, b or c` -- however many there are."""
    names = list(names)
    if len(names) < 2:
        return names[0] if names else ""
    return f"{', '.join(names[:-1])} or {names[-1]}"


def remedy_for(remedy: str, fallbacks: bool) -> str:
    """What to do about a coverage that came out at zero.

    In the config's own words. This is the surface where somebody edits a
    .conf, and a line naming a checkbox would be naming a control the reader
    cannot see. The panel words the same answers for itself.

    Two of the three depend on whether the family reads the bundled set at
    all. Fetching faces into a folder this build does not open leaves the
    range as empty as it was, so with the set switched off the line carries
    both moves.
    """
    if remedy == "unused":
        return ("`fallback_order` leaves the bundled faces out. Put `bundled` "
                "back in it." if fallbacks
                else "Set `fallbacks = yes` and build again.")
    if remedy == "fetch":
        return ("The bundled set is short of faces here. Run "
                "`crossglyph fetch-fallbacks` and build again." if fallbacks
                else "The bundled set is short of faces here, and this family "
                     "does not read it anyway. Run "
                     "`crossglyph fetch-fallbacks`, set `fallbacks = yes`, "
                     "and build again.")
    # Nothing in a complete set draws it, which is true whatever `fallbacks`
    # says: the folder was read for this answer and the chain was not.
    return ("No bundled face covers it. Name a family in `fallback_regular`, "
            "or drop the tick.")


def say_uncovered(empty: fontbuild.Uncovered) -> str:
    """One family's empty coverage, for a terminal.

    The filenames are here and not in the panel. There is no control to press
    at a command line, so which file would draw the range is the part worth
    its own line.
    """
    lines = [f"  {empty.family}: nothing in this build draws "
             f"{_listed(empty.tokens)}."]
    if empty.faces:
        # What is on the disk and went unopened, without saying it answers
        # every token above. One face can cover one of two empty ranges, and a
        # line promising both would be wrong half the time.
        lines.append(f"    {_listed(empty.faces)} "
                     f"{'is' if len(empty.faces) < 2 else 'are'} in the "
                     f"fallbacks folder and this build did not open "
                     f"{'it' if len(empty.faces) < 2 else 'them'}.")
    lines.append(f"    {remedy_for(empty.remedy, empty.fallbacks)}")
    return "\n".join(lines)


def describe(config: Config) -> None:
    origin = config.path.name
    if config.derived:
        origin += " (shared defaults, no config of its own)"
    print(f"{config.name}  <- {origin}")
    print(f"  family    {config.family}  (in {config.dir})")
    for style in STYLES:
        path = config.styles.get(style)
        print(f"  {style:<12}{path.name if path else '-'}")
    for key, path in sorted(config.user_fallbacks.items()):
        print(f"  {key:<12}{path.name}")
    print(f"  coverage  {config.coverage}"
          f"{'' if config.fallbacks else '  (no bundled fallbacks)'}")
    default = Tuning().as_dict()
    changed = [f"{key}={value}" for key, value in config.tuning.as_dict().items()
               if value != default[key]]
    if changed:
        print(f"  tuning    {', '.join(changed)}")
    if config.space_widths:
        print("  spaces    " + ", ".join(
            f"U+{cp:04X}={width}"
            for cp, width in sorted(config.space_widths.items())))
    missing = [s for s in STYLES if s not in config.styles]
    if missing:
        # Worth saying out loud: the device has no synthetic bold or oblique, so
        # a missing face means that emphasis simply does not render.
        print(f"  NOTE      no {', '.join(missing)} face; emphasis will not show")
    for variant in config.variants():
        # A fractional size is named for the whole number it rounds to, so the
        # list alone does not say which files this builds.
        sizes = " ".join(size_with_label(size) for size in variant.sizes)
        print(f"  -> {variant.name}: {sizes}")


def main(argv=None) -> int:
    opts = build_parser().parse_args(argv)
    source = pathlib.Path(opts.fonts)
    out_dir = pathlib.Path(opts.out)

    if not source.is_dir():
        print(f"workspace not found: {source}\n"
              f"Create it, drop TTF or OTF files in, and put a <family>.conf "
              f"in its conf/ folder. Or pass --fonts.", file=sys.stderr)
        return 2

    if opts.fetch_fallbacks:
        # Every coverage the folder asks for, so one fetch serves the lot --
        # and a CJK face only if some config really wants one.
        wanted = ",".join(config.coverage
                          for config in fontbuild.gather(source)[0])
        try:
            fontbuild.fetch_fallbacks(source, wanted)
        except OSError as exc:
            print(f"could not fetch the fallback faces: {exc}", file=sys.stderr)
            return 2
        return 0

    try:
        configs, errors = fontbuild.gather(source, opts.configs)
    except FontConfigError as exc:
        print(exc, file=sys.stderr)
        return 2

    for error in errors:
        print(f"FAILED: {error}", file=sys.stderr)

    if not configs:
        if not errors:
            print(f"no *.conf files and no fonts in {source}", file=sys.stderr)
        return 1

    if opts.list_only:
        for config in configs:
            describe(config)
        return 1 if errors else 0

    plans = fontbuild.plan_families(configs, out_dir, force=opts.force)
    jobs = fontbuild.all_jobs(plans)
    reports = fontbuild.reports_by_variant(plans)

    # Against every family the workspace accounts for, not against the ones
    # this run was asked for: building one family says nothing about the
    # others, while a directory no config claims at all is left over whichever
    # family you happen to be building.
    for path in fontbuild.orphan_dirs(out_dir,
                                      fontbuild.wanted_families(source)):
        shutil.rmtree(path)
        print(f"removed {path.name}/ (no config produces it any more)")
    fontbuild.sweep_stray(out_dir)

    for plan in plans:
        for path in plan.report.removed:
            print(f"{plan.variant.name}: removed {path.name} "
                  f"(size no longer in the config)")
        if plan.report.skipped:
            print(f"{plan.variant.name}: up to date "
                  f"{' '.join(size_with_label(s) for s in plan.report.skipped)}")

    # Faces the coverage asks for that the folder does not have. Said once
    # before the run and not per family, because it is the workspace's answer
    # and the same for all of them, and said rather than raised: fetching them
    # is the only thing that fixes it, and a build that stops has still not
    # built the families it could have.
    # Faces only. A fetch brings the licence down beside them, and a line about
    # what a build could not draw has no business naming it.
    absent = [name for name in fontbuild.missing_fallbacks(
                  source, " ".join(plan.variant.config.coverage
                                   for plan in plans))
              if name != fontbuild.FALLBACK_LICENCE]
    short_of_faces = absent and any(plan.variant.config.fallbacks
                                    for plan in plans)
    if short_of_faces:
        print(f"fallbacks: {fontbuild.fallback_dir(source) or source} is short "
              f"{', '.join(absent)}. Whatever only "
              f"{'those faces' if len(absent) > 1 else 'that face'} could have "
              f"drawn is left out of this build. Run "
              f"`crossglyph fetch-fallbacks` to add "
              f"{'them' if len(absent) > 1 else 'it'}.",
              file=sys.stderr, flush=True)

    # Every warning this run raises, for the gate at the end. The folder being
    # short is one of them: it is printed as a warning, and a flag that says
    # it fails on any warning has to mean it.
    warned = bool(short_of_faces)
    workers = fontbuild.worker_count(len(jobs), opts.jobs)
    if jobs:
        print(f"building {len(jobs)} size(s) on {workers} worker(s)", flush=True)
    started = time.monotonic()
    for job, elapsed, error, built in fontbuild.run_jobs(jobs, out_dir,
                                                         workers):
        report = reports[id(job.variant)]
        if error:
            report.failed.append(job.size)
            print(f"  {job.label} FAILED after {elapsed:.0f}s: {error}",
                  file=sys.stderr, flush=True)
        else:
            report.built.append(job.size)
            # Glyph count alongside the size: it is what distinguishes a
            # genuinely wide family from a narrow one padded out by the
            # bundled fallbacks.
            print(f"  {job.label} ({built.bytes / 1024 / 1024:.1f} MB, "
                  f"{built.glyphs} glyphs, {elapsed:.0f}s)", flush=True)
            for warning in built.warnings:
                print(f"    warning: {warning}", file=sys.stderr, flush=True)
                warned = True

    for plan in plans:
        if plan.report.built or plan.report.failed:
            empty = fontbuild.finalize_variant(
                plan.variant, out_dir, failed=set(plan.report.failed))
            if empty:
                warned = True
                print(say_uncovered(empty), file=sys.stderr, flush=True)

    built = sum(len(plan.report.built) for plan in plans)
    failures = len(errors) + sum(len(plan.report.failed) for plan in plans)
    if jobs:
        print(f"\n{built} size(s) built in {time.monotonic() - started:.0f}s"
              f"{f', {failures} failed' if failures else ''}")
    elif not failures:
        print("\neverything up to date")
    # The gate comes after the writing. Whoever asked for it wants to stop on a
    # warning, and they still want the fonts the run managed to produce.
    return 1 if failures or (warned and opts.fail_on_warning) else 0


if __name__ == "__main__":
    raise SystemExit(main())

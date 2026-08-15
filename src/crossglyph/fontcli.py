"""crossglyph build - build .cpfont families from a folder of fonts and configs."""
from __future__ import annotations

import argparse
import pathlib
import shutil
import sys
import time

from . import fontbuild
from .cpfont.tuning import Tuning
from .fontconf import STYLES, Config, FontConfigError


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
    parser.add_argument("--fetch-fallbacks", dest="fetch_fallbacks",
                        action="store_true",
                        help="put the bundled Noto fallback faces in the "
                             "workspace and build nothing (3.4 MB; a CJK "
                             "face is 15.7 MB more and comes only when a "
                             "config asks for one)")
    return parser


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
        sizes = " ".join(str(s) for s in variant.sizes)
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
                  f"{' '.join(str(s) for s in plan.report.skipped)}")

    workers = fontbuild.worker_count(len(jobs), opts.jobs)
    if jobs:
        print(f"building {len(jobs)} size(s) on {workers} worker(s)", flush=True)
    started = time.monotonic()
    try:
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
    except fontbuild.FallbacksMissing as exc:
        # Not one size's failure but the workspace's, and it is the same for
        # every family that wanted them, so it is said once and the run stops.
        # Caught here because the sizes are rasterized in worker processes: an
        # exception crossing back out of the pool arrives wrapped in its own
        # traceback and this one carries the sentence that says what to do.
        print(exc, file=sys.stderr)
        return 2

    for plan in plans:
        if plan.report.built or plan.report.failed:
            fontbuild.finalize_variant(plan.variant, out_dir,
                                       failed=set(plan.report.failed))

    built = sum(len(plan.report.built) for plan in plans)
    failures = len(errors) + sum(len(plan.report.failed) for plan in plans)
    if jobs:
        print(f"\n{built} size(s) built in {time.monotonic() - started:.0f}s"
              f"{f', {failures} failed' if failures else ''}")
    elif not failures:
        print("\neverything up to date")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

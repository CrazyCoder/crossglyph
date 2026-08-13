"""crossglyph build - build .cpfont families from a folder of fonts and configs."""
from __future__ import annotations

import argparse
import concurrent.futures
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

    # Plan every family first, then run all the outstanding sizes through one
    # pool. Planning per family and building per family would leave workers
    # idle whenever a family had fewer stale sizes than there are cores.
    variants, reports, jobs = [], {}, []
    for config in configs:
        for variant in config.variants():
            report, pending = fontbuild.plan_variant(variant, out_dir,
                                                     force=opts.force)
            variants.append(variant)
            reports[variant.name] = report
            jobs += pending

    # Only when building everything: with an explicit config list, the families
    # that were not asked for are absent from `variants`, not orphaned.
    if not opts.configs:
        for path in fontbuild.orphan_dirs(out_dir, {v.name for v in variants}):
            shutil.rmtree(path)
            print(f"removed {path.name}/ (no config produces it any more)")

    for variant in variants:
        report = reports[variant.name]
        for path in report.removed:
            print(f"{variant.name}: removed {path.name} "
                  f"(size no longer in the config)")
        if report.skipped:
            print(f"{variant.name}: up to date "
                  f"{' '.join(str(s) for s in report.skipped)}")

    workers = max(1, min(opts.jobs, len(jobs))) if jobs else 1
    if jobs:
        print(f"building {len(jobs)} size(s) on {workers} worker(s)", flush=True)
    started = time.monotonic()
    # Processes, not threads: rasterizing is CPU-bound Python, so threads would
    # serialize on the GIL. This used to be a subprocess per size, which paid a
    # whole interpreter start plus a uv resolve for the same parallelism.
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_run, job, out_dir): job for job in jobs}
        for future in concurrent.futures.as_completed(futures):
            job = futures[future]
            elapsed, error, built = future.result()
            if error:
                reports[job.variant.name].failed.append(job.size)
                print(f"  {job.label} FAILED after {elapsed:.0f}s: {error}",
                      file=sys.stderr, flush=True)
            else:
                reports[job.variant.name].built.append(job.size)
                # Glyph count alongside the size: it is what distinguishes a
                # genuinely wide family from a narrow one padded out by the
                # bundled fallbacks.
                print(f"  {job.label} ({built.bytes / 1024 / 1024:.1f} MB, "
                      f"{built.glyphs} glyphs, {elapsed:.0f}s)", flush=True)
                for warning in built.warnings:
                    print(f"    warning: {warning}", file=sys.stderr, flush=True)

    for variant in variants:
        report = reports[variant.name]
        if report.built or report.failed:
            fontbuild.finalize_variant(variant, out_dir,
                                       failed=set(report.failed))

    built = sum(len(r.built) for r in reports.values())
    failures = len(errors) + sum(len(r.failed) for r in reports.values())
    if jobs:
        print(f"\n{built} size(s) built in {time.monotonic() - started:.0f}s"
              f"{f', {failures} failed' if failures else ''}")
    elif not failures:
        print("\neverything up to date")
    return 1 if failures else 0


def _run(job, out_dir: pathlib.Path):
    """Run one job, returning (seconds, error or None, Built).

    Module-level and picklable, because the pool spawns processes on Windows.
    """
    started = time.monotonic()
    try:
        built = fontbuild.build_size(job, out_dir)
    except fontbuild.FontBuildError as exc:
        return time.monotonic() - started, str(exc), fontbuild.Built(0, 0)
    return time.monotonic() - started, None, built


if __name__ == "__main__":
    raise SystemExit(main())

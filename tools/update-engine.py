"""Update the firmware checkout the render core is built from, and say whether
anything the build compiles has changed.

The core is the firmware's own drawing code compiled to WebAssembly, so it has
to come from somewhere deliberate. That somewhere is a checkout of its own:
`../crosspoint-reader-engine`, on one branch, touched by nothing but this. A
working checkout is for building firmware and running the emulator, and moves
between branches for reasons that have nothing to do with the preview.

    uv run tools/update-engine.py            # fetch, fast-forward, report
    uv run tools/update-engine.py --ref pr-1234
    uv run tools/update-engine.py --dry-run

It never builds. That needs emsdk, and on Windows a shell this is not; the
command is printed instead.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILD = ROOT / "src" / "render" / "build.sh"
STAMP = ROOT / "src" / "crossglyph" / "render" / "render.built-from.json"

#: Where the checkout goes, and what it tracks. One branch, because the whole
#: point of a second checkout is that this one does not move for other reasons.
DIRECTORY = ROOT.parent / "crosspoint-reader-engine"
URL = "https://github.com/crosspoint-reader/crosspoint-reader.git"
BRANCH = "develop"

#: Everything under $FW that build.sh names, sources and include directories
#: both. Read out of the script rather than repeated here: a source added
#: there has to reach this report, and a list in two places would not.
_FW_PATH = re.compile(r"\$FW/([^\s\\\"]+)")


def git(*args: str, at: pathlib.Path | None = None,
        check: bool = True) -> str:
    where = ["-C", str(at)] if at else []
    done = subprocess.run(["git", *where, *args], capture_output=True,
                          text=True, check=False)
    if check and done.returncode:
        raise SystemExit(f"git {' '.join(args)}: "
                         f"{done.stderr.strip() or done.returncode}")
    return done.stdout.strip()


def compiled_paths() -> list[str]:
    """What the build reads, as repository-relative paths."""
    text = BUILD.read_text(encoding="utf-8")
    return sorted({match.group(1) for match in _FW_PATH.finditer(text)})


def built_from() -> str | None:
    try:
        return json.loads(STAMP.read_text(encoding="utf-8")).get("firmware")
    except (OSError, ValueError):
        return None


def clone() -> None:
    print(f"cloning {URL} ({BRANCH}) into {DIRECTORY}")
    # Blob-filtered: this checkout is read, never worked in, so the history's
    # file contents can stay on the server until something asks for them.
    subprocess.run(["git", "clone", "--filter=blob:none", "--branch", BRANCH,
                    URL, str(DIRECTORY)], check=True)


def refuse_if_used(at: pathlib.Path) -> None:
    """This checkout belongs to the build. Anything else there is a surprise."""
    dirty = git("status", "--porcelain", at=at)
    if dirty:
        raise SystemExit(
            f"{at} has uncommitted changes, and it is meant to be a checkout "
            f"nothing works in:\n{dirty}\n"
            f"Build from a working checkout with FW=<path> instead.")
    branch = git("rev-parse", "--abbrev-ref", "HEAD", at=at)
    if branch != BRANCH:
        raise SystemExit(
            f"{at} is on {branch}, not {BRANCH}. It tracks one branch so that "
            f"what the engine is built from is never a question. Switch it "
            f"back, or point FW at the checkout you mean.")


def report(at: pathlib.Path, was: str | None, now: str) -> bool:
    """What moved under the build's feet. True when a rebuild is warranted."""
    if was is None:
        print("the module carries no stamp, so anything it was built from is "
              "a guess. Rebuild it.")
        return True
    if was == now:
        print(f"the render core is current: {now[:12]}")
        return False
    paths = compiled_paths()
    ours = git("log", "--oneline", f"{was}..{now}", "--", *paths, at=at,
               check=False)
    every = git("log", "--oneline", f"{was}..{now}", at=at, check=False)
    count = len(every.splitlines())
    print(f"{was[:12]} -> {now[:12]}, {count} commit(s) on {BRANCH}")
    if not ours:
        print("none of them touch what the render core compiles, so the "
              "module on disk still draws what this firmware draws.")
        return False
    print(f"\n{len(ours.splitlines())} of them touch what it compiles:\n")
    for line in ours.splitlines():
        print(f"  {line}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Update the firmware checkout the render core is built "
                    "from.")
    parser.add_argument("--ref", default=BRANCH,
                        help=f"what to check out, for a one-off build from a "
                             f"tag or a pull request (default: {BRANCH})")
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch and report, changing no working tree")
    opts = parser.parse_args(argv)

    if not (DIRECTORY / ".git").is_dir():
        if opts.dry_run:
            print(f"no checkout at {DIRECTORY} yet")
            return 0
        clone()
    elif opts.ref == BRANCH:
        refuse_if_used(DIRECTORY)

    print(f"fetching {DIRECTORY}")
    git("fetch", "--quiet", "origin", at=DIRECTORY)
    target = git("rev-parse", f"origin/{opts.ref}", at=DIRECTORY, check=False) \
        or git("rev-parse", opts.ref, at=DIRECTORY)
    if not opts.dry_run and opts.ref == BRANCH:
        git("checkout", "--quiet", BRANCH, at=DIRECTORY)
        # Fast-forward only. A checkout nothing works in has nothing worth
        # merging, so a refusal here means it is not the checkout it should be.
        git("merge", "--ff-only", "--quiet", f"origin/{BRANCH}", at=DIRECTORY)
    elif not opts.dry_run:
        # A one-off from a tag or a pull request, detached so the branch this
        # tracks is left where it was and the next plain run restores it.
        git("checkout", "--quiet", "--detach", target, at=DIRECTORY)

    print()
    warranted = report(DIRECTORY, built_from(), target)
    if warranted:
        print(f"\nrebuild it with:\n  bash {BUILD}")
        print("and run the suite after: a renderer change moves what the "
              "preview draws, and the layout tests are the ones that say so.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

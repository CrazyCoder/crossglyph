"""crossglyph: build and tune .cpfont families for CrossPoint readers."""
from __future__ import annotations

import sys

from . import install, updates, version
from .render import stamp

USAGE = """usage: crossglyph [preview|build|fetch-fallbacks|update] [options]

  preview            tune a font against the device's own renderer (default)
  build              build .cpfont families from the workspace
  fetch-fallbacks    download the bundled Noto faces and build nothing
  update --check     ask now whether a newer release exists

  --version          what this install is, and the renderer it carries
  --no-update-check  skip the update check for this run

`crossglyph <command> --help` lists that command's own options."""

#: Not a subcommand's flag, so it comes off before one sees it.
NO_CHECK_FLAG = "--no-update-check"


def _preview(argv: list[str]) -> int:
    # Imported here rather than at the top, so `build` does not pay for a web
    # framework it never touches.
    from .preview import server
    return server.main(argv)


def _build(argv: list[str]) -> int:
    from . import fontcli
    return fontcli.main(argv)


def version_report() -> str:
    """Two lines: what this is, and which renderer it carries.

    The firmware commit is here because it is the other half of "what am I
    running": the preview draws with the renderer that was compiled in, and
    two installs on the same version can carry different ones.
    """
    said = install.label(install.detect(install.root()))
    note = f" ({said})" if said else ""
    return (f"crossglyph {version.installed()}{note}\n"
            f"render core built from "
            f"{stamp.FIRMWARE.name} {stamp.short(stamp.build_stamp())}")


def update_note() -> str:
    """One line about a newer release, or nothing at all.

    Run after the work rather than before it, so the wait it can cost lands
    where nobody is watching for output. A font build takes far longer than
    the check does, which is what makes that affordable without the detached
    child process npm's update-notifier needs.
    """
    root = install.root()
    found = updates.available(updates.check(root))
    if not found:
        return ""
    return f"note: {found} is available. {install.instruction(install.detect(root))}"


def _checked(code: int, quiet: bool) -> int:
    """Run the work's exit code back out, with a note after it if there is one.

    The code is passed through untouched: a build that failed stays failed,
    however cheerful the note is.
    """
    if not quiet:
        note = update_note()
        if note:
            print(note)
    return code


def _update(argv: list[str]) -> int:
    """Checking is all this version does. Applying is the next one.

    A bare `update` is refused rather than quietly treated as `--check`: a
    command that half works is harder to trust than one that says what it is.
    """
    if argv != ["--check"]:
        print("usage: crossglyph update --check", file=sys.stderr)
        return 2
    root = install.root()
    state = updates.check(root, force=True)
    # Both of these are states the automatic check never says out loud, and
    # both are why somebody asked by hand.
    if state.error:
        print(f"could not reach the update server: {state.error}",
              file=sys.stderr)
        return 1
    found = updates.available(state)
    if found:
        print(f"{found} is available. "
              f"{install.instruction(install.detect(root))}")
    else:
        print(f"crossglyph {version.installed()} is up to date.")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    quiet = NO_CHECK_FLAG in argv
    argv = [item for item in argv if item != NO_CHECK_FLAG]
    # No arguments is the double-click case, and the preview is what a tester
    # unpacked the zip for.
    if not argv:
        return _preview([])
    command, rest = argv[0], argv[1:]
    if command in ("-h", "--help"):
        print(USAGE)
        return 0
    if command == "--version":
        print(version_report())
        return 0
    if command == "preview":
        return _preview(rest)
    if command == "build":
        return _checked(_build(rest), quiet)
    if command == "fetch-fallbacks":
        return _checked(_build(["--fetch-fallbacks", *rest]), quiet)
    if command == "update":
        return _update(rest)
    print(f"unknown command {command!r}\n\n{USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

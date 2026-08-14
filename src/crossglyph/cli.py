"""crossglyph: build and tune .cpfont families for CrossPoint readers."""
from __future__ import annotations

import sys

from . import install, layout, updateconf, updates, upgrade, version
from .render import stamp

USAGE = """usage: crossglyph [preview|build|fetch-fallbacks|update] [options]

  preview            tune a font against the device's own renderer (default)
  build              build .cpfont families from the workspace
  fetch-fallbacks    download the bundled Noto faces and build nothing
  update             install the newest release
  update --check     ask whether a newer release exists, and install nothing
  update --rollback  go back to the version before this one

  --version          what this install is, and the renderer it carries
  --no-update-check  skip the update check for this run

`crossglyph <command> --help` lists that command's own options."""

#: Not a subcommand's flag, so it comes off before one sees it.
NO_CHECK_FLAG = "--no-update-check"

#: The commands that are a launch rather than a question. Housekeeping runs
#: for these and not for --help or --version: those answer without doing
#: anything, and a diagnostic that deletes a directory is a surprise.
TIDIES = ("build", "fetch-fallbacks", "update")


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


def _check_only(root) -> int:
    """Ask now, and install nothing.

    Both of the states it can report are ones the automatic check keeps to
    itself, and both are why somebody asked by hand.
    """
    state = updates.check(root, force=True)
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


def _rollback(root) -> int:
    try:
        gone = upgrade.rollback(root)
    except upgrade.Refused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"back on {gone}. Restart CrossGlyph to use it.\n"
          f"Update checks will stay quiet until something newer than the "
          f"version you left appears.")
    return 0


def _apply(root) -> int:
    """Install the newest release, saying how far it has got.

    The percentage rewrites one line, and only when somebody is watching it: a
    log file wants the two sentences either side of it, not two hundred of
    these.
    """
    watching = sys.stdout.isatty()
    shown = -1
    for step in upgrade.steps(root):
        event = step["event"]
        if event == "plan":
            doing = "converting this install to" if step["converting"] \
                else "updating to"
            print(f"{doing} {step['version']} ({step['bytes'] / 1e6:.1f} MB)")
        elif event == "step" and watching:
            percent = step["got"] * 100 // max(step["bytes"], 1)
            if percent != shown:
                shown = percent
                print(f"\r  {percent}%", end="", flush=True)
        elif event == "current":
            print(f"crossglyph {step['version']} is up to date.")
        elif event == "error":
            if watching and shown >= 0:
                print()
            print(step["error"], file=sys.stderr)
            return 1
        elif event == "done":
            if watching and shown >= 0:
                print()
            for kept in step["kept"]:
                print(f"kept your fonts/{kept}. The new one is beside it as "
                      f"{kept.rsplit('/', 1)[-1]}{upgrade.SUFFIX}.")
            if step["converting"]:
                print("The files at the root are no longer read. Deleting "
                      "them is safe, and leaving them costs disk.")
            print(f"{step['version']} installed. Restart CrossGlyph to use "
                  f"it.")
    return 0


def _update(argv: list[str]) -> int:
    root = install.root()
    if not argv:
        return _apply(root)
    if argv == ["--check"]:
        return _check_only(root)
    if argv == ["--rollback"]:
        return _rollback(root)
    print("usage: crossglyph update [--check|--rollback]", file=sys.stderr)
    return 2


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
    # Before the work rather than after it, so a build that fails still leaves
    # the install tidy, and so it is never tied to the update-check flags:
    # retention is housekeeping and not a check. The preview does the same on
    # its startup thread, where a large removal cannot delay the page.
    if command in TIDIES:
        root = install.root()
        layout.tidy(root, updateconf.settings(root).keep_versions)
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

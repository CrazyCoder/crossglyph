"""crossglyph: build and tune .cpfont families for CrossPoint readers."""
from __future__ import annotations

import sys

from . import install, version
from .render import stamp

USAGE = """usage: crossglyph [preview|build|fetch-fallbacks] [options]

  preview           tune a font against the device's own renderer (default)
  build             build .cpfont families from the workspace
  fetch-fallbacks   download the bundled Noto faces and build nothing

  --version         what this install is, and the renderer it carries

`crossglyph <command> --help` lists that command's own options."""

#: What a kind is called in the report. Only the ones worth naming: an
#: ordinary release says nothing, because a line on every run is noise.
KIND_NOTES = {
    install.CHECKOUT: "checkout",
    install.SOURCE: "source download, will not update itself",
    install.CONTAINER: "container",
    install.UNKNOWN: "will not update itself",
}


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
    kind = install.detect(install.root())
    note = "" if install.can_self_update(kind) \
        else f" ({KIND_NOTES.get(kind, kind)})"
    return (f"crossglyph {version.installed()}{note}\n"
            f"render core built from "
            f"{stamp.FIRMWARE.name} {stamp.short(stamp.build_stamp())}")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
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
        return _build(rest)
    if command == "fetch-fallbacks":
        return _build(["--fetch-fallbacks", *rest])
    print(f"unknown command {command!r}\n\n{USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

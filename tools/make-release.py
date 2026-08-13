"""Build the release zip from a commit, and check what came out.

    uv run tools/make-release.py

`git archive` does the packing, which is what keeps the polyglot wrappers
byte exact and carries the executable bits. Everything after it is the check:
a release that has lost a line ending or an executable bit still unpacks, runs
nowhere, and says nothing about why.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Without any one of these the release does not run.
REQUIRED = [
    "pyproject.toml", "uv.lock", "LICENSE", "README.md",
    "THIRD-PARTY-NOTICES.md", "crossglyph.sh", "crossglyph.cmd",
    "fonts/README.md",
    "src/crossglyph/cli.py",
    "src/crossglyph/render/render.wasm",
    "src/crossglyph/render/render.built-from.json",
    "src/crossglyph/preview/static/index.html",
    "tools/uv.cmd", "tools/tool-wrapper.sh", "tools/tool-wrapper.cmd",
    "tools/tool-wrapper.ps1",
]

#: A checkout's own furniture, which means nothing to somebody unpacking a zip.
#: `export-ignore` in .gitattributes is what keeps them out; this is the check.
EXCLUDED = [".gitattributes", ".gitignore", ".githooks/pre-commit"]

#: Executed on macOS and Linux, so the bit has to survive the archive. uv.cmd
#: is on the list because crossglyph.sh execs it.
EXECUTABLE = [
    "crossglyph.sh", "tools/uv.cmd", "tools/tool-wrapper.sh",
    "tools/check-line-endings.sh", "src/render/build.sh",
]


def version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    found = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    if not found:
        raise SystemExit("pyproject.toml declares no version")
    return found.group(1)


def git(*args: str) -> str:
    done = subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True, check=True)
    return done.stdout.strip()


def check_polyglot(data: bytes, name: str) -> list[str]:
    """The mixed line endings, read back out of the archive.

    The header and the batch half are CRLF for cmd.exe, the bash body is LF.
    Uniform either way breaks one of the two interpreters, and a zip tool that
    "helpfully" converts text files is exactly how that happens.
    """
    problems = []
    if not data.startswith(b':<<"::CMDLITERAL"\r\n'):
        problems.append(f"{name}: the header is not CRLF")
    if b"\nset -eu\r\n" in data:
        problems.append(f"{name}: the bash body carries carriage returns")
    # The label opens the batch half, so it ends CRLF. What precedes it is the
    # last line of the bash body, and ends LF.
    if b"\n:CMDSCRIPT\r\n" not in data:
        problems.append(f"{name}: the batch body is not CRLF")
    return problems


def main() -> int:
    if git("status", "--porcelain"):
        print("the working tree has uncommitted changes; commit them first, "
              "since the archive is built from HEAD and would not match",
              file=sys.stderr)
        return 2

    name = f"crossglyph-{version()}"
    out = ROOT / "dist" / f"{name}.zip"
    out.parent.mkdir(exist_ok=True)
    git("archive", "--format=zip", f"--prefix={name}/", "-o", str(out), "HEAD")

    problems = []
    with zipfile.ZipFile(out) as archive:
        members = {info.filename[len(name) + 1:]: info
                   for info in archive.infolist()}
        for wanted in REQUIRED:
            if wanted not in members:
                problems.append(f"missing: {wanted}")
        for unwanted in EXCLUDED:
            if unwanted in members:
                problems.append(f"should not be in a release: {unwanted}")
        for path in EXECUTABLE:
            info = members.get(path)
            if info is None:
                continue                      # already reported, if required
            if not (info.external_attr >> 16) & 0o111:
                problems.append(f"not executable: {path}")
        if "tools/uv.cmd" in members:
            problems.extend(check_polyglot(archive.read(f"{name}/tools/uv.cmd"),
                                           "tools/uv.cmd"))
        total = sum(info.file_size for info in archive.infolist())

    if problems:
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(f"{out.name} is not fit to release", file=sys.stderr)
        return 1

    print(f"{out}\n"
          f"  {len(members)} files, {total / 1024:.0f} KB unpacked, "
          f"{out.stat().st_size / 1024:.0f} KB zipped\n"
          f"  from {git('rev-parse', '--short', 'HEAD')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Build the release zip from a commit, and check what came out.

    uv run tools/make-release.py

`git archive` does the reading, and the tree it produces is then repacked into
the release layout: the launcher and the workspace at the root, the code under
versions/<v>, so an update can add a version beside the live one rather than
overwrite it. Members are copied as bytes rather than through the filesystem,
which is what keeps the polyglot wrappers exact and carries the executable
bits.

Everything after that is the check: a release that has lost a line ending or
an executable bit still unpacks, runs nowhere, and says nothing about why.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: What stays outside versions/, because it outlives any one version: the
#: launcher, which an update cannot replace while cmd.exe is holding it, and
#: the workspace, which is the user's. `current` is generated, not tracked.
ROOT_FILES = frozenset({"crossglyph.cmd", "crossglyph.sh"})

#: Without any one of these the release does not run. `{v}` is the version
#: directory, filled in per build.
REQUIRED = [
    "current",
    "crossglyph.sh", "crossglyph.cmd",
    "fonts/README.md", "fonts/conf/all.conf",
    "{v}/pyproject.toml", "{v}/uv.lock", "{v}/LICENSE", "{v}/README.md",
    "{v}/THIRD-PARTY-NOTICES.md",
    "{v}/src/crossglyph/cli.py",
    "{v}/src/crossglyph/render/render.wasm",
    "{v}/src/crossglyph/render/render.built-from.json",
    "{v}/src/crossglyph/preview/static/index.html",
    # The family the preview opens on before anybody has filled the workspace
    # in, and the licence the OFL requires travel with it.
    "{v}/src/crossglyph/starter/Literata[opsz,wght].ttf",
    "{v}/src/crossglyph/starter/Literata-Italic[opsz,wght].ttf",
    "{v}/src/crossglyph/starter/OFL.txt",
    "{v}/tools/uv.cmd", "{v}/tools/tool-wrapper.sh",
    "{v}/tools/tool-wrapper.cmd", "{v}/tools/tool-wrapper.ps1",
]

#: A checkout's own furniture, which means nothing to somebody unpacking a zip.
#: `export-ignore` in .gitattributes is what keeps them out; this is the check.
EXCLUDED = [".gitattributes", ".gitignore", ".githooks/pre-commit"]

#: Executed on macOS and Linux, so the bit has to survive the archive and the
#: repack. uv.cmd is on the list because crossglyph.sh execs it.
EXECUTABLE = [
    "crossglyph.sh", "{v}/tools/uv.cmd", "{v}/tools/tool-wrapper.sh",
    "{v}/tools/check-line-endings.sh", "{v}/src/render/build.sh",
]


def release_path(path: str, version: str) -> str:
    """Where a tracked file lands in the release tree.

    Everything belongs to one version except the launcher and the workspace,
    which outlive every version: an update adds a directory under versions/
    and rewrites `current`, and must not touch either of those.
    """
    if path in ROOT_FILES or path == "fonts" or path.startswith("fonts/"):
        return path
    return f"versions/{version}/{path}"


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


def repack(source: zipfile.ZipFile, out: pathlib.Path, name: str,
           version: str) -> None:
    """The archive git produced, restructured into the release tree.

    Each member's bytes and its external_attr are copied straight across
    rather than extracted to disk and re-added: the executable bits and the
    mixed line endings in tools/uv.cmd both live in the archive, and a round
    trip through the filesystem is where either of them would quietly be lost.
    """
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for info in source.infolist():
            if info.is_dir():
                continue
            inner = info.filename[len(name) + 1:]
            moved = zipfile.ZipInfo(f"{name}/{release_path(inner, version)}",
                                    date_time=info.date_time)
            moved.external_attr = info.external_attr
            moved.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(moved, source.read(info))
        # Generated rather than tracked: a checkout has no live version, and a
        # file saying one would be wrong the moment it was committed.
        current = zipfile.ZipInfo(f"{name}/current",
                                  date_time=(1980, 1, 1, 0, 0, 0))
        current.external_attr = 0o644 << 16
        archive.writestr(current, f"{version}\n")


def main() -> int:
    if git("status", "--porcelain"):
        print("the working tree has uncommitted changes; commit them first, "
              "since the archive is built from HEAD and would not match",
              file=sys.stderr)
        return 2

    release = version()
    name = f"crossglyph-{release}"
    out = ROOT / "dist" / f"{name}.zip"
    out.parent.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory() as work:
        flat = pathlib.Path(work) / "flat.zip"
        git("archive", "--format=zip", f"--prefix={name}/", "-o", str(flat),
            "HEAD")
        with zipfile.ZipFile(flat) as source:
            repack(source, out, name, release)

    where = f"versions/{release}"
    problems = []
    with zipfile.ZipFile(out) as archive:
        members = {info.filename[len(name) + 1:]: info
                   for info in archive.infolist()}
        for wanted in REQUIRED:
            if wanted.format(v=where) not in members:
                problems.append(f"missing: {wanted.format(v=where)}")
        for unwanted in EXCLUDED:
            for path in (unwanted, f"{where}/{unwanted}"):
                if path in members:
                    problems.append(f"should not be in a release: {path}")
        for path in EXECUTABLE:
            info = members.get(path.format(v=where))
            if info is None:
                continue                      # already reported, if required
            if not (info.external_attr >> 16) & 0o111:
                problems.append(f"not executable: {path.format(v=where)}")
        uv = f"{where}/tools/uv.cmd"
        if uv in members:
            problems.extend(check_polyglot(archive.read(f"{name}/{uv}"),
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

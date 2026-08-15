"""Bump the pinned uv, checksums and all.

    uv run tools/bump-uv.py              # to uv's latest release
    uv run tools/bump-uv.py 0.12.4       # to a named one
    uv run tools/bump-uv.py --commit     # and commit the result

The version sits in tools/uv.cmd twice, once in each half of the polyglot,
beside six SHA-256 checksums that have to move with it. By hand that is six
copied hashes, and a wrapper with one of them wrong runs nowhere.

Astral publishes a .sha256 beside every archive, so the checksums are read
rather than computed: nothing here downloads a release to hash it. One archive
is downloaded at the end, by running the wrapper, which is the only step that
proves the new pin works on the machine doing the bump.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "tools" / "uv.cmd"

#: What GitHub redirects to the newest tag. A HEAD against this rather than the
#: API: no token, no rate limit, and uv tags are the bare version, which is
#: also what the download URLs interpolate.
LATEST = "https://github.com/astral-sh/uv/releases/latest"

PLATFORMS = ("LINUX_X64", "LINUX_ARM64", "WINDOWS_X64", "WINDOWS_ARM64",
             "MACOS_X64", "MACOS_ARM64")

TIMEOUT = 30


def latest_version() -> str:
    """The version of uv's newest release, from where the redirect lands."""
    request = urllib.request.Request(LATEST, method="HEAD")
    with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
        tag = answer.geturl().rstrip("/").rsplit("/", 1)[-1]
    if not re.fullmatch(r"\d+(\.\d+)+", tag):
        raise SystemExit(f"{LATEST} redirected to {tag!r}, which is not a "
                         "version; name the one you want instead")
    return tag


def read_wrapper(text: str) -> tuple[str, dict[str, str], dict[str, str]]:
    """What the wrapper pins: the version, the URL templates and the hashes.

    Everything is read out of the bash half, whose `NAME="value"` form the
    batch half's `set "NAME=value"` does not match. The batch half is not read
    but is rewritten, and `bump` checks that both halves said the same thing by
    counting what it replaced.
    """
    def one(pattern: str, label: str) -> str:
        found = re.search(pattern, text)
        if not found:
            raise SystemExit(f"tools/uv.cmd: no {label}")
        return found.group(1)

    version = one(r'TOOL_VERSION="([^"]+)"', "TOOL_VERSION")
    urls = {p: one(rf'TOOL_URL_{p}="([^"]+)"', f"TOOL_URL_{p}")
            for p in PLATFORMS}
    sums = {p: one(rf'TOOL_CHECKSUM_{p}="([a-f0-9]{{64}})"',
                   f"TOOL_CHECKSUM_{p}") for p in PLATFORMS}
    return version, urls, sums


def published_checksum(url: str) -> str:
    """The SHA-256 astral published beside an archive.

    A missing one is fatal rather than a reason to download 30 MB and hash it.
    Every uv release has carried these, so their absence means the URL is
    wrong, which is worth stopping for.
    """
    try:
        with urllib.request.urlopen(f"{url}.sha256", timeout=TIMEOUT) as got:
            first = got.read().decode("utf-8", "replace").split()
    except urllib.error.HTTPError as bad:
        raise SystemExit(f"{url}.sha256: HTTP {bad.code}; is that release "
                         "published for every platform?") from bad
    if not first or not re.fullmatch(r"[a-f0-9]{64}", first[0]):
        raise SystemExit(f"{url}.sha256 does not start with a SHA-256")
    return first[0]


def replacements(old: str, new: str, old_sums: dict[str, str],
                 new_sums: dict[str, str]) -> list[tuple[str, str, int]]:
    """Every literal to swap, with how many times it must occur.

    The two version forms are disjoint: bash writes `TOOL_VERSION="0.12.3"`
    and batch `set "TOOL_VERSION=0.12.3"`, so each pattern hits its own half
    exactly once. A checksum is spelt the same in both halves and so occurs
    twice. Counting is what turns a wrapper whose halves have drifted into a
    refusal rather than a file rewritten down one side.
    """
    pairs = [(f'TOOL_VERSION="{old}"', f'TOOL_VERSION="{new}"', 1),
             (f'TOOL_VERSION={old}"', f'TOOL_VERSION={new}"', 1)]
    pairs += [(old_sums[p], new_sums[p], 2) for p in PLATFORMS]
    return pairs


def line_endings(data: bytes) -> list[bool]:
    """Which of this file's lines end CRLF, as a shape two files can compare.

    tools/uv.cmd is mixed on purpose and most editors flatten it silently, so
    the rewrite has to be provably incapable of that. It replaces fixed
    substrings that hold no newline, so the shape cannot change; this is the
    assertion that says so.
    """
    return [line.endswith(b"\r") for line in data.split(b"\n")]


def bump(data: bytes, pairs: list[tuple[str, str, int]]) -> bytes:
    """The wrapper's bytes with every literal swapped, and nothing else."""
    was = line_endings(data)
    for old, new, expected in pairs:
        found = data.count(old.encode())
        if found != expected:
            raise SystemExit(f"tools/uv.cmd: {old!r} occurs {found} times, "
                             f"expected {expected}; the halves have drifted "
                             "apart or the file is not what this script reads")
        data = data.replace(old.encode(), new.encode())
    if line_endings(data) != was:
        raise SystemExit("the rewrite moved a line ending, which it cannot do "
                         "by construction; nothing was written")
    return data


def run_wrapper(args: list[str], environ: dict[str, str] | None = None) -> int:
    """Run tools/uv.cmd through the interpreter that reads its half.

    Which half runs is the whole of the platform difference. cmd.exe on
    Windows, bash everywhere else: the bash half dies on `Unsupported OS:
    MINGW64_NT` if a Git Bash is what reaches it, so Windows never takes that
    branch even when the bump is run from one. `cmd /c call` rather than
    `cmd /c`, because cmd strips the quotes off a command that begins with one
    and an install path with a space in it would otherwise arrive in pieces.
    """
    command = ["cmd", "/c", "call", str(WRAPPER), *args] if os.name == "nt" \
        else ["bash", str(WRAPPER), *args]
    # The child writes to the same console and does not share this buffer, so
    # without the flush its download lands above the line announcing it.
    sys.stdout.flush()
    env = dict(os.environ, **(environ or {}))
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode


def git(*args: str) -> str:
    done = subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True, check=True)
    return done.stdout.strip()


def preflight() -> None:
    """Refuse to fold somebody else's edit into a chore commit.

    Runs before anything is fetched, so a refusal costs nothing. It also means
    what the bump starts from is committed, and therefore went past the
    pre-commit hook that checks the line endings.
    """
    try:
        git("rev-parse", "--git-dir")
    except (OSError, subprocess.CalledProcessError) as bad:
        raise SystemExit("--commit needs a git repository") from bad
    if git("status", "--porcelain", "--", "tools/uv.cmd"):
        raise SystemExit("tools/uv.cmd already has uncommitted changes; "
                         "commit or stash them first")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bump the uv pinned in tools/uv.cmd.")
    parser.add_argument("version", nargs="?",
                        help="which version to pin, default uv's latest")
    parser.add_argument("--verify", action="store_true",
                        help="check all six platform archives, not just the "
                             "one this machine runs")
    parser.add_argument("--commit", action="store_true",
                        help="commit tools/uv.cmd once it runs")
    args = parser.parse_args()

    if args.commit:
        preflight()

    data = WRAPPER.read_bytes()
    current, urls, sums = read_wrapper(data.decode("utf-8"))
    wanted = args.version or latest_version()

    if wanted == current:
        print(f"tools/uv.cmd already pins uv {wanted}")
    else:
        print(f"uv {current} to {wanted}")
        fresh = {}
        for platform in PLATFORMS:
            url = urls[platform].replace("${TOOL_VERSION}", wanted)
            fresh[platform] = published_checksum(url)
            print(f"  {platform:<14} {fresh[platform]}")
        WRAPPER.write_bytes(
            bump(data, replacements(current, wanted, sums, fresh)))
        print("  wrote tools/uv.cmd")

    # The one download. It verifies this platform's checksum for real, which
    # is the part a published .sha256 cannot vouch for: that the archive at
    # that URL is the archive the hash describes. A failure leaves the wrapper
    # as written, since seeing the bad pin is more use than losing it.
    print("\nRunning the wrapper, which downloads and verifies one archive.")
    if run_wrapper(["--version"]):
        print("the wrapper failed; git checkout -- tools/uv.cmd puts it back",
              file=sys.stderr)
        return 1

    if args.verify:
        print("\nVerifying all six platforms.")
        if run_wrapper([], {"TOOL_VERIFY_ALL_PLATFORMS": "1"}):
            print("verification failed; git checkout -- tools/uv.cmd puts it "
                  "back", file=sys.stderr)
            return 1

    if args.commit:
        if wanted == current:
            print("\nNothing changed, so nothing to commit.")
        else:
            # By pathspec, so anything else already staged is left alone.
            git("commit", "-m", f"chore(tools): bump uv to {wanted}",
                "--", "tools/uv.cmd")
            print(f"\nCommitted: chore(tools): bump uv to {wanted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

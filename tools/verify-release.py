#!/usr/bin/env python3
"""Verify every public artifact made by a CrossGlyph release tag.

    uv run tools/verify-release.py v0.4.0

Run this after the release workflow succeeds. It reads the GitHub release and
Pages manifest, downloads the published zip, and asks Docker for the image
that users will pull. Nothing is written outside Docker's ordinary image
cache.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import io
import json
import re
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Sequence
from typing import Any

from crossglyph import updates

REPO = "CrazyCoder/crossglyph"
IMAGE = "ghcr.io/crazycoder/crossglyph"
REQUIRED_PLATFORMS = frozenset({"linux/amd64", "linux/arm64"})
_VERSION = re.compile(r"v?(\d+\.\d+\.\d+)")

Runner = Callable[[Sequence[str]], str]
Fetcher = Callable[[str], bytes]


class VerificationError(RuntimeError):
    """A published release does not match its other public artifacts."""


@dataclasses.dataclass(frozen=True)
class Report:
    version: str
    release_url: str
    asset_name: str
    asset_size: int
    asset_sha256: str
    image_digest: str
    platforms: tuple[str, ...]
    container_version: str


def normalize_version(value: str) -> str:
    match = _VERSION.fullmatch(value)
    if match is None:
        raise VerificationError(
            f"expected a release version like v0.4.0, got {value!r}")
    return match.group(1)


def run_command(arguments: Sequence[str]) -> str:
    try:
        result = subprocess.run(
            list(arguments), capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise VerificationError(
            f"required command not found: {arguments[0]}") from exc
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        suffix = f": {detail}" if detail else ""
        raise VerificationError(
            f"{' '.join(arguments)} exited {result.returncode}{suffix}")
    return result.stdout


def fetch_url(url: str) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": "crossglyph-release-verifier"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except (OSError, urllib.error.URLError) as exc:
        raise VerificationError(f"could not fetch {url}: {exc}") from exc


def _json(body: str | bytes, label: str) -> Any:
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise VerificationError(f"{label} did not return valid JSON") from exc


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def _release(version: str, runner: Runner) -> tuple[dict[str, Any], dict[str, Any]]:
    tag = f"v{version}"
    release = _json(runner([
        "gh", "release", "view", tag, "--repo", REPO,
        "--json", "url,tagName,assets",
    ]), "GitHub release")
    _require(isinstance(release, dict), "GitHub release is not an object")
    _require(release.get("tagName") == tag,
             f"GitHub release does not describe {tag}")

    name = f"crossglyph-{version}.zip"
    published = release.get("assets")
    _require(isinstance(published, list),
             "GitHub release assets are not a list")
    assets = [asset for asset in published
              if isinstance(asset, dict) and asset.get("name") == name]
    _require(len(assets) == 1,
             f"GitHub release must contain exactly one {name}")
    asset = assets[0]
    _require(asset.get("state") == "uploaded",
             f"GitHub asset {name} is not uploaded")
    _require(isinstance(asset.get("size"), int),
             f"GitHub asset {name} has no size")
    _require(isinstance(asset.get("url"), str),
             f"GitHub asset {name} has no download URL")
    digest = asset.get("digest")
    _require(isinstance(digest, str)
             and re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is not None,
             f"GitHub asset {name} has no SHA-256 digest")
    return release, asset


def _archive(version: str, asset: dict[str, Any], fetcher: Fetcher) -> str:
    body = fetcher(asset["url"])
    _require(len(body) == asset["size"],
             "downloaded release size does not match GitHub")
    digest = hashlib.sha256(body).hexdigest()
    _require(f"sha256:{digest}" == asset["digest"],
             "downloaded release SHA-256 does not match GitHub")

    root = f"crossglyph-{version}"
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            current = archive.read(f"{root}/current").decode("utf-8").strip()
            project = tomllib.loads(archive.read(
                f"{root}/versions/{version}/pyproject.toml").decode("utf-8"))
    except (KeyError, UnicodeDecodeError, tomllib.TOMLDecodeError,
            zipfile.BadZipFile) as exc:
        raise VerificationError(
            "published release does not have the expected layout") from exc
    _require(current == version,
             f"published current pointer says {current!r}, not {version!r}")
    declared = project.get("project", {}).get("version")
    _require(declared == version,
             f"packaged project says {declared!r}, not {version!r}")
    return digest


def _manifest(version: str, release: dict[str, Any], asset: dict[str, Any],
              digest: str, fetcher: Fetcher) -> None:
    manifest = _json(fetcher(updates.MANIFEST_URL), "Pages manifest")
    _require(isinstance(manifest, dict), "Pages manifest is not an object")
    expected = {
        "version": version,
        "url": asset["url"],
        "sha256": digest,
        "size": asset["size"],
        "notes_url": release["url"],
    }
    for key, value in expected.items():
        _require(manifest.get(key) == value,
                 f"Pages manifest {key} is {manifest.get(key)!r}, not {value!r}")


def _images(version: str, runner: Runner) -> tuple[str, tuple[str, ...]]:
    minor = ".".join(version.split(".")[:2])
    manifests: dict[str, dict[str, Any]] = {}
    for tag in (version, minor, "latest"):
        body = runner([
            "docker", "buildx", "imagetools", "inspect",
            f"{IMAGE}:{tag}", "--format", "{{json .Manifest}}",
        ])
        manifest = _json(body, f"container tag {tag}")
        _require(isinstance(manifest, dict),
                 f"container tag {tag} is not an image index")
        digest = manifest.get("digest")
        _require(isinstance(digest, str)
                 and re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is not None,
                 f"container tag {tag} has no digest")
        manifests[tag] = manifest

    digests = {manifest["digest"] for manifest in manifests.values()}
    _require(len(digests) == 1,
             f"container tags do not share one digest: {sorted(digests)}")

    platforms = {
        f"{platform.get('os')}/{platform.get('architecture')}"
        for item in manifests[version].get("manifests", [])
        if isinstance(item, dict)
        and isinstance((platform := item.get("platform")), dict)
    }
    missing = REQUIRED_PLATFORMS - platforms
    _require(not missing,
             f"container image is missing platforms: {', '.join(sorted(missing))}")
    return digests.pop(), tuple(sorted(REQUIRED_PLATFORMS))


def verify_release(version: str, *, runner: Runner = run_command,
                   fetcher: Fetcher = fetch_url) -> Report:
    version = normalize_version(version)
    release, asset = _release(version, runner)
    digest = _archive(version, asset, fetcher)
    _manifest(version, release, asset, digest, fetcher)
    image_digest, platforms = _images(version, runner)

    container_output = runner([
        "docker", "run", "--rm", f"{IMAGE}:{version}", "--version"])
    expected_version = f"crossglyph {version} (container)"
    lines = {line.strip() for line in container_output.splitlines()}
    _require(expected_version in lines,
             f"container did not report {expected_version!r}")
    return Report(
        version=version,
        release_url=release["url"],
        asset_name=asset["name"],
        asset_size=asset["size"],
        asset_sha256=digest,
        image_digest=image_digest,
        platforms=platforms,
        container_version=expected_version,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="verify a published CrossGlyph release")
    parser.add_argument("version", help="release tag, for example v0.4.0")
    args = parser.parse_args(argv)
    try:
        report = verify_release(args.version)
    except VerificationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"release: {report.release_url}")
    print(f"asset: {report.asset_name}, {report.asset_size} bytes, "
          f"sha256:{report.asset_sha256}")
    print("manifest: version, URL, size, digest and notes URL match")
    print(f"container: {report.image_digest} "
          f"({', '.join(report.platforms)})")
    print(f"version: {report.container_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

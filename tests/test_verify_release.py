"""The public release, updater manifest and container describe one build."""
import hashlib
import importlib.util
import io
import json
import pathlib
import sys
import zipfile

import pytest

IMAGE_DIGEST = "sha256:" + "1" * 64
OLDER_IMAGE_DIGEST = "sha256:" + "2" * 64

REPO = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "verify_release", REPO / "tools" / "verify-release.py")
assert _spec and _spec.loader
verify_release = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = verify_release
_spec.loader.exec_module(verify_release)


def _archive(version="0.4.0"):
    output = io.BytesIO()
    root = f"crossglyph-{version}"
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(f"{root}/current", f"{version}\n")
        archive.writestr(
            f"{root}/versions/{version}/pyproject.toml",
            f'[project]\nname = "crossglyph"\nversion = "{version}"\n')
    return output.getvalue()


def _published(*, manifest_version="0.4.0", image_digests=None,
               platforms=("amd64", "arm64")):
    version = "0.4.0"
    tag = f"v{version}"
    asset_name = f"crossglyph-{version}.zip"
    asset_url = f"https://example.invalid/{tag}/{asset_name}"
    release_url = f"https://example.invalid/releases/{tag}"
    body = _archive(version)
    digest = hashlib.sha256(body).hexdigest()
    release = {
        "url": release_url,
        "tagName": tag,
        "assets": [{
            "name": asset_name,
            "state": "uploaded",
            "size": len(body),
            "digest": f"sha256:{digest}",
            "url": asset_url,
        }],
    }
    manifest = {
        "version": manifest_version,
        "url": asset_url,
        "sha256": digest,
        "size": len(body),
        "notes_url": release_url,
    }
    image_digests = image_digests or {
        "0.4.0": IMAGE_DIGEST, "0.4": IMAGE_DIGEST,
        "latest": IMAGE_DIGEST,
    }
    seen = []

    def runner(arguments):
        seen.append(tuple(arguments))
        if arguments[:3] == ["gh", "release", "view"]:
            return json.dumps(release)
        if arguments[:4] == ["docker", "buildx", "imagetools", "inspect"]:
            image_tag = arguments[4].rsplit(":", 1)[1]
            return json.dumps({
                "digest": image_digests[image_tag],
                "manifests": [
                    {"platform": {"os": "linux", "architecture": platform}}
                    for platform in platforms
                ],
            })
        if arguments[:3] == ["docker", "run", "--rm"]:
            return ("crossglyph 0.4.0 (container)\n"
                    "render core built from crosspoint-reader develop abc\n")
        raise AssertionError(arguments)

    def fetcher(url):
        if url == asset_url:
            return body
        if url == verify_release.updates.MANIFEST_URL:
            return json.dumps(manifest).encode()
        raise AssertionError(url)

    return runner, fetcher, seen


def test_the_public_release_is_one_build_everywhere():
    runner, fetcher, seen = _published()

    report = verify_release.verify_release(
        "v0.4.0", runner=runner, fetcher=fetcher)

    assert report.version == "0.4.0"
    assert report.asset_sha256
    assert report.image_digest == IMAGE_DIGEST
    assert report.platforms == ("linux/amd64", "linux/arm64")
    inspected = {
        command[4].rsplit(":", 1)[1]
        for command in seen
        if command[:4] == ("docker", "buildx", "imagetools", "inspect")
    }
    assert inspected == {"0.4.0", "0.4", "latest"}


def test_a_stale_pages_manifest_fails_the_round_trip():
    runner, fetcher, _ = _published(manifest_version="0.3.0")

    with pytest.raises(verify_release.VerificationError,
                       match="Pages manifest version"):
        verify_release.verify_release(
            "0.4.0", runner=runner, fetcher=fetcher)


def test_container_tags_must_resolve_to_one_image():
    runner, fetcher, _ = _published(image_digests={
        "0.4.0": IMAGE_DIGEST, "0.4": IMAGE_DIGEST,
        "latest": OLDER_IMAGE_DIGEST,
    })

    with pytest.raises(verify_release.VerificationError,
                       match="do not share one digest"):
        verify_release.verify_release(
            "0.4.0", runner=runner, fetcher=fetcher)


def test_the_release_image_needs_both_supported_platforms():
    runner, fetcher, _ = _published(platforms=("amd64",))

    with pytest.raises(verify_release.VerificationError,
                       match="linux/arm64"):
        verify_release.verify_release(
            "0.4.0", runner=runner, fetcher=fetcher)


def test_a_release_argument_is_a_full_semantic_version():
    with pytest.raises(verify_release.VerificationError,
                       match="like v0.4.0"):
        verify_release.normalize_version("0.4")

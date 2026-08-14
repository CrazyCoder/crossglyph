"""Reading the manifest, remembering the answer, and not asking twice a day."""
import json
import urllib.request

import pytest

from crossglyph import updates

GOOD = {
    "version": "0.2.0",
    "url": "https://github.com/CrazyCoder/crossglyph/releases/download/"
           "v0.2.0/crossglyph-0.2.0.zip",
    "sha256": "a" * 64,
    "size": 1656832,
    "notes_url": "https://github.com/CrazyCoder/crossglyph/releases/tag/v0.2.0",
    "launcher_changed": False,
    "signature": None,
}


def _raw(**over) -> bytes:
    return json.dumps({**GOOD, **over}).encode("utf-8")


def test_a_good_manifest_parses():
    said = updates.parse(_raw())
    assert said.version == "0.2.0"
    assert said.sha256 == "a" * 64
    assert said.launcher_changed is False


def test_an_unknown_key_is_ignored():
    """The format has to be able to grow without every install refusing it."""
    assert updates.parse(_raw(future_field="whatever")).version == "0.2.0"


@pytest.mark.parametrize("raw", [
    b"", b"not json", b"[]", b"null",
    json.dumps({k: v for k, v in GOOD.items() if k != "version"}).encode(),
    json.dumps({k: v for k, v in GOOD.items() if k != "url"}).encode(),
])
def test_a_manifest_that_is_not_one_is_refused(raw):
    with pytest.raises(ValueError):
        updates.parse(raw)


def test_a_version_that_will_not_order_is_refused():
    with pytest.raises(ValueError):
        updates.parse(_raw(version="latest"))


def test_a_hash_that_is_not_a_sha256_is_refused():
    """It is the only thing standing between a download and being run."""
    with pytest.raises(ValueError):
        updates.parse(_raw(sha256="deadbeef"))


def test_an_artifact_served_over_plain_http_is_refused():
    with pytest.raises(ValueError):
        updates.parse(_raw(url="http://example.com/crossglyph-0.2.0.zip"))


# --- state ----------------------------------------------------------------


def test_no_state_file_reads_as_never_checked(tmp_path):
    said = updates.load_state(tmp_path)
    assert said.checked_at == 0
    assert said.latest is None


def test_state_survives_a_round_trip(tmp_path):
    updates.save_state(tmp_path, updates.State(checked_at=1000.0,
                                               latest="0.2.0", error=None))
    assert updates.load_state(tmp_path).latest == "0.2.0"


def test_unreadable_state_reads_as_never_checked(tmp_path):
    """A truncated write is not a reason to refuse to run."""
    (tmp_path / updates.STATE_NAME).write_text("{ broken", encoding="utf-8")
    assert updates.load_state(tmp_path).checked_at == 0


def test_a_state_that_cannot_be_written_is_not_an_error(tmp_path, monkeypatch):
    """A read-only install still runs. It just asks again next time."""
    def refuse(*args, **kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(updates.pathlib.Path, "write_text", refuse)
    updates.save_state(tmp_path, updates.State(1.0, "0.2.0", None))


# --- the check ------------------------------------------------------------


@pytest.fixture
def offline(monkeypatch):
    """No test reaches the network. Every fetch goes through this one seam."""
    calls = []

    def fetch(url, timeout=2.0):
        calls.append(url)
        return _raw()

    monkeypatch.setattr(updates, "fetch", fetch)
    return calls


def test_a_first_check_fetches_and_remembers(tmp_path, offline):
    said = updates.check(tmp_path, now=1000.0, environ={})
    assert len(offline) == 1
    assert said.latest == "0.2.0"
    assert updates.load_state(tmp_path).latest == "0.2.0"


def test_a_second_check_inside_the_window_does_not_fetch(tmp_path, offline):
    updates.check(tmp_path, now=1000.0, environ={})
    updates.check(tmp_path, now=1000.0 + 3600, environ={})
    assert len(offline) == 1, "it asked again inside the throttle"


def test_a_check_after_the_window_fetches(tmp_path, offline):
    updates.check(tmp_path, now=1000.0, environ={})
    updates.check(tmp_path, now=1000.0 + 25 * 3600, environ={})
    assert len(offline) == 2


def test_a_clock_that_moved_back_does_not_wedge_the_throttle(tmp_path,
                                                             offline):
    """A stored time in the future would otherwise hold it shut until the
    clock caught up, which for a badly set one is never."""
    updates.check(tmp_path, now=99999.0, environ={})
    updates.check(tmp_path, now=1000.0, environ={})
    assert len(offline) == 2


def test_a_forced_check_ignores_the_window(tmp_path, offline):
    updates.check(tmp_path, now=1000.0, environ={})
    updates.check(tmp_path, now=1000.0, force=True, environ={})
    assert len(offline) == 2


def test_the_interval_is_the_one_the_config_asks_for(tmp_path, offline):
    (tmp_path / "update.conf").write_text("interval_hours = 1\n",
                                          encoding="utf-8")
    updates.check(tmp_path, now=1000.0, environ={})
    updates.check(tmp_path, now=1000.0 + 2 * 3600, environ={})
    assert len(offline) == 2


def test_checking_off_does_not_fetch(tmp_path, offline):
    (tmp_path / "update.conf").write_text("check = no\n", encoding="utf-8")
    updates.check(tmp_path, now=1000.0, environ={})
    assert offline == []


def test_checking_off_keeps_what_was_already_found(tmp_path, offline):
    """Turning it off silences the asking, not the answer already on disk."""
    updates.check(tmp_path, now=1000.0, environ={})
    (tmp_path / "update.conf").write_text("check = no\n", encoding="utf-8")
    assert updates.check(tmp_path, now=99999.0, environ={}).latest == "0.2.0"


def test_a_forced_check_runs_even_when_checking_is_off(tmp_path, offline):
    """Opting out stops it asking on its own. The button is the one way it
    still can, and taking that away would leave nothing to click."""
    (tmp_path / "update.conf").write_text("check = no\n", encoding="utf-8")
    updates.check(tmp_path, now=1000.0, force=True, environ={})
    assert len(offline) == 1


def test_a_network_failure_is_recorded_rather_than_raised(tmp_path,
                                                          monkeypatch):
    def boom(url, timeout=2.0):
        raise OSError("no route to host")

    monkeypatch.setattr(updates, "fetch", boom)
    said = updates.check(tmp_path, now=1000.0, environ={})
    assert said.error
    assert said.latest is None


def test_a_failure_still_marks_the_time(tmp_path, monkeypatch):
    """Otherwise an install with no network meets the timeout on every run."""
    def boom(url, timeout=2.0):
        raise OSError("down")

    monkeypatch.setattr(updates, "fetch", boom)
    updates.check(tmp_path, now=1000.0, environ={})
    assert updates.load_state(tmp_path).checked_at == 1000.0


def test_a_malformed_manifest_is_a_failed_check_and_not_a_crash(tmp_path,
                                                                monkeypatch):
    monkeypatch.setattr(updates, "fetch", lambda url, timeout=2.0: b"{")
    assert updates.check(tmp_path, now=1000.0, environ={}).error


# --- what to do about it --------------------------------------------------


def test_a_newer_release_is_available(monkeypatch):
    monkeypatch.setattr(updates.version, "installed", lambda: "0.1.0")
    assert updates.available(updates.State(1000.0, "0.2.0", None)) == "0.2.0"


def test_the_same_version_is_not(monkeypatch):
    monkeypatch.setattr(updates.version, "installed", lambda: "0.2.0")
    assert updates.available(updates.State(1000.0, "0.2.0", None)) is None


def test_an_older_release_is_not(monkeypatch):
    """A checkout of master can be ahead of the last release. Telling somebody
    to move backwards is worse than saying nothing."""
    monkeypatch.setattr(updates.version, "installed", lambda: "0.3.0")
    assert updates.available(updates.State(1000.0, "0.2.0", None)) is None


def test_a_failed_check_offers_nothing():
    assert updates.available(updates.State(1000.0, None, "down")) is None


def test_nothing_in_this_file_reaches_the_network(monkeypatch):
    """The seam is one function. If a later test calls check() without the
    offline fixture, this is what makes it obvious rather than slow."""
    def forbidden(*args, **kwargs):
        raise AssertionError("a test tried to open the network")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    with pytest.raises(AssertionError):
        updates.fetch(updates.MANIFEST_URL)

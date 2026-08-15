"""The background preview: start, stop, status, restart."""
import json
import os
import pathlib
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

from crossglyph import daemon, render

needs_wasm = pytest.mark.skipif(
    not render.WASM_PATH.is_file(),
    reason="no src/crossglyph/render/render.wasm; run src/render/build.sh")

REPO = pathlib.Path(__file__).resolve().parents[1]


def a_state(**changes) -> daemon.State:
    fields = dict(pid=1234, host="127.0.0.1", port=8000, rest=[],
                  version="0.1.2", started=time.time())
    return daemon.State(**{**fields, **changes})


def free_port() -> int:
    """A port nothing holds, for a test that starts a real server."""
    with socket.socket() as found:
        found.bind(("127.0.0.1", 0))
        return found.getsockname()[1]


# --- state ----------------------------------------------------------------


def test_the_state_survives_a_round_trip(tmp_path):
    daemon.save(tmp_path, a_state(port=8123, rest=["--family", "notosans"]))
    read = daemon.load(tmp_path)
    assert (read.port, read.rest) == (8123, ["--family", "notosans"])


def test_no_state_at_all_reads_as_nothing_running(tmp_path):
    assert daemon.load(tmp_path) is None


def test_a_state_file_we_cannot_parse_counts_as_none(tmp_path):
    daemon.state_path(tmp_path).write_text("{not json", encoding="utf-8")
    assert daemon.load(tmp_path) is None


def test_a_state_file_missing_a_field_counts_as_none(tmp_path):
    """An older layout, or a half-written file. Either way, write it again."""
    daemon.state_path(tmp_path).write_text(json.dumps({"pid": 7}),
                                           encoding="utf-8")
    assert daemon.load(tmp_path) is None


def test_a_state_whose_process_is_gone_is_swept(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon, "alive", lambda pid: False)
    daemon.save(tmp_path, a_state(port=free_port()))
    assert daemon.look(tmp_path) == (None, None)
    assert not daemon.state_path(tmp_path).exists()


def test_a_server_that_stopped_answering_is_kept_not_swept(tmp_path,
                                                           monkeypatch):
    """Its process is still there, so it is wedged rather than gone, and
    something has to be able to stop it."""
    monkeypatch.setattr(daemon, "alive", lambda pid: True)
    daemon.save(tmp_path, a_state(port=free_port()))
    state, body = daemon.look(tmp_path)
    assert state is not None and body is None
    assert daemon.state_path(tmp_path).exists()


def test_stop_kills_a_preview_that_is_not_answering(tmp_path, monkeypatch):
    killed = []
    monkeypatch.setattr(daemon, "alive", lambda pid: True)
    monkeypatch.setattr(daemon, "terminate", killed.append)
    daemon.save(tmp_path, a_state(pid=4321, port=free_port()))
    assert daemon.stop(tmp_path) == 0
    assert killed == [4321]
    assert not daemon.state_path(tmp_path).exists()


def test_status_says_a_preview_is_wedged_rather_than_gone(tmp_path, capsys,
                                                          monkeypatch):
    monkeypatch.setattr(daemon, "alive", lambda pid: True)
    daemon.save(tmp_path, a_state(port=free_port()))
    assert daemon.status(tmp_path) == 1
    assert "not answering" in capsys.readouterr().out


# --- addresses ------------------------------------------------------------


@pytest.mark.parametrize("bound, browsed", [
    ("127.0.0.1", "http://127.0.0.1:8000"),
    # Bound to everything is not an address anything can ask.
    ("0.0.0.0", "http://127.0.0.1:8000"),
    ("::", "http://[::1]:8000"),
    ("192.168.1.5", "http://192.168.1.5:8000"),
])
def test_the_url_is_one_a_browser_can_open(bound, browsed):
    assert daemon.url(bound, 8000) == browsed


def test_a_dead_pid_is_not_alive():
    """0 is never a process here, and negatives would be a signal to a group."""
    assert not daemon.alive(0)
    assert not daemon.alive(-1)


def test_this_process_is_alive():
    """Cheap, and the one case that must not use os.kill on Windows."""
    assert daemon.alive(os.getpid())


# --- which interpreter a start uses ---------------------------------------


def a_release(root: pathlib.Path, name: str, venv: bool) -> pathlib.Path:
    (root / "versions" / name / "src").mkdir(parents=True)
    (root / "current").write_text(name, encoding="utf-8")
    python = root / "versions" / name / daemon.VENV_PYTHON
    if venv:
        python.parent.mkdir(parents=True)
        python.write_text("", encoding="utf-8")
    (root / "crossglyph.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / "crossglyph.cmd").write_text("@echo off\n", encoding="utf-8")
    return python


def test_a_release_starts_from_the_current_versions_own_python(tmp_path):
    """What makes a restart land on a version installed since this one began."""
    python = a_release(tmp_path, "0.2.0", venv=True)
    assert daemon.command(tmp_path) == [str(python), "-m", "crossglyph"]


def test_a_version_with_no_venv_yet_goes_through_the_launcher(tmp_path):
    """An update unpacks the tree; only the launcher can call uv to fill it."""
    a_release(tmp_path, "0.2.0", venv=False)
    assert str(tmp_path / daemon.LAUNCHER) in daemon.command(tmp_path)


def test_a_checkout_starts_from_the_interpreter_running_it(tmp_path):
    assert daemon.command(tmp_path) == [sys.executable, "-m", "crossglyph"]


# --- filling in what was not asked for ------------------------------------


def test_a_bare_restart_replays_the_last_start():
    opts = daemon.parse(["--no-open"], "restart")
    daemon.settle(opts, a_state(port=8123, rest=["--family", "notosans"]))
    assert (opts.host, opts.port, opts.rest) == \
        ("127.0.0.1", 8123, ["--family", "notosans"])
    assert opts.open_browser is False


def test_a_restart_moving_the_port_keeps_everything_else():
    opts = daemon.parse(["--port", "9000"], "restart")
    daemon.settle(opts, a_state(port=8123, rest=["--family", "notosans"]))
    assert (opts.port, opts.rest) == (9000, ["--family", "notosans"])


def test_a_start_with_nothing_stored_takes_the_defaults():
    opts = daemon.parse([], "start")
    daemon.settle(opts, None)
    assert (opts.host, opts.port, opts.open_browser) == \
        (daemon.DEFAULT_HOST, daemon.DEFAULT_PORT, True)


# --- the shutdown endpoint ------------------------------------------------


def test_shutdown_is_refused_from_anywhere_but_this_machine():
    """A page served on 0.0.0.0 is not a licence to stop the server."""
    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    with TestClient(server.app, client=("10.0.0.9", 55555)) as client:
        answer = client.post("/shutdown")
    assert answer.status_code == 403
    assert "machine it runs on" in answer.json()["detail"]


def test_shutdown_from_this_machine_asks_the_server_to_leave(monkeypatch):
    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    class Uvicorn:
        should_exit = False

    monkeypatch.setattr(server, "_server", Uvicorn)
    with TestClient(server.app, client=("127.0.0.1", 55555)) as client:
        answer = client.post("/shutdown")
    assert answer.status_code == 200
    assert Uvicorn.should_exit


def test_a_foreground_page_render_has_nothing_to_shut_down():
    """--png and the test client run the app without a server behind it."""
    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    with TestClient(server.app, client=("127.0.0.1", 55555)) as client:
        assert client.post("/shutdown").status_code == 409


# --- the whole thing ------------------------------------------------------


@needs_wasm
def test_a_real_server_starts_reports_and_stops(tmp_path, monkeypatch):
    """The one test that spawns the thing, since that is the feature.

    Runs against the checkout rather than a release, so `command()` resolves
    to this interpreter and the child is the code under test.
    """
    monkeypatch.setenv("CROSSGLYPH_HOME", str(REPO))
    # Armed for real: every probe below goes through the opener, and one that
    # honoured this would find nothing running on a machine that is.
    monkeypatch.setenv("http_proxy", "http://proxy.invalid:3128")
    monkeypatch.setattr(daemon, "state_path",
                        lambda root: tmp_path / daemon.STATE_NAME)
    monkeypatch.setattr(daemon.webbrowser, "open",
                        lambda *a, **k: pytest.fail("--no-open opened one"))
    port = free_port()
    opts = daemon.parse(["--port", str(port), "--no-open"], "start")
    daemon.settle(opts, None)

    assert daemon.start(REPO, opts) == 0
    try:
        state, body = daemon.look(REPO)
        assert state.port == port
        assert body["version"]
        # The server's own pid, not the one that was spawned. On Windows uv's
        # venv python is a trampoline, so those differ and killing the wrong
        # one would leave the port held.
        assert state.pid == body["pid"] and daemon.alive(state.pid)
        assert daemon.status(REPO) == 0
    finally:
        assert daemon.stop(REPO) == 0
    assert daemon.look(REPO) == (None, None)
    assert daemon.status(REPO) == 1


def test_a_port_somebody_else_holds_is_refused_before_spawning(tmp_path,
                                                               monkeypatch):
    """Nothing is started, so there is nothing to leave behind either."""
    monkeypatch.setattr(daemon, "state_path",
                        lambda root: tmp_path / daemon.STATE_NAME)
    held = socket.socket()
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    port = held.getsockname()[1]
    try:
        opts = daemon.parse(["--port", str(port), "--no-open"], "start")
        daemon.settle(opts, None)
        # Something is listening, and it is not us: refused before spawning.
        assert daemon.start(REPO, opts) == 1
    finally:
        held.close()
    assert daemon.load(tmp_path) is None


def test_the_log_tail_is_what_a_failed_start_prints(tmp_path):
    (tmp_path / daemon.LOG_NAME).write_text(
        "\n".join(f"line {n}" for n in range(40)), encoding="utf-8")
    tail = daemon.log_tail(tmp_path, lines=3)
    assert tail.splitlines() == ["line 37", "line 38", "line 39"]


def test_a_missing_log_is_not_an_error(tmp_path):
    assert daemon.log_tail(tmp_path) == ""


@pytest.mark.parametrize("seconds, said", [
    (3, "3s"), (89, "89s"), (600, "10m"), (7200, "2h"), (300000, "3d")])
def test_uptime_is_said_the_way_a_person_would(seconds, said):
    assert daemon.since(time.time() - seconds) == said


def test_the_module_entry_point_is_the_cli():
    """`python -m crossglyph` is what a background start runs."""
    answer = subprocess.run([sys.executable, "-m", "crossglyph", "--version"],
                            capture_output=True, text=True, cwd=str(REPO))
    assert answer.returncode == 0
    assert "crossglyph" in answer.stdout


def test_the_workspace_is_reported_by_the_server_it_serves(tmp_path,
                                                           monkeypatch):
    """--fonts and $CROSSGLYPH_FONTS both move it, so status asks rather than
    reads the command back."""
    from fastapi.testclient import TestClient

    from crossglyph import fontbuild
    from crossglyph.preview import server

    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)
    with TestClient(server.app) as client:
        assert client.get("/update").json()["workspace"] == str(tmp_path)


def test_a_proxy_in_the_environment_is_not_consulted(monkeypatch):
    """http_proxy is for the internet, and every request here is to this
    machine. Left on, a company proxy answers for 127.0.0.1 and every command
    reports nothing running."""
    monkeypatch.setenv("http_proxy", "http://proxy.invalid:3128")
    assert urllib.request.getproxies().get("http"), "the trap is not armed"
    # urllib drops a ProxyHandler that maps nothing, which is the point: with
    # none installed there is nothing left to read the environment.
    assert not any(isinstance(handler, urllib.request.ProxyHandler)
                   and handler.proxies
                   for handler in daemon._OPENER.handlers)


def test_the_background_child_is_started_without_a_window():
    """DETACHED_PROCESS is the flag that reads right and shows a console: a
    console program launched by a process with no console gets a new one, and
    uv's venv python launches the real interpreter."""
    if os.name != "nt":
        assert daemon.DETACH == {"start_new_session": True}
        return
    flags = daemon.DETACH["creationflags"]
    assert flags & subprocess.CREATE_NO_WINDOW
    assert flags & subprocess.CREATE_NEW_PROCESS_GROUP
    assert not flags & subprocess.DETACHED_PROCESS


def test_a_port_held_by_something_that_is_not_ours_reads_as_taken():
    """create_connection rather than an AF_INET socket, so a preview on ::1
    is not read as a free port."""
    held = socket.socket()
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    port = held.getsockname()[1]
    try:
        assert daemon.taken("127.0.0.1", port)
        assert daemon.probe("127.0.0.1", port, timeout=0.5) is None
    finally:
        held.close()
    assert not daemon.taken("127.0.0.1", port)


def test_the_server_reports_its_own_pid():
    """A launcher, and uv's venv python on Windows, both hand off to a child,
    so the pid that was spawned is not always the one holding the port."""
    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    with TestClient(server.app) as client:
        assert client.get("/update").json()["pid"] == os.getpid()


@needs_wasm
def test_the_log_can_be_read_while_the_server_is_still_up(tmp_path,
                                                          monkeypatch):
    """Python block-buffers stdout to a file, so without PYTHONUNBUFFERED the
    log fills only at exit, which is the one moment nobody needs it."""
    monkeypatch.setenv("CROSSGLYPH_HOME", str(REPO))
    monkeypatch.setattr(daemon, "state_path",
                        lambda root: tmp_path / daemon.STATE_NAME)
    opts = daemon.parse(["--port", str(free_port()), "--no-open"], "start")
    daemon.settle(opts, None)
    assert daemon.start(REPO, opts) == 0
    try:
        assert "preview on" in daemon.log_tail(REPO)
    finally:
        daemon.stop(REPO)


def test_a_restart_with_nothing_running_is_a_start(tmp_path, monkeypatch):
    """Saying "no preview is running" first would read as a refusal."""
    started = []
    monkeypatch.setattr(daemon, "state_path",
                        lambda root: tmp_path / daemon.STATE_NAME)
    monkeypatch.setattr(daemon, "stop",
                        lambda root: pytest.fail("stopped nothing"))
    monkeypatch.setattr(daemon, "start",
                        lambda root, opts: started.append(opts) or 0)
    assert daemon.restart(tmp_path, daemon.parse([], "restart")) == 0
    assert started and started[0].port == daemon.DEFAULT_PORT

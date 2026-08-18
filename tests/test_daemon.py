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

from crossglyph import cli, daemon, render

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


def test_a_kill_that_did_not_free_the_port_keeps_the_state(tmp_path,
                                                           monkeypatch):
    """Something is still serving there, and dropping the state would leave no
    command able to name it: the next one would say nothing is running."""
    monkeypatch.setattr(daemon, "STOP_TIMEOUT", 0.0)
    monkeypatch.setattr(daemon.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(daemon, "alive", lambda pid: True)
    monkeypatch.setattr(daemon, "terminate", lambda pid: None)
    monkeypatch.setattr(daemon, "probe", lambda *a, **k: {"version": "0.1.2"})
    monkeypatch.setattr(daemon, "ask", lambda *a, **k: None)
    daemon.save(tmp_path, a_state(pid=4321))
    assert daemon.stop(tmp_path) == 1
    assert daemon.load(tmp_path).pid == 4321


def test_status_says_a_preview_is_wedged_rather_than_gone(tmp_path, capsys,
                                                          monkeypatch):
    monkeypatch.setattr(daemon, "alive", lambda pid: True)
    daemon.save(tmp_path, a_state(port=free_port()))
    assert daemon.status(tmp_path) == 1
    assert "not answering" in capsys.readouterr().out


# --- naming a preview by address ------------------------------------------


def test_a_port_on_its_own_keeps_the_running_previews_host():
    """`stop --port 8001` on an install serving 0.0.0.0 means that install's
    address, not a different one."""
    assert daemon.resolve(a_state(host="0.0.0.0"), None, 8001) == \
        ("0.0.0.0", 8001)
    assert daemon.resolve(None, None, None) == \
        (daemon.DEFAULT_HOST, daemon.DEFAULT_PORT)


def answering(monkeypatch, ports: set, **extra):
    """Make `probe` answer as a preview on these ports and nowhere else."""
    def probe(host, port, **_kwargs):
        return {"version": "0.1.2", "pid": 99, **extra} if port in ports \
            else None

    monkeypatch.setattr(daemon, "probe", probe)


def test_stop_can_name_a_preview_this_install_did_not_start(tmp_path, capsys,
                                                            monkeypatch):
    """A foreground `crossglyph preview`, or a second instance on another
    port, leaves no state file. Without an address there is nothing to name it
    by, and the only way left to stop it is finding its process by hand.
    """
    running = {8123}
    answering(monkeypatch, running)

    def shutdown(where, **_kwargs):
        running.clear()
        return {"stopping": True}

    monkeypatch.setattr(daemon, "ask", shutdown)
    daemon.save(tmp_path, a_state(port=8000, pid=4321))

    assert daemon.stop(tmp_path, port=8123) == 0

    assert "stopped the preview on http://127.0.0.1:8123." in \
        capsys.readouterr().out
    # The tracked preview is untouched. Forgetting it because something else
    # was stopped would leave no command able to name it again.
    assert daemon.load(tmp_path).port == 8000


def test_status_says_when_what_it_found_is_not_the_tracked_one(tmp_path,
                                                               capsys,
                                                               monkeypatch):
    answering(monkeypatch, {8123}, workspace="/w")

    assert daemon.status(tmp_path, port=8123) == 0

    said = capsys.readouterr().out
    assert "preview on http://127.0.0.1:8123" in said
    assert "pid 99, crossglyph 0.1.2" in said
    assert "fonts /w" in said
    assert "not the preview this install is tracking" in said
    # No uptime: the start time is kept in the state file and that preview
    # wrote none. And no log line, which would name a different process's.
    assert "up " not in said
    assert daemon.LOG_NAME not in said


def test_an_address_with_nothing_on_it_says_which_address(tmp_path, capsys):
    port = free_port()
    assert daemon.status(tmp_path, port=port) == 1
    assert daemon.stop(tmp_path, port=port) == 0
    said = capsys.readouterr().out
    assert said.count(f"no preview is running on http://127.0.0.1:{port}.") == 2


def test_stop_leaves_alone_something_that_is_not_a_preview(tmp_path, capsys,
                                                           monkeypatch):
    """The same refusal a start makes. A pid is not even known here, and a
    port being busy is no licence to kill what is holding it."""
    killed = []
    monkeypatch.setattr(daemon, "terminate", killed.append)
    held = socket.socket()
    held.bind(("127.0.0.1", 0))
    # Room for more than one: the probe that goes first leaves its connection
    # in the queue, and a backlog of 1 would refuse the check that follows.
    held.listen(8)
    port = held.getsockname()[1]
    try:
        assert daemon.stop(tmp_path, port=port) == 1
    finally:
        held.close()
    assert killed == []
    assert "not CrossGlyph is listening" in capsys.readouterr().err


def test_asking_about_another_address_does_not_sweep_the_tracked_state(
        tmp_path, monkeypatch):
    """The sweep is for a state whose process is gone. A question about 8123
    is no evidence at all about the process on 8000."""
    monkeypatch.setattr(daemon, "alive", lambda pid: False)
    answering(monkeypatch, set())
    daemon.save(tmp_path, a_state(port=8000))

    assert daemon.status(tmp_path, port=8123) == 1

    assert daemon.load(tmp_path) is not None


def test_naming_the_tracked_address_is_still_the_tracked_preview(tmp_path,
                                                                 monkeypatch):
    """`stop --port 8000` where 8000 is the one that was started forgets it,
    the way a bare stop does. Anything else would leave a state file naming a
    preview that has gone."""
    running = {8000}
    answering(monkeypatch, running)
    monkeypatch.setattr(daemon, "ask",
                        lambda where, **k: (running.clear(), {"ok": True})[1])
    daemon.save(tmp_path, a_state(port=8000))

    assert daemon.stop(tmp_path, port=8000) == 0

    assert daemon.load(tmp_path) is None


def test_a_pid_of_zero_is_never_signalled(monkeypatch):
    """0 stands in for a preview that reported no pid of its own, and on POSIX
    it is a signal to the caller's whole process group."""
    monkeypatch.setattr(daemon.os, "kill",
                        lambda *a: pytest.fail("signalled the process group"))
    daemon.terminate(0)


# --- what --help says -----------------------------------------------------


@pytest.mark.parametrize("name", cli.SERVICE)
def test_every_background_command_documents_its_address(name, capsys):
    with pytest.raises(SystemExit) as leaving:
        daemon.parse(["--help"], name)
    assert leaving.value.code == 0
    # Rewrapped: argparse breaks help text at whatever width it is given.
    said = " ".join(capsys.readouterr().out.split())
    assert "--host ADDRESS" in said and "--port PORT" in said
    assert daemon.ABOUT[name] in said
    for default in daemon.ADDRESS_DEFAULT[name]:
        assert f"(default: {default})" in said, default


@pytest.mark.parametrize("name", ("stop", "status"))
def test_stop_and_status_refuse_what_they_do_not_take(name, capsys):
    """They launch nothing, so a preview option here is a misspelling rather
    than something to pass on."""
    with pytest.raises(SystemExit) as leaving:
        daemon.parse(["--family", "notosans"], name)
    assert leaving.value.code == 2
    assert "--family" in capsys.readouterr().err


# --- a foreground preview on a port that is already held -------------------


def test_a_held_port_is_answered_before_anything_is_claimed(tmp_path,
                                                            monkeypatch):
    """`crossglyph start` then a bare `crossglyph` is the way into this, and
    uvicorn's own answer is a line of errno printed after "preview on ..." has
    already gone out for a preview that never started."""
    daemon.save(tmp_path, a_state(port=8000))
    monkeypatch.setattr(daemon, "taken", lambda host, port: port == 8000)
    answering(monkeypatch, {8000})

    said = daemon.busy(tmp_path, "127.0.0.1", 8000, "preview")

    assert said is not None
    assert "already running on http://127.0.0.1:8000" in said
    # The tracked one, so a bare stop is what stops it.
    assert "`crossglyph stop`" in said
    # And a free port to put a second one on, found rather than guessed.
    assert "`crossglyph preview --port 8001`" in said


def test_a_preview_on_a_port_this_install_did_not_start_is_named_by_port(
        tmp_path, monkeypatch):
    monkeypatch.setattr(daemon, "taken", lambda host, port: port == 8001)
    answering(monkeypatch, {8001})

    assert "`crossglyph stop --port 8001`" in \
        daemon.busy(tmp_path, "127.0.0.1", 8001, "preview")


def test_the_command_that_could_not_serve_is_the_one_offered(tmp_path,
                                                             monkeypatch):
    """`start` says start and `preview` says preview: the suggestion is a line
    to run, and the other one backgrounds itself or does not."""
    monkeypatch.setattr(daemon, "taken", lambda host, port: port == 8000)
    answering(monkeypatch, {8000})

    assert "`crossglyph start --port 8001`" in \
        daemon.busy(tmp_path, "127.0.0.1", 8000, "start")


def test_something_else_on_the_port_is_said_to_be_something_else(tmp_path,
                                                                 monkeypatch):
    monkeypatch.setattr(daemon, "taken", lambda host, port: port == 8000)
    monkeypatch.setattr(daemon, "probe", lambda host, port, **k: None)

    said = daemon.busy(tmp_path, "127.0.0.1", 8000, "preview")

    assert "not CrossGlyph is listening" in said
    assert "crossglyph stop" not in said


def test_a_free_port_is_not_answered_at_all(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon, "taken", lambda host, port: False)
    assert daemon.busy(tmp_path, "127.0.0.1", 8000, "preview") is None


def test_the_suggested_port_is_one_nothing_holds(tmp_path, monkeypatch):
    """Suggesting the next number would send you into the next held port on a
    machine running several of these."""
    monkeypatch.setattr(daemon, "taken",
                        lambda host, port: port in (8000, 8001, 8002))
    answering(monkeypatch, {8000, 8001, 8002})

    assert "--port 8003`" in daemon.busy(tmp_path, "127.0.0.1", 8000,
                                         "preview")


def test_a_machine_with_no_free_port_still_says_what_to_do(tmp_path,
                                                           monkeypatch):
    """The offer is dropped rather than the whole answer: what is on the port
    is still worth knowing when there is nowhere to put a second one."""
    monkeypatch.setattr(daemon, "taken", lambda host, port: True)
    monkeypatch.setattr(daemon, "probe", lambda host, port, **k: None)

    said = daemon.busy(tmp_path, "127.0.0.1", 8000, "preview")

    assert "not CrossGlyph is listening" in said
    assert "Pass --port" in said


def test_the_last_port_has_nothing_above_it():
    """The search walks upwards, so 65535 is where it runs out."""
    assert daemon.spare_port("127.0.0.1", 65535) is None


def test_a_start_onto_an_untracked_preview_does_not_call_it_a_stranger(
        tmp_path, capsys, monkeypatch):
    """It is another CrossGlyph, and saying otherwise sends you looking for
    somebody else's server on a port your own tool is holding."""
    monkeypatch.setattr(daemon, "taken", lambda host, port: port == 8000)
    answering(monkeypatch, {8000})
    opts = daemon.parse(["--port", "8000", "--no-open"], "start")
    daemon.settle(opts, None)

    assert daemon.start(tmp_path, opts) == 1

    said = capsys.readouterr().err
    assert "a preview is already running on http://127.0.0.1:8000" in said
    assert "`crossglyph stop --port 8000`" in said
    assert "not CrossGlyph" not in said


def test_the_address_a_preview_answers_on_is_the_one_it_was_started_on(
        tmp_path, monkeypatch):
    """A start on 0.0.0.0 is the preview answering on the loopback, so
    stopping it by the address it answers on forgets the state naming it."""
    assert daemon.same_address(("0.0.0.0", 8000), ("127.0.0.1", 8000))
    assert not daemon.same_address(("192.0.2.1", 8000), ("127.0.0.1", 8000))

    running = {8000}
    answering(monkeypatch, running)
    monkeypatch.setattr(daemon, "ask",
                        lambda where, **k: (running.clear(), {"ok": True})[1])
    daemon.save(tmp_path, a_state(host="0.0.0.0", port=8000))

    assert daemon.stop(tmp_path, host="127.0.0.1", port=8000) == 0

    assert daemon.load(tmp_path) is None


def test_the_foreground_preview_says_what_its_port_defaults_to(capsys):
    from crossglyph.preview import server

    with pytest.raises(SystemExit):
        server.main(["--help"])
    said = " ".join(capsys.readouterr().out.split())
    assert "--port PORT port to serve on (default: 8000)" in said
    assert "$CROSSGLYPH_HOST" in said


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
    """An ordinary first start goes through the launcher that calls uv."""
    a_release(tmp_path, "0.2.0", venv=False)
    assert str(tmp_path / daemon.LAUNCHER) in daemon.command(tmp_path)


def test_update_handoff_uses_the_targets_private_python(tmp_path):
    """The root launcher may be the batch file waiting on the old process."""
    python = a_release(tmp_path, "0.2.0", venv=True)
    assert daemon.handoff_command(tmp_path, "0.2.0") == [
        str(python), "-m", "crossglyph", "restart", "--no-open"]


def test_update_handoff_bootstraps_an_unopened_release_from_its_wrapper(
        tmp_path):
    a_release(tmp_path, "0.2.0", venv=False)
    uv = tmp_path / "versions" / "0.2.0" / "tools" / "uv.cmd"
    uv.parent.mkdir()
    uv.write_text("", encoding="utf-8")

    command = daemon.handoff_command(tmp_path, "0.2.0")

    assert command is not None
    assert str(tmp_path / daemon.LAUNCHER) not in command
    if os.name == "nt":
        assert isinstance(command, str)
        assert f"%{daemon.HANDOFF_UV_ENV}%" in command
        assert f"%{daemon.HANDOFF_PROJECT_ENV}%" in command
    else:
        assert command[:2] == ["/bin/sh", str(uv)]
        assert command[-4:] == [
            str(tmp_path / "versions" / "0.2.0"),
            "crossglyph", "restart", "--no-open"]


def test_handoff_preserves_the_running_preview_for_restart(
        tmp_path, monkeypatch):
    a_release(tmp_path, "0.2.0", venv=True)
    state = a_state(port=8123, rest=["--family", "notosans"])
    launched = {}

    def popen(command, **options):
        launched.update(command=command, options=options)
        return object()

    monkeypatch.setattr(daemon.subprocess, "Popen", popen)
    daemon.handoff(tmp_path, "0.2.0", state)

    assert daemon.load(tmp_path) == state
    assert launched["command"] == daemon.handoff_command(tmp_path, "0.2.0")
    assert launched["options"]["cwd"] == str(tmp_path)
    assert launched["options"]["env"]["CROSSGLYPH_HOME"] == str(tmp_path)
    assert pathlib.Path(launched["options"]["stdout"].name) == \
        tmp_path / daemon.LOG_NAME
    assert launched["options"]["stderr"] is subprocess.STDOUT
    if os.name == "nt":
        assert launched["options"]["env"][daemon.HANDOFF_UV_ENV].endswith(
            "tools\\uv.cmd")
        assert launched["options"]["env"][daemon.HANDOFF_PROJECT_ENV] == \
            str(tmp_path / "versions" / "0.2.0")


def test_a_handoff_that_cannot_start_leaves_the_failure_in_the_log(
        tmp_path, monkeypatch):
    a_release(tmp_path, "0.2.0", venv=True)

    def refused(*_args, **_kwargs):
        raise OSError("process creation was refused")

    monkeypatch.setattr(daemon.subprocess, "Popen", refused)

    assert daemon.handoff(tmp_path, "0.2.0", a_state()) is None
    log = (tmp_path / daemon.LOG_NAME).read_text(encoding="utf-8")
    assert "process creation was refused" in log


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe only")
def test_windows_handoff_preserves_every_valid_path_character(tmp_path):
    root = tmp_path / "install&()^%PATH%! space"
    a_release(root, "0.2.0", venv=False)
    uv = root / "versions" / "0.2.0" / "tools" / "uv.cmd"
    uv.parent.mkdir()
    marker = tmp_path / "handoff-ran.txt"
    uv.write_bytes(
        f'@echo off\r\n> "{marker}" echo %*\r\necho HANDOFF_OK\r\n'.encode())

    process = daemon.handoff(root, "0.2.0", a_state())

    assert process is not None
    assert process.wait(timeout=10) == 0
    assert marker.read_text(encoding="utf-8").strip().endswith(
        "crossglyph restart --no-open")
    assert "HANDOFF_OK" in (
        root / daemon.LOG_NAME).read_text(encoding="utf-8")


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
def test_a_real_server_starts_reports_and_stops(tmp_path, capsys, monkeypatch):
    """The one test that spawns the thing, since that is the feature.

    Runs against the checkout rather than a release, so `command()` resolves
    to this interpreter and the child is the code under test.

    The root is this test's own directory rather than the checkout, because
    the root is where the log is written and `spawn` truncates it: two tests
    sharing one would have each emptying the other's log mid-run. The
    workspace the server reads is CROSSGLYPH_HOME, which stays the checkout.
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

    assert daemon.start(tmp_path, opts) == 0
    said = capsys.readouterr().out
    try:
        state, body = daemon.look(tmp_path)
        assert state.port == port
        assert body["version"]
        # The server's own pid, not the one that was spawned. On Windows uv's
        # venv python is a trampoline, so those differ and killing the wrong
        # one would leave the port held.
        assert state.pid == body["pid"] and daemon.alive(state.pid)
        # And the one the start printed, or `status` names a different process
        # a moment later and neither line can be trusted.
        assert f"pid {state.pid}" in said
        assert daemon.status(tmp_path) == 0
    finally:
        assert daemon.stop(tmp_path) == 0
    assert daemon.look(tmp_path) == (None, None)
    assert daemon.status(tmp_path) == 1


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
    log fills only at exit, which is the one moment nobody needs it.

    Its own root, for the reason the test above gives: the log this reads is
    the one `spawn` truncates, so sharing a root with another spawning test
    means reading an empty file whenever the two overlap.
    """
    monkeypatch.setenv("CROSSGLYPH_HOME", str(REPO))
    monkeypatch.setattr(daemon, "state_path",
                        lambda root: tmp_path / daemon.STATE_NAME)
    opts = daemon.parse(["--port", str(free_port()), "--no-open"], "start")
    daemon.settle(opts, None)
    assert daemon.start(tmp_path, opts) == 0
    try:
        assert "preview on" in daemon.log_tail(tmp_path)
    finally:
        daemon.stop(tmp_path)


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


@pytest.mark.parametrize("name", ("start", "stop", "status", "restart"))
def test_background_commands_are_refused_in_a_container(
        name, tmp_path, monkeypatch, capsys):
    """Docker owns the process lifetime, so its app writes no native daemon
    state and never detaches a child from the container's foreground process."""
    monkeypatch.setattr(daemon.install, "root", lambda: tmp_path)
    monkeypatch.setattr(
        daemon.install, "detect",
        lambda root: daemon.install.CONTAINER)

    assert daemon.main(name, []) == 2
    assert "Docker or Compose" in capsys.readouterr().err
    assert not any(tmp_path.iterdir())

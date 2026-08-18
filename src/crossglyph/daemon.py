"""Run the preview in the background, and say what is running.

Three things do all of it: a JSON state file beside the update state, a log
the detached child writes, and the server's own `/shutdown`. None of them is
the launcher, which is what keeps this working for an install updated by any
route: nothing here edits a script, and the one case that has to call one
calls it as it found it.

`crossglyph preview` is unchanged and still the foreground command. This is
for working on fonts without a terminal window in the way.
"""
from __future__ import annotations

import argparse
import dataclasses
import functools
import json
import os
import pathlib
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

from . import install, layout, version

#: Beside .update-state.json, and for the same reason: the install root is the
#: one directory that both survives an update and is not the workspace.
STATE_NAME = ".preview-state.json"

#: Where the detached child's output goes. Not a dotfile, since it is the
#: first thing to read when a start fails and it has to be findable. Truncated
#: at each start rather than rotated: what went wrong is what just happened.
LOG_NAME = "preview.log"

#: How long to wait for a page before giving up. Generous because the slow
#: case is real: a start that lands on a version whose dependencies have never
#: been synced pays for that once, and it is the worst moment to give up.
READY_TIMEOUT = 90.0
POLL = 0.25

#: How long a stop waits for the server to go before terminating it.
STOP_TIMEOUT = 10.0

VENV_PYTHON = pathlib.Path(".venv") / (
    "Scripts/python.exe" if os.name == "nt" else "bin/python")

LAUNCHER = "crossglyph.cmd" if os.name == "nt" else "crossglyph.sh"
HANDOFF_UV_ENV = "CROSSGLYPH_HANDOFF_UV"
HANDOFF_PROJECT_ENV = "CROSSGLYPH_HANDOFF_PROJECT"


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


#: What --host and --port fall back to, per command, for its own --help.
ADDRESS_DEFAULT = {
    "start": (DEFAULT_HOST, str(DEFAULT_PORT)),
    "restart": ("the address of the preview it replaces",
                "the port of the preview it replaces"),
    "stop": ("the one this install started",) * 2,
    "status": ("the one this install started",) * 2,
}

#: One line each, for the same.
ABOUT = {
    "start": "Run the preview in the background and open a browser on it.",
    "stop": "Stop a background preview.",
    "status": "Say which preview is running, and what it is on.",
    "restart": "Stop the preview and start it again, on whichever version is "
               "current by then.",
}


@dataclasses.dataclass
class State:
    """What a background start left behind, so the other commands can find it."""
    #: The process serving the page, which is not always the one that was
    #: spawned: the server reports its own, and a launcher or a trampoline in
    #: between makes those differ.
    pid: int
    host: str
    port: int
    #: The preview options it was given beyond the address, `--family` and the
    #: rest, which a restart replays.
    rest: list[str]
    version: str
    started: float


def state_path(root: pathlib.Path) -> pathlib.Path:
    return root / STATE_NAME


def load(root: pathlib.Path) -> State | None:
    """The recorded state, or None when there is none to read.

    A file that cannot be parsed counts as none. It is a note this tool wrote
    to itself, so the only thing to do with a broken one is write it again.
    """
    try:
        body = json.loads(state_path(root).read_text(encoding="utf-8"))
        return State(**body)
    except (OSError, ValueError, TypeError):
        return None


def save(root: pathlib.Path, state: State) -> None:
    state_path(root).write_text(json.dumps(dataclasses.asdict(state)),
                                encoding="utf-8")


def clear(root: pathlib.Path) -> None:
    state_path(root).unlink(missing_ok=True)


def browsable(host: str) -> str:
    """The address to connect to, which is not always the one bound.

    `0.0.0.0` and `::` mean every interface, and neither is somewhere a
    browser or a probe can go.
    """
    return {"0.0.0.0": "127.0.0.1", "::": "::1", "": "127.0.0.1"}.get(host, host)


def url(host: str, port: int) -> str:
    shown = browsable(host)
    return f"http://[{shown}]:{port}" if ":" in shown else f"http://{shown}:{port}"


def same_address(one: tuple[str, int], two: tuple[str, int]) -> bool:
    """Whether two addresses reach the same server.

    Through `browsable`, so 0.0.0.0 and 127.0.0.1 are one target: a preview
    started on every interface is the preview answering on the loopback, and
    stopping it by the address it answers on has to forget the state naming it.
    """
    return (browsable(one[0]), one[1]) == (browsable(two[0]), two[1])


#: Every request here is to this machine, and a proxy has no business in it.
#: urlopen would otherwise read http_proxy from the environment and send a
#: shutdown for 127.0.0.1 to whatever a company network put there, which
#: fails as "nothing is running" on the one machine where something is.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def ask(where: str, method: str = "GET", timeout: float = 2.0) -> dict | None:
    """One request to a preview, or None if it did not answer as one.

    Anything that is not a JSON object naming a version is not a CrossGlyph,
    whatever else it may be serving on that port.
    """
    request = urllib.request.Request(where, method=method,
                                     data=b"" if method == "POST" else None)
    try:
        with _OPENER.open(request, timeout=timeout) as answer:
            body = json.loads(answer.read())
    except (OSError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def probe(host: str, port: int, timeout: float = 2.0) -> dict | None:
    """What a CrossGlyph on this port says about itself, or None.

    `GET /update` is the identity check and the version report at once: the
    page asks for it on every load, it names the version the process is
    actually running, and nothing else serves it.
    """
    body = ask(f"{url(host, port)}/update", timeout=timeout)
    return body if body and "version" in body else None


def taken(host: str, port: int) -> bool:
    """Whether anything at all is listening, ours or not."""
    try:
        # create_connection rather than a socket of our own, since it resolves
        # the address family: a preview bound to ::1 is not reachable from an
        # AF_INET socket, and reading that as a free port would be a start
        # that fails with the port already in use.
        with socket.create_connection((browsable(host), port), timeout=0.5):
            return True
    except OSError:
        return False


QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259


@functools.cache
def _kernel32():
    """kernel32, with the signatures of what is called on it spelled out.

    Not `ctypes.windll.kernel32`, which is one object shared by everything in
    the process: a restype set on it is set for every other caller too. And a
    restype has to be set, because the default is c_int while a HANDLE is a
    pointer -- an opened handle narrowed into an int and widened back out of
    one is not certain to be the handle that was opened.
    """
    import ctypes

    lib = ctypes.WinDLL("kernel32", use_last_error=True)
    lib.OpenProcess.restype = ctypes.c_void_p
    lib.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
    lib.GetExitCodeProcess.argtypes = (ctypes.c_void_p,
                                       ctypes.POINTER(ctypes.c_ulong))
    lib.CloseHandle.argtypes = (ctypes.c_void_p,)
    return lib


def alive(pid: int) -> bool:
    """Whether a pid is a live process. Not whether it is ours."""
    if pid <= 0:
        return False
    if os.name == "nt":
        # Not os.kill(pid, 0): on Windows that is not a liveness question at
        # all, since anything but CTRL_C_EVENT and CTRL_BREAK_EVENT goes to
        # TerminateProcess. Asking whether a process is alive would kill it.
        import ctypes

        kernel32 = _kernel32()
        handle = kernel32.OpenProcess(QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        try:
            got = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        finally:
            kernel32.CloseHandle(handle)
        return bool(got) and code.value == STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True                     # somebody else's, so it does exist
    except OSError:
        return False
    return True


def command(root: pathlib.Path) -> list[str]:
    """What starts the current version during an ordinary background start.

    An environment that already exists is the shortest path and avoids the
    console-script shim, which an update may replace while it is running. A
    version that has never run normally goes through the root launcher so uv
    can create that environment. The update handoff below deliberately uses
    the new version's own uv wrapper instead: a foreground Windows launcher
    may still be paused around the old Python process.
    """
    name = layout.current(root)
    if name:
        python = layout.version_dir(root, name) / VENV_PYTHON
        if python.is_file():
            return [str(python), "-m", "crossglyph"]
        launcher = root / LAUNCHER
        if launcher.is_file():
            # cmd.exe, because CreateProcess cannot run a .cmd itself.
            return ["cmd", "/c", str(launcher)] if os.name == "nt" \
                else [str(launcher)]
    return [sys.executable, "-m", "crossglyph"]


def handoff_command(root: pathlib.Path, target: str) -> list[str] | str | None:
    """Bootstrap `target` without touching a root launcher that may be live."""
    directory = layout.version_dir(root, target)
    python = directory / VENV_PYTHON
    if python.is_file():
        return [str(python), "-m", "crossglyph", "restart", "--no-open"]
    uv = directory / "tools" / "uv.cmd"
    if not uv.is_file():
        return None
    if os.name == "nt":
        # Paths arrive through the environment rather than cmd.exe's command
        # text. Expansion happens inside quotes and is not parsed a second
        # time, so valid path characters such as &, ^ and % stay characters.
        return (
            'cmd.exe /d /s /v:off /c '
            f'""%{HANDOFF_UV_ENV}%" run --project '
            f'"%{HANDOFF_PROJECT_ENV}%" crossglyph restart --no-open"')
    return ["/bin/sh", str(uv), "run", "--project", str(directory),
            "crossglyph", "restart", "--no-open"]


#: What keeps the child alive after this command returns, and off the screen.
#:
#: On Windows that is CREATE_NO_WINDOW, and not DETACHED_PROCESS, which is the
#: flag that sounds right and puts a console window on the screen. Detached
#: means no console at all, and a console program started by a process that
#: has none is given a brand new one: uv's venv python is a trampoline that
#: launches the real interpreter, so the window turns up for the grandchild.
#: A hidden console is inherited, and nothing in the tree draws anything.
DETACH: dict = {"creationflags": (subprocess.CREATE_NO_WINDOW
                                  | subprocess.CREATE_NEW_PROCESS_GROUP)} \
    if os.name == "nt" else {"start_new_session": True}


def handoff(root: pathlib.Path, target: str,
            state: State) -> subprocess.Popen | None:
    """Let the installed version stop this preview and replace it.

    The root launcher's staged copy stays beside it. On Windows the launcher
    that started a foreground preview is a cmd.exe still waiting for Python;
    replacing its script would make it resume at the same byte offset in
    different bytes. The target's private wrapper is new and cannot be open.
    It creates the target environment before `restart` asks this server to
    stop, after which daemon.start finds that environment and bypasses the
    root launcher again.
    """
    command = handoff_command(root, target)
    if command is None:
        return None
    save(root, state)
    directory = layout.version_dir(root, target)
    env = dict(os.environ, PYTHONUNBUFFERED="1",
               CROSSGLYPH_HOME=str(root))
    env.setdefault("CROSSGLYPH_FONTS", str(root / "fonts"))
    if os.name == "nt":
        env[HANDOFF_UV_ENV] = str(directory / "tools" / "uv.cmd")
        env[HANDOFF_PROJECT_ENV] = str(directory)
    log = root / LOG_NAME
    with log.open("ab") as output:
        output.write(
            f"\nupdate restart: starting CrossGlyph {target}\n".encode())
        output.flush()
        try:
            return subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=output,
                stderr=subprocess.STDOUT, cwd=str(root), env=env,
                close_fds=True, **DETACH)
        except OSError as exc:
            output.write(f"update restart could not start: {exc}\n".encode())
            return None


def spawn(root: pathlib.Path, argv: list[str]) -> subprocess.Popen:
    """The preview, detached from this terminal and writing to the log."""
    # Unbuffered, or the log is empty for as long as it would be useful:
    # Python block-buffers stdout when it is a file, so a server that is up
    # and misbehaving writes nothing until it exits. In the environment
    # rather than as -u, since the launcher path runs a shell script.
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    # The handle is closed as soon as the child has it: the child holds its
    # own descriptor, and a copy left open here would keep the file locked on
    # Windows long after this command has finished.
    with (root / LOG_NAME).open("wb") as handle:
        return subprocess.Popen([*command(root), "preview", *argv],
                                stdin=subprocess.DEVNULL, stdout=handle,
                                stderr=subprocess.STDOUT, cwd=str(root),
                                env=env, close_fds=True, **DETACH)


def log_tail(root: pathlib.Path, lines: int = 15) -> str:
    try:
        text = (root / LOG_NAME).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


#: When to change unit, and to what. An hour and a half of minutes and two
#: days of hours, so the number stays small without the unit changing at the
#: moment it would still have been the useful one.
UNITS = ((172800, 86400, "d"), (5400, 3600, "h"), (90, 60, "m"))


def since(started: float) -> str:
    """How long it has been up, said the way a person would."""
    seconds = max(0, int(time.time() - started))
    for at, size, unit in UNITS:
        if seconds >= at:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


@dataclasses.dataclass
class Found:
    """The preview a command is to act on.

    Either the one the state file names or one named by address. The
    difference matters in one place: only a tracked preview has a state file
    to forget when it stops.
    """
    host: str
    port: int
    #: The process serving it: the state file's for a tracked preview, and the
    #: server's own report for one found by address, which is the only pid
    #: anything here could have for that one.
    pid: int
    #: What it says about itself, or None for a tracked preview that has
    #: stopped answering. One found by address is never that: an address which
    #: does not answer is not a preview anything here can name.
    body: dict | None
    #: The state file's record, when this is the preview it names.
    state: State | None

    @property
    def where(self) -> str:
        return url(self.host, self.port)


def resolve(state: State | None, host: str | None,
            port: int | None) -> tuple[str, int]:
    """The address a command was pointed at, filling in what it did not name.

    A port on its own keeps the running preview's host, so `stop --port 8001`
    means what it looks like on an install serving 0.0.0.0.
    """
    return (host if host is not None else state.host if state else DEFAULT_HOST,
            port if port is not None else state.port if state else DEFAULT_PORT)


def find(root: pathlib.Path, state: State | None, host: str | None,
         port: int | None) -> Found | None:
    """The preview to act on, or None when nothing there answers as one.

    With no address that is the one the state file names, and there are three
    answers rather than two: no state at all, a state whose server answers,
    and a state whose server does not while its process is still there. That
    last one is a wedged preview, and calling it "not running" would leave
    something holding the port that no command of ours would ever stop. A
    state whose process is gone is swept here instead, so a server that was
    killed never confuses the next command.

    With an address it is whatever answers there. A foreground `crossglyph
    preview`, or a second instance on another port, is a preview these
    commands should be able to name, and neither leaves a state file to be
    found in.
    """
    where = resolve(state, host, port)
    if state is not None and same_address((state.host, state.port), where):
        body = probe(*where)
        if body is None and not alive(state.pid):
            clear(root)
            return None
        return Found(*where, state.pid, body, state)
    if host is None and port is None:
        return None
    body = probe(*where)
    return None if body is None else Found(*where, body.get("pid") or 0,
                                           body, None)


def look(root: pathlib.Path) -> tuple[State | None, dict | None]:
    """The tracked preview and what it has to say, for a start to check."""
    found = find(root, load(root), None, None)
    return (None, None) if found is None else (found.state, found.body)


def forget(root: pathlib.Path, found: Found) -> None:
    """Drop the state file, when what was stopped is what it names."""
    if found.state is not None:
        clear(root)


def stranger(where: tuple[str, int]) -> str:
    """A port held by a server that is not one of ours. Said the same way by
    everything that finds one, since it is the same fact each time."""
    return f"something that is not CrossGlyph is listening on {url(*where)}."


def missing(where: tuple[str, int], named: bool) -> tuple[str, bool]:
    """What to say about an address holding no preview of ours, and whether
    that is a complaint.

    Something else listening there is one: a command aimed at a port somebody
    else's server holds did not do what it was asked, and saying "no preview
    is running" would read as though there were nothing to explain.
    """
    if named and taken(*where):
        return stranger(where), True
    return (f"no preview is running{f' on {url(*where)}' if named else ''}.",
            False)


def spare_port(host: str, port: int, tries: int = 20) -> int | None:
    """The first port above this one that nothing is listening on."""
    for offset in range(1, tries + 1):
        if port + offset > 65535:
            break
        if not taken(host, port + offset):
            return port + offset
    return None


def busy(root: pathlib.Path, host: str, port: int,
         command: str) -> str | None:
    """Why this address cannot be served on, and what to do about it, or None.

    Asked before anything is claimed. Left to uvicorn it is a line of errno
    with the word bind in it, arriving after the foreground preview has
    already printed "preview on ..." for a preview that never started. Asking
    first also lets the answer name what is there, which is nearly always
    another CrossGlyph and most often this install's own: calling that
    "something that is not CrossGlyph" sends a reader looking for a stranger's
    server.
    """
    if not taken(host, port):
        return None
    where = (host, port)
    spare = spare_port(host, port)
    instead = (f"Serve one beside it with `crossglyph {command} --port "
               f"{spare}`." if spare else
               "Pass --port to serve on another port.")
    if probe(host, port) is None:
        return f"{stranger(where)}\n{instead}"
    state = load(root)
    tracked = state is not None and same_address((state.host, state.port),
                                                 where)
    ending = "crossglyph stop" if tracked else f"crossglyph stop --port {port}"
    return (f"a preview is already running on {url(*where)}. Open that one, "
            f"or stop it with `{ending}`.\n{instead}")


def announce(said: str, where: str, pid: int, running: str,
             open_browser: bool) -> int:
    """Say what is serving and open a browser on it. Always a success."""
    print(f"{said} {where}  (pid {pid}, crossglyph {running})")
    if open_browser:
        webbrowser.open(where)
    return 0


def start(root: pathlib.Path, opts: argparse.Namespace) -> int:
    """Start the preview in the background and wait until it draws.

    Waiting is the point: a start that returns before the page answers can
    only report that a process was created, which is not the question. The
    browser opens after the page is there, so a failure is a failure on this
    terminal rather than an error page in a new tab.
    """
    state, body = look(root)
    if state is not None:
        running = url(state.host, state.port)
        if body is None:
            print(f"a preview on {running} (pid {state.pid}) is not "
                  f"answering. Stop it first.", file=sys.stderr)
            return 1
        if (state.host, state.port) != (opts.host, opts.port):
            print(f"a preview is already running on {running}. Stop it "
                  f"first, or ask for that address.", file=sys.stderr)
            return 1
        # Already what was asked for, so this is the answer to the question
        # rather than an error: say where it is and open it.
        return announce("preview already on", running, state.pid,
                        body["version"], opts.open_browser)
    held = busy(root, opts.host, opts.port, "start")
    if held is not None:
        print(held, file=sys.stderr)
        return 1

    where = url(opts.host, opts.port)
    argv = ["--no-open", "--host", opts.host, "--port", str(opts.port),
            *opts.rest]
    child = spawn(root, argv)

    def record(running_version: str, pid: int) -> None:
        save(root, State(pid=pid, host=opts.host, port=opts.port,
                         rest=list(opts.rest), version=running_version,
                         started=time.time()))

    record(version.installed(), child.pid)
    deadline = time.monotonic() + READY_TIMEOUT
    while time.monotonic() < deadline:
        body = probe(opts.host, opts.port, timeout=1.0)
        if body is not None:
            # What the server says about itself, rather than what this process
            # knows: after an update the versions differ, and the pid differs
            # whenever something stood between the spawn and the server. The
            # same pid is printed as is recorded, or `status` would name a
            # different process a moment later.
            pid = body.get("pid") or child.pid
            record(body["version"], pid)
            return announce("preview on", where, pid, body["version"],
                            opts.open_browser)
        if child.poll() is not None:
            clear(root)
            print(f"the preview exited at once. {root / LOG_NAME} ends:\n"
                  f"{log_tail(root)}", file=sys.stderr)
            return 1
        time.sleep(POLL)

    print(f"the preview did not answer within {READY_TIMEOUT:.0f}s. It may "
          f"still be starting; see {root / LOG_NAME}.", file=sys.stderr)
    return 1


def terminate(pid: int) -> None:
    """The answer to a server that will not stop being asked.

    A pid the operating system has since given to something else would be a
    stranger to kill, which is why nothing here reaches this without having
    asked politely first and waited: the window is between a server going
    unresponsive and this command running, and it is the same window every
    tool with a pid file lives with.

    A preview found by address reports its own pid, and 0 is what stands in
    for one that reported none. That is not a process: on POSIX it is the
    caller's whole process group, so it is refused here rather than at every
    call site.
    """
    if pid <= 0:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def stop(root: pathlib.Path, host: str | None = None,
         port: int | None = None) -> int:
    """Stop a background preview, gracefully if it will have it.

    The endpoint rather than a signal, because Windows has neither: a
    detached child has no console for a Ctrl+Break to arrive through, and
    everything else there is a kill. Asking works the same way on all three
    platforms, and the kill is what answers a server that has stopped
    listening.

    An address names which preview, for the ones this install did not start
    and has no state file for. Only a tracked preview is forgotten here:
    stopping something else must leave the running one nameable.
    """
    state = load(root)
    where = resolve(state, host, port)
    found = find(root, state, host, port)
    if found is None:
        said, wrong = missing(where, host is not None or port is not None)
        print(said, file=sys.stderr if wrong else sys.stdout)
        return 1 if wrong else 0
    if found.body is None:
        # Alive but not answering, which is the one case a stop must not walk
        # away from: nothing else would ever free that port.
        terminate(found.pid)
        forget(root, found)
        print(f"the preview on {found.where} was not answering. Killed pid "
              f"{found.pid}.")
        return 0

    asked = ask(f"{found.where}/shutdown", method="POST",
                timeout=5.0) is not None
    deadline = time.monotonic() + STOP_TIMEOUT
    while time.monotonic() < deadline:
        if probe(found.host, found.port, timeout=1.0) is None:
            forget(root, found)
            print(f"stopped the preview on {found.where}.")
            return 0
        time.sleep(POLL)

    terminate(found.pid)
    time.sleep(1.0)
    if probe(found.host, found.port, timeout=1.0) is not None:
        # The state stays: something is still serving on that port, and
        # forgetting it here would leave no command able to name it again.
        print(f"the preview on {found.where} did not stop. Its pid is "
              f"{found.pid}.", file=sys.stderr)
        return 1
    forget(root, found)
    reason = "did not stop when asked" if asked else "would not take the ask"
    print(f"stopped the preview on {found.where}, which {reason}.")
    return 0


def status(root: pathlib.Path, host: str | None = None,
           port: int | None = None) -> int:
    """Say what is running. Exit 0 when something is, 1 when nothing is.

    An address asks about that preview instead of the tracked one, which is
    the only way to see a foreground `crossglyph preview` or a second
    instance: neither writes a state file to be read here.
    """
    state = load(root)
    where = resolve(state, host, port)
    found = find(root, state, host, port)
    if found is None:
        print(missing(where, host is not None or port is not None)[0])
        return 1
    if found.body is None:
        print(f"a preview on {found.where} (pid {found.pid}) is not "
              f"answering. `crossglyph stop` will kill it.")
        print(f"  log {root / LOG_NAME}")
        return 1
    print(f"preview on {found.where}")
    # No uptime for one found by address: the state file is where a start time
    # is kept, and that preview left none.
    up = f", up {since(found.state.started)}" if found.state else ""
    print(f"  pid {found.pid}, crossglyph {found.body['version']}{up}")
    if found.body.get("workspace"):
        print(f"  fonts {found.body['workspace']}")
    if found.body.get("pending"):
        print(f"  {found.body['pending']} is installed; a restart would run it")
    if found.state is None:
        print("  not the preview this install is tracking, so a bare stop or "
              "restart leaves it alone")
    else:
        # The log belongs to the tracked start. Naming it under another
        # preview would send a reader to a file about a different process.
        print(f"  log {root / LOG_NAME}")
    return 0


def restart(root: pathlib.Path, opts: argparse.Namespace) -> int:
    """Stop and start, on whichever version is current by then.

    Anything it is not told, it takes from the start it is replacing, so a
    bare `restart` comes back on the same address showing the same family and
    `restart --port 9000` moves only the port. Whether to open a browser is
    not one of those: that is a fact about this command, not about the server.
    """
    state = load(root)
    settle(opts, state)
    # Only stop what is there. A restart with nothing running is a start, and
    # saying "no preview is running" first would read as a refusal.
    if state is not None:
        code = stop(root)
        if code:
            return code
    return start(root, opts)


def settle(opts: argparse.Namespace, state: State | None) -> None:
    """Fill in what was not asked for, from the last start or the defaults."""
    if opts.host is None:
        opts.host = state.host if state else DEFAULT_HOST
    if opts.port is None:
        opts.port = state.port if state else DEFAULT_PORT
    if not opts.rest and state:
        opts.rest = list(state.rest)


def parse(argv: list[str], name: str) -> argparse.Namespace:
    """The options a background command takes.

    A launch takes the preview's as well: everything `start` and `restart` do
    not name themselves is passed through, so `--family`, `--font` and the
    rest mean what they mean in the foreground. `stop` and `status` launch
    nothing, so they take an address and refuse anything else rather than
    swallow a misspelling.

    The address has no default here: unset is what lets a restart tell "leave
    it as it was" apart from "put it on 8000".
    """
    launching = name in ("start", "restart")
    parser = argparse.ArgumentParser(
        prog=f"crossglyph {name}", description=ABOUT[name],
        epilog=("Any other option goes to the preview, so --family, --font, "
                "--fonts and --size mean what they mean in `crossglyph "
                "preview`." if launching else None))
    doing = "to serve on" if launching else "of the preview to act on"
    where, which = ADDRESS_DEFAULT[name]
    parser.add_argument("--host", default=None, metavar="ADDRESS",
                        help=f"address {doing} (default: {where})")
    parser.add_argument("--port", type=int, default=None, metavar="PORT",
                        help=f"port {doing} (default: {which})")
    if not launching:
        return parser.parse_args(argv)
    parser.add_argument("--no-open", dest="open_browser",
                        action="store_false",
                        help="start it without opening a browser")
    opts, rest = parser.parse_known_args(argv)
    opts.rest = rest
    return opts


def main(name: str, argv: list[str]) -> int:
    """One of start, stop, status, restart."""
    root = install.root()
    if install.detect(root) == install.CONTAINER:
        print("background preview commands are not available in a container. "
              "Run `crossglyph preview` in the foreground, and use Docker or "
              "Compose to start and stop the container.", file=sys.stderr)
        return 2
    opts = parse(argv, name)
    if name in ("stop", "status"):
        act = stop if name == "stop" else status
        return act(root, opts.host, opts.port)
    if name == "start":
        settle(opts, None)
        return start(root, opts)
    return restart(root, opts)

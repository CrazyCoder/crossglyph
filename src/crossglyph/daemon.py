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


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


@dataclasses.dataclass
class State:
    """What a background start left behind, so the other commands can find it."""
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


def alive(pid: int) -> bool:
    """Whether a pid is a live process. Not whether it is ours."""
    if pid <= 0:
        return False
    if os.name == "nt":
        # Not os.kill(pid, 0): on Windows that is not a liveness question at
        # all, since anything but CTRL_C_EVENT and CTRL_BREAK_EVENT goes to
        # TerminateProcess. Asking whether a process is alive would kill it.
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED
        if not handle:
            return False
        code = ctypes.c_ulong()
        got = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return bool(got) and code.value == 259              # STILL_ACTIVE
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
    """What to run for a background start, in the order that keeps updates working.

    The current version's own interpreter first, since that is what makes
    `restart` land on a release installed since this process started. A
    version that has never run has no `.venv` yet and only the launcher can
    make one, because the launcher is what calls uv; that costs a sync once,
    and every start after it takes the first line again.

    `-m crossglyph` rather than the `crossglyph` console script: on Windows an
    update replaces that shim while it is running, and a module inside the
    package being started is not a file anything has to write over.
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


def spawn(root: pathlib.Path, argv: list[str]) -> subprocess.Popen:
    """The preview, detached from this terminal and writing to the log."""
    # Closed here as soon as the child has it: the child holds its own
    # descriptor, and a copy left open in this process would keep the file
    # locked on Windows long after this command has finished.
    with (root / LOG_NAME).open("wb") as handle:
        return subprocess.Popen([*command(root), "preview", *argv],
                                stdin=subprocess.DEVNULL, stdout=handle,
                                stderr=subprocess.STDOUT, cwd=str(root),
                                close_fds=True, **DETACH)


def log_tail(root: pathlib.Path, lines: int = 15) -> str:
    try:
        text = (root / LOG_NAME).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def since(started: float) -> str:
    """How long it has been up, said the way a person would."""
    seconds = max(0, int(time.time() - started))
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60}m"
    if seconds < 172800:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def look(root: pathlib.Path) -> tuple[State | None, dict | None]:
    """What was started, and what it has to say for itself.

    Three answers, and the third is the one worth having: no state at all,
    a state whose server answers, and a state whose server does not while
    its process is still there. That last one is a wedged preview, and
    calling it "not running" would leave something holding the port that no
    command of ours would ever stop.

    A state whose process is gone is swept here, so a server that was killed
    never confuses the next command.
    """
    state = load(root)
    if state is None:
        return None, None
    body = probe(state.host, state.port)
    if body is None and not alive(state.pid):
        clear(root)
        return None, None
    return state, body


def start(root: pathlib.Path, opts: argparse.Namespace) -> int:
    """Start the preview in the background and wait until it draws.

    Waiting is the point: a start that returns before the page answers can
    only report that a process was created, which is not the question. The
    browser opens after the page is there, so a failure is a failure on this
    terminal rather than an error page in a new tab.
    """
    state, body = look(root)
    if state is not None:
        where = url(state.host, state.port)
        if body is None:
            print(f"a preview on {where} (pid {state.pid}) is not answering. "
                  f"Stop it first.", file=sys.stderr)
            return 1
        if (state.host, state.port) != (opts.host, opts.port):
            print(f"a preview is already running on {where}. Stop it first, "
                  f"or ask for that address.", file=sys.stderr)
            return 1
        # Already what was asked for, so this is the answer to the question
        # rather than an error: say where it is and open it.
        print(f"preview already on {where}  "
              f"(pid {state.pid}, crossglyph {body['version']})")
        if opts.open_browser:
            webbrowser.open(where)
        return 0
    if taken(opts.host, opts.port):
        print(f"something that is not CrossGlyph is listening on port "
              f"{opts.port}.", file=sys.stderr)
        return 1

    argv = ["--no-open", "--host", opts.host, "--port", str(opts.port),
            *opts.rest]
    child = spawn(root, argv)

    def record(running_version: str) -> None:
        save(root, State(pid=child.pid, host=opts.host, port=opts.port,
                         rest=list(opts.rest), version=running_version,
                         started=time.time()))

    record(version.installed())
    deadline = time.monotonic() + READY_TIMEOUT
    while time.monotonic() < deadline:
        body = probe(opts.host, opts.port, timeout=1.0)
        if body is not None:
            # The version the child reports, not this process's own: after an
            # update those differ, and the one serving pages is the true one.
            record(body["version"])
            print(f"preview on {url(opts.host, opts.port)}  "
                  f"(pid {child.pid}, crossglyph {body['version']})")
            if opts.open_browser:
                webbrowser.open(url(opts.host, opts.port))
            return 0
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
    """
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def stop(root: pathlib.Path) -> int:
    """Stop the background preview, gracefully if it will have it.

    The endpoint rather than a signal, because Windows has neither: a
    detached child has no console for a Ctrl+Break to arrive through, and
    everything else there is a kill. Asking works the same way on all three
    platforms, and the kill is what answers a server that has stopped
    listening.
    """
    state, body = look(root)
    if state is None:
        print("no preview is running.")
        return 0
    where = url(state.host, state.port)
    if body is None:
        # Alive but not answering, which is the one case a stop must not walk
        # away from: nothing else would ever free that port.
        terminate(state.pid)
        clear(root)
        print(f"the preview on {where} was not answering. Killed pid "
              f"{state.pid}.")
        return 0

    asked = ask(f"{where}/shutdown", method="POST", timeout=5.0) is not None
    deadline = time.monotonic() + STOP_TIMEOUT
    while time.monotonic() < deadline:
        if probe(state.host, state.port, timeout=1.0) is None:
            clear(root)
            print(f"stopped the preview on {where}.")
            return 0
        time.sleep(POLL)

    terminate(state.pid)
    time.sleep(1.0)
    clear(root)
    if probe(state.host, state.port, timeout=1.0) is not None:
        print(f"the preview on {where} did not stop. Its pid is {state.pid}.",
              file=sys.stderr)
        return 1
    reason = "did not stop when asked" if asked else "would not take the ask"
    print(f"stopped the preview on {where}, which {reason}.")
    return 0


def status(root: pathlib.Path) -> int:
    """Say what is running. Exit 0 when something is, 1 when nothing is."""
    state, body = look(root)
    if state is None:
        print("no preview is running.")
        return 1
    if body is None:
        print(f"a preview on {url(state.host, state.port)} (pid {state.pid}) "
              f"is not answering. `crossglyph stop` will kill it.")
        print(f"  log {root / LOG_NAME}")
        return 1
    print(f"preview on {url(state.host, state.port)}")
    print(f"  pid {state.pid}, crossglyph {body['version']}, "
          f"up {since(state.started)}")
    if body.get("workspace"):
        print(f"  fonts {body['workspace']}")
    if body.get("pending"):
        print(f"  {body['pending']} is installed; a restart would run it")
    print(f"  log {root / LOG_NAME}")
    return 0


def restart(root: pathlib.Path, opts: argparse.Namespace) -> int:
    """Stop and start, on whichever version is current by then.

    Anything it is not told, it takes from the start it is replacing, so a
    bare `restart` comes back on the same address showing the same family and
    `restart --port 9000` moves only the port. Whether to open a browser is
    not one of those: that is a fact about this command, not about the server.
    """
    settle(opts, load(root))
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
    """The options a background command takes, which are the preview's.

    Everything it does not name itself is passed through, so `--family`,
    `--font` and the rest mean what they mean in the foreground. The address
    has no default here: unset is what lets a restart tell "leave it as it
    was" apart from "put it on 8000".
    """
    parser = argparse.ArgumentParser(
        prog=f"crossglyph {name}",
        description="Run the preview in the background.")
    parser.add_argument("--host", default=None,
                        help=f"default: {DEFAULT_HOST}")
    parser.add_argument("--port", type=int, default=None,
                        help=f"default: {DEFAULT_PORT}")
    parser.add_argument("--no-open", dest="open_browser",
                        action="store_false",
                        help="start it without opening a browser")
    opts, rest = parser.parse_known_args(argv)
    opts.rest = rest
    return opts


def main(name: str, argv: list[str]) -> int:
    """One of start, stop, status, restart."""
    root = install.root()
    if name in ("stop", "status"):
        if argv:
            print(f"usage: crossglyph {name}", file=sys.stderr)
            return 2
        return stop(root) if name == "stop" else status(root)
    opts = parse(argv, name)
    if name == "start":
        settle(opts, None)
        return start(root, opts)
    return restart(root, opts)

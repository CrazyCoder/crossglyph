"""The launcher picks a project directory and says where the workspace is.

Two layouts have to work: a release, where versions/<v> holds the code and
`current` names the live one, and a checkout or source download, which is run
in place. Getting the second wrong breaks the everyday developer flow, and it
would break silently -- uv would simply run the wrong project.
"""
import os
import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]

sh = shutil.which("sh") or shutil.which("bash")
needs_sh = pytest.mark.skipif(sh is None, reason="no POSIX shell on PATH")
needs_windows = pytest.mark.skipif(os.name != "nt", reason="cmd.exe only")

#: Prints what the shim decided, then stops. Real uv is never reached.
#:
#: Which interpreter reads it is decided by the platform and not by the
#: launcher under test: on Windows a .cmd is handed to cmd.exe even when a
#: POSIX shell is what exec'd it, which is the whole reason the real
#: tools/uv.cmd is a polyglot. So the batch stub is what both launchers get
#: here, and the sh one is for everywhere else.
STUB = ("@ECHO OFF\r\necho PROJECT=%~3\r\necho HOME=%CROSSGLYPH_HOME%\r\n"
        "echo FONTS=%CROSSGLYPH_FONTS%\r\n") if os.name == "nt" else (
    '#!/bin/sh\necho "PROJECT=$3"\necho "HOME=${CROSSGLYPH_HOME:-}"\n'
    'echo "FONTS=${CROSSGLYPH_FONTS:-}"\n')


def _tools(directory: pathlib.Path) -> None:
    tools = directory / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    stub = tools / "uv.cmd"
    stub.write_bytes(STUB.encode("utf-8"))
    stub.chmod(0o755)


def _release(root: pathlib.Path, version: str = "0.2.0") -> pathlib.Path:
    (root / "versions" / version).mkdir(parents=True)
    _tools(root / "versions" / version)
    (root / "current").write_text(f"{version}\n", encoding="utf-8")
    (root / "fonts").mkdir()
    return root


def _in_place(root: pathlib.Path) -> pathlib.Path:
    (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    _tools(root)
    return root


def _install(root: pathlib.Path, name: str) -> pathlib.Path:
    shutil.copyfile(REPO / name, root / name)
    (root / name).chmod(0o755)
    return root / name


#: The two variables the shim may set, cleared so a run that does not set one
#: is distinguishable from this process happening to have it.
CLEAN = {**os.environ, "CROSSGLYPH_HOME": "", "CROSSGLYPH_FONTS": ""}


def _run(root: pathlib.Path, name: str, *runner: str,
         **env: str) -> subprocess.CompletedProcess:
    return subprocess.run([*runner, str(_install(root, name))],
                          capture_output=True, text=True, env={**CLEAN, **env})


def _said(done: subprocess.CompletedProcess) -> dict[str, str]:
    """What the stub reported, with separators levelled.

    Three combinations produce three spellings of the same path: cmd.exe hands
    on backslashes, and a POSIX shell on Windows hands on /c/... . None of that
    is what these tests are about.
    """
    assert done.returncode == 0, done.stderr
    said = dict(line.split("=", 1)
                for line in done.stdout.splitlines() if "=" in line)
    return {key: value.strip().replace("\\", "/").rstrip("/")
            for key, value in said.items()}


def _sh(root: pathlib.Path, **env: str) -> subprocess.CompletedProcess:
    assert sh is not None                       # guarded by needs_sh
    return _run(root, "crossglyph.sh", sh, **env)


def _cmd(root: pathlib.Path, **env: str) -> subprocess.CompletedProcess:
    return _run(root, "crossglyph.cmd", "cmd.exe", "/c", **env)


@needs_sh
def test_a_release_runs_the_version_that_current_names(tmp_path):
    said = _said(_sh(_release(tmp_path)))
    assert said["PROJECT"].endswith("versions/0.2.0")


@needs_sh
def test_a_release_names_the_install_root_and_the_workspace(tmp_path):
    said = _said(_sh(_release(tmp_path)))
    assert said["HOME"].endswith(tmp_path.name)
    assert said["FONTS"].endswith("fonts")


@needs_sh
def test_a_checkout_is_run_in_place(tmp_path):
    """Without this branch, ./crossglyph.sh in a clone would fail on a
    `current` file that only a built release has."""
    said = _said(_sh(_in_place(tmp_path)))
    assert said["PROJECT"].endswith(tmp_path.name)
    assert "versions" not in said["PROJECT"]


@needs_sh
def test_running_in_place_exports_neither_variable(tmp_path):
    """ROOT/fonts is already right there, so nothing has to be said."""
    said = _said(_sh(_in_place(tmp_path)))
    assert said["HOME"] == ""
    assert said["FONTS"] == ""


@needs_sh
def test_a_workspace_the_caller_chose_is_left_alone(tmp_path):
    """$CROSSGLYPH_FONTS names another workspace, and the shim must not
    overwrite a choice somebody already made.

    A name rather than an absolute path: MSYS rewrites a leading slash into a
    Windows path on the way through, which would be measuring git bash.
    """
    said = _said(_sh(_release(tmp_path), CROSSGLYPH_FONTS="chosen-workspace"))
    assert said["FONTS"] == "chosen-workspace"


@needs_sh
def test_a_current_that_names_nothing_falls_back_and_warns(tmp_path):
    root = _release(tmp_path, "0.2.0")
    (root / "current").write_text("0.9.9\n", encoding="utf-8")
    done = _sh(root)
    assert done.returncode == 0, done.stderr
    assert "0.2.0" in done.stdout
    assert "0.9.9" in done.stderr, "it should say which version went missing"


@needs_sh
def test_an_empty_current_falls_back_rather_than_running_versions_itself(
        tmp_path):
    """What an interrupted write leaves. The trap is that versions/<nothing>
    is versions/, which exists, so a naive check finds a directory and hands
    uv the wrong project instead of recovering."""
    root = _release(tmp_path, "0.2.0")
    (root / "current").write_text("", encoding="utf-8")
    said = _said(_sh(root))
    assert said["PROJECT"].endswith("versions/0.2.0")


@needs_windows
def test_the_batch_launcher_survives_an_empty_current(tmp_path):
    root = _release(tmp_path)
    (root / "current").write_text("", encoding="utf-8")
    said = _said(_cmd(root))
    assert said["PROJECT"].endswith("versions/0.2.0")


@needs_sh
def test_neither_layout_fails_with_a_message_naming_the_problem(tmp_path):
    done = _sh(tmp_path)
    assert done.returncode != 0
    assert "CrossGlyph install" in done.stderr


@needs_windows
def test_the_batch_launcher_picks_the_same_directories(tmp_path):
    said = _said(_cmd(_release(tmp_path)))
    assert said["PROJECT"].endswith("versions/0.2.0")
    assert said["FONTS"].endswith("fonts")


@needs_windows
def test_the_batch_launcher_runs_a_checkout_in_place(tmp_path):
    said = _said(_cmd(_in_place(tmp_path)))
    assert "versions" not in said["PROJECT"]


@needs_windows
def test_the_batch_launcher_reports_neither_layout(tmp_path):
    done = _cmd(tmp_path)
    assert done.returncode != 0
    assert "CrossGlyph install" in done.stdout + done.stderr


# --- a launcher an update left beside this one ----------------------------
#
# An update cannot write over the launcher: it is open, and both cmd.exe and a
# POSIX shell resume at the byte offset they had reached, which in a file that
# changed length is the middle of a word. So the new one is staged, and this
# is the run that applies it. Measured on both, because the failure is a
# corrupt launcher and nobody would guess at it from a stack trace.


def _staged(root: pathlib.Path, name: str, says: str) -> pathlib.Path:
    """A newer launcher waiting to be applied, which reports and stops."""
    body = (f"@ECHO OFF\r\necho PROJECT={says}\r\n" if name.endswith(".cmd")
            else f'#!/bin/sh\necho "PROJECT={says}"\n')
    staged = root / (name + ".staged")
    staged.write_bytes(body.encode("utf-8"))
    return staged


@needs_sh
def test_a_staged_launcher_is_applied_and_run(tmp_path):
    root = _release(tmp_path)
    _staged(root, "crossglyph.sh", "the-new-launcher")
    said = _said(_sh(root))
    assert said["PROJECT"] == "the-new-launcher", "the staged one did not run"
    assert not (root / "crossglyph.sh.staged").exists()
    assert "the-new-launcher" in (root / "crossglyph.sh").read_text(
        encoding="utf-8")


@needs_sh
def test_the_launcher_it_replaced_is_kept(tmp_path):
    """A release that shipped a broken launcher is then a rename away from
    being undone, rather than a reinstall."""
    root = _release(tmp_path)
    _staged(root, "crossglyph.sh", "the-new-launcher")
    _sh(root)
    assert "CrossGlyph install" in (root / "crossglyph.sh.previous").read_text(
        encoding="utf-8")


@needs_sh
def test_nothing_staged_leaves_the_launcher_alone(tmp_path):
    root = _release(tmp_path)
    _said(_sh(root))
    assert not (root / "crossglyph.sh.previous").exists()


@needs_windows
def test_the_batch_launcher_applies_a_staged_one(tmp_path):
    root = _release(tmp_path)
    _staged(root, "crossglyph.cmd", "the-new-launcher")
    said = _said(_cmd(root))
    assert said["PROJECT"] == "the-new-launcher"
    assert not (root / "crossglyph.cmd.staged").exists()
    assert (root / "crossglyph.cmd.previous").is_file()


@pytest.mark.skipif(os.name == "nt",
                    reason="the read-only attribute does not stop a rename")
@needs_sh
def test_a_staged_launcher_that_will_not_move_does_not_loop(tmp_path):
    """Without the guard this is not a failed update, it is a launcher that
    re-runs itself forever: the staged file is still there, so the run it
    starts finds it and starts another."""
    root = _release(tmp_path)
    launcher = _install(root, "crossglyph.sh")
    _staged(root, "crossglyph.sh", "the-new-launcher")
    assert sh is not None                       # guarded by needs_sh
    root.chmod(0o555)
    try:
        done = subprocess.run([sh, str(launcher)], capture_output=True,
                              text=True, env=CLEAN, timeout=30)
    finally:
        root.chmod(0o755)
    assert "the-new-launcher" not in done.stdout, "it moved a file it could not"
    assert "versions/0.2.0" in done.stdout.replace("\\", "/"), \
        "it should fall through and run the launcher it has"


@needs_sh
def test_the_staged_run_still_reports_what_the_work_returned(tmp_path):
    """exec on this side, so the code comes back out. The batch launcher
    cannot do that on the one run that applies a staged launcher, and the test
    below the platform split says so."""
    root = _release(tmp_path)
    (root / "crossglyph.sh.staged").write_bytes(b"#!/bin/sh\nexit 3\n")
    assert _sh(root).returncode == 3


@needs_windows
def test_the_batch_run_that_applies_one_cannot_carry_the_code_out(tmp_path):
    """Measured, and accepted rather than worked around. Reporting the code
    needs a line after the call, and a line after the call is what corrupts
    the run: cmd.exe would read it out of the replaced file. Delayed expansion
    would buy the code back at the price of eating a `!` in anybody's
    arguments, which is the more common thing to get wrong.

    Only this one run, and only the number: what the user sees comes from the
    launcher inside, which is whole.
    """
    root = _release(tmp_path)
    (root / "crossglyph.cmd.staged").write_bytes(
        b"@ECHO OFF\r\nexit /B 3\r\n")
    assert _cmd(root).returncode == 0


@needs_windows
def test_the_batch_launcher_reads_no_further_after_applying_one(tmp_path):
    """The reason the apply is one line ending in exit /B. With it on several,
    cmd.exe resumes in the replaced file at the offset it had reached and runs
    fragments: 'ause' rather than pause, and a nonzero exit nobody asked for.
    """
    root = _release(tmp_path)
    # Much shorter than the launcher it replaces, so any later read lands in
    # a completely different place.
    (root / "crossglyph.cmd.staged").write_bytes(b"@ECHO OFF\r\n")
    done = _cmd(root)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "not recognized" not in done.stdout + done.stderr

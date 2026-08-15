"""Host launchers turn a successful detached start into useful directions."""
import os
import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SH = shutil.which("sh") or shutil.which("bash")
NEEDS_SH = pytest.mark.skipif(SH is None, reason="no POSIX shell on PATH")
NEEDS_WINDOWS = pytest.mark.skipif(os.name != "nt", reason="cmd.exe only")


SH_DOCKER = r'''#!/bin/sh
printf '%s\n' "$*" >> "$DOCKER_CALLS"
if [ "$1" = inspect ]; then
    printf '%s\n' "$FAKE_WORKSPACE"
    exit 0
fi
case " $* " in
    *" port crossglyph 8000 "*) printf '%s\n' '127.0.0.1:8123' ;;
    *" ps -q crossglyph "*) printf '%s\n' 'crossglyph-container' ;;
    *" up "*) exit "${DOCKER_UP_EXIT:-0}" ;;
esac
'''

CMD_DOCKER = r'''@ECHO OFF
>>"%DOCKER_CALLS%" echo %*
if "%~1"=="inspect" (
    echo %FAKE_WORKSPACE%
    exit /B 0
)
echo %* | "%SystemRoot%\System32\find.exe" " port crossglyph 8000" >nul
if not errorlevel 1 (
    echo 127.0.0.1:8123
    exit /B 0
)
echo %* | "%SystemRoot%\System32\find.exe" " ps -q crossglyph" >nul
if not errorlevel 1 (
    echo crossglyph-container
    exit /B 0
)
echo %* | "%SystemRoot%\System32\find.exe" " up " >nul
if not errorlevel 1 (
    if defined DOCKER_UP_EXIT exit /B %DOCKER_UP_EXIT%
    exit /B 0
)
exit /B 0
'''


def _environment(tmp_path: pathlib.Path, docker: str, suffix: str) -> tuple[dict, pathlib.Path]:
    commands = tmp_path / "docker-calls.txt"
    binary = tmp_path / f"docker{suffix}"
    binary.write_bytes(docker.encode("utf-8"))
    binary.chmod(0o755)
    workspace = tmp_path / "mounted fonts"
    env = {
        **os.environ,
        "PATH": str(tmp_path) + os.pathsep + os.environ.get("PATH", ""),
        "DOCKER_CALLS": str(commands),
        "FAKE_WORKSPACE": str(workspace),
    }
    return env, commands


def _launcher(tmp_path: pathlib.Path, name: str) -> pathlib.Path:
    target = tmp_path / name
    shutil.copyfile(REPO / name, target)
    target.chmod(0o755)
    return target


def _assert_success(done: subprocess.CompletedProcess, commands: pathlib.Path,
                    workspace: pathlib.Path, local: bool) -> None:
    assert done.returncode == 0, done.stderr
    calls = commands.read_text(encoding="utf-8").splitlines()
    expected = "docker compose -f compose.yaml -f compose.build.yaml" \
        if local else "docker compose"
    assert ("compose -f compose.yaml -f compose.build.yaml up -d --build --wait"
            if local else "compose up -d --wait") in calls[0]
    assert "Open:      http://127.0.0.1:8123/" in done.stdout
    assert f"Workspace: {workspace}" in done.stdout
    assert f"Follow logs: {expected} logs -f" in done.stdout
    assert f"Stop:        {expected} down" in done.stdout
    assert f"Clean up:    {expected} down --rmi all" in done.stdout


@pytest.mark.parametrize("local", [False, True])
@NEEDS_SH
def test_the_unix_launcher_reports_the_running_service(tmp_path, local):
    assert SH is not None
    env, commands = _environment(tmp_path, SH_DOCKER, "")
    launcher = _launcher(tmp_path, "crossglyph-docker.sh")
    args = [SH, str(launcher), *(["--local"] if local else [])]
    done = subprocess.run(
        args, capture_output=True, text=True, env=env, check=False)
    _assert_success(done, commands, tmp_path / "mounted fonts", local)


@pytest.mark.parametrize("local", [False, True])
@NEEDS_WINDOWS
def test_the_windows_launcher_reports_the_running_service(tmp_path, local):
    env, commands = _environment(
        tmp_path, CMD_DOCKER.replace("\n", "\r\n"), ".cmd")
    launcher = _launcher(tmp_path, "crossglyph-docker.cmd")
    args = ["cmd.exe", "/d", "/c", str(launcher),
            *(["--local"] if local else [])]
    done = subprocess.run(
        args, capture_output=True, text=True, env=env, check=False)
    _assert_success(done, commands, tmp_path / "mounted fonts", local)


@pytest.mark.parametrize(
    ("name", "runner", "docker", "suffix"),
    [
        pytest.param(
            "crossglyph-docker.sh", [SH or "sh"], SH_DOCKER, "",
            marks=NEEDS_SH),
        pytest.param(
            "crossglyph-docker.cmd", ["cmd.exe", "/d", "/c"],
            CMD_DOCKER.replace("\n", "\r\n"), ".cmd",
            marks=NEEDS_WINDOWS),
    ])
def test_a_compose_failure_is_returned(
        tmp_path, name, runner, docker, suffix):
    env, commands = _environment(tmp_path, docker, suffix)
    env["DOCKER_UP_EXIT"] = "19"
    launcher = _launcher(tmp_path, name)
    done = subprocess.run(
        [*runner, str(launcher)], capture_output=True, text=True, env=env,
        check=False)
    assert done.returncode == 19
    assert "CrossGlyph is ready" not in done.stdout
    assert len(commands.read_text(encoding="utf-8").splitlines()) == 1


@NEEDS_SH
def test_the_unix_launcher_applies_a_staged_update(tmp_path):
    assert SH is not None
    launcher = _launcher(tmp_path, "crossglyph-docker.sh")
    staged = launcher.with_name(launcher.name + ".staged")
    staged.write_text(
        "#!/bin/sh\nprintf '%s\\n' 'updated Docker launcher'\n",
        encoding="utf-8")
    staged.chmod(0o755)
    done = subprocess.run(
        [SH, str(launcher)], capture_output=True, text=True, check=False)
    assert done.returncode == 0
    assert done.stdout.strip() == "updated Docker launcher"
    assert not staged.exists()
    assert launcher.with_name(launcher.name + ".previous").is_file()


@NEEDS_WINDOWS
def test_the_windows_launcher_applies_a_staged_update(tmp_path):
    launcher = _launcher(tmp_path, "crossglyph-docker.cmd")
    staged = launcher.with_name(launcher.name + ".staged")
    staged.write_bytes(b"@ECHO OFF\r\necho updated Docker launcher\r\n")
    done = subprocess.run(
        ["cmd.exe", "/d", "/c", str(launcher)],
        capture_output=True, text=True, check=False)
    assert done.returncode == 0
    assert done.stdout.strip() == "updated Docker launcher"
    assert not staged.exists()
    assert launcher.with_name(launcher.name + ".previous").is_file()

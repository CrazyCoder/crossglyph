@ECHO OFF
REM Run CrossGlyph, fetching uv on first use. With no arguments it opens the
REM preview in a browser.
REM
REM Two layouts, as in crossglyph.sh: a release runs versions\<current>, and a
REM clone or source download is run where it stands.
SETLOCAL EnableExtensions

REM Double-clicked in Explorer, this script is started as `cmd /c "...\
REM crossglyph.cmd"`, so cmd.exe's own command line names it. Started from a
REM console it does not. The difference matters because a console window opened
REM by Explorer closes the moment the script ends, taking any error message
REM with it. %cmdcmdline% is quoted for the pipe, since a path may hold an &.
REM find.exe by its full path: a PATH carrying MSYS or GnuWin32 puts a POSIX
REM find first, which would take /i as a directory and print an error.
set "CG_WAIT="
echo "%cmdcmdline%" | "%SystemRoot%\System32\find.exe" /i "%~nx0" >nul
if not errorlevel 1 set "CG_WAIT=1"

REM "%~dp0." rather than "%~dp0": %~dp0 ends in a backslash, which would escape
REM the closing quote. %%~fI then resolves the trailing dot away, so what is
REM exported below is a path somebody could read.
for %%I in ("%~dp0.") do set "CG_ROOT=%%~fI"

if not exist "%CG_ROOT%\current" goto :inplace
if not exist "%CG_ROOT%\versions\" goto :inplace

REM Cleared first: set /p leaves the variable alone when the file is empty,
REM which is what an interrupted write leaves behind. Undefined then expands
REM to nothing, naming versions\ itself -- a directory that does exist, so
REM without the guard the check below would pass and hand uv the folder the
REM versions live in rather than a version.
set "CG_VERSION="
set /p CG_VERSION=<"%CG_ROOT%\current"
if not defined CG_VERSION goto :recover
set "CG_DIR=%CG_ROOT%\versions\%CG_VERSION%"
if exist "%CG_DIR%\" goto :release

:recover
REM Recovery only, as in crossglyph.sh: take whichever version is there.
set "CG_DIR="
for /d %%D in ("%CG_ROOT%\versions\*") do set "CG_DIR=%%~fD"
if not defined CG_DIR (
    echo no version is installed under %CG_ROOT%\versions 1>&2
    set "CG_EXIT=1"
    goto :done
)
echo warning: current names %CG_VERSION%, which is not there. Using %CG_DIR% 1>&2

:release
set "CROSSGLYPH_HOME=%CG_ROOT%"
REM Only when nobody has chosen one, as in crossglyph.sh.
if not defined CROSSGLYPH_FONTS set "CROSSGLYPH_FONTS=%CG_ROOT%\fonts"
goto :run

:inplace
if not exist "%CG_ROOT%\pyproject.toml" goto :broken
set "CG_DIR=%CG_ROOT%"
goto :run

:broken
echo this does not look like a CrossGlyph install: %CG_ROOT% 1>&2
set "CG_EXIT=1"
goto :done

:run
call "%CG_DIR%\tools\uv.cmd" run --project "%CG_DIR%" crossglyph %*
set "CG_EXIT=%ERRORLEVEL%"

:done
if defined CG_WAIT if not "%CG_EXIT%"=="0" (
    echo.
    pause
)
exit /B %CG_EXIT%

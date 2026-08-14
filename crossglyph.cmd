@ECHO OFF
REM Run CrossGlyph, fetching uv on first use. With no arguments it opens the
REM preview in a browser.
REM
REM Two layouts, as in crossglyph.sh: a release runs versions\<current>, and a
REM clone or source download is run where it stands.
SETLOCAL EnableExtensions

REM An update leaves a new launcher beside this one rather than writing over
REM it, and this line is where it lands. It has to be one line, and it has to
REM end the script: cmd.exe reads this file as it runs it, and resumes at the
REM byte offset it had reached, so a file that changed length under it is
REM executed from the middle of a word. Measured on Windows 10, not assumed:
REM replacing this file mid run, by write or by rename, makes cmd run
REM fragments like 'ause'. A whole line, on the other hand, is parsed before
REM any of it executes, so `call` and `exit /B` here both come from memory.
REM The outgoing launcher is kept as .previous, so a release that shipped a
REM broken one is a rename away from being undone rather than a reinstall.
REM
REM This one run reports success whatever the tool returned: carrying the code
REM out needs a line after the call, and a line after the call is the thing
REM that cannot exist here. Everything the user sees, including the pause on a
REM failed double click, comes from the run inside, which has the whole
REM launcher and is unaffected. crossglyph.sh has no such trouble: exec leaves
REM nothing behind to lose it.
if exist "%~f0.staged" (copy /y "%~f0" "%~f0.previous" >nul & move /y "%~f0.staged" "%~f0" >nul & call "%~f0" %* & exit /B)

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

@ECHO OFF
REM Run CrossGlyph, fetching uv on first use. With no arguments it opens the
REM preview in a browser.
REM
REM "%~dp0." rather than "%~dp0": %~dp0 ends in a backslash, which would escape
REM the closing quote and hand uv the rest of the line as part of the path.

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

call "%~dp0tools\uv.cmd" run --project "%~dp0." crossglyph %*
set "CG_EXIT=%ERRORLEVEL%"

if defined CG_WAIT if not "%CG_EXIT%"=="0" (
    echo.
    pause
)
exit /B %CG_EXIT%

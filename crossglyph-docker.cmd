@ECHO OFF
REM Start CrossGlyph through Docker Compose, then report its address and mount.
SETLOCAL EnableExtensions

REM Apply an update before this launcher is read any further. The outgoing copy
REM remains beside it for recovery if a release ever ships a broken launcher.
if exist "%~f0.staged" (copy /y "%~f0" "%~f0.previous" >nul 2>&1 & move /y "%~f0.staged" "%~f0" >nul && (call "%~f0" %* & exit /B))

for %%I in ("%~dp0.") do set "CG_ROOT=%%~fI"
set "CG_LOCAL="
set "CG_EXIT=0"

if "%~1"=="" goto :start
if /i "%~1"=="--local" if "%~2"=="" (
    set "CG_LOCAL=1"
    goto :start
)
if /i "%~1"=="-h" goto :help
if /i "%~1"=="--help" goto :help
goto :usage

:help
echo usage: crossglyph-docker.cmd [--local]
echo.
echo Start CrossGlyph with its published image. Use --local to build the image
echo from the checkout, or from the matching version inside an unpacked release.
goto :done

:usage
echo usage: crossglyph-docker.cmd [--local] 1>&2
set "CG_EXIT=2"
goto :done

:start
pushd "%CG_ROOT%" >nul
if errorlevel 1 (
    echo could not open the CrossGlyph folder: %CG_ROOT% 1>&2
    set "CG_EXIT=1"
    goto :done
)
set "CG_PUSHED=1"
set "CG_FILES="
set "CG_COMMAND=docker compose"
if defined CG_LOCAL (
    set "CG_FILES=-f compose.yaml -f compose.build.yaml"
    set "CG_COMMAND=docker compose -f compose.yaml -f compose.build.yaml"
    call docker compose -f compose.yaml -f compose.build.yaml up -d --build --wait
) else (
    call docker compose up -d --wait
)
set "CG_EXIT=%ERRORLEVEL%"
if not "%CG_EXIT%"=="0" goto :done

set "CG_ADDRESS="
for /f "delims=" %%A in ('docker compose %CG_FILES% port crossglyph 8000 2^>nul') do if not defined CG_ADDRESS set "CG_ADDRESS=%%A"
set "CG_CONTAINER="
for /f "delims=" %%I in ('docker compose %CG_FILES% ps -q crossglyph 2^>nul') do if not defined CG_CONTAINER set "CG_CONTAINER=%%I"
set "CG_WORKSPACE="
if defined CG_CONTAINER for /f "delims=" %%W in ('docker inspect --format "{{(index .Mounts 0).Source}}" "%CG_CONTAINER%" 2^>nul') do if not defined CG_WORKSPACE set "CG_WORKSPACE=%%W"

echo.
echo CrossGlyph is ready.
if defined CG_ADDRESS echo   Open:      http://%CG_ADDRESS%/
if defined CG_WORKSPACE (
    echo   Workspace: %CG_WORKSPACE%
    echo   Put TTF or OTF files there. Built families appear under cpfonts.
)
echo.
echo Next commands:
echo   Follow logs: %CG_COMMAND% logs -f
echo   Stop:        %CG_COMMAND% down
echo   Clean up:    %CG_COMMAND% down --rmi all

:done
if defined CG_PUSHED popd >nul
exit /B %CG_EXIT%

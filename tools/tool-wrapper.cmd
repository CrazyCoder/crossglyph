@echo off
REM Tool Wrapper - Reusable download/verify/execute wrapper for external tools (Windows)
REM See tool-wrapper.design.md for usage and environment variable reference

setlocal

REM Validate required environment variables
if "%TOOL_NAME%"=="" (
  echo ERROR: TOOL_NAME not set >&2
  exit /B 1
)
if "%TOOL_VERSION%"=="" (
  echo ERROR: TOOL_VERSION not set >&2
  exit /B 1
)
if "%TOOL_BINARY_WINDOWS%"=="" (
  echo ERROR: TOOL_BINARY_WINDOWS not set >&2
  exit /B 1
)

REM Detect architecture using registry (more reliable than env var)
for /f "tokens=3 delims= " %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v "PROCESSOR_ARCHITECTURE"') do set "ARCH=%%a"

if "%ARCH%"=="ARM64" (
  set "PLATFORM=WINDOWS_ARM64"
) else if "%ARCH%"=="AMD64" (
  set "PLATFORM=WINDOWS_X64"
) else (
  echo ERROR: Unsupported Windows architecture: %ARCH% >&2
  exit /B 1
)

REM Set cache directory
set "CACHE_DIR=%LOCALAPPDATA%\CrossGlyph\tools"
set "TARGET_DIR=%CACHE_DIR%\%TOOL_NAME%\%TOOL_VERSION%"
set "FLAG_FILE=%TARGET_DIR%\.complete"

REM Check for verification mode
if "%TOOL_VERIFY_ALL_PLATFORMS%"=="1" goto :verify_all

REM Get platform-specific checksum and URL
call :get_platform_vars
if errorlevel 1 exit /B 1

REM Determine binary path (computed once, before any block that needs it)
set "BINARY_PATH=%TARGET_DIR%\%TOOL_BINARY_WINDOWS%"

REM Check if already cached (flag file with correct checksum)
if exist "%FLAG_FILE%" (
  for /f "usebackq delims=" %%c in ("%FLAG_FILE%") do (
    if "%%c"=="%EXPECTED_CHECKSUM%" (
      if exist "%BINARY_PATH%" goto :execute
    )
  )
)

REM Fallback: binary exists but flag file is missing or stale (e.g. interrupted
REM install, disk cleanup). Version is pinned in the path so trust it.
REM Don't write .complete here — cache may be incomplete (e.g. node.exe exists
REM but npm.cmd is missing). Only a full download+extraction writes the flag.
if exist "%BINARY_PATH%" goto :execute

REM Download and verify using PowerShell script
set "POWERSHELL=%SystemRoot%\system32\WindowsPowerShell\v1.0\powershell.exe"
set "PS_SCRIPT=%~dp0tool-wrapper.ps1"

"%POWERSHELL%" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%PS_SCRIPT%"
if errorlevel 1 (
  echo ERROR: Download or verification failed >&2
  exit /B 1
)

:execute
if not exist "%BINARY_PATH%" (
  echo ERROR: Binary not found: %BINARY_PATH% >&2
  exit /B 1
)

REM Add tool directory to PATH so scripts can find related binaries (e.g., npx needs node)
set "PATH=%TARGET_DIR%;%PATH%"

REM Ctrl+C marks the current batch for a termination prompt after the tool exits.
REM Another CALL parsed on the same physical line clears that pending abort
REM before cmd.exe can ask. The first CALL expansion saves the tool's exit code
REM before the harmless invalid IF changes it. Keep all three commands together.
"%BINARY_PATH%" %* & call set "TOOL_EXIT=%%ERRORLEVEL%%" & call if EnsureError
exit /B %TOOL_EXIT%

:get_platform_vars
REM Get checksum for current platform
if "%PLATFORM%"=="WINDOWS_X64" (
  set "EXPECTED_CHECKSUM=%TOOL_CHECKSUM_WINDOWS_X64%"
  set "DOWNLOAD_URL=%TOOL_URL_WINDOWS_X64%"
) else if "%PLATFORM%"=="WINDOWS_ARM64" (
  set "EXPECTED_CHECKSUM=%TOOL_CHECKSUM_WINDOWS_ARM64%"
  set "DOWNLOAD_URL=%TOOL_URL_WINDOWS_ARM64%"
) else (
  echo ERROR: Unknown platform: %PLATFORM% >&2
  exit /B 1
)

if "%EXPECTED_CHECKSUM%"=="" (
  echo ERROR: No checksum defined for platform: %PLATFORM% >&2
  exit /B 1
)
if "%DOWNLOAD_URL%"=="" (
  echo ERROR: No URL defined for platform: %PLATFORM% >&2
  exit /B 1
)
exit /B 0

:verify_all
REM Verify all platforms mode using PowerShell script
set "POWERSHELL=%SystemRoot%\system32\WindowsPowerShell\v1.0\powershell.exe"
set "PS_SCRIPT=%~dp0tool-wrapper.ps1"

"%POWERSHELL%" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%PS_SCRIPT%" -VerifyAllPlatforms
exit /B %ERRORLEVEL%

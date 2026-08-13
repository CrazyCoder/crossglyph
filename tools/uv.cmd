:<<"::CMDLITERAL"
@ECHO OFF
GOTO :CMDSCRIPT
::CMDLITERAL

# uv wrapper - Unix section
#
# Mixed line endings on purpose: CRLF header and batch body, LF bash
# body. Do not rewrite this file wholesale -- see CONTRIBUTING.md.
# Downloads uv and executes it with version pinning and checksum verification
#
# IMPORTANT: After updating TOOL_VERSION or checksums, you MUST run:
#   TOOL_VERIFY_ALL_PLATFORMS=1 ./tools/uv.cmd
# to verify all platform checksums before committing.

set -eu

# uv configuration
export TOOL_NAME="uv"
export TOOL_VERSION="0.12.3"

# SHA-256 checksums for each platform
export TOOL_CHECKSUM_LINUX_X64="600cf9a742aca00d292673b16b5acffaa7b8c269a364ad0c2e79498dcb1fe101"
export TOOL_CHECKSUM_LINUX_ARM64="bb66cb52e7b1823aed1183630d8d8e5c958840d584a4c55ec10a4cfc168dcca2"
export TOOL_CHECKSUM_WINDOWS_X64="b23350c79e8ad0192b8124af13a0f17e8d4e4549524785e1aef389ae5a06990e"
export TOOL_CHECKSUM_WINDOWS_ARM64="4343217d668727b8a8eb5cad92389a1d2eeead93c89940d1b955ba1bb15462eb"
export TOOL_CHECKSUM_MACOS_X64="4c9f52262a14da336e4a42ed24992d12d0c956acde87619e4611d321dffa602b"
export TOOL_CHECKSUM_MACOS_ARM64="546f7f8a6c70ff13a3a9d2bc958db3427298cebf3e0cb756f9177133b7068843"

# Download URLs (GitHub releases)
export TOOL_URL_LINUX_X64="https://github.com/astral-sh/uv/releases/download/${TOOL_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz"
export TOOL_URL_LINUX_ARM64="https://github.com/astral-sh/uv/releases/download/${TOOL_VERSION}/uv-aarch64-unknown-linux-gnu.tar.gz"
export TOOL_URL_WINDOWS_X64="https://github.com/astral-sh/uv/releases/download/${TOOL_VERSION}/uv-x86_64-pc-windows-msvc.zip"
export TOOL_URL_WINDOWS_ARM64="https://github.com/astral-sh/uv/releases/download/${TOOL_VERSION}/uv-aarch64-pc-windows-msvc.zip"
export TOOL_URL_MACOS_X64="https://github.com/astral-sh/uv/releases/download/${TOOL_VERSION}/uv-x86_64-apple-darwin.tar.gz"
export TOOL_URL_MACOS_ARM64="https://github.com/astral-sh/uv/releases/download/${TOOL_VERSION}/uv-aarch64-apple-darwin.tar.gz"

# Binary path within extracted archive
# tar.gz: nested (top-level dir stripped) → uv
# zip: flat → uv.exe
export TOOL_BINARY_UNIX="uv"
export TOOL_BINARY_WINDOWS="uv.exe"

# Invoke wrapper
root="$(cd "$(dirname "$0")"; pwd)"
exec "$root/tool-wrapper.sh" "$@"

:CMDSCRIPT

setlocal

REM uv wrapper - Windows section
REM
REM Mixed line endings on purpose: CRLF header and batch body, LF bash
REM body. Do not rewrite this file wholesale -- see CONTRIBUTING.md.
REM IMPORTANT: After updating TOOL_VERSION or checksums, you MUST run:
REM   set TOOL_VERIFY_ALL_PLATFORMS=1 && tools\uv.cmd
REM to verify all platform checksums before committing.

REM uv configuration
set "TOOL_NAME=uv"
set "TOOL_VERSION=0.12.3"

REM SHA-256 checksums for each platform
set "TOOL_CHECKSUM_LINUX_X64=600cf9a742aca00d292673b16b5acffaa7b8c269a364ad0c2e79498dcb1fe101"
set "TOOL_CHECKSUM_LINUX_ARM64=bb66cb52e7b1823aed1183630d8d8e5c958840d584a4c55ec10a4cfc168dcca2"
set "TOOL_CHECKSUM_WINDOWS_X64=b23350c79e8ad0192b8124af13a0f17e8d4e4549524785e1aef389ae5a06990e"
set "TOOL_CHECKSUM_WINDOWS_ARM64=4343217d668727b8a8eb5cad92389a1d2eeead93c89940d1b955ba1bb15462eb"
set "TOOL_CHECKSUM_MACOS_X64=4c9f52262a14da336e4a42ed24992d12d0c956acde87619e4611d321dffa602b"
set "TOOL_CHECKSUM_MACOS_ARM64=546f7f8a6c70ff13a3a9d2bc958db3427298cebf3e0cb756f9177133b7068843"

REM Download URLs (GitHub releases)
set "TOOL_URL_LINUX_X64=https://github.com/astral-sh/uv/releases/download/%TOOL_VERSION%/uv-x86_64-unknown-linux-gnu.tar.gz"
set "TOOL_URL_LINUX_ARM64=https://github.com/astral-sh/uv/releases/download/%TOOL_VERSION%/uv-aarch64-unknown-linux-gnu.tar.gz"
set "TOOL_URL_WINDOWS_X64=https://github.com/astral-sh/uv/releases/download/%TOOL_VERSION%/uv-x86_64-pc-windows-msvc.zip"
set "TOOL_URL_WINDOWS_ARM64=https://github.com/astral-sh/uv/releases/download/%TOOL_VERSION%/uv-aarch64-pc-windows-msvc.zip"
set "TOOL_URL_MACOS_X64=https://github.com/astral-sh/uv/releases/download/%TOOL_VERSION%/uv-x86_64-apple-darwin.tar.gz"
set "TOOL_URL_MACOS_ARM64=https://github.com/astral-sh/uv/releases/download/%TOOL_VERSION%/uv-aarch64-apple-darwin.tar.gz"

REM Binary path within extracted archive
set "TOOL_BINARY_UNIX=uv"
set "TOOL_BINARY_WINDOWS=uv.exe"

REM Invoke wrapper
call "%~dp0tool-wrapper.cmd" %*
exit /B %ERRORLEVEL%

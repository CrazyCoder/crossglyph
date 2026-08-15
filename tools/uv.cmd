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
export TOOL_VERSION="0.12.5"

# SHA-256 checksums for each platform
export TOOL_CHECKSUM_LINUX_X64="68a509da24b06b4223a1c0175fb5eb5bc79342b76cbeff0cfe51ac3f5b17b6b2"
export TOOL_CHECKSUM_LINUX_ARM64="9bf43b4d1a07665bf64d4c4e710930b382321a785e0eb10aac07f46471f86a31"
export TOOL_CHECKSUM_WINDOWS_X64="4c4d49d8738847d9b71ba319e49a5688c93eac0fe6204b1df24e98528dddf39a"
export TOOL_CHECKSUM_WINDOWS_ARM64="724279317fee6e5fa8ad1908e4eba2bbe764ef1ece5b3f4597927b62b1fe562a"
export TOOL_CHECKSUM_MACOS_X64="b3b2137477cf96c9686ebfb71524614cec780c673fd73e59bce099aef02e70e8"
export TOOL_CHECKSUM_MACOS_ARM64="5bb0e5fe008a773c3dbcb97ff79cd89e1241464fe9d2f986d52ad8f1b037bd62"

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
set "TOOL_VERSION=0.12.5"

REM SHA-256 checksums for each platform
set "TOOL_CHECKSUM_LINUX_X64=68a509da24b06b4223a1c0175fb5eb5bc79342b76cbeff0cfe51ac3f5b17b6b2"
set "TOOL_CHECKSUM_LINUX_ARM64=9bf43b4d1a07665bf64d4c4e710930b382321a785e0eb10aac07f46471f86a31"
set "TOOL_CHECKSUM_WINDOWS_X64=4c4d49d8738847d9b71ba319e49a5688c93eac0fe6204b1df24e98528dddf39a"
set "TOOL_CHECKSUM_WINDOWS_ARM64=724279317fee6e5fa8ad1908e4eba2bbe764ef1ece5b3f4597927b62b1fe562a"
set "TOOL_CHECKSUM_MACOS_X64=b3b2137477cf96c9686ebfb71524614cec780c673fd73e59bce099aef02e70e8"
set "TOOL_CHECKSUM_MACOS_ARM64=5bb0e5fe008a773c3dbcb97ff79cd89e1241464fe9d2f986d52ad8f1b037bd62"

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

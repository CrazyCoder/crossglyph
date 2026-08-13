# Tool Wrapper - PowerShell download/verify/execute logic for external tools
# See tool-wrapper.design.md for usage and environment variable reference

param(
    [switch]$VerifyAllPlatforms
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version 3.0

# Helper function for SHA256 hash (works with PowerShell 2.0+)
function Get-FileSHA256 {
    param([string]$Path)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        try {
            $hash = $sha256.ComputeHash($stream)
            return [BitConverter]::ToString($hash).Replace('-', '').ToLower()
        } finally {
            $stream.Close()
        }
    } finally {
        $sha256.Dispose()
    }
}

# Get binary path for platform
function Get-BinaryForPlatform {
    param([string]$Platform)
    if ($Platform -like 'WINDOWS_*') {
        return $env:TOOL_BINARY_WINDOWS
    } else {
        return $env:TOOL_BINARY_UNIX
    }
}

# List archive entries without extracting.
# Zip entries use forward slashes natively; tar.exe -tzf prints paths the same way.
function Get-ArchiveEntries {
    param([string]$Path, [string]$Url)
    if ($Url -match '\.zip$') {
        Add-Type -AssemblyName System.IO.Compression.FileSystem | Out-Null
        $zip = [System.IO.Compression.ZipFile]::OpenRead($Path)
        try {
            return @($zip.Entries | ForEach-Object { $_.FullName })
        } finally {
            $zip.Dispose()
        }
    } else {
        $windowsTar = "$env:SystemRoot\system32\tar.exe"
        return @(& $windowsTar -tzf $Path)
    }
}

# Detect "nested:<dir>" (single top-level entry) vs "flat" (multiple) from a
# flat list of archive entries. Ignores __MACOSX — macOS zip tooling emits it
# as a parallel resource-fork directory, and it would otherwise flip detection
# from nested to flat (see bun's bun-darwin-*.zip).
function Get-ArchiveStructure {
    param([string[]]$Entries)
    $topLevel = @($Entries |
        ForEach-Object { ($_ -split '[/\\]')[0] } |
        Where-Object { $_ -ne '' -and $_ -ne '__MACOSX' } |
        Sort-Object -Unique)
    if ($topLevel.Count -eq 1) {
        return @{ Structure = "nested:$($topLevel[0])"; TopLevel = $topLevel[0] }
    } else {
        return @{ Structure = 'flat'; TopLevel = $null }
    }
}

# Get environment variables
$toolName = $env:TOOL_NAME
$toolVersion = $env:TOOL_VERSION
$toolBinary = $env:TOOL_BINARY_WINDOWS
$targetDir = $env:TARGET_DIR
$flagFile = $env:FLAG_FILE

if ($VerifyAllPlatforms) {
    # Validate required environment variables
    if ([string]::IsNullOrEmpty($env:TOOL_NAME)) {
        Write-Host 'ERROR: TOOL_NAME not set' -ForegroundColor Red
        exit 1
    }
    if ([string]::IsNullOrEmpty($env:TOOL_VERSION)) {
        Write-Host 'ERROR: TOOL_VERSION not set' -ForegroundColor Red
        exit 1
    }
    if ([string]::IsNullOrEmpty($env:TOOL_BINARY_UNIX)) {
        Write-Host 'ERROR: TOOL_BINARY_UNIX not set' -ForegroundColor Red
        exit 1
    }
    if ([string]::IsNullOrEmpty($env:TOOL_BINARY_WINDOWS)) {
        Write-Host 'ERROR: TOOL_BINARY_WINDOWS not set' -ForegroundColor Red
        exit 1
    }

    # Verify all platforms mode
    $platforms = @(
        @{Name='LINUX_X64'; Checksum=$env:TOOL_CHECKSUM_LINUX_X64; Url=$env:TOOL_URL_LINUX_X64},
        @{Name='LINUX_ARM64'; Checksum=$env:TOOL_CHECKSUM_LINUX_ARM64; Url=$env:TOOL_URL_LINUX_ARM64},
        @{Name='WINDOWS_X64'; Checksum=$env:TOOL_CHECKSUM_WINDOWS_X64; Url=$env:TOOL_URL_WINDOWS_X64},
        @{Name='WINDOWS_ARM64'; Checksum=$env:TOOL_CHECKSUM_WINDOWS_ARM64; Url=$env:TOOL_URL_WINDOWS_ARM64},
        @{Name='MACOS_X64'; Checksum=$env:TOOL_CHECKSUM_MACOS_X64; Url=$env:TOOL_URL_MACOS_X64},
        @{Name='MACOS_ARM64'; Checksum=$env:TOOL_CHECKSUM_MACOS_ARM64; Url=$env:TOOL_URL_MACOS_ARM64}
    )

    $tempDir = Join-Path $env:TEMP ('tool-verify-' + [guid]::NewGuid().ToString())
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
    $allPassed = $true

    # Archives are cached under CACHE_DIR\_verify keyed by expected sha256.
    # When the wrapper's declared checksum changes (e.g. a version bump) the
    # cache key changes too, so stale archives can never satisfy a fresh
    # lookup — no invalidation needed. Set TOOL_VERIFY_NO_CACHE=1 to force
    # re-downloads (e.g. for bandwidth testing).
    $cacheRoot = if ($env:CACHE_DIR) { $env:CACHE_DIR } else { Join-Path $env:LOCALAPPDATA 'CrossGlyph\tools' }
    $verifyCacheDir = Join-Path $cacheRoot '_verify'
    if (-not (Test-Path $verifyCacheDir)) {
        New-Item -ItemType Directory -Path $verifyCacheDir -Force | Out-Null
    }

    Write-Host "=== Verifying all platforms for $toolName $toolVersion ===" -ForegroundColor Cyan
    Write-Host ''

    try {
        foreach ($p in $platforms) {
            Write-Host "Platform: $($p.Name)" -ForegroundColor Yellow
            Write-Host "  URL: $($p.Url)"
            Write-Host "  Expected: $($p.Checksum)"

            if ([string]::IsNullOrEmpty($p.Checksum) -or [string]::IsNullOrEmpty($p.Url)) {
                Write-Host '  Status:   FAIL (not configured - missing checksum or URL)' -ForegroundColor Red
                Write-Host ''
                $allPassed = $false
                continue
            }

            $cachedArchive = Join-Path $verifyCacheDir $p.Checksum
            $tempArchive = Join-Path $tempDir "$($p.Name).archive"
            $archivePath = $null
            $usedCache = $false

            try {
                if (-not $env:TOOL_VERIFY_NO_CACHE -and (Test-Path $cachedArchive)) {
                    $cachedSum = Get-FileSHA256 -Path $cachedArchive
                    if ($cachedSum -eq $p.Checksum) {
                        $archivePath = $cachedArchive
                        $usedCache = $true
                    } else {
                        Remove-Item -Path $cachedArchive -Force
                    }
                }

                if (-not $usedCache) {
                    $webClient = New-Object System.Net.WebClient
                    $webClient.DownloadFile($p.Url, $tempArchive)
                    $archivePath = $tempArchive
                }

                $actualChecksum = Get-FileSHA256 -Path $archivePath
                $fileSize = (Get-Item $archivePath).Length

                if ($usedCache) { Write-Host '  Cached:   yes' }
                Write-Host "  Actual:   $actualChecksum"
                Write-Host "  Size:     $fileSize bytes"

                if ($actualChecksum -ne $p.Checksum) {
                    Write-Host '  Status:   FAIL (checksum mismatch)' -ForegroundColor Red
                    $allPassed = $false
                    continue
                }

                # Listing-based check — avoids writing thousands of files for
                # large archives (e.g. go's ~70 MB zips). Binary path inside
                # the archive: "<nested>/<binary>" or just "<binary>" for flat.
                $entries = Get-ArchiveEntries -Path $archivePath -Url $p.Url
                $info = Get-ArchiveStructure -Entries $entries
                if ($info.Structure -eq 'flat') {
                    Write-Host '  Structure: flat (no top-level directory)'
                } else {
                    Write-Host "  Structure: nested (top-level: $($info.TopLevel))"
                }

                $platformBinary = Get-BinaryForPlatform -Platform $p.Name
                $binaryInArchive = ($platformBinary -replace '\\', '/')
                if ($info.Structure -ne 'flat') {
                    $binaryInArchive = "$($info.TopLevel)/$binaryInArchive"
                }
                $normalized = @($entries | ForEach-Object { $_ -replace '\\', '/' })

                if ($normalized -contains $binaryInArchive) {
                    Write-Host "  Binary:   $platformBinary (found)"
                    Write-Host '  Status:   PASS' -ForegroundColor Green
                } else {
                    Write-Host "  Binary:   $platformBinary (NOT FOUND)" -ForegroundColor Red
                    Write-Host '  Status:   FAIL (binary missing)' -ForegroundColor Red
                    $allPassed = $false
                }

                # Promote to cache only after checksum passes — never persist a bad archive.
                if (-not $usedCache -and -not $env:TOOL_VERIFY_NO_CACHE) {
                    Move-Item -Path $tempArchive -Destination $cachedArchive -Force
                }
            } catch {
                Write-Host "  Status:   FAIL (error: $_)" -ForegroundColor Red
                $allPassed = $false
            } finally {
                if ((Test-Path $tempArchive) -and ($tempArchive -ne $cachedArchive)) {
                    Remove-Item -Path $tempArchive -Force -ErrorAction SilentlyContinue
                }
            }

            Write-Host ''
        }
    } finally {
        if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue }
    }

    if ($allPassed) {
        Write-Host '=== All platforms verified successfully ===' -ForegroundColor Green
        exit 0
    } else {
        Write-Host '=== Some platforms failed verification ===' -ForegroundColor Red
        exit 1
    }
}

# Normal download mode
$url = $env:DOWNLOAD_URL
$expectedChecksum = $env:EXPECTED_CHECKSUM

$createdNew = $false
$mutexName = 'Global\tool-wrapper-' + $toolName
$mutex = New-Object System.Threading.Mutex($true, $mutexName, [ref]$createdNew)

if (-not $createdNew) {
    Write-Host "Waiting for another process to finish downloading $toolName..." -ForegroundColor Yellow
    [void]$mutex.WaitOne()
}

try {
    $binaryPath = Join-Path $targetDir $toolBinary
    if ((Test-Path $flagFile) -and ((Get-Content $flagFile -ErrorAction Ignore) -eq $expectedChecksum) -and (Test-Path $binaryPath)) {
        Write-Host 'Already downloaded (verified after lock)' -ForegroundColor Green
        exit 0
    }

    $tempDir = Join-Path $env:TEMP ('tool-wrapper-' + [guid]::NewGuid().ToString())
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

    try {
        $archivePath = Join-Path $tempDir 'archive.zip'

        Write-Host "Downloading $url" -ForegroundColor Cyan
        $webClient = New-Object System.Net.WebClient
        $webClient.DownloadFile($url, $archivePath)

        $actualChecksum = Get-FileSHA256 -Path $archivePath
        if ($actualChecksum -ne $expectedChecksum) {
            throw "Checksum mismatch`nExpected: $expectedChecksum`nActual:   $actualChecksum"
        }
        Write-Host "Checksum verified: $actualChecksum" -ForegroundColor Green

        $extractTemp = Join-Path $tempDir 'extract'
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::ExtractToDirectory($archivePath, $extractTemp)

        # Drop macOS zip metadata so nested-structure detection isn't fooled by it
        # (see bun's bun-darwin-*.zip). No-op for the usual Windows-only archives.
        $macosxMeta = Join-Path $extractTemp '__MACOSX'
        if (Test-Path $macosxMeta) { Remove-Item $macosxMeta -Recurse -Force -ErrorAction SilentlyContinue }

        $topLevel = @(Get-ChildItem -Path $extractTemp)
        $isNested = ($topLevel.Count -eq 1 -and $topLevel[0].PSIsContainer)

        # Try clean replace first; fall back to merge if files are locked
        $merged = $false
        if (Test-Path $targetDir) {
            try {
                Remove-Item -Path $targetDir -Recurse -Force
            } catch {
                # Locked files (e.g. node.exe in use) — merge new files in
                $merged = $true
            }
        }

        $parentDir = Split-Path $targetDir -Parent
        New-Item -ItemType Directory -Path $parentDir -Force | Out-Null
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

        $sourceDir = if ($isNested) { $topLevel[0].FullName } else { $extractTemp }
        if ($merged) {
            # Copy files individually so a locked file doesn't block the rest.
            # Locked files are identical (same version) so skipping them is safe.
            foreach ($item in Get-ChildItem -Path $sourceDir) {
                try {
                    if ($item.PSIsContainer) {
                        Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $targetDir $item.Name) -Recurse -Force
                    } else {
                        Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $targetDir $item.Name) -Force
                    }
                } catch [System.IO.IOException], [System.UnauthorizedAccessException] {
                    # Expected: locked files can't be overwritten (same version, identical content)
                }
            }
        } else {
            Get-ChildItem -Path $sourceDir | Move-Item -Destination $targetDir -Force
        }

        $binaryPath = Join-Path $targetDir $toolBinary
        if (-not (Test-Path $binaryPath)) {
            throw "Binary not found after extraction: $toolBinary"
        }

        Set-Content -Path $flagFile -Value $expectedChecksum
        Write-Host "Cached: $targetDir" -ForegroundColor Green
    }
    finally {
        if (Test-Path $tempDir) {
            Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
finally {
    $mutex.ReleaseMutex()
}

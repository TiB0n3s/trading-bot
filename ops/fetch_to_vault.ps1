#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Pull one trading day's bot_events ledger + run logs from the trading VM into
  the vault's 01-raw/ as an immutable, dated source bundle.

.DESCRIPTION
  One-way and read-only. Invokes the VM's pinned export_for_vault.sh forced
  command over SSH, captures the gzip-tar stream, and extracts it under
  01-raw/bot-export-<date>/. Never writes to the VM. Refuses to overwrite an
  existing dated bundle, preserving 01-raw immutability.

  After this lands a bundle, run /learn in the vault to compile it into the
  wiki. This script only does faithful transport — no synthesis.

.NOTES
  Requires the built-in Windows OpenSSH client (ssh.exe) and bsdtar (tar.exe),
  both present on Windows 10 1809+ / Windows 11.

.EXAMPLE
  ./fetch_to_vault.ps1                 # pull today
  ./fetch_to_vault.ps1 -Date 2026-06-17
#>
[CmdletBinding()]
param(
    [string]$Date   = (Get-Date -Format 'yyyy-MM-dd'),
    [string]$VmHost  = '192.168.99.28',
    [string]$VmUser  = 'tradingbot',
    [string]$SshKey  = "$HOME\.ssh\vault_pull",
    [string]$RawDir  = 'D:\AI Brain\Trading Project\01-raw'
)

$ErrorActionPreference = 'Stop'

if ($Date -notmatch '^\d{4}-\d{2}-\d{2}$') {
    throw "Date must be YYYY-MM-DD; got '$Date'"
}

$destDir = Join-Path $RawDir "bot-export-$Date"
if (Test-Path $destDir) {
    throw "01-raw already has '$destDir' — sources are immutable; refusing to overwrite. Remove it by hand if you truly mean to re-pull."
}
if (-not (Test-Path $RawDir)) {
    throw "Vault 01-raw not found at '$RawDir'."
}

# Capture the binary tar stream. NOTE: PowerShell's '>' / native pipelines
# re-encode text and corrupt gzip data, so we use Start-Process with a raw
# -RedirectStandardOutput (byte-faithful) into a temp file.
$tmpOut = New-TemporaryFile
$tmpErr = New-TemporaryFile
try {
    Write-Host "Pulling bot-export-$Date from $VmUser@$VmHost ..."
    $sshArgs = @(
        '-i', $SshKey,
        '-o', 'BatchMode=yes',                  # fail rather than prompt; forces key auth
        '-o', 'StrictHostKeyChecking=accept-new', # trust host key on first connect (verify fingerprint for stricter setups)
        "$VmUser@$VmHost",
        $Date                                   # arrives on the VM as $SSH_ORIGINAL_COMMAND
    )
    $p = Start-Process -FilePath ssh -ArgumentList $sshArgs `
        -RedirectStandardOutput $tmpOut -RedirectStandardError $tmpErr `
        -NoNewWindow -Wait -PassThru

    if ($p.ExitCode -ne 0) {
        $err = (Get-Content $tmpErr -Raw)
        throw "ssh export failed (exit $($p.ExitCode)): $err"
    }
    if ((Get-Item $tmpOut).Length -eq 0) {
        throw "empty bundle returned from VM"
    }

    New-Item -ItemType Directory -Path $destDir | Out-Null
    # bundle's top dir is bot-export-<date>/, so strip it into our dest of the same name.
    & tar -xzf $tmpOut -C $destDir --strip-components=1
    if ($LASTEXITCODE -ne 0) { throw "tar extract failed (exit $LASTEXITCODE)" }
}
finally {
    Remove-Item $tmpOut, $tmpErr -Force -ErrorAction SilentlyContinue
}

# Surface the manifest — especially the truncation flag (faithful-record check).
$manifestPath = Join-Path $destDir 'manifest.json'
if (Test-Path $manifestPath) {
    $m = Get-Content $manifestPath -Raw | ConvertFrom-Json
    Write-Host ""
    Write-Host "Pulled into $destDir"
    Write-Host ("  events for {0}: {1}" -f $m.date, $m.events_for_date)
    Write-Host ("  generated (UTC): {0}   bot commit: {1}" -f $m.generated_at_utc, $m.git_commit)
    if ($m.possibly_truncated) {
        Write-Warning "Ledger may be TRUNCATED (query hit limit $($m.event_query_limit)). Raise LIMIT in export_for_vault.sh and re-pull."
    }
} else {
    Write-Warning "No manifest.json in bundle — verify export_for_vault.sh ran fully on the VM."
}

Write-Host ""
Write-Host "Bundle is now an immutable source in 01-raw. Run /learn in the vault to compile it."

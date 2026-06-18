# setup_wsl_on_d.ps1
#
# STEP 0 of the migration — run this in a Windows Terminal (PowerShell) on the
# LOCAL PC, BEFORE migration/wsl_restore.sh.
#
# It relocates the Ubuntu WSL distro's virtual disk onto the 8TB D: drive and
# sizes WSL to use a generous share of this 32-CPU / 64GB host. After this, the
# ENTIRE Linux filesystem — code, the ~60GB SQLite DB, all runtime state —
# physically lives on D: and runs at native ext4 speed.
#
# Why not just point the project at D:\ (/mnt/d)? Because WSL reaches Windows
# drives through a slow translation layer that is unreliable for SQLite file
# locking + WAL — a real corruption risk for trades.db. The DB must live on
# ext4. Relocating the vhdx puts ext4 *on D:*, which is what we want.

$ErrorActionPreference = 'Stop'

# ---- adjust if desired -----------------------------------------------------
$Distro    = 'Ubuntu'                 # your default distro (from `wsl -l -v`)
$TargetDir = 'D:\WSL\Ubuntu'          # where ext4.vhdx will live, on the 8TB drive
$SwapPath  = 'D:\WSL\swap.vhdx'       # keep WSL swap on D: too
# Host has 32 logical CPUs / 64GB RAM. These leave Windows comfortable headroom.
$MemoryGB     = 48
$Processors   = 24
$SwapGB       = 16
# ---------------------------------------------------------------------------

Write-Host "==> WSL version check" -ForegroundColor Cyan
wsl --version

Write-Host "`n==> Shutting down WSL so the distro can be moved" -ForegroundColor Cyan
wsl --shutdown
Start-Sleep -Seconds 3

Write-Host "`n==> Creating target dir $TargetDir" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $SwapPath) | Out-Null

Write-Host "`n==> Relocating '$Distro' onto D: (copies the vhdx — may take a while)" -ForegroundColor Cyan
# In-place move; preserves the distro registration, users, and default user.
wsl --manage $Distro --move $TargetDir

Write-Host "`n==> Writing $env:USERPROFILE\.wslconfig (resource caps + swap on D:)" -ForegroundColor Cyan
$wslConfig = @"
[wsl2]
memory=${MemoryGB}GB
processors=$Processors
swap=${SwapGB}GB
swapFile=$($SwapPath -replace '\\','\\')
"@
Set-Content -Path (Join-Path $env:USERPROFILE '.wslconfig') -Value $wslConfig -Encoding ascii
Get-Content (Join-Path $env:USERPROFILE '.wslconfig')

Write-Host "`n==> Applying config" -ForegroundColor Cyan
wsl --shutdown
Start-Sleep -Seconds 3

Write-Host "`n==> Result" -ForegroundColor Cyan
wsl -l -v
Write-Host "`nDistro disk now at: $TargetDir\ext4.vhdx" -ForegroundColor Green
Write-Host "Next: open Ubuntu and run  bash migration/wsl_restore.sh" -ForegroundColor Green
Write-Host "Browse the Linux files from Windows at:  \\wsl.localhost\$Distro\home\tradingbot\trading-bot" -ForegroundColor Green

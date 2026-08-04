param(
    [string]$ReplayJson = 'D:\metro\output\unity_replay\clearance_50_complete.replay.json'
)

$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$player = Join-Path $project 'Builds\Windows\MetroStation3DReplay.exe'
if (-not (Test-Path -LiteralPath $player)) {
    & (Join-Path $PSScriptRoot 'build.ps1')
}
Start-Process -FilePath $player -ArgumentList @('--replay-json', $ReplayJson) -WindowStyle Normal

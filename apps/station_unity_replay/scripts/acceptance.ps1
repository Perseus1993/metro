param(
    [string]$ReplayJson = 'D:\metro\output\unity_replay\clearance_50_complete.replay.json',
    [int]$Seconds = 120
)

$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$player = Join-Path $project 'Builds\Windows\MetroStation3DReplay.exe'
$artifacts = Join-Path $project 'Artifacts'
$report = Join-Path $artifacts 'runtime-acceptance.json'
New-Item -ItemType Directory -Path $artifacts -Force | Out-Null
if (-not (Test-Path -LiteralPath $player)) {
    & (Join-Path $PSScriptRoot 'build.ps1')
}

$arguments = @(
    '--replay-json', $ReplayJson,
    '--acceptance-out', $report,
    '--acceptance-seconds', $Seconds,
    '-batchmode',
    '-screen-width', '1600',
    '-screen-height', '900',
    '-logFile', (Join-Path $artifacts 'runtime-acceptance.log')
)
$process = Start-Process -FilePath $player -ArgumentList $arguments -Wait -PassThru -WindowStyle Minimized
if ($process.ExitCode -ne 0) {
    throw "Unity runtime acceptance failed with exit code $($process.ExitCode)."
}
Get-Content -LiteralPath $report

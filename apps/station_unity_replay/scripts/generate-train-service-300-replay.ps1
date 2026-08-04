$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$python = Join-Path $workspace '.venv\Scripts\python.exe'
$outputDirectory = Join-Path $workspace 'output\unity_replay'
$replay = Join-Path $outputDirectory 'train_service_300.replay.json'
$tracks = Join-Path $outputDirectory 'train_service_300_tracks.js'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Workspace Python was not found: $python"
}

New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
$arguments = @(
    '-m', 'metro_station.adapters.simulation.cli',
    '--scenario-mode', 'operations',
    '--entry-count-hour', '18000',
    '--exit-count-hour', '0',
    '--transfer-count-hour', '0',
    '--minutes', '3',
    '--demand-minutes', '1',
    '--clearance-minutes', '2',
    '--tick-seconds', '5',
    '--group-size', '1',
    '--movement-backend', 'batched_jupedsim',
    '--clock-mode', 'physical',
    '--jupedsim-model', 'collision_free_speed',
    '--design-template', 'visual_demo_station',
    '--seed', '42',
    '--no-audit',
    '--tracks-out', $tracks,
    '--replay-json-out', $replay
)

Push-Location $workspace
try {
    & $python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python replay generation failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

$payload = Get-Content -Raw -LiteralPath $replay | ConvertFrom-Json
$snapshots = @($payload.simulation_trace.snapshots)
$boarding = @($snapshots | Where-Object { $_.trains[0].state -eq 'boarding' })
$departure = @($snapshots | Where-Object { $_.trains[0].departure_elapsed_seconds -eq 0 })
$agentCount = @($payload.agents).Count
$maxVisible = ($snapshots | ForEach-Object { @($_.passengers).Count } | Measure-Object -Maximum).Maximum
$maxBoardingVisible = ($boarding | ForEach-Object { @($_.passengers).Count } | Measure-Object -Maximum).Maximum

if ($agentCount -ne 300 -or $maxVisible -ne 300 -or $maxBoardingVisible -ne 300) {
    throw "Replay did not preserve 300 visible passengers during train service: agents=$agentCount max=$maxVisible boarding_max=$maxBoardingVisible"
}
if ($boarding.Count -eq 0 -or $departure.Count -eq 0) {
    throw 'Replay does not contain both authoritative boarding and departure train snapshots.'
}

Write-Output "Verified 300-passenger train service replay: $replay"
Write-Output "First boarding: $($boarding[0].time_seconds)s; first departure: $($departure[0].time_seconds)s"
Write-Output "Visible passengers during boarding: $maxBoardingVisible"

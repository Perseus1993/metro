$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$python = Join-Path $workspace '.venv\Scripts\python.exe'
$outputDirectory = Join-Path $workspace 'output\unity_replay'
$replay = Join-Path $outputDirectory 'train_service_demo.replay.json'
$tracks = Join-Path $outputDirectory 'train_service_demo_tracks.js'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Workspace Python was not found: $python"
}

New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
$arguments = @(
    '-m', 'metro_station.adapters.simulation.cli',
    '--scenario-mode', 'operations',
    '--entry-count-hour', '120',
    '--exit-count-hour', '0',
    '--transfer-count-hour', '0',
    '--minutes', '3',
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
$trainSnapshots = @($payload.simulation_trace.snapshots | Where-Object { $_.trains.Count -gt 0 })
$boarding = @($trainSnapshots | Where-Object { $_.trains[0].state -eq 'boarding' })
$departure = @($trainSnapshots | Where-Object { $_.trains[0].departure_elapsed_seconds -eq 0 })
if ($boarding.Count -eq 0 -or $departure.Count -eq 0) {
    throw 'Replay does not contain both authoritative boarding and departure train snapshots.'
}

Write-Output "Verified train service replay: $replay"
Write-Output "First boarding: $($boarding[0].time_seconds)s; first departure: $($departure[0].time_seconds)s"

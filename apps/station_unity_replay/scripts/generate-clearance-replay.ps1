$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$python = Join-Path $workspace '.venv\Scripts\python.exe'
$outputDirectory = Join-Path $workspace 'output\unity_replay'
$replay = Join-Path $outputDirectory 'clearance_300_complete.replay.json'
$tracks = Join-Path $outputDirectory 'clearance_300_complete_tracks.js'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Workspace Python was not found: $python"
}

New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
$arguments = @(
    '-m', 'metro_station.adapters.simulation.cli',
    '--scenario-mode', 'evacuation',
    '--initial-platform-persons', '300',
    '--entry-count-hour', '0',
    '--exit-count-hour', '0',
    '--transfer-count-hour', '0',
    '--minutes', '30',
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
$audit = $payload.clearance_audit
if (-not $audit.cleared -or $audit.total_agents -ne 300 -or $audit.remaining_agents -ne 0) {
    throw "Replay did not satisfy 300-person clearance acceptance: $($audit | ConvertTo-Json -Compress)"
}

Write-Output "Verified complete clearance replay: $replay"
Write-Output "Clearance time: $($audit.clearance_time_s)s; completed: $($audit.completed_agents)/$($audit.total_agents)"

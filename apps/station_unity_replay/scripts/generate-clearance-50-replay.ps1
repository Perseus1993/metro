$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $workspace '.venv\Scripts\python.exe'
$outputDirectory = Join-Path $workspace 'output\unity_replay'
$replay = Join-Path $outputDirectory 'clearance_50_complete.replay.json'
$tracks = Join-Path $outputDirectory 'clearance_50_complete_tracks.js'
$defaultReplay = Join-Path $project 'Assets\StreamingAssets\replay.json'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Workspace Python was not found: $python"
}

New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
$arguments = @(
    '-m', 'metro_station.adapters.simulation.cli',
    '--scenario-mode', 'evacuation',
    '--initial-platform-persons', '50',
    '--entry-count-hour', '0',
    '--exit-count-hour', '0',
    '--transfer-count-hour', '0',
    '--minutes', '30',
    '--tick-seconds', '1',
    '--group-size', '1',
    '--movement-backend', 'batched_jupedsim',
    '--clock-mode', 'physical',
    '--jupedsim-model', 'collision_free_speed',
    '--routing-algorithm', 'builtin_shortest_path',
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
if (-not $audit.cleared -or $audit.total_agents -ne 50 -or $audit.remaining_agents -ne 0) {
    throw "Replay did not satisfy 50-person clearance acceptance: $($audit | ConvertTo-Json -Compress)"
}
$fidelity = $payload.simulation_trace.metadata.replay_fidelity
$routing = $payload.simulation_trace.metadata.routing_evidence
if ($fidelity.position_authority -ne 'simulation_trace.snapshots' -or
    [double]$fidelity.snapshot_interval_seconds -gt 1.0) {
    throw "Replay is not a high-fidelity authoritative trace: $($fidelity | ConvertTo-Json -Compress)"
}
if ($routing.plugin_ids -notcontains 'metro.shortest_path' -or $routing.decision_count -le 0) {
    throw "Replay has no versioned routing evidence: $($routing | ConvertTo-Json -Compress)"
}
if ($null -ne $payload.visualization_bundle) {
    throw 'Unity replay must not contain presentation-only visual_tracks.'
}

Copy-Item -LiteralPath $replay -Destination $defaultReplay -Force
Write-Output "Verified complete 50-person clearance replay: $replay"
Write-Output "Installed as Unity default replay: $defaultReplay"
Write-Output "Clearance time: $($audit.clearance_time_s)s; completed: $($audit.completed_agents)/$($audit.total_agents)"
Write-Output "Trajectory fidelity: authoritative snapshots every $($fidelity.snapshot_interval_seconds)s"
Write-Output "Routing evidence: $($routing.plugin_ids -join ', '), decisions=$($routing.decision_count)"

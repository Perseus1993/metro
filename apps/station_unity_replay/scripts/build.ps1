$ErrorActionPreference = 'Stop'
$unity = 'C:\Unity\6000.3.18f1\Editor\Unity.exe'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$artifacts = Join-Path $project 'Artifacts'
$output = Join-Path $project 'Builds\Windows\MetroStation3DReplay.exe'
New-Item -ItemType Directory -Path $artifacts -Force | Out-Null

$arguments = @(
    '-batchmode',
    '-nographics',
    '-projectPath', $project,
    '-executeMethod', 'MetroReplay.Editor.BuildAutomation.BuildWindows',
    '-build-output', $output,
    '-logFile', (Join-Path $artifacts 'build.log'),
    '-quit'
)
$process = Start-Process -FilePath $unity -ArgumentList $arguments -Wait -PassThru

if ($process.ExitCode -ne 0) {
    throw "Unity Windows build failed with exit code $($process.ExitCode)."
}

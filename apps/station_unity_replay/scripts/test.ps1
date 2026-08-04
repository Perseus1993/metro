$ErrorActionPreference = 'Stop'
$unity = 'C:\Unity\6000.3.18f1\Editor\Unity.exe'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$artifacts = Join-Path $project 'Artifacts'
New-Item -ItemType Directory -Path $artifacts -Force | Out-Null

$arguments = @(
    '-batchmode',
    '-nographics',
    '-projectPath', $project,
    '-runTests',
    '-testPlatform', 'EditMode',
    '-testResults', (Join-Path $artifacts 'editmode-results.xml'),
    '-logFile', (Join-Path $artifacts 'editmode.log')
)
$process = Start-Process -FilePath $unity -ArgumentList $arguments -Wait -PassThru

if ($process.ExitCode -ne 0) {
    throw "Unity EditMode tests failed with exit code $($process.ExitCode)."
}

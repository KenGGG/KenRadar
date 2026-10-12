param(
    [Parameter(Mandatory=$true)][ValidateSet('start','stop','status','diagnose','init')][string]$Action,
    [Parameter(Mandatory=$true)][string]$Config,
    [string]$Python = ''
)
$ErrorActionPreference = 'Stop'
if (!$Python) {
    $Python = Join-Path $PSScriptRoot '.venv/python.exe'
    if (!(Test-Path -LiteralPath $Python)) { $Python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe' }
}
if (!(Test-Path -LiteralPath $Python)) { throw 'Project Python environment required; specify -Python explicitly.' }
Push-Location $PSScriptRoot
try {
    if ($Action -eq 'init') { & $Python -m kenradar --config $Config migrate }
    else { & $Python -m kenradar.runtime_control $Action --config $Config }
    if ($LASTEXITCODE -ne 0) { throw 'KenRadar operation failed; check runtime logs.' }
} finally { Pop-Location }

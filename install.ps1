param(
    [string]$PythonPath = '',
    [string]$EnvironmentPath = '.venv'
)
$ErrorActionPreference = 'Stop'
$repoRoot = $PSScriptRoot
if (-not $PythonPath) {
    $pythonCommand = Get-Command python -CommandType Application -ErrorAction SilentlyContinue
    if ($pythonCommand) { $PythonPath = $pythonCommand.Source }
}
$targetPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $EnvironmentPath))
$repoPrefix = $repoRoot.TrimEnd('\') + '\'
if (-not $targetPath.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'The environment must stay inside the KenRadar repository.'
}
if (Test-Path -LiteralPath $targetPath) {
    throw 'Environment already exists; choose a new EnvironmentPath inside this repository or reuse its interpreter.'
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw 'Interpreter not found; specify an installed Python 3.11 with -PythonPath.'
}
& $PythonPath -c "import sys; assert sys.version_info[:2] == (3, 11), 'Python 3.11 required'"
if ($LASTEXITCODE -ne 0) { throw 'Python version check failed.' }
& $PythonPath -m venv $targetPath
if ($LASTEXITCODE -ne 0) { throw 'Failed to create the project environment.' }
$projectPython = Join-Path $targetPath 'Scripts\python.exe'
& $projectPython -m pip install --require-hashes -r (Join-Path $repoRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Locked dependency installation failed; environment retained for diagnosis.' }
& $projectPython -c "import sqlite3; assert sqlite3.sqlite_version_info >= (3,51,3), 'SQLite is too old; use a verified Python/SQLite combination'; print('Python SQLite:', sqlite3.sqlite_version)"
if ($LASTEXITCODE -ne 0) { throw 'SQLite WAL baseline check failed; services were not started.' }
Write-Output "Environment ready: $projectPython. Initialize with an explicit isolated config; services were not started."

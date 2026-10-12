$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$auditRoot = Join-Path $workspace 'data/maintenance/cleanup-20261010'
if (Test-Path -LiteralPath $auditRoot) { throw 'Cleanup report already exists; inspect before rerunning.' }
New-Item -ItemType Directory -Path $auditRoot | Out-Null
$candidates = @('.pytest_cache', '.venv-install-check', 'data/install-wheels', 'data/tmp', 'data/validation', 'data/funasr_server.log', 'data/funasr_server.pid', 'data/funasr-start.lock', 'kenradar/web/frontend/src/components/ConfigEditor.tsx')
$candidates += Get-ChildItem -LiteralPath (Join-Path $workspace 'data') -Directory | Where-Object Name -Like 'pytest-*' | ForEach-Object { 'data/' + $_.Name }
$testRoot = Join-Path $workspace 'data/test-migration'
# Preserve only historical evidence and rollback snapshots, not fixture databases.
$keep = @('p0', 'ui', 'pages-recovery', 'query-benchmark-20261010', 'fresh-core-install-20261010')
$candidates += Get-ChildItem -LiteralPath $testRoot -Force | Where-Object Name -NotIn $keep | ForEach-Object { 'data/test-migration/' + $_.Name }
$candidates += @('data/test-migration/pages-recovery/source')
foreach ($dir in @('data/test-migration/ui','data/test-migration/query-benchmark-20261010','data/test-migration/fresh-core-install-20261010')) {
    $full = Join-Path $workspace $dir
    if (Test-Path -LiteralPath $full) {
        $candidates += Get-ChildItem -LiteralPath $full -Force | Where-Object { $_.PSIsContainer -or $_.Extension -notin @('.json','.jpg','.png') } | ForEach-Object { $dir + '/' + $_.Name }
    }
}
foreach ($dir in @('kenradar','scripts','tests')) {
    $candidates += Get-ChildItem -LiteralPath (Join-Path $workspace $dir) -Directory -Recurse | Where-Object Name -EQ '__pycache__' | ForEach-Object { [IO.Path]::GetRelativePath($workspace,$_.FullName) }
}
$records = @()
foreach ($relative in ($candidates | Select-Object -Unique)) {
    $target = [IO.Path]::GetFullPath((Join-Path $workspace $relative))
    if (!$target.StartsWith($workspace + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Target escapes workspace' }
    if (!(Test-Path -LiteralPath $target)) { continue }
    $item = Get-Item -LiteralPath $target -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Refusing linked target: $relative" }
    $files = if ($item.PSIsContainer) { @(Get-ChildItem -LiteralPath $target -File -Recurse -Force) } else { @($item) }
    $records += [pscustomobject]@{path=$relative; files=$files.Count; bytes=($files | Measure-Object Length -Sum).Sum}
}
$records | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $auditRoot 'removed.json') -Encoding utf8
foreach ($record in $records) {
    $target = [IO.Path]::GetFullPath((Join-Path $workspace $record.path))
    if (!$target.StartsWith($workspace + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Target escapes workspace' }
    Remove-Item -LiteralPath $target -Recurse -Force
}
[pscustomobject]@{targets=$records.Count; files=($records | Measure-Object files -Sum).Sum; freedMB=[math]::Round(($records | Measure-Object bytes -Sum).Sum/1MB,1)} | ConvertTo-Json

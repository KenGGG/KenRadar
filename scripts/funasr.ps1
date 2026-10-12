param([ValidateSet('start', 'status')][string]$Action = 'start')
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path $PSScriptRoot -Parent
$PythonBin = Join-Path $RepoRoot '.venv/python.exe'
if (!(Test-Path -LiteralPath $PythonBin)) { throw '请先安装仓库 .venv Python 环境' }
Push-Location $RepoRoot
try {
    $ControlCode = @'
import json
import sys
from pathlib import Path
import requests
from kenradar.core.config import AppConfig, load_config
from kenradar.core.funasr_service import FunASRServiceManager
from kenradar.core.gpu_scheduler import GpuResourceManager
p = Path('config/config.yaml')
c = load_config(p) if p.exists() else AppConfig({'ai': {'funasr': {'endpoint': 'http://127.0.0.1:18002/v1', 'startup_timeout_seconds': 900}}}, p)
manager = FunASRServiceManager(c)
if sys.argv[1] == 'start':
    with GpuResourceManager(c).gpu_task('funasr:start'):
        manager.ensure_available()
response = requests.get(manager._health_url(), timeout=5)
response.raise_for_status()
print(json.dumps(response.json(), ensure_ascii=False, indent=2))
'@
    & $PythonBin -c $ControlCode $Action
    if ($LASTEXITCODE -ne 0) { throw 'FunASR 操作失败，请查看 data/funasr_server.log' }
} finally { Pop-Location }

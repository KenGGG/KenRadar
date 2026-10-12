"""Actual Pagefind fixture build, never indexes repository/private content."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import pytest


def test_pagefind_uses_only_manifest_and_rejects_tampered_source(tmp_path):
    node = shutil.which('node')
    script = Path('kenradar/web/frontend/scripts/public-search-preview.mjs').resolve()
    if not node or not (script.parent.parent / 'node_modules/pagefind').exists():
        pytest.skip('repository-local Pagefind dependency is not installed')
    source = tmp_path / 'public-fixture'
    source.mkdir()
    body = '<!doctype html><html lang="zh-CN"><title>合成研究样本</title><body><h1>国债基金研究</h1><p>算力产业与金融资产。</p></body></html>'
    (source/'approved.html').write_text(body,encoding='utf-8')
    (source/'private.html').write_text('<html lang="zh-CN">不得被索引的私密标记</html>',encoding='utf-8')
    (source/'.env').write_text('API_KEY=fixture-secret',encoding='utf-8')
    manifest = tmp_path/'allowlist.json'
    manifest.write_text(json.dumps({'format':'kenradar-public-preview/1','files':[{'path':'approved.html','sha256':hashlib.sha256(body.encode()).hexdigest()}]}),encoding='utf-8')
    target = tmp_path/'preview'
    result = subprocess.run([node,str(script),str(source),str(manifest),str(target)],capture_output=True,text=True,timeout=45)
    assert result.returncode == 0, result.stderr
    assert (target/'pagefind/pagefind.js').is_file()
    assert (target/'approved.html').is_file()
    assert not (target/'private.html').exists() and not (target/'.env').exists()
    (source/'approved.html').write_text(body+'changed',encoding='utf-8')
    rejected = subprocess.run([node,str(script),str(source),str(manifest),str(tmp_path/'bad-preview')],capture_output=True,text=True,timeout=45)
    assert rejected.returncode != 0 and not (tmp_path/'bad-preview').exists()

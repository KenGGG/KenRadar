"""Read the existing independent Pages checkout without importing fake results."""
from __future__ import annotations

import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import unquote

from kenradar.integrations.privacy import artifact_privacy_snapshot, private_artifact


def archive_root(config):
    return config.resolve_path(config.get('publishing.github_pages.output_dir', './data/github_pages')).resolve()


def _contained(root, relative):
    relative = unquote(str(relative))
    if '\\' in relative or '\x00' in relative or ':' in relative:
        return None
    path = (root / relative).resolve()
    return path if path.is_relative_to(root) and path.is_file() else None


def archive_entries(config):
    root = archive_root(config)
    index = root / 'content-index.json'
    if not index.is_file():
        return []
    entries, seen = [], set()
    with artifact_privacy_snapshot(config):
        for item in json.loads(index.read_text(encoding='utf-8')).get('items', []):
            rel = str(item.get('relative_url') or '')
            path = _contained(root, rel)
            if not path or path.suffix.lower() != '.html' or private_artifact(path, config):
                continue
            if rel in seen:
                continue
            seen.add(rel)
            entries.append(item)
    return entries


def archive_file(config, relative):
    """Only serve catalog articles, navigation and the generated site's assets."""
    root = archive_root(config)
    path = _contained(root, relative)
    if not path or private_artifact(path, config):
        return None
    rel = path.relative_to(root).as_posix()
    if path.suffix.lower() == '.html':
        navigation = rel in ('index.html', 'sources.html') or (
            rel.startswith(('notes/', 'briefs/')) and path.name == 'index.html')
        if not navigation and rel not in {str(i.get('relative_url')) for i in archive_entries(config)}:
            return None
        payload = path.read_bytes()
        if re.search(rb'hermes_private\s*["\x27]?\s*[:=]\s*(true|1)', payload, re.I):
            return None
        return payload, 'text/html; charset=utf-8'
    if rel == 'content-index.json':
        return json.dumps({'schema_version': 1, 'items': archive_entries(config)}, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8'
    if rel.startswith(('assets/', 'pagefind/')) and path.suffix.lower() in (
        '.css', '.js', '.json', '.wasm', '.pf_fragment', '.pf_index', '.pf_meta', '.png', '.jpg', '.jpeg', '.webp', '.svg', '.woff', '.woff2'):
        return path.read_bytes(), mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    return None


def serve_archive(handler, config_path, path):
    from kenradar.core.config import load_config
    from kenradar.web.responses import error_response
    result = archive_file(load_config(config_path), path.removeprefix('/published/'))
    if result is None:
        error_response(handler, '公开归档文件不存在', 404)
        return
    payload, content_type = result
    handler.send_response(200)
    handler.send_header('Content-Type', content_type)
    handler.send_header('Content-Length', str(len(payload)))
    handler.send_header('X-Content-Type-Options', 'nosniff')
    handler.end_headers()
    if getattr(handler, 'command', 'GET') != 'HEAD':
        handler.wfile.write(payload)

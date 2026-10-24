"""Derive an isolated acceptance config without printing secrets or changing production."""
from copy import deepcopy
import argparse
import os
from pathlib import Path

import yaml
from kenradar.core.config import load_config


REPO = Path(__file__).resolve().parents[1]


def prepare(source, target, *, port=8876):
    original = load_config(source)
    root = Path(target).resolve()
    allowed = (REPO / 'data/test-migration/hermes-v1').resolve()
    if not root.is_relative_to(allowed):
        raise ValueError('Acceptance data must remain under data/test-migration/hermes-v1')
    destination = root / 'config/isolated.yaml'
    if destination.exists():
        raise ValueError('Refusing to overwrite an existing acceptance config')
    raw = deepcopy(original.raw)
    def absolute_paths(data):
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str) and value.startswith(('./', 'data/', 'config/', 'scripts/')) and any(word in key for word in ('path', 'dir', 'root', 'file', 'python')):
                    data[key] = str(original.resolve_path(value))
                elif isinstance(value, (dict, list)):
                    absolute_paths(value)
        elif isinstance(data, list):
            for item in data:
                absolute_paths(item)
    absolute_paths(raw)
    app = raw.setdefault('app', {})
    app.update(data_dir=str(root), database_url='sqlite:///' + (root / 'db/kenradar.sqlite3').as_posix(),
        web_base_url=f'http://127.0.0.1:{port}', web_password='')
    raw.setdefault('web', {})['password'] = ''
    raw['bloggers'] = []
    raw.setdefault('schedule', {}).update(enabled=False, source_radar_enabled=False)
    # Acceptance may consume an existing service, never manage/start one.
    raw.setdefault('ai', {}).setdefault('funasr', {})['managed'] = False
    raw['ai'].setdefault('qwen_asr', {})['start_on_fallback'] = False
    # Missing Whisper assets must never populate an inherited/default shared cache.
    raw['ai'].setdefault('whisper', {})['download_root'] = str(root / 'models/whisper')
    raw.setdefault('notification', {})['enabled'] = False
    raw['notification'].setdefault('channels', {}).setdefault('feishu', {})['enabled'] = False
    raw['notification']['channels']['feishu']['webhook_url'] = ''
    raw.setdefault('publishing', {}).setdefault('github_pages', {}).update(enabled=False, output_dir=str(root / 'pages'))
    raw['publishing'].setdefault('github_sync', {}).update(enabled=False, auto_commit=False, auto_push=False, repo_dir=str(root / 'pages'))
    raw.setdefault('output', {})['obsidian_root'] = str(root / 'archive')
    raw.setdefault('download', {})['path'] = str(root / 'media')
    raw.setdefault('sources', {}).setdefault('xiaoyuzhou', {}).update(audio_temp_dir=str(root / 'media'), auto_push_feishu=False)
    organizer = raw.setdefault('ai', {}).setdefault('organizer', {})
    organizer['rate_limit_dir'] = str(original.resolve_path(original.get('ai.organizer.rate_limit_dir', original.data_dir / 'runtime/rate_limits')))
    # Materialize only the existing provider credential into a local, ignored config.
    # Never copy a notification webhook or a production DATABASE_URL override.
    from kenradar.core.organizer import ContentOrganizer
    credential_resolver = ContentOrganizer(original)
    for provider in organizer.get('providers', []) or []:
        if isinstance(provider, dict):
            provider['api_key'] = credential_resolver._provider_api_key(provider)
    raw.setdefault('logging', {})['file'] = str(root / 'logs/kenradar.log')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding='utf-8')
    destination.chmod(0o600)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='config/config.yaml')
    parser.add_argument('--target', required=True)
    parser.add_argument('--port', type=int, default=8876)
    args = parser.parse_args()
    path = prepare(args.source, args.target, port=args.port)
    print('Isolated config prepared:', path)
    print('No database initialized or tasks submitted. Config contains local provider credentials; do not share it.')

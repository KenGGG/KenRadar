"""Durable private-artifact boundary shared by delivery and publication fallbacks."""
from pathlib import Path


def private_artifact(path, config=None):
    candidate = Path(path).resolve()
    if 'hermes-private' in {part.lower() for part in candidate.parts}:
        return True
    if candidate.is_file() and candidate.suffix.lower() in ('.md', '.markdown'):
        # A copied artifact retains its policy, independent of its new path.
        import yaml
        text = candidate.read_text(encoding='utf-8', errors='replace')
        if text.startswith('---'):
            try:
                metadata = yaml.safe_load(text.split('---', 2)[1]) or {}
                if isinstance(metadata, dict) and metadata.get('hermes_private') is True:
                    return True
            except (yaml.YAMLError, IndexError):
                return True  # Unknown frontmatter must not become public by accident.
    if config is not None and candidate.is_file():
        # Read-only SQLite lookup also protects legacy notes without frontmatter.
        from kenradar.storage.sqlite_engine import database_path
        import sqlite3
        url = config.database_url
        if url.startswith('sqlite:'):
            db_path = database_path(url)
            if db_path.is_file():
                from contextlib import closing
                with closing(sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
                    rows = conn.execute("SELECT n.note_path, c.content_id FROM content_item c "
                        "LEFT JOIN content_note n ON n.content_item_id=c.id "
                        "WHERE json_extract(c.extra, '$.hermes_private')=1").fetchall()
                for note_path, external_id in rows:
                    if (note_path and Path(note_path).resolve() == candidate) or str(external_id) in candidate.stem:
                        return True
    return False


def private_content(database, external_id, platform=None):
    if not external_id or not callable(getattr(database, 'find_content_item', None)):
        return False
    for code in ([platform] if platform else ['douyin', 'xiaoyuzhou']):
        content = database.find_content_item(code, str(external_id))
        if isinstance(content, dict) and (content.get('extra') or {}).get('hermes_private'):
            return True
    return False


def rendering_policy(workflow, external_id, platform):
    private = private_content(getattr(workflow, 'database', None), external_id, platform)
    isolated = private_artifact(workflow.config.get('output.obsidian_root', workflow.config.data_dir))
    if private and not isolated:
        raise ValueError('PRIVATE_CONTENT: legacy public rendering is forbidden')
    return private or isolated


def require_deliverable(bundle):
    content = (bundle or {}).get('content') or {}
    note = (bundle or {}).get('note') or {}
    if (content.get('extra') or {}).get('hermes_private') or private_artifact(note.get('note_path') or ''):
        raise ValueError('PRIVATE_CONTENT: external delivery is forbidden')

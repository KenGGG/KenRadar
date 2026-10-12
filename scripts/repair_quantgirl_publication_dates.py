"""Restore note publication dates from canonical source timestamps."""
from pathlib import Path
import re
import shutil
import hashlib
from sqlalchemy import update
from kenradar.core.config import load_config
from kenradar.core.workflow import Workflow
from kenradar.storage import create_database

def main():
    cfg = load_config('config/config.yaml')
    db = create_database(cfg)
    backup = cfg.resolve_path('data/test-migration/recovery-129/notes-before-publication-date-repair')
    with db.connect() as conn:
        rows = conn.execute("SELECT n.id,n.note_path,c.publish_time FROM content_note n JOIN content_item c ON c.id=n.content_item_id JOIN creator cr ON cr.id=c.creator_id WHERE cr.platform_uid=? AND n.note_type='content'", ('MS4wLjABAAAA_C2VXT1FT00QgTcH9v14uws4BQRaUXjKMP6JOD-UvWA',)).fetchall()
    assert len(rows) == 129
    changed=0
    for row in rows:
        stamp=Workflow._format_timestamp(row['publish_time'])
        assert stamp, row['note_path']
        path=Path(row['note_path']).resolve()
        assert path.is_relative_to((cfg.data_dir/'notes').resolve())
        text=path.read_text(encoding='utf-8')
        updated,count=re.subn(r'^published_at:.*$', 'published_at: "'+stamp+'"', text, count=1, flags=re.MULTILINE)
        assert count == 1
        if text != updated:
            backup.mkdir(parents=True,exist_ok=True)
            if not (backup/path.name).exists(): shutil.copy2(path,backup/path.name)
            path.write_text(updated,encoding='utf-8')
            t=db.table('content_note')
            if 'content_hash' in t.c:
                with db.connect(write=True) as conn:
                    conn.execute(update(t).where(t.c.id==row['id']).values(content_hash=hashlib.sha256(path.read_bytes()).hexdigest()))
            changed+=1
    print(f'Checked 129 original publication timestamps; repaired {changed} note frontmatter values.')

if __name__=='__main__': main()

"""Verify the requested recovery using current SQLite records and actual note files."""
from pathlib import Path
import json
from collections import Counter

from kenradar.core.config import load_config
from kenradar.storage import create_database


def main():
    db = create_database(load_config('config/config.yaml'))
    with db.connect() as conn:
        rows = [dict(row) for row in conn.execute("SELECT ci.content_id,t.status AS transcript_status,t.text_content,a.status AS ai_status,n.note_path,ci.status AS content_status FROM content_item ci JOIN creator cr ON cr.id=ci.creator_id LEFT JOIN transcript t ON t.content_item_id=ci.id LEFT JOIN ai_analysis a ON a.content_item_id=ci.id AND a.analysis_type='summary' LEFT JOIN content_note n ON n.content_item_id=ci.id AND n.note_type='content' WHERE cr.platform_uid=?",
            ('MS4wLjABAAAA_C2VXT1FT00QgTcH9v14uws4BQRaUXjKMP6JOD-UvWA',)).fetchall()]
    problems = []
    required = ['一、内容简述', '二、分段原文', '三、知识关联', '四、视频原始转录', '> [!summary]']
    paths = []
    for row in rows:
        path = Path(row['note_path']) if row['note_path'] else None
        if row['transcript_status'] != 'success' or row['ai_status'] != 'success' or not path or not path.is_file():
            problems.append({'id': row['content_id'], 'reason': 'incomplete current result'})
            continue
        text = path.read_text(encoding='utf-8')
        if not all(section in text for section in required):
            problems.append({'id': row['content_id'], 'reason': 'missing required note sections'})
        if str(row['content_id']) not in text or not row['text_content'] or row['text_content'].strip() not in text:
            problems.append({'id': row['content_id'], 'reason': 'missing original transcript or identity'})
        paths.append(str(path.resolve()))
    result = {'total': len(rows), 'transcripts': dict(Counter(row['transcript_status'] for row in rows)),
        'analyses': dict(Counter(row['ai_status'] for row in rows)), 'unique_current_notes': len(set(paths)),
        'non_speech_items': [row['content_id'] for row in rows if str(row['text_content']).startswith('【无可转录语音】')],
        'problems': problems}
    Path('data/test-migration/recovery-129/final-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))
    if len(rows)!=129 or len(set(paths))!=129 or problems:
        raise SystemExit(1)


if __name__=='__main__':
    main()

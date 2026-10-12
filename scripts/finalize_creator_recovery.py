"""Reconcile current research items only after all 129 real results are verified."""
from collections import Counter
import hashlib
import json
from pathlib import Path
from sqlalchemy import update

from kenradar.core.config import load_config
from kenradar.storage import create_database
from scripts.verify_creator_recovery import main as verify


def main():
    verify()
    config=load_config('config/config.yaml')
    db=create_database(config)
    root=config.resolve_path('data/test-migration/recovery-129')
    notes_root=(config.data_dir/'notes').resolve()
    annotations={
        '7282422173682224421': '该短片音轨主要是英文配乐；分段原文保留 ASR 结果，不代表博主的中文讲解。作品介绍与音轨转录应分别理解，不据此补造完整研究论述。',
        '7055981437790555392': '原视频经语音活动检测为 0 秒语音，配乐为主；Whisper 重复幻觉已拒绝。原始转录小节明确记录无可辨识口播，不存在可补造的口播原文。',
    }
    n=db.table('content_note')
    for aid,notice in annotations.items():
        with db.connect() as conn:
            row=dict(conn.execute("SELECT n.id,n.note_path FROM content_note n JOIN content_item c ON c.id=n.content_item_id WHERE c.content_id=? AND n.note_type='content'",(aid,)).fetchone())
        path=Path(row['note_path']).resolve()
        assert path.is_relative_to(notes_root)
        text=path.read_text(encoding='utf-8')
        marker='> [!info] 转录说明'
        if marker not in text:
            text=text.replace('## 一、内容简述',marker+'\n> '+notice+'\n\n## 一、内容简述',1)
            path.write_text(text,encoding='utf-8')
            if 'content_hash' in n.c:
                with db.connect(write=True) as conn:
                    conn.execute(update(n).where(n.c.id==row['id']).values(content_hash=hashlib.sha256(path.read_bytes()).hexdigest()))
    before=[]
    for job_id in (1,3):
        items=db.list_research_job_items(job_id,limit=10000)
        before.extend({'job_id':job_id,**item} for item in items)
        for item in items:
            assert item['summary_status']=='success' and item['transcript_status']=='success'
            if item['status']!='skipped':
                db.upsert_research_job_item(job_id,item['aweme_id'],'success',None)
        counts=Counter(item['status'] for item in db.list_research_job_items(job_id,limit=10000))
        db.update_research_job(job_id,status='success',success_count=counts['success'],failed_count=0,skipped_count=counts['skipped'],pending_count=0,last_error=None)
    (root/'research-items-before-reconciliation.json').write_text(json.dumps(before,ensure_ascii=False,default=str,indent=2),encoding='utf-8')
    verify()
    print('Current research items reconciled; historical task attempts and backups retained.')


if __name__=='__main__':
    main()

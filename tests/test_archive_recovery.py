import hashlib
import json
import sqlite3

import pytest

from test_sqlite_v2 import sqlite_db
from kenradar.storage.archive_recovery import html_article_to_markdown, identity, import_note


def candidate(tmp_path, external="7000000000000000001", kind="git-original"):
    path = tmp_path / (external + ".md")
    path.write_text('---\nplatform: 抖音\ncreator: test\nvideo_id: "' + external +
                    '"\ntitle: Recovered\n---\n## 一、内容简述\nExisting analysis\n'
                    '## 四、视频原始转录\nOriginal ASR retained\n', encoding="utf8")
    return dict(platform="抖音", external_id=external, source_file=str(path),
                relative_path="notes/douyin/test/" + path.name, kind=kind,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(), provenance={"test": True})


def test_import_is_insert_only_idempotent_and_does_not_enqueue(sqlite_db, tmp_path):
    db, _ = sqlite_db
    conn = sqlite3.connect(db.path)
    item = candidate(tmp_path)
    assert import_note(conn, tmp_path / "official", item) == "imported"
    assert import_note(conn, tmp_path / "official", item) == "existing_content"
    assert conn.execute("select count(*) from task_run").fetchone()[0] == 0
    assert conn.execute("select text_content from transcript").fetchone()[0] == "Original ASR retained"
    note = conn.execute("select note_path from content_note").fetchone()[0]
    from pathlib import Path
    assert Path(note).read_bytes() == Path(item["source_file"]).read_bytes()
    assert conn.execute("select code from platform where id=(select platform_id from content_item)").fetchone()[0] == "douyin"
    conn.close()


def test_active_tasks_private_markers_and_path_traversal(sqlite_db, tmp_path):
    db, _ = sqlite_db
    conn = sqlite3.connect(db.path)
    item = candidate(tmp_path)
    conn.execute("insert into task_run(task_type,payload_json,status) values ('process_url',?,'queued')",
                 (json.dumps({"external_content_id": item["external_id"]}),))
    conn.commit()
    assert import_note(conn, tmp_path / "official", item) == "active_task"
    item["relative_path"] = "../escape.md"
    with pytest.raises(ValueError, match="Unsafe"):
        import_note(conn, tmp_path / "official", item)
    private = candidate(tmp_path, "7000000000000000002")
    from pathlib import Path
    p = Path(private["source_file"])
    p.write_text(p.read_text(encoding="utf8").replace('platform:', 'hermes_private: true\nplatform:'), encoding="utf8")
    private["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
    assert import_note(conn, tmp_path / "official", private) == "private"
    assert conn.execute("select count(*) from content_item").fetchone()[0] == 0
    conn.close()


def test_pages_import_does_not_invent_transcript(sqlite_db, tmp_path):
    db, _ = sqlite_db
    conn = sqlite3.connect(db.path)
    assert import_note(conn, tmp_path / "official", candidate(tmp_path, kind="pages-html")) == "imported"
    assert conn.execute("select count(*) from transcript").fetchone()[0] == 0
    conn.close()


def test_html_body_keeps_collapsed_text_and_excludes_navigation():
    html = '<nav>Not article</nav><div class="article-copy"><h2>Heading</h2><p>Historical article text remains intact.</p><details><summary>Raw transcript</summary><p>Original words in collapsed area.</p></details><script>bad()</script><a href="../source.html">Source</a></div>'
    result = html_article_to_markdown(html, "https://example.com/notes/post.html")
    assert "Original words" in result and "Not article" not in result and "bad()" not in result
    assert "https://example.com/source.html" in result
    with pytest.raises(ValueError):
        html_article_to_markdown('<nav>Only navigation</nav>', 'https://example.com')
    assert identity("抖音", "", "note_7000000000000000001.html") == ("douyin", "7000000000000000001")
    assert identity("douyin", "", "note_6a0c4d261b7bd5029572c64a.html") == ("xiaoyuzhou", "6a0c4d261b7bd5029572c64a")
    assert identity("douyin", "ckdpuemqyjm990862tkhllsyh") == ("xiaoyuzhou", "ckdpuemqyjm990862tkhllsyh")


def test_brief_tables_and_short_messages_remain_readable():
    html = '<div class="article-copy"><table><thead><tr><th>Title</th><th>Link</th></tr></thead><tbody><tr><td>A</td><td><a href="/a">Read</a></td></tr></tbody></table></div>'
    result = html_article_to_markdown(html, "https://example.com")
    assert "| Title | Link |\n| --- | --- |\n| A | [Read](https://example.com/a) |" in result
    assert html_article_to_markdown('<div class="article-copy"><p>本次无更新。</p></div>', 'https://example.com').strip() == "本次无更新。"

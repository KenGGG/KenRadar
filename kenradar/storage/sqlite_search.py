"""Rebuildable private trigram index. Canonical V2 tables remain authoritative."""
from sqlalchemy import column, select, table

INDEX = "content_search"


def rebuild(db):
    # Index maintenance runs locally in one explicit transaction; no model calls.
    with db.connect(write=True) as conn:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS content_search USING fts5(body, tokenize='trigram')")
        conn.execute("CREATE VIEW IF NOT EXISTS content_search_source AS SELECT ci.id, ci.creator_id, coalesce(ci.title,'') || char(10) || coalesce(cr.nickname,'') || char(10) || coalesce(ai.result_text,'') || char(10) || coalesce(tr.text_content,'') AS body FROM content_item ci JOIN creator cr ON cr.id=ci.creator_id LEFT JOIN ai_analysis ai ON ai.content_item_id=ci.id AND ai.analysis_type='summary' LEFT JOIN transcript tr ON tr.content_item_id=ci.id")
        conn.execute("DELETE FROM content_search")
        conn.execute("INSERT INTO content_search(rowid,body) SELECT id,body FROM content_search_source")
        for name in ("content_item", "ai_analysis", "transcript", "creator"):
            for operation in ("INSERT", "UPDATE", "DELETE"):
                reference = "old" if operation == "DELETE" else "new"
                if name == "creator":
                    predicate = f"creator_id={reference}.id"
                elif name == "content_item":
                    predicate = f"id={reference}.id"
                else:
                    predicate = f"id={reference}.content_item_id"
                trigger = f"kr_search_{name}_{operation.lower()}"
                # All identifiers above are constants, never supplied by a caller.
                removed = f"rowid={reference}.id" if name == "content_item" else f"rowid IN (SELECT id FROM content_search_source WHERE {predicate})"
                conn.execute(f"CREATE TRIGGER IF NOT EXISTS {trigger} AFTER {operation} ON {name} BEGIN DELETE FROM content_search WHERE {removed}; INSERT INTO content_search(rowid,body) SELECT id,body FROM content_search_source WHERE {predicate}; END")
        return conn.execute("SELECT count(*) FROM content_search").fetchone()[0]


def candidate_ids(db, keyword):
    if len(keyword) < 3 or any(char in keyword for char in ("%", "_", "\\")):
        return None
    with db.connect() as conn:
        present = conn.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name='content_search'").fetchone()
    if not present:
        return None
    fts = table(INDEX, column("rowid"), column("body"))
    return select(fts.c.rowid).where(fts.c.body.like("%" + keyword + "%"))

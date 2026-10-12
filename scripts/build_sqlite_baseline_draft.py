"""Development-only DDL inventory extractor. Output requires review/testing.

Does not execute a PostgreSQL migration or translate runtime SQL. The frozen
SQLite baseline, not this script, is the SQLite schema version source.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def split_fields(body: str) -> list[str]:
    return re.split(r",\s*(?![^()]*\))(?=(?:[^']*'[^']*')*[^']*$)", body)


def main() -> None:
    source = ast.parse((ROOT / "kenradar/storage/pg_database.py").read_text(encoding="utf-8"))
    schema = next(ast.literal_eval(n.value) for n in source.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "SCHEMA_SQL" for t in n.targets))
    texts = [schema]
    for path in sorted((ROOT / "kenradar/storage/migrations/versions").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        upgrade = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade"), None)
        if upgrade:
            texts += [n.value for n in ast.walk(upgrade) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    tables: dict[str, list[str]] = {}
    for text in texts:
        for match in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\)\s*(?:;|$)", text, re.S):
            tables.setdefault(match[1], [f.strip() for f in split_fields(match[2]) if f.strip()])
        for match in re.finditer(r"ALTER TABLE (\w+)\s+(ADD COLUMN IF NOT EXISTS .*?)(?:;|$)", text, re.S):
            for field in re.split(r",\s*ADD COLUMN IF NOT EXISTS ", match[2].removeprefix("ADD COLUMN IF NOT EXISTS ")):
                field = field.strip()
                if "DROP " in field or "ALTER " in field:
                    continue
                name = field.split()[0]
                if match[1] in tables and not any(f.split()[0] == name for f in tables[match[1]]):
                    tables[match[1]].append(field)
    def convert(field: str) -> str:
        field = re.sub(r"\b(?:BIGSERIAL|SERIAL)\b", "INTEGER", field)
        field = re.sub(r"\b(?:BIGINT|INT)\b", "INTEGER", field)
        field = re.sub(r"VARCHAR\(\d+\)|\bTIMESTAMPTZ\b|\bDATE\b", "TEXT", field)
        field = field.replace("DOUBLE PRECISION", "REAL").replace("BOOLEAN", "INTEGER")
        is_json = "JSONB" in field
        field = field.replace("JSONB", "TEXT").replace("::jsonb", "")
        field = field.replace("NOW()", "(strftime('%Y-%m-%dT%H:%M:%f000Z','now'))")
        field = re.sub(r"\bTRUE\b", "1", field)
        field = re.sub(r"\bFALSE\b", "0", field)
        if is_json:
            name = field.split()[0]
            field += f" CHECK ({name} IS NULL OR json_valid({name}))"
        return field
    # Current V2 status constraint. Delivery defaults are deliberately opt-in.
    tables["task_run"] += ["lease_token TEXT", "config_revision TEXT", "CHECK (status IN ('queued','running','retry_wait','paused','success','failed','cancelled'))"]
    tables["task_attempt"] += ["lease_token TEXT"]
    tables["task_step"] += ["lease_token TEXT", "FOREIGN KEY(content_item_id) REFERENCES content_item(id)"]
    tables["outbox_event"] += ["locked_at TIMESTAMPTZ", "lease_token TEXT"]
    tables["transcript_revision"] = ["id INTEGER PRIMARY KEY", "content_item_id INTEGER NOT NULL REFERENCES content_item(id)",
                                      "text_content TEXT NOT NULL", "record_json JSONB NOT NULL", "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"]
    output = "-- UNREVIEWED development draft extracted from PG 0018. Never run automatically.\n"
    for name, fields in tables.items():
        fields = [convert(f) for f in fields]
        fields.sort(key=lambda f: f.startswith(('UNIQUE', 'CHECK', 'FOREIGN KEY')))
        output += f"CREATE TABLE {name} (\n    " + ",\n    ".join(fields) + "\n);\n\n"
    for text in texts:
        for stmt in re.findall(r"CREATE (?:UNIQUE )?INDEX IF NOT EXISTS .*?(?:;|$)", text, re.S):
            stmt = stmt.rstrip("; ")
            if "content_curation" in stmt or "DO " in stmt:
                continue
            output += stmt + ";\n"
    output += "CREATE INDEX IF NOT EXISTS idx_transcript_revision_content ON transcript_revision(content_item_id,id);\n"
    target = ROOT / "data/test-migration/schema-draft/baseline.sql"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(output, encoding="utf-8")
    print(f"Draft: {len(tables)} tables; review {target}")


if __name__ == "__main__":
    main()

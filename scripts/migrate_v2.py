"""Source export / offline import / backup / restore. Never activates a target."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Run as `python -m scripts.migrate_v2` so repository imports stay in this repo.
from kenradar.storage.offline_migration import export_postgres, import_snapshot
from kenradar.storage.sqlite_backup import backup_database, restore_snapshot, backup_application, restore_application


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    source = sub.add_parser("export-pg")
    source.add_argument("--dsn-env", default="KENRADAR_MIGRATION_PG_URL")
    source.add_argument("--package", required=True)
    source.add_argument("--data-root")
    source.add_argument("--writers-stopped", action="store_true")
    target = sub.add_parser("import")
    target.add_argument("--package", required=True)
    target.add_argument("--target", required=True)
    target.add_argument("--path-map", help="JSON file containing explicit old-root -> new-root mappings")
    target.add_argument("--resume", action="store_true")
    for command in ("backup", "restore"):
        child = sub.add_parser(command)
        child.add_argument("--source", required=True)
        child.add_argument("--target", required=True)
    full = sub.add_parser("backup-app")
    full.add_argument("--config", required=True)
    full.add_argument("--package", required=True)
    full.add_argument("--writers-stopped", action="store_true")
    restore = sub.add_parser("restore-app")
    restore.add_argument("--package", required=True)
    restore.add_argument("--target", required=True)
    restore.add_argument("--data-root", required=True)
    args = parser.parse_args()
    if args.command == "export-pg":
        dsn = os.getenv(args.dsn_env, "")
        if not dsn:
            parser.error("缺少指定的 PG URL 环境变量；不在命令行显示凭据")
        result = export_postgres(dsn, args.package, data_root=args.data_root, writers_stopped=args.writers_stopped)
    elif args.command == "import":
        mappings = json.loads(Path(args.path_map).read_text(encoding="utf-8")) if args.path_map else {}
        result = import_snapshot(args.package, args.target, mappings, resume=args.resume)
    elif args.command == "backup":
        result = backup_database(args.source, args.target)
    elif args.command == "backup-app":
        from kenradar.core.config import load_config
        result = backup_application(load_config(args.config), args.package, writers_stopped=args.writers_stopped)
    elif args.command == "restore-app":
        result = restore_application(args.package, args.target, args.data_root)
    else:
        result = restore_snapshot(args.source, args.target)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # DSNs/row values from driver exceptions may contain secrets. Details
        # remain local through debugger; CLI shows a bounded diagnostic type.
        print(f"迁移操作未完成: {type(exc).__name__}；原始库和生产配置未替换", file=sys.stderr)
        raise SystemExit(1)

#!/usr/bin/env bash
# KenRadar PostgreSQL 备份脚本
# 用法: ./scripts/backup_pg.sh [备份目录]
set -euo pipefail

BACKUP_DIR="${1:-./data/backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DB_URL="${DATABASE_URL:-}"

if [ -z "$DB_URL" ]; then
  if [ -f .env ]; then
    set -a; source .env; set +a
    DB_URL="${DATABASE_URL:-}"
  fi
fi

if [ -z "$DB_URL" ]; then
  echo "错误: 未设置 DATABASE_URL (在环境变量或 .env 文件中)"
  exit 1
fi

mkdir -p "$BACKUP_DIR"
BACKUP_FILE="$BACKUP_DIR/kenradar_$TIMESTAMP.sql.gz"

echo "备份中... -> $BACKUP_FILE"
pg_dump "$DB_URL" | gzip > "$BACKUP_FILE"
echo "完成: $(du -h "$BACKUP_FILE" | cut -f1)"

# 清理 7 天前的备份
find "$BACKUP_DIR" -name "kenradar_*.sql.gz" -mtime +7 -delete
echo "保留 $(find "$BACKUP_DIR" -name 'kenradar_*.sql.gz' | wc -l) 个备份文件"

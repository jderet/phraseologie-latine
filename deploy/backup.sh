#!/bin/sh
# Daily backup of the whole PostgreSQL database (pg_dump custom format, compressed).
# The dump is checked with pg_restore before it is kept; backups older than
# BACKUP_RETENTION_DAYS are deleted, as the privacy policy promises.
#   deploy/backup.sh
# Procedures and schedule: docs/exploitation.md.
set -eu

cd "$(dirname "$0")/.."
COMPOSE="${COMPOSE:-docker compose}"
BACKUP_DIR="${BACKUP_DIR:-backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

mkdir -p "$BACKUP_DIR"
name="phraseologie-$(date -u +%Y%m%dT%H%M%SZ).dump"
partial="$BACKUP_DIR/.$name.partial"
trap 'rm -f "$partial"' EXIT

$COMPOSE exec -T db sh -c 'pg_dump --username="$POSTGRES_USER" --format=custom "$POSTGRES_DB"' \
  > "$partial"
# A dump that pg_restore cannot read is not a backup.
$COMPOSE exec -T db pg_restore --list < "$partial" > /dev/null
mv "$partial" "$BACKUP_DIR/$name"

# -mtime +N matches files at least N + 1 full days old.
find "$BACKUP_DIR" -name 'phraseologie-*.dump' -mtime +"$((RETENTION_DAYS - 1))" -delete

echo "$BACKUP_DIR/$name"

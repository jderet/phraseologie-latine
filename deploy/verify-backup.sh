#!/bin/sh
# Check that backups can be restored: take a new backup (or use the one given), restore it
# into a temporary database, compare the number of rows of every table with the database
# in service, then drop the temporary database.
#   deploy/verify-backup.sh                 new backup, compared at once
#   deploy/verify-backup.sh BACKUP_FILE     older backup: later changes show as differences
set -eu

here="$(cd "$(dirname "$0")" && pwd)"
backup=""
if [ "$#" -ge 1 ]; then
  backup="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
fi
cd "$here/.."
COMPOSE="${COMPOSE:-docker compose}"
target=phraseologie_verification

run_sql() { # DATABASE (empty: the database in service); SQL on standard input
  $COMPOSE exec -T db sh -c \
    'psql --username="$POSTGRES_USER" --dbname="${1:-$POSTGRES_DB}" --tuples-only --no-align --quiet' \
    sh "$1"
}

count_rows() { # DATABASE: one line "table rows" per table, exact counts
  run_sql "$1" <<'SQL'
select table_name || ' ' || (xpath('/row/n/text()', query_to_xml(
  format('select count(*) as n from public.%I', table_name), false, true, '')))[1]::text
from information_schema.tables
where table_schema = 'public' and table_type = 'BASE TABLE'
order by table_name;
SQL
}

if [ -n "$(echo "select 1 from pg_database where datname = '$target';" | run_sql "")" ]; then
  echo "La base $target existe déjà : supprimez-la ou vérifiez ce qu'elle contient." >&2
  exit 1
fi

live="$(mktemp)"
restored="$(mktemp)"
cleanup() {
  rm -f "$live" "$restored"
  $COMPOSE exec -T db sh -c 'dropdb --username="$POSTGRES_USER" --if-exists "$1"' sh "$target"
}
trap cleanup EXIT

if [ -z "$backup" ]; then
  backup="$(pwd)/$("$here/backup.sh")"
fi
"$here/restore.sh" "$backup" "$target"
count_rows "" > "$live"
count_rows "$target" > "$restored"

if diff "$live" "$restored"; then
  tables="$(wc -l < "$live" | tr -d ' ')"
  rows="$(awk '{ total += $2 } END { print total }' "$live")"
  echo "Sauvegarde vérifiée : $(basename "$backup"), $tables tables et $rows lignes identiques."
else
  echo "La base restaurée diffère de la base en service (lignes < en service, > restaurée)." >&2
  exit 1
fi

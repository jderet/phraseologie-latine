#!/bin/sh
# Restore a backup into a new database. It never overwrites data: the database must not
# exist yet.
#   deploy/restore.sh BACKUP_FILE DATABASE
# To put a backup back into service, follow docs/exploitation.md.
set -eu

if [ "$#" -ne 2 ]; then
  echo "Usage : $0 SAUVEGARDE BASE" >&2
  exit 2
fi
backup="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
target="$2"
case "$target" in
  "" | *[!a-z0-9_]*)
    echo "Nom de base invalide (minuscules, chiffres et _ seulement) : $target" >&2
    exit 2
    ;;
esac

cd "$(dirname "$0")/.."
COMPOSE="${COMPOSE:-docker compose}"

$COMPOSE exec -T db sh -c 'createdb --username="$POSTGRES_USER" "$1"' sh "$target"
$COMPOSE exec -T db sh -c \
  'pg_restore --username="$POSTGRES_USER" --dbname="$1" --no-owner --exit-on-error --single-transaction' \
  sh "$target" < "$backup"

echo "Sauvegarde $(basename "$backup") restaurée dans la base $target."

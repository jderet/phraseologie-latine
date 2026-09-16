#!/bin/bash
# Start the site for local work: PostgreSQL, migrations, then the development server.
# Double-click this file in the Finder, or run ./lancer-le-site.command [port].
set -u
cd "$(dirname "$0")" || exit 1
PORT="${1:-8001}"
URL="http://127.0.0.1:$PORT/"

fail() {
  echo
  echo "⚠️  $1"
  echo
  read -r -p "Appuie sur Entrée pour fermer. " _
  exit 1
}

if [ ! -x .venv/bin/python ]; then
  fail "L’environnement Python est absent (.venv). Demande à Claude de le réinstaller."
fi

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Le site tourne déjà sur le port $PORT."
  echo "Ouvre $URL dans le navigateur."
  open "$URL" 2>/dev/null
  exit 0
fi

echo "1/3 · Base de données PostgreSQL…"
if ! docker info >/dev/null 2>&1; then
  fail "Docker Desktop n’est pas lancé : ouvre-le, attends qu’il soit prêt, puis relance ce script."
fi
docker compose up -d --wait >/dev/null || fail "La base de données n’a pas démarré."

echo "2/3 · Mise à jour de la base…"
.venv/bin/python manage.py migrate --noinput >/dev/null || fail "La mise à jour de la base a échoué."

echo "3/3 · Site en cours de démarrage sur $URL"
echo "      Laisse cette fenêtre ouverte ; ferme-la ou fais Ctrl-C pour arrêter le site."
(sleep 2 && open "$URL" 2>/dev/null) &
.venv/bin/python manage.py runserver "127.0.0.1:$PORT"

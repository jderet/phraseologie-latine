# Phraséologie latine

Plateforme collaborative pour traduire vers le latin, relever la phraséologie des auteurs dans le corpus et justifier chaque choix de traduction par des attestations. Nom définitif à venir.

État : en construction. Étape 1 terminée : comptes, modération, corpus du noyau analysé, recherche par forme et par lemme. Voir la [feuille de route](docs/feuille-de-route.md).

## Documents

- [Cahier des charges](docs/cahier-des-charges.md)
- [Modèle de données](docs/modele-de-donnees.md)
- [Feuille de route](docs/feuille-de-route.md)

## Lancer le site en local

Il faut Python 3.13 et Docker Desktop (pour PostgreSQL).

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
docker compose up -d
python manage.py migrate
python manage.py createcachetable
python manage.py runserver
```

Dans `.env` :

- remplacer `DJANGO_SECRET_KEY` par une longue chaîne aléatoire (la commande est indiquée dans le fichier) ;
- décommenter `DATABASE_URL` pour utiliser PostgreSQL, lancé par `docker compose up -d` (Docker Desktop doit être ouvert). Sans cette ligne, le site utilise un fichier SQLite, suffisant tant que le corpus n'est pas importé.

Le site est ensuite sur http://127.0.0.1:8000. Pour arrêter PostgreSQL : `docker compose stop` (les données sont conservées).

Le corpus latin vient de [Perseus canonical-latinLit](https://github.com/PerseusDL/canonical-latinLit), à cloner à la racine du projet :

```bash
git clone https://github.com/PerseusDL/canonical-latinLit.git
```

Puis importer le noyau dans PostgreSQL (environ 3 minutes, 350 Mo) :

```bash
python manage.py import_perseus
```

La liste des œuvres importées, les éditions retenues et leurs métadonnées sont décrites dans [corpus/data](corpus/data/README.md).

L'analyse linguistique (lemmes, morphologie, syntaxe) utilise LatinCy, installé sur le Mac seulement :

```bash
pip install -r requirements-corpus.txt
```

Puis, pour analyser le corpus importé (environ 45 minutes pour le noyau) et rendre la recherche par lemme disponible :

```bash
python manage.py analyze_corpus --make-default
```

## Licences

- Code : [AGPL-3.0](LICENSE).
- Contributions (traductions, fiches, justifications) : CC BY-SA 4.0.
- Corpus Perseus : CC BY-SA 4.0.

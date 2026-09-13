# Phraséologie latine

Plateforme collaborative pour traduire vers le latin, relever la phraséologie des auteurs dans le corpus et justifier chaque choix de traduction par des attestations. Nom définitif à venir.

État : en construction (phase 0). Voir la [feuille de route](docs/feuille-de-route.md).

## Documents

- [Cahier des charges](docs/cahier-des-charges.md)
- [Modèle de données](docs/modele-de-donnees.md)
- [Feuille de route](docs/feuille-de-route.md)

## Lancer le site en local

Il faut Python 3.13.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver
```

Dans `.env`, remplacer `DJANGO_SECRET_KEY` par une longue chaîne aléatoire (la commande est indiquée dans le fichier). Le site est ensuite sur http://127.0.0.1:8000.

Le corpus latin vient de [Perseus canonical-latinLit](https://github.com/PerseusDL/canonical-latinLit), à cloner à la racine du projet :

```bash
git clone https://github.com/PerseusDL/canonical-latinLit.git
```

## Licences

- Code : [AGPL-3.0](LICENSE).
- Contributions (traductions, fiches, justifications) : CC BY-SA 4.0.
- Corpus Perseus : CC BY-SA 4.0.

# CLAUDE.md

Plateforme collaborative de phraséologie latine : traduire vers le latin à plusieurs, relever la phraséologie des auteurs dans le corpus, justifier chaque choix de traduction par le corpus.

## À lire avant de coder

- [Cahier des charges](docs/cahier-des-charges.md) : décisions et règles, avec leurs renvois aux questionnaires de conception (Q1 à Q72, T1 à T19).
- [Modèle de données](docs/modele-de-donnees.md) : objets, statuts, règles à respecter.
- [Feuille de route](docs/feuille-de-route.md) : étapes et cases à cocher.

Ces décisions sont prises : les appliquer sans les rediscuter. Si une demande les contredit, le signaler avant d'agir.

## Travailler avec le porteur du projet

- Le porteur ne code pas et pilote le développement avec toi. Écris en français, avec le tutoiement, sans jargon inutile.
- Avance par petites étapes : une fonction, ses tests, puis un compte rendu simple (ce qui a changé, comment le voir sur le site).
- Coche les cases de la feuille de route quand une tâche est finie et vérifiée.
- Demande avant toute action qui sort de la machine ou qui coûte : envoi sur GitHub, mise en ligne, service payant, création de compte.
- Budget total : moins de 20 € par mois. Le traitement du corpus tourne sur le Mac, jamais sur le serveur.

## Commandes

```bash
source .venv/bin/activate                  # activer l'environnement Python
python manage.py runserver                 # site sur http://127.0.0.1:8000
python manage.py test                      # tests
ruff check . && ruff format --check .      # style et analyse de sécurité statique
python manage.py makemigrations            # après modification d'un modèle
python manage.py migrate
python manage.py makemessages -l en --ignore=.venv --ignore=canonical-latinLit
python manage.py compilemessages --ignore=.venv --ignore=canonical-latinLit
docker compose up -d                       # PostgreSQL local (Docker Desktop lancé)
python manage.py import_perseus            # importer le noyau Perseus (sur le Mac, environ 3 min)
pip install -r requirements-corpus.txt     # spaCy et LatinCy, sur le Mac seulement
python manage.py analyze_corpus --make-default   # analyse LatinCy du corpus (sur le Mac, environ 45 min)
```

## Architecture

- Django 6.1, PostgreSQL, HTMX, un seul composant JavaScript pour l'éditeur de traduction. Le corpus étant importé, PostgreSQL (Docker) est nécessaire en local ; l'intégration continue teste aussi sur PostgreSQL.
- Réglages lus dans les variables d'environnement (`.env`, modèle dans `.env.example`) avec django-environ.
- `config/` contient les réglages et les routes. Une application Django par domaine :

| Application | Rôle | État |
|---|---|---|
| `accounts` | utilisateurs, rôles, limites des nouveaux comptes | connexion par e-mail, inscription, rôles, limites |
| `core` | pages générales | page d'accueil |
| `corpus` | auteurs, œuvres, éditions, passages, mots, analyses | noyau importé et analysé (LatinCy), lecture, recherche par forme et par lemme |
| `moderation` | révisions, signalements, discussions, votes | révisions, retour arrière, signalements, discussions, avis indicatifs |
| `translations` | textes sources, projets, versions, segments | textes découpés, projets, versions, comparaison, éditeur, exports bilingue et imprimable |
| `justifications` | justifications, preuves, ouvrages, contestations | justifications et preuves, ouvrages de référence, contestations |
| `phraseology` | unités, réalisations, sens, attestations, candidats, néologismes | fiches (schéma, sens, équivalents, réalisations, relations, renvois, attestations), proposition, validation, contestation, fréquence calculée ; lexique de néologismes |

- `canonical-latinLit/` : clone du dépôt Perseus (CC BY-SA 4.0), ignoré par Git. Chemin réglable par `PERSEUS_LATIN_DIR`.
- Les traitements lourds du corpus sont des commandes `manage.py` lancées sur le Mac : `import_perseus` lit le catalogue `corpus/data/` et les fichiers TEI ; `analyze_corpus` crée une couche d'analyse LatinCy, raccrochée aux mots par leur position dans le texte (un seul processus : le modèle ne se transmet pas entre processus).
- Contenus contribués : hériter de `moderation.models.ModeratedContent`, s'inscrire avec `moderation.registry.register` et enregistrer chaque modification par `moderation.services.save_with_revision`. `register` déclare aussi le propriétaire, la règle de visibilité (brouillons), ce qui compte dans la limite des nouveaux comptes, les champs qu'un retour arrière ne rétablit pas, et qui peut discuter ou voter.
- L'éditeur de traduction est le seul composant JavaScript (`static/js/editor.js`) ; sans lui, les pages fonctionnent par formulaires. Le PDF est enregistré par le navigateur depuis la page imprimable.

## Conventions

- Code, commentaires et docstrings en anglais. Documentation et messages de commit en français.
- Textes d'interface écrits en français dans le code, toujours marqués pour traduction (`{% translate %}`, `gettext`) ; traduction anglaise dans `locale/en/`, fichiers `.mo` compilés et versionnés.
- Chaque fonction arrive avec ses tests. `python manage.py test` et `ruff check .` passent avant chaque commit.
- Pas de nouvelle dépendance sans raison claire ; versions figées dans `requirements*.txt`.
- Aucune requête vers des services tiers depuis les pages (polices, scripts, statistiques) : tout est servi par le site.

## Glossaire

| Terme du projet | Nom dans le code |
|---|---|
| unité phraséologique | `Unit` |
| réalisation | `Realization` |
| sens | `Sense` |
| équivalent | `Equivalent` |
| attestation validée ou automatique | `Attestation` (`level` : `validated`, `automatic`) |
| candidat | `Candidate` |
| néologisme | `Neologism` |
| recherche infructueuse | `NegativeSearch` |
| auteur, œuvre, édition | `Author`, `Work`, `Edition` |
| passage, mot | `Passage`, `Token` |
| couche d'analyse | `AnalysisLayer` |
| texte source, segment | `SourceText`, `Segment` |
| projet de traduction | `TranslationProject` |
| version en brouillon ou publiée | `TranslationVersion` (`state` : `draft`, `published`) |
| style déclaré | `style` |
| justification, preuve | `Justification`, `Evidence` |
| force de preuve | `evidence_strength` |
| ouvrage de référence | `BibliographicWork` |
| contestation | `Challenge` |
| révision, signalement | `Revision`, `Report` |
| contributeur, relecteur, administrateur | groupes `contributor`, `reviewer`, `administrator` |

## Règles non négociables

Le détail est dans la section 7 du [modèle de données](docs/modele-de-donnees.md). En résumé :

- Les annotations humaines pointent vers des identifiants de mots stables.
- Une attestation automatique n'est jamais présentée comme validée ; toute mention d'absence indique la version du corpus.
- Un brouillon n'est visible que de son auteur, y compris dans l'API et les exports.
- Aucun texte source sans licence compatible ; aucune ressource sous droits stockée.
- Toute modification de contenu crée une révision ; supprimer un compte anonymise ses contributions.

## Sécurité

- Aucun secret dans le dépôt : `.env` est ignoré par Git.
- S'appuyer sur les protections de Django (ORM, échappement des gabarits, CSRF). Ne jamais marquer du contenu saisi par un utilisateur comme sûr (`mark_safe`, filtre `safe`).
- Toute vue qui modifie des données vérifie les permissions côté serveur.
- Avant une mise en ligne : `python manage.py check --deploy`, et une revue de sécurité des changements (`/security-review`), surtout pour les comptes, les permissions et les données saisies.

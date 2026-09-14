# Revue de sécurité

Revue du 14 septembre 2026, sur la branche `etape-5`. Elle porte sur tout le code du site (vues, fonctions métier, formulaires, gabarits, réglages) et sur les scripts de `deploy/`. La configuration de production n'est pas encore écrite : ce qu'il faudra y vérifier est listé à la fin. Les dépendances sont surveillées par Dependabot.

## Méthode

- Lecture de toutes les vues qui modifient des données, des règles d'accès (`moderation/registry.py`, fichiers `permissions.py`) et des fonctions métier (`services.py`).
- Recherche dans le code des motifs à risque : contenu marqué comme sûr, SQL écrit à la main, redirections vers une adresse reçue, protection CSRF désactivée, formulaires ouverts à tous les champs, fichiers envoyés, exécution de commandes.
- Mesure des requêtes les plus coûteuses sur le corpus réel (4,7 millions de mots analysés).

## Ce qui est déjà solide

- **Droits** : chaque action est contrôlée deux fois, dans la vue et dans la fonction métier, qui refuse d'elle-même (`PermissionDenied`). Un contenu invisible répond « introuvable » (`Http404`).
- **Brouillons** : une seule règle de visibilité (`can_view`) sert les pages, les exports texte, TEI, TMX et imprimable, l'API (qui interroge comme un visiteur anonyme) et l'export complet.
- **Injection de code dans les pages** : aucun `mark_safe` ni filtre `safe` ; les deux balises de gabarit qui produisent du HTML passent par `format_html`, qui échappe les valeurs.
- **SQL** : un seul SQL écrit à la main (extraction des candidats, commande lancée sur le Mac), avec des paramètres liés.
- **Redirections** : la seule adresse de retour reçue d'un formulaire est vérifiée (`url_has_allowed_host_and_scheme`).
- **CSRF** : protection active partout ; l'éditeur envoie le jeton avec chaque enregistrement.
- **Comptes** : activation par un bouton (et non à l'ouverture du lien), jetons à usage unique, mot de passe demandé pour supprimer un compte, anonymisation des contributions.
- **Recherches bornées** : 100 caractères par terme, distance de 20 mots au plus, schéma de 300 caractères au plus, 100 mots surlignés au plus.
- **API** : lecture seule, sans cookie ; l'ouverture à tous les sites (CORS) est volontaire, les données étant publiques.

## Problèmes trouvés et corrigés

| Problème | Risque | Correction |
|---|---|---|
| Essais de mot de passe illimités, sur le site et dans l'administration | deviner un mot de passe | 5 échecs en 15 minutes par adresse, puis le mot de passe n'est plus vérifié |
| E-mails d'activation et de réinitialisation illimités | inonder la boîte de quelqu'un | 3 e-mails par heure par adresse ; la page répond de la même façon |
| Aucune politique de sécurité du contenu (CSP) | aggraver une faille d'injection | scripts, styles et images du site seulement, aucun affichage dans le cadre d'un autre site |
| Requêtes sans durée maximale (37 secondes mesurées pour une recherche très large) | occuper le serveur par quelques recherches | `DATABASE_STATEMENT_TIMEOUT` ; la page invite à restreindre la recherche |
| Inscriptions jamais activées gardées sans limite | données inutiles conservées | effacées au bout de 7 jours (`purge_pending_signups`) |

Les compteurs d'essais sont gardés dans la base (cache partagé par tous les processus), sous une empreinte de l'adresse : ni l'adresse ni l'adresse IP ne sont enregistrées.

## Risques acceptés

- **L'inscription dit si une adresse a déjà un compte.** Le message aide les personnes qui ont oublié leur inscription ; la réinitialisation du mot de passe, elle, ne le dit pas.
- **La limite d'essais compte par adresse e-mail, pas par adresse IP**, puisque le site n'enregistre pas d'adresse IP. Une attaque répartie sur de nombreux comptes reste possible ; les règles de mot de passe de Django (longueur, mots courants, chiffres seuls) la freinent.
- **Échouer exprès bloque la connexion d'un compte pendant 15 minutes.**

## À vérifier avec la configuration de production

- `DJANGO_DEBUG` faux, clé secrète propre au serveur, `DJANGO_ALLOWED_HOSTS` réduit au nom de domaine.
- `SECURE_PROXY_SSL_HEADER` réglé derrière le serveur web, sinon la redirection vers HTTPS tourne en boucle.
- `DATABASE_STATEMENT_TIMEOUT=25` pour le site seulement, délai du serveur d'application à 30 secondes.
- Journaux d'erreurs sur la sortie standard, et aucun journal d'accès avec adresse IP, comme l'annonce la politique de confidentialité.
- `python manage.py createcachetable` après chaque `migrate`.
- Durée HSTS et décision sur le préchargement.
- `python manage.py check --deploy` sans avertissement.

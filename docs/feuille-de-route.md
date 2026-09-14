# Feuille de route

À cocher au fur et à mesure. Le détail des fonctions est dans le [cahier des charges](cahier-des-charges.md), les objets dans le [modèle de données](modele-de-donnees.md).

## Phase 0 : fondations

Porteur :

- [ ] Choisir le nom latin et réserver le nom de domaine
- [ ] Choisir les 2 à 4 membres du comité consultatif
- [ ] Rédiger la charte d'une page
- [ ] Rédiger le guide d'annotation v0 avec le comité : typologie, schémas et réalisations, niveaux d'attestation, échelle de force
- [ ] Tester le modèle dans un tableur : un article de Wikipédia traduit par trois personnes, une vingtaine de justifications
- [ ] Réunir 5 à 10 testeurs du latin vivant
- [ ] Créer le dépôt public (GitHub) et y envoyer le code

Développement :

- [x] Dépôt Git local, licence AGPL-3.0, `CLAUDE.md`
- [x] Squelette Django qui tourne en local : français et anglais, modèle d'utilisateur personnalisé, tests
- [x] Intégration continue écrite (tests et vérifications à chaque modification, alertes sur les dépendances) ; elle s'exécutera dès que le dépôt sera sur GitHub
- [ ] Archivage par Software Heritage, une fois le dépôt public

## Étape 1 : socle

- [x] PostgreSQL en local (Docker)
- [x] Comptes : inscription par e-mail, déclaration de majorité, trois rôles, limites des nouveaux comptes
- [x] Révisions, retour arrière et signalements sur tout contenu
- [x] Import du noyau depuis Perseus : œuvres, passages, mots à identifiants stables, URN CTS
- [x] Métadonnées : date, genre, registre, prose ou vers, époque
- [x] Forme normalisée pour la recherche
- [x] Analyse automatique sur le Mac (LatinCy) : lemmes, morphologie, syntaxe UD, en couches versionnées
- [x] Recherche par forme et par lemme, avec filtres et contexte

Terminé quand on trouve toutes les occurrences de *consilium capere* dans le noyau, avec leurs références.

Vérifié le 13 septembre 2026 (Perseus 4620cf8, LatinCy la_core_web_lg 3.9.6) : 123 occurrences à cinq mots au plus. La recherche par lemme en trouve 121 ; la recherche par forme (`consili*` et `cap* | cep*`) rattrape les 2 que le lemmatiseur a manquées (*Att.* 7, 10, 1 *cepi* ; Liv. 9, 3, 11 *caperetur*). Les attestations automatiques devront donc être relues par des personnes, comme prévu à l'étape 4.

## Étape 2 : traduction

- [x] Textes sources avec licence déclarée, découpés en phrases
- [x] Projets ; versions en brouillon puis publiées ; styles déclarés
- [x] Vue de comparaison phrase par phrase ; version de référence choisie par le créateur du projet
- [x] Éditeur en trois colonnes, saisie des macrons
- [x] Justifications : preuves, force, commentaire obligatoire pour l'analogie, passage « à revoir »
- [x] Contestation : contre-exemples, discussion, votes
- [x] Exports bilingue et PDF avec notes

Terminé quand les testeurs ont traduit, comparé et justifié un texte dans plusieurs styles.

## Étape 3 : phraséologie

- [x] Fiches : schéma, réalisations, sens, équivalents, relations, marques d'usage
- [x] Création à trois champs, validation à tous les champs, fréquence calculée
- [x] Lexique de néologismes justifiés
- [x] Candidats extraits automatiquement (paires syntaxiques, score d'association) et file de validation
- [x] Surlignage des unités connues pendant la saisie, avec leurs attestations
- [x] Liens entre justifications et fiches, dans les deux sens

Terminé quand une centaine de fiches sont validées.

## Étape 4 : exhaustivité et recherche

- [x] Relevé automatique de toutes les réalisations d'une unité, validation par lots sur le noyau
- [x] Attestations automatiques hors du noyau, affichées comme telles
- [x] Mention « introuvable dans le corpus (version X) »
- [x] Requêtes par schémas
- [x] Profils statistiques de collocations
- [x] Traductions du domaine public en regard
- [x] Élargissement au reste de la latinité classique
- [x] Exports TEI et TMX, API publique, export complet

## Étape 5 : préparation de l'ouverture

Tout se fait sur le Mac : rien n'est mis en ligne, aucun service payant.

- [x] Réserve contre l'entraînement de modèles, lisible par les robots
- [x] Mentions légales, politique de confidentialité et conditions d'utilisation, à compléter par le porteur
- [x] Interface entièrement traduite en anglais, vérifiée à chaque modification
- [ ] Configuration de production : image Docker, serveur d'application, HTTPS, pages d'erreur, journaux
- [x] Sauvegardes quotidiennes et restauration testée en local
- [ ] Revue de sécurité complète, sans problème ouvert

Terminé quand le site tourne sur le Mac dans sa configuration de production, qu'une sauvegarde y a été restaurée et que la revue de sécurité ne laisse aucun problème ouvert.

## Étape 6 : lecture et annotation du corpus

Menée avant les deux cases restantes de l'étape 5 (choix du 14 septembre 2026). Détail dans la section 4.10 du [cahier des charges](cahier-des-charges.md). Dans l'ordre de travail : la lecture d'abord, puis l'annotation.

- [x] Fiches d'exemple en local : une commande les crée, une autre les efface
- [x] Mode lecture : œuvre en continu, navigation par livre et par chapitre, traduction en regard dans une colonne masquable
- [x] Unités soulignées dans le texte : couleur par type, légende, mots d'une occurrence qui s'allument ensemble, traits empilés
- [x] Filtres : statuts (validées et proposées par défaut), type, marque d'usage, registre, une seule fiche avec occurrence suivante et précédente
- [x] Panneau latéral de la fiche ; analyse d'un mot au clic
- [x] Soulignements dans la page d'un passage, les résultats de recherche, les versions publiées et la comparaison
- [x] Mode « annoter » : mots choisis au clic, fiches suggérées, recherche, fiche pré-remplie ; réalisation, sens, note, exemple proposé
- [x] Occurrences du schéma des fiches pas encore attestées, confirmées en un clic
- [x] Relecture dans le texte, attestation douteuse, contestation d'une attestation
- [x] Repérages sans fiche et leur file
- [x] Passage entièrement relu, file des passages à relire, progression par œuvre
- [x] Page de l'annotateur, file du relecteur, chiffres publics
- [x] Corrections d'analyse proposées puis validées, prises en compte par la lecture, la recherche et les relevés
- [x] Notes de lecture publiques, masquables
- [x] Carnet personnel : surlignages, notes privées, listes de passages, page « mon carnet »
- [x] Guide d'annotation en pages datées, lié depuis l'outil d'annotation
- [x] Annotations dans l'API et l'export complet ; exports TEI et CoNLL-U d'un passage ou d'une œuvre

Terminé quand un livre du noyau (par exemple Cic. *Off.* 1) est entièrement relu, avec ses attestations visibles dans le texte.

## Ouverture publique

- [ ] Conditions de la section 7 du cahier des charges remplies
- [ ] Choisir l'hébergeur, le nom de domaine et le service d'envoi des e-mails
- [ ] Serveur européen, sauvegardes copiées hors du serveur, restauration testée sur le serveur
- [ ] Pages légales complétées et publiées
- [ ] Décider du préchargement HSTS (difficile à annuler)
- [ ] Passage à Django 6.2 LTS (sortie prévue en avril 2027)

## Après l'ouverture

- [ ] Dépôt périodique sur Zenodo
- [ ] Suggestions de traduction par IA
- [ ] Interface en allemand, italien, espagnol et latin
- [ ] Latin tardif, médiéval et néo-latin
- [ ] Usage en classe
- [ ] Édition simultanée

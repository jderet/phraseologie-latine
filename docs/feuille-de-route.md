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
- [ ] Candidats extraits automatiquement (paires syntaxiques, score d'association) et file de validation
- [ ] Surlignage des unités connues pendant la saisie, avec leurs attestations
- [ ] Liens entre justifications et fiches, dans les deux sens

Terminé quand une centaine de fiches sont validées.

## Étape 4 : exhaustivité et recherche

- [ ] Relevé automatique de toutes les réalisations d'une unité, validation par lots sur le noyau
- [ ] Attestations automatiques hors du noyau, affichées comme telles
- [ ] Mention « introuvable dans le corpus (version X) »
- [ ] Requêtes par schémas
- [ ] Profils statistiques de collocations
- [ ] Traductions du domaine public en regard
- [ ] Élargissement au reste de la latinité classique
- [ ] Exports TEI et TMX, API publique, export complet

## Ouverture publique

- [ ] Conditions de la section 7 du cahier des charges remplies
- [ ] Serveur européen, sauvegardes quotidiennes, restauration testée
- [ ] Revue de sécurité complète
- [ ] Mentions légales, politique de confidentialité, conditions d'utilisation, réserve contre l'entraînement de modèles
- [ ] Passage à Django 6.2 LTS (sortie prévue en avril 2027)

## Après l'ouverture

- [ ] Dépôt périodique sur Zenodo
- [ ] Suggestions de traduction par IA
- [ ] Interface en allemand, italien, espagnol et latin
- [ ] Latin tardif, médiéval et néo-latin
- [ ] Usage en classe
- [ ] Édition simultanée

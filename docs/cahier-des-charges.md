# Cahier des charges

Plateforme collaborative de phraséologie latine. Nom définitif à choisir (un nom latin).

Version du 13 septembre 2026. Les renvois entre parenthèses désignent les réponses aux deux questionnaires de conception : 72 questions (Q1 à Q72), puis 19 tensions (T1 à T19).

## 1. Objet

La plateforme poursuit trois buts liés :

1. **Traduire à plusieurs** des textes de langues modernes vers le latin.
2. **Annoter et extraire à plusieurs** la phraséologie latine à partir du corpus.
3. **Justifier** chaque choix de traduction par le corpus annoté.

L'objet central est l'**unité phraséologique** (par exemple *consilium capere*). Une justification relie un passage d'une traduction à des passages d'auteurs où l'unité est attestée.

## 2. Porteur et gouvernance

- Un porteur unique, dont le nom figure dans les mentions légales (T18).
- Un comité consultatif de 2 à 4 personnes choisies par le porteur. Le porteur tranche en dernier ressort sur la charte, le guide d'annotation et les litiges (T11).
- La communauté propose des évolutions du guide d'annotation ; chaque version du guide est datée (Q54).
- Dans les désaccords de fond, les positions argumentées sont affichées côte à côte (Q53).
- Le développement est piloté avec une IA ; le porteur ne code pas (Q9).

## 3. Public et posture

- Public prioritaire : la communauté du latin vivant (Q1). Quelques centaines d'utilisateurs actifs visés à deux ans (Q8). Majeurs seulement (Q57).
- Le site est à la fois un atelier, un ouvrage de référence et une communauté (Q2).
- Posture descriptive : on montre ce qui est attesté, où et combien de fois. Des recommandations sont possibles, signées et argumentées (Q3).
- Le latin visé est déclaré pour chaque version de traduction, sous forme de style : cicéronien, tacitéen… (Q4, Q41).
- Langues sources : français, anglais, allemand, italien, espagnol (Q5).

## 4. Fonctions

### 4.1 Traduction collaborative

- Un **projet** porte sur un texte source découpé en phrases (Q35).
- Chaque participant rédige **sa propre version** latine et déclare un style (Q36, Q41).
- Une version reste un **brouillon visible de son seul auteur**, jusqu'à ce que celui-ci la publie (T7). Tout ce qui est publié est public ; il n'y a pas d'espace de groupe privé (Q42).
- Une **vue de comparaison** aligne toutes les versions publiées, phrase par phrase.
- Le **créateur du projet** désigne la version de référence (T6).
- Alignement phrase à phrase, et au niveau du groupe de mots en option (Q39).
- Écran principal en trois colonnes : texte source, latin, corpus et justifications (Q67). Saisie facilitée des macrons (Q68) : une voyelle suivie de = prend un macron (a= donne ā), et des boutons ā ē ī ō ū ȳ complètent la saisie. Conçu d'abord pour ordinateur (Q69).
- Réalités modernes : périphrase classique de préférence. Le *Lexicon recentis Latinitatis* est cité par simple référence. La plateforme tient son propre lexique de néologismes, justifiés comme le reste et marqués « néologisme » (Q40, T5).
- Édition simultanée en temps réel : plus tard (Q38).
- Exports : texte bilingue, PDF avec notes justificatives, TEI, TMX (Q43). Le PDF est enregistré par le navigateur à partir d'une page imprimable, sans outil supplémentaire sur le serveur (choix du 13 septembre 2026).

### 4.2 Phraséologie

- Phénomènes retenus (Q10) : collocations (verbe–nom, adjectif–nom, adverbe–verbe…), locutions figées, formules, constructions à case vide, marqueurs de discours, clausules. Les tours purement syntaxiques (ablatif absolu) n'en font pas partie.
- Une unité est un **schéma** (par exemple *bellum gerere* : verbe *gero* → objet *bellum*), relié à ses **réalisations** (*bellum geritur*, *gerere bella*…) (Q11).
- Classement : typologie fermée, définie dans le guide d'annotation, complétée par des étiquettes libres (Q12). En attendant le guide, une typologie provisoire reprend les phénomènes retenus : collocations verbe–nom, adjectif–nom, adverbe–verbe, nom–nom, locution figée, formule, construction à case vide, marqueur de discours, clausule (choix du 14 septembre 2026).
- Une fiche en brouillon n'est modifiée que par son créateur ; une fois proposée, tout compte actif la complète ou la corrige, comme un wiki : chaque modification reste dans l'historique, avec retour arrière et signalement. Une fiche validée reste validée (choix du 14 septembre 2026).
- Relations entre unités : synonyme, variante, antonyme, plus général, plus précis (Q13).
- Marques d'usage : « poétique seulement », « tardif », « à éviter » (Q13).
- Une unité peut avoir plusieurs sens ; les équivalents modernes sont rattachés à chaque sens (Q14).
- **Créer une fiche** demande trois champs : forme de référence, sens, une attestation (T3).
- **Valider une fiche** demande tous les champs (Q15) : forme de référence, sens, construction, registre, fréquence et répartition par auteur (calculées automatiquement), exemples choisis, équivalents, renvois bibliographiques.
- Extraction manuelle et semi-automatique : le système propose des candidats (paires de mots liés syntaxiquement, classées par force d'association), que l'on retient ou rejette (Q16).
- **Attestations à deux niveaux** (Q17, T2) :
  - *validées* : toutes les occurrences dans le noyau du corpus, vérifiées par des personnes ;
  - *repérées automatiquement* : dans le reste du corpus, affichées comme telles.
- L'absence est documentée : « introuvable dans le corpus (version X) », jamais « non attesté » (Q18).

### 4.3 Justification

- On sélectionne un passage de sa version latine et on y joint une ou plusieurs preuves (Q44) :
  - des attestations du corpus ;
  - une règle de grammaire (Kühner-Stegmann, Ernout-Thomas, Allen & Greenough…) ;
  - un article de dictionnaire.
- Chaque justification porte une **force de preuve**, sur une échelle explicite (Q45) :
  1. attesté tel quel en prose classique ;
  2. attesté avec variante ;
  3. attesté seulement en poésie ou à basse époque ;
  4. par analogie, avec un **commentaire obligatoire** (T4) ;
  5. introuvable dans le corpus.
- Justifier est facultatif, sauf pour un choix contesté (Q46).
- Contestation : contre-exemples, fil de discussion, votes (Q48).
- Pendant la saisie du latin, les unités connues sont surlignées et leurs attestations affichées. Pas d'alerte automatique sur les combinaisons introuvables (Q47).
- Une justification enrichit la fiche de l'unité, et chaque fiche montre les traductions qui l'emploient (Q49).

### 4.4 Corpus

- **Noyau** (Q19) : Cicéron, César, Salluste, Tite-Live, Sénèque, Pline le Jeune.
- **Élargissement**, avec marque d'époque (Q20) : latin archaïque, reste de la latinité impériale, latin tardif et chrétien, latin médiéval, néo-latin. Les attestations y sont repérées automatiquement (T2). Premier élargissement, avant l'ouverture : du latin archaïque à la fin du IIe siècle (Plaute à Apulée et Aulu-Gelle) ; le latin tardif et chrétien vient après l'ouverture (choix du 14 septembre 2026).
- Poésie incluse, signalée comme non normative pour la prose (Q21).
- Éditions libres (Q22). Source principale : Perseus *canonical-latinLit* (TEI, CC BY-SA 4.0), déjà cloné dans le dossier du projet.
- Variantes et passages corrompus ignorés au départ (Q23).
- Graphie de l'édition conservée ; recherche sur une forme normalisée (u/v, i/j, ae/æ, macrons…) (Q24).
- Citation par référence usuelle (Cic. *Off.* 1, 23) et par identifiant stable, l'URN CTS (Q25).
- Métadonnées de filtrage : date, genre, registre, prose ou vers, œuvre et livre (Q26).
- Traductions du domaine public affichées en regard (Q27).

### 4.5 Analyse linguistique et recherche

- Lemmes et morphologie importés de données vérifiées quand la licence le permet, calculés automatiquement ailleurs, corrigeables par la communauté (Q28).
- Analyse syntaxique en dépendances, avec les étiquettes Universal Dependencies (Q29, Q30).
- Les annotations humaines pointent vers des **identifiants de mots stables**, qui survivent à une nouvelle analyse automatique (Q31).
- Recherche par forme et par lemme, puis requêtes par schémas (Q32) et profils statistiques de collocations (Q33).

### 4.6 Comptes, rôles et modération

- Inscription libre, avec déclaration de majorité (Q51, Q57).
- Trois rôles au lancement : contributeur, relecteur, administrateur (T9).
- Validation selon l'objet (fiche, attestation, traduction). Statuts : brouillon, proposé, validé, contesté (Q52).
- Nouveaux comptes limités jusqu'à une première contribution validée (T10) : pas de liens, et quelques créations de contenu par jour (texte, projet, version, justification, contestation, message). Les modifications et l'enregistrement des phrases d'une version ne comptent pas (choix du 13 septembre 2026).
- Signalement et retour à une version précédente, sur tout contenu (T10). Historique complet des modifications.
- Reconnaissance des contributeurs : nom affiché, page de profil, ORCID facultatif (Q55).

### 4.7 Intelligence artificielle

- Au lancement : pré-annotation seulement (lemmes, syntaxe, candidats) (Q58).
- Suggestions de traduction par IA reportées après l'ouverture (T15). Le moment venu : contenus générés signalés, aucune citation affichée sans vérification dans le corpus, validation humaine obligatoire (Q59).

### 4.8 Interface

- Français et anglais à l'ouverture ; puis allemand, italien, espagnol et latin, traduits par des bénévoles (T19). L'interface est traduisible dès la première ligne de code.

### 4.9 Données ouvertes

- API publique et export complet téléchargeable (Q65).
- Dépôt périodique des données sur Zenodo, avec la liste des contributeurs qui acceptent d'y figurer (T13, T17). Modalités à préciser.

## 5. Règles juridiques

- **Contributions** : CC BY-SA 4.0 (Q61).
- **Code** : AGPL-3.0 (Q62).
- **Entraînement de modèles** : refusé (Q60), exprimé par une réserve lisible par les robots. Sans garantie juridique, puisque la CC BY-SA autorise en pratique cette réutilisation (T12).
- **Textes sources** : domaine public (auteur mort depuis plus de 70 ans) ou licence libre compatible, déclarée à l'ajout (T8). Les articles de Wikipédia sont acceptés (CC BY-SA).
- **Corpus Perseus** : CC BY-SA 4.0. Les corrections apportées aux textes doivent être proposées à Perseus.
- **Ressources sous droits** (OLD, LASLA, PHI, traductions Budé, *Lexicon recentis Latinitatis*) : citées par simple référence, jamais recopiées (Q63).
- **Mentions légales** au nom du porteur (T18).
- **Données personnelles** : le porteur est responsable du traitement. Politique de confidentialité, données minimales, majeurs seulement. À la suppression d'un compte, les contributions restent (CC BY-SA) mais sont anonymisées.
- **Contenus signalés** : le porteur, qui héberge les contributions, retire promptement un contenu manifestement illicite qu'on lui signale.

## 6. Contraintes techniques

- Budget : moins de 20 € par mois (T14).
- Framework éprouvé et outils automatiques de sécurité (T16) : Django, PostgreSQL, HTMX, un composant JavaScript pour l'éditeur.
- Hébergement : petit serveur virtuel européen, Docker, mises à jour automatiques, sauvegardes quotidiennes copiées hors du serveur. Pendant le développement, tout tourne sur le Mac du porteur.
- Le traitement du corpus (lemmatisation, syntaxe, candidats) tourne sur le Mac du porteur ; le serveur ne sert que les résultats.
- Standards : TEI et URN CTS en entrée, Universal Dependencies (CoNLL-U) pour l'analyse, exports ouverts.
- Pérennité : code et données archivés publiquement (Software Heritage, Zenodo) (T17).

## 7. Conditions d'ouverture publique

L'ouverture n'est pas datée : elle a lieu quand toutes ces conditions sont remplies. Six mois de construction ou plus sont acceptés (T1).

- Au moins un texte traduit dans plusieurs styles, comparé et justifié.
- Un premier lot de fiches validées (une centaine, par exemple).
- Une revue de sécurité sans problème ouvert, et une restauration de sauvegarde réussie.
- Mentions légales, politique de confidentialité et conditions d'utilisation publiées.
- Interface disponible en français et en anglais.

## 8. Indicateurs de réussite à un an

Nombre de fiches validées, textes traduits et justifiés, utilisateurs actifs réguliers (Q72).

## 9. Hors périmètre au lancement

Suggestions de traduction par IA, usage en classe (Q56), édition simultanée (Q38), langues d'interface autres que le français et l'anglais, corpus au-delà de la latinité classique, dépôt sur Zenodo.

## 10. Questions ouvertes

- Nom latin du site et nom de domaine.
- Membres du comité consultatif.
- Typologie détaillée des unités (guide d'annotation v0).
- Modalités du co-autorat et fréquence des dépôts sur Zenodo.
- Choix précis de l'hébergeur.
- Source des traductions du domaine public affichées en regard.

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
- **Le texte source reste modifiable** (choix du 15 septembre 2026) : on ajoute des phrases (au début, à la fin ou entre deux phrases), on modifie une phrase, on fusionne deux phrases ou on en scinde une. Le changement vaut pour tous les projets qui utilisent ce texte.
  - La personne qui a ajouté le texte et les relecteurs le modifient directement. Tout compte actif peut **proposer** plusieurs changements, avec une explication et une discussion ; ces mêmes personnes les adoptent ou les refusent en bloc. Une proposition ne s'adopte plus si le texte a changé entre-temps.
  - Une phrase n'est jamais écrasée : l'ancienne reste, pour les étapes qui l'ont figée. Une scission ne change aucun mot ; aucune phrase n'est supprimée.
  - Dans le texte de travail de chaque version, le latin suit : deux phrases fusionnées mettent leurs latins bout à bout, une phrase scindée garde son latin sur sa première partie, une phrase modifiée garde le sien, une phrase ajoutée n'en a pas. L'éditeur signale les phrases touchées, avec l'ancien texte source, jusqu'à l'étape suivante.
  - Une étape fige aussi le texte source : le public garde celui de la dernière étape publique, et la prochaine étape de l'auteur intègre le nouveau.
  - L'historique des étapes résume ce qu'a changé chaque étape (phrases traduites, phrases du texte source) et en déplie le détail mot à mot.
- Chaque participant rédige **sa propre version** latine et déclare un style (Q36, Q41).
- Une version reste un **brouillon visible de son seul auteur**, jusqu'à ce que celui-ci la publie (T7). Tout ce qui est publié est public ; il n'y a pas d'espace de groupe privé (Q42).
- Une **vue de comparaison** aligne toutes les versions publiées, phrase par phrase.
- Le **créateur du projet** désigne la version de référence (T6). Elle suit la dernière étape de la version choisie.
- **Étapes, à la manière de Git** (choix du 15 septembre 2026) :
  - L'éditeur enregistre chaque phrase au fil de la saisie : c'est le **texte de travail**, visible de son seul auteur. Quand il le décide, l'auteur crée une **étape** de toute la version, avec un message. Chaque étape garde le texte de toutes les phrases et reste consultable à une adresse fixe, citable.
  - Le public voit la **dernière étape** d'une version publiée : les retouches restent privées jusqu'à l'étape suivante. La vue de comparaison, les exports et l'API montrent aussi la dernière étape.
  - Publier crée une étape. L'auteur choisit alors, une fois pour toutes, de montrer ou non les étapes créées pendant le brouillon.
  - Une justification paraît avec l'étape qui suit sa création. Une contestation vise le texte d'une étape publique.
  - On compare deux étapes, ou la dernière étape et le texte de travail, phrase par phrase et mot à mot. Chaque phrase d'une étape indique l'étape où elle a changé et qui l'a écrite.
  - Tout compte peut **partir d'une version publiée** : il obtient sa propre version, en brouillon, qui mentionne son origine (version et étape). Les justifications ne sont pas copiées ; chaque phrase reprise reste au nom de qui l'a écrite.
  - Tout compte actif peut **proposer des modifications** à la version publiée d'un autre, avec une explication et une discussion. L'auteur de la version accepte ou refuse chaque phrase proposée ; une phrase acceptée entre dans son texte de travail, au nom de qui l'a proposée, et paraît à l'étape suivante. L'auteur reste seul maître de sa version (Q36). Une proposition compte dans la limite des nouveaux comptes (T10).
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
- Traductions du domaine public affichées en regard (Q27). Source retenue pour commencer : les traductions anglaises numérisées par Perseus, dont le traducteur est mort depuis plus de 70 ans ; le français viendra plus tard (choix du 14 septembre 2026).

### 4.5 Analyse linguistique et recherche

- Lemmes et morphologie importés de données vérifiées quand la licence le permet, calculés automatiquement ailleurs, corrigeables par la communauté (Q28).
- Analyse syntaxique en dépendances, avec les étiquettes Universal Dependencies (Q29, Q30).
- Les annotations humaines pointent vers des **identifiants de mots stables**, qui survivent à une nouvelle analyse automatique (Q31).
- Recherche par forme et par lemme, jusqu'à cinq mots (chacun à une distance donnée du premier), dans la page de recherche comme dans les panneaux des fiches, des justifications et de l'éditeur (choix du 15 septembre 2026), puis requêtes par schémas (Q32) et profils statistiques de collocations (Q33).

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

- API publique et export complet téléchargeable (Q65). L'API est en lecture seule, au format JSON et sans clé ; l'export complet est une archive de fichiers JSON produite par une commande et téléchargeable sur la page « Données ouvertes ». Ni l'une ni l'autre ne contient de brouillon, de contenu masqué ou d'adresse e-mail. Les versions de traduction s'exportent aussi en TEI et en TMX (choix du 14 septembre 2026).
- Dépôt périodique des données sur Zenodo, avec la liste des contributeurs qui acceptent d'y figurer (T13, T17). Modalités à préciser.

### 4.10 Lecture et annotation du corpus

Choix du 14 septembre 2026, à la suite d'un questionnaire de 40 questions sur l'annotation. Ces fonctions forment l'étape 6 de la feuille de route, menée avant de finir l'étape 5.

**Lecture**

- Un **mode lecture** présente une œuvre en continu : texte large, navigation par livre et par chapitre, traduction du domaine public dans une colonne à côté, masquable (dessous sur téléphone).
- La phraséologie apparaît partout où le latin s'affiche : mode lecture, page d'un passage, résultats de recherche, versions latines publiées et vue de comparaison.
- Chaque occurrence d'unité est soulignée, d'une couleur par type, avec une légende. Au survol ou au toucher, tous les mots de l'occurrence s'allument ensemble, même éloignés. Quand des unités partagent des mots, leurs traits s'empilent ; un clic sur le mot les liste toutes.
- Le lecteur choisit les statuts affichés : validées, proposées, repérées automatiquement, chacun dans un style distinct (une attestation automatique n'est jamais présentée comme validée). À la première visite, validées et proposées sont cochées ; le site garde ensuite le choix du lecteur. Autres filtres : type d'unité, marque d'usage, registre, et une seule fiche, avec occurrence suivante et précédente dans l'œuvre.
- Un clic sur une unité ouvre un **panneau latéral** : sens et équivalents, fréquence et répartition par auteur (avec la version du corpus), deux ou trois autres exemples, statut de l'attestation et qui l'a ajoutée, actions du relecteur.
- Un clic sur un mot montre son analyse (lemme, morphologie, fonction), marquée « analyse automatique » avec l'outil et sa version, ou « corrigée ».
- Dans les versions latines publiées, les unités connues repérées dans la phrase sont soulignées comme suggestions ; les passages justifiés par une fiche ont leur propre style.
- La lecture fonctionne sur tout appareil ; l'annotation est pensée pour l'ordinateur (Q69).

**Annotation**

- Un **mode « annoter »**, activé depuis la page de lecture, fait apparaître les outils. On choisit les mots d'une attestation en cliquant chacun d'eux, même éloignés.
- Le site propose d'abord les fiches dont les lemmes correspondent aux mots choisis, puis une recherche parmi les fiches, enfin une fiche nouvelle pré-remplie (forme de référence, schéma deviné, attestation). On peut préciser la réalisation, le sens et une note, et proposer l'attestation comme exemple choisi, ce qu'un relecteur décide.
- Un **repérage** signale « il y a de la phraséologie ici » sans choisir de fiche. Il entre dans une file : tout compte actif le rattache à une fiche, existante ou nouvelle, et l'attestation obtenue est proposée ; un relecteur peut classer un repérage sans suite.
- En mode annoter, les occurrences du schéma des fiches connues qui n'ont pas encore d'attestation s'affichent en pointillé, repérées automatiquement. Dans le noyau, un clic en fait une attestation proposée, qu'un relecteur valide. Hors du noyau, le clic l'enregistre comme attestation repérée automatiquement, jamais validée, comme le relevé (T2). Les candidats sans fiche ne s'affichent pas dans le texte.
- Un relecteur valide ou rejette une attestation depuis le panneau, en plus de l'examen par lots du relevé. Un contributeur qui juge une attestation fausse la signale **douteuse**, avec un motif ; un relecteur tranche.
- Une attestation se conteste comme une fiche : un argument ouvre la discussion, avec des votes indicatifs ; un relecteur tranche, et les positions restent affichées (Q53).
- Un relecteur déclare un passage **entièrement relu** quand toutes ses unités sont relevées. Une file montre, par œuvre, les passages du noyau qui ne le sont pas encore ; chacun y pioche.

**Autres annotations**

- **Correction d'analyse** (Q28) : tout compte actif propose une correction du lemme, de la morphologie ou de la relation syntaxique d'un mot ; un relecteur la valide. Validée, elle remplace l'analyse automatique dans la lecture, la recherche et les relevés, et survit à une nouvelle analyse, puisqu'elle pointe vers l'identifiant stable du mot (Q31).
- **Note de lecture** : un commentaire public sur un groupe de mots, écrit par tout compte actif. C'est un contenu modéré, qui compte dans la limite des nouveaux comptes. Une case affiche ou masque les notes.
- **Carnet personnel** : surlignages en quelques couleurs, notes privées et listes de passages nommées, réunis sur une page « mon carnet ». Il n'est visible que de son auteur : aucune autre page, ni l'API, ni les exports ne le montrent.

**Suivi**

- Progression par œuvre : passages entièrement relus, attestations validées.
- Page de l'annotateur : ses attestations, repérages, corrections et notes, avec leur statut.
- File du relecteur : attestations proposées ou douteuses, repérages, corrections d'analyse, groupés par passage.
- Chiffres publics : fiches, attestations, passages relus.
- Le guide d'annotation vit dans des pages du site, chaque version datée (Q54) ; l'outil d'annotation y renvoie. Le porteur le rédige avec le comité ; les administrateurs le publient.

**Exports**

- Attestations, repérages, notes de lecture et corrections validées entrent dans l'API et l'export complet. Un passage ou une œuvre s'exporte aussi en TEI, avec ses unités, et en CoNLL-U, avec l'analyse corrigée et les unités. Le carnet personnel n'est jamais exporté.

**Technique**

- La lecture annotée est un second composant JavaScript, à côté de l'éditeur : un fichier servi par le site, sans bibliothèque externe. Sans JavaScript, le texte reste lisible, avec ses soulignements et des liens vers les fiches.
- Le dessin du schéma est un troisième composant JavaScript (choix du 15 septembre 2026). Dans la création et la modification des fiches et dans la recherche par schéma, on relie des mots au lieu d'écrire le schéma : clic sur le mot qui régit puis sur celui qui en dépend, ou flèche tirée de l'un à l'autre, relation choisie par son nom français. Le lemme de chaque mot est proposé d'après l'analyse du corpus ; le schéma écrit reste visible sur demande et modifiable. Sans JavaScript, le schéma s'écrit à la main.
- Fiches composées et syntagmes prépositionnels (choix du 15 septembre 2026). Le syntagme prépositionnel se note plus simplement que dans l'annotation UD : la préposition en tête, rattachée au mot qui régit (`mereor -sp-> de`), le nom comme son régime (`de -reg-> res`), le cas du régime facultatif ; dans le corpus, il trouve les compléments en `obl` et `nmod`. Les schémas écrits à la manière UD sont convertis une fois, avec une révision, puis à l'enregistrement. Une fiche dont le schéma contient celui d'une autre la montre comme composante (*rēs pūblica* dans *dē rē pūblicā bene merērī*) : repérée automatiquement parmi les fiches visibles, dans le dessin, sur la fiche et dans la recherche par schéma ; la fiche de la composante indique où elle entre ; le dessin peut insérer les liens d'une fiche existante.
- Création d'une construction à partir d'une autre (choix du 15 septembre 2026). La forme de référence peut marquer une fiche qu'elle contient : `[rēs pūblica;rem pūblicam] administrāre`. La forme simple reste la forme de référence, la forme balisée est gardée à côté ; ses mots s'affichent en surbrillance, avec une bulle qui mène à la fiche (celle au schéma contenu d'abord), sur la fiche, dans les listes et sous le champ. On marque une fiche soi-même, par le champ « Construite sur la fiche », ou en acceptant la suggestion d'une fiche connue trouvée dans les mots. Dans la création d'une fiche, la recherche d'attestations suit le schéma et cherche ses lemmes ; toute recherche d'attestations part en lemme.
- Recherche par construction (choix du 15 septembre 2026). Une recherche peut chercher une fiche comme construction, par son schéma, là où l'analyse du corpus la repère, et la combiner aux mots par la distance. Les constructions s'affichent en tête des mots, se retirent et s'ajoutent par leur nom, sur la page « Recherche » et dans les recherches d'attestations. La recherche d'attestations d'une fiche part des fiches que marque sa forme de référence (*rēs pūblica* pour `[rēs pūblica;rem pūblicam] administrāre`), puis des autres lemmes de son schéma (*administro*).

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
- Framework éprouvé et outils automatiques de sécurité (T16) : Django, PostgreSQL, HTMX, trois composants JavaScript : l'éditeur de traduction, la lecture annotée (choix du 14 septembre 2026) et le dessin du schéma (choix du 15 septembre 2026).
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
- Ce que devient un passage « entièrement relu » quand une fiche créée plus tard, ou une nouvelle analyse, y trouve une occurrence pas encore relevée.

# Catalogue du corpus

Deux fichiers décrivent les auteurs et les œuvres à importer depuis Perseus *canonical-latinLit*. On peut les ouvrir dans un tableur ; les enregistrer ensuite au format CSV (UTF-8, séparateur virgule).

- `authors.csv` : un auteur par ligne.
- `works.csv` : une œuvre par ligne, avec le fichier de l'édition Perseus retenue.

Après une modification :

```bash
python manage.py import_perseus --metadata-only   # met à jour auteurs et œuvres, sans relire les textes
python manage.py import_perseus                   # importe les textes (sur le Mac)
python manage.py import_perseus --work phi0474.phi055   # une seule œuvre
```

La commande s'arrête avec un message qui indique le fichier, la ligne et le problème si une valeur n'est pas permise.

## Colonnes

`authors.csv`

| Colonne | Contenu |
|---|---|
| `cts_id` | identifiant Perseus de l'auteur (`phi0474`) |
| `name_fr`, `name_en` | nom usuel en français et en anglais |
| `latin_name` | nom latin |
| `abbreviation` | abréviation dans les citations (`Cic.`) |
| `birth_year`, `death_year` | années ; négatives avant notre ère |
| `period` | époque (voir les valeurs ci-dessous) |

`works.csv`

| Colonne | Contenu |
|---|---|
| `cts_urn` | URN CTS de l'œuvre (`urn:cts:latinLit:phi0474.phi055`) |
| `author` | `cts_id` de l'auteur (Sénèque : `phi1017`, y compris pour ses dialogues classés `stoa0255` chez Perseus) |
| `edition_file` | chemin du fichier TEI dans le clone Perseus |
| `title`, `abbreviation` | titre latin et abréviation (`Off.`) ; l'abréviation peut rester vide (Tite-Live : `Liv. 1, 1, 1`) |
| `genre`, `register`, `form` | voir les valeurs ci-dessous |
| `date_from`, `date_to` | dates de composition ; vides si inconnues |
| `is_core` | `oui` si l'œuvre fait partie du noyau (attestations vérifiées par des personnes) |
| `is_fragmentary` | `oui` si le texte est fragmentaire ou lacunaire |
| `exclude` | expression régulière : les passages dont la référence y correspond entièrement sont écartés |

## Valeurs permises

| Colonne | Valeurs |
|---|---|
| `period` | `archaic` (latin archaïque), `classical` (classique), `imperial` (impérial), `late` (tardif), `medieval` (médiéval), `neo` (néo-latin) |
| `genre` | prose : `oratory` (éloquence), `rhetoric` (rhétorique), `philosophy` (philosophie), `letters` (lettres), `history` (histoire), `biography` (biographie), `technical` (traité technique), `miscellany` (miscellanées), `novel` (roman) ; poésie : `tragedy` (tragédie), `comedy` (comédie), `epic` (épopée), `didactic` (poésie didactique), `bucolic` (bucolique), `lyric` (poésie lyrique), `elegy` (élégie), `epigram` (épigramme), `fable` (fable) ; `satire` (satire, en vers ou ménippée) |
| `register` | `elevated` (soutenu), `standard` (courant), `familiar` (familier) |
| `form` | `prose`, `verse` (vers), `prosimetrum` (prosimètre) |

## Choix faits pour le noyau (13 septembre 2026, à relire)

- **Éditions** : quand Perseus en propose plusieurs, celle qui est découpée selon les références CTS usuelles. Tite-Live : l'édition complète `lat2` (les fichiers par livre ne sont pas découpés en CTS). Salluste, *Catilina* et *Jugurtha* : `lat4`. Cicéron, *De divinatione* : `lat1` (le fichier `lat2` contient une erreur XML).
- **Parties écartées** : listes de manuscrits et index (partout) ; *Periochae* de Tite-Live (`\d+s`), résumés tardifs qui ne sont pas de Tite-Live ; préface de l'éditeur des *Tusculanes* (`praef`) et argument de *De divinatione* II (`2arg`).
- **Sénèque** : prose dans le noyau ; les dix tragédies, *Octavia* comprise, importées hors noyau.
- **Absents de Perseus** : Cicéron *De legibus*, Sénèque *Naturales quaestiones*, Pline *Panégyrique*. Le Pseudo-César et Sénèque le Père ne font pas partie du noyau.
- **Genre, registre et dates** : première proposition, à relire avec le comité.

## Choix faits pour l'élargissement (14 septembre 2026, à relire)

Le reste de la latinité classique, du latin archaïque à la fin du IIe siècle, hors noyau : 34 auteurs et 123 œuvres. Le latin tardif et chrétien (Tertullien, Minucius Felix, *Histoire Auguste*, Ammien, Augustin…) viendra après l'ouverture.

- **Éditions** : Celse, l'édition de Marx (`lat6`) ; Pétrone, `lat2` (le fichier `lat1` n'est pas découpé en CTS). Les vers sont cités par livre ou poème puis vers (*Aen.* 1, 1), selon le motif de citation du fichier ; les sections marquées `<seg>` (Népos) et les chapitres marqués par des jalons (Tacite, *Annales*) donnent chacun un passage.
- **Parties écartées** : distributions, résumés et didascalies des comédies de Térence (`cast|subject_\d+|production`), qui ne sont pas de Térence ; adresse non numérotée du *Commentariolum petitionis* (`^$`) ; *Punica* 11, 453-458, en double dans le fichier.
- **Pseudo-César** : les trois *Bella* sous un seul auteur (`phi0428`), comme les dialogues de Sénèque.
- **Laissés de côté pour l'instant** : Caton, *De agri cultura* (deux chapitres 1 dans le fichier Perseus) ; *Appendix Vergiliana* (fichiers sans divisions lisibles, textes apocryphes) ; Auguste (absent de Perseus).
- **Salluste, *Historiae*** : le fichier est désormais lu section par section. L'édition déjà importée reste telle quelle (une édition importée est figée) ; le changement vaudra à la prochaine version de Perseus.
- **Dates des auteurs** : approximatives quand elles sont incertaines (Phèdre, Juvénal, Suétone) ; vides quand elles sont inconnues.

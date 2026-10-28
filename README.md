# Erika (PC-8801) : portage natif

Réimplémentation en Python du jeu d'aventure **Erika** (JAST, 1986, NEC PC-8801), pour y
jouer sur un PC actuel **sans émulateur**. Le moteur lit les données directement depuis
l'image disque d'origine : images, textes, polices, vocabulaire, scripts, voix numérisées.
Il les réinterprète ensuite en Python, sans exécuter le code Z80.

Le dépôt ne contient **aucune donnée du jeu** : il faut fournir sa propre image disque
`erika.d88`.

> Erika est un jeu pour adultes : certaines scènes sont explicites.

## Installation

Il faut [uv](https://docs.astral.sh/uv/) et Python 3.13 ou plus récent (uv peut
l'installer lui-même).

```sh
git clone <ce dépôt> erika && cd erika
cp /chemin/vers/erika.d88 .   # image 2D à deux disquettes (DISK A + DISK B)
uv run erika play
```

`uv run` installe automatiquement les dépendances (pygame-ce, numpy, Pillow, z80dis).
Pour utiliser une image ailleurs : `uv run erika --image /chemin/erika.d88 play`.

## Jouer

Sur l'écran titre, appuie sur **Entrée** une fois le texte affiché. Le jeu commence dans le
cockpit d'un avion de chasse écrasé. Tape tes commandes après le ♡, puis valide avec Entrée.

Une commande associe un **verbe** et un **nom**, dans n'importe quel ordre :
`konpyu-ta shiraberu` (examiner l'ordinateur), `souzi deru` (sortir du cockpit),
`hidari susumu` (aller à gauche). Le jeu cherche les trois premières lettres de chaque mot
n'importe où dans la phrase.

### Touches

| Touche | Effet |
|---|---|
| Entrée | valider une commande, passer un « HIT ANY KEY » |
| Retour arrière | effacer |
| ESC (pendant une saisie) | sauvegarder (Entrée confirme, une autre touche annule) |
| ESC (sur l'écran titre) | charger la sauvegarde |
| F2 | changer de saisie : traduite (si une traduction est chargée), romaji moderne, romaji d'origine |
| F11 | plein écran |
| Une touche pendant un dessin | terminer le dessin tout de suite |

### Saisie

- **Moderne** (par défaut) : romaji courant, converti au fil de la frappe.
  - `shi`, `chi`, `tsu`, `fu`, `ja`, `kya`…
  - `nn` ou `n'` donnent ん ; une consonne doublée donne っ.
  - `-` donne ー : tape `ka-do` pour かーど (`kaado` donne かあど, que le jeu ne reconnaît pas).
  - Les petits kana sont écrits en grand, comme dans le vocabulaire du jeu : `uchuu` donne うちゆう.
- **D'origine** (`--saisie origine` ou F2) : la conversion du jeu de 1986, bizarreries comprises.
  - `WI` donne ん, `WU` donne ー.
  - Il n'y a ni `SHI`, ni `CHI`, ni `TSU`, ni `FU`, ni petits kana.
  - C, F, J, L, Q, V et X sont refusés.
  - `WO` affiche un ゛ isolé (bug d'origine).
- Un **IME japonais** fonctionne aussi dans les deux modes.

### Menu de la souris

Le panneau de droite (前に行く, 見る, 調べる…) est cliquable.
- Une direction ou やめる envoie la commande directement.
- Un verbe s'ajoute à la saisie ; il reste à taper le nom.
- Un clic fait aussi avancer les « HIT ANY KEY ».

### Jouer dans une autre langue

```sh
uv run erika play --langue fr          # charge translations/fr.po
uv run erika play --traduction autre.po
```

Les messages, le menu et l'interface s'affichent dans la langue de la traduction, avec une
police pixel 6×10. Un texte pas encore traduit reste en japonais. La saisie passe en mode
**traduit** : tape tes commandes librement (« examiner l'ordinateur », « sortir du
cockpit »). Elles sont converties en mots japonais d'origine, puis analysées comme dans
le jeu. **F2** passe ensuite en romaji moderne, puis en romaji d'origine.

### Sauvegarde

Il y a un seul emplacement, comme dans l'original. Le fichier est
`~/.local/share/erika/save.bin` (`%APPDATA%\erika\save.bin` sous Windows), au format du
secteur de sauvegarde d'origine. Tant qu'il n'existe pas, le chargement lit la sauvegarde
éventuellement présente sur la disquette. L'image `erika.d88` n'est jamais modifiée.

### Différences avec l'original

- Les demandes de changement de disquette sont sautées : le moteur lit les deux disquettes.
- Après un GAME OVER ou une fin, une touche ramène à l'écran titre (l'original se figeait).
- Les images se dessinent plus vite que sur un PC-88 à 4 MHz (environ 1 s au lieu de 4 à 5 s).
- Le volume des voix est normalisé, car les enregistrements ont des niveaux très inégaux.

## Traduire le jeu

Les traductions sont des fichiers gettext `.po`, éditables avec Poedit, Lokalize, Weblate…

1. `uv run erika i18n` génère `translations/erika.pot` depuis ton image disque : environ
   1 250 entrées, avec le japonais d'origine.
2. Crée `translations/<langue>.po` à partir de ce modèle (Poedit : « Nouvelle traduction à
   partir d'un fichier POT »), puis traduis.
3. Relance `uv run erika i18n` quand le modèle change : il met à jour tous les `.po`
   présents dans `translations/`.

Le contexte (`msgctxt`) de chaque entrée indique de quoi il s'agit :

| Contexte | Contenu | Remarque |
|---|---|---|
| `systeme 0xNN` | messages communs à tout le jeu | |
| `salle NN 0xMM` | textes de la salle NN | une ligne fait 106 caractères ; un « appuyez sur une touche » tous les deux retours à la ligne |
| `menu NN` | lignes du menu de droite | 14 caractères au plus |
| `interface …` | APPUYEZ SUR UNE TOUCHE, PARTIE TERMINÉE, sauvegarde, chargement | une ligne |
| `verbe 0xNN`, `nom 0xNN` | mots que le joueur peut taper | plusieurs synonymes séparés par `|` (`examiner|fouiller`) |
| `reponse 0xNNNN` | réponses aux questions du jeu (nom du héros…) | formes acceptées séparées par `|` ; les nombres comme `615` passent tels quels |

Pour la saisie traduite, la casse et les accents sont ignorés, un « s » ou un « x » final
est toléré, et un synonyme peut contenir plusieurs mots (`à gauche`). Les mots du
vocabulaire japonais sont souvent tronqués à trois caractères (こくぴ pour « cockpit »,
こんぴ pour « ordinateur ») : le contexte des messages aide à les identifier.

`translations/fr.po` est un exemple partiel : la salle 1, le menu, l'interface et le
vocabulaire de départ.

> Un `.po` contient le texte japonais d'origine (en `msgid`), qui appartient à JAST :
> réfléchis avant de le publier dans un dépôt public.

## Son

Le jeu envoie ses voix numérisées sur le **port imprimante** du PC-88, et non sur une puce
sonore. Elles passaient très probablement par le boîtier vocal « JAST SOUND ». Sans ce
boîtier, le jeu d'origine était muet, et MAME l'est aussi. Le moteur décode les 30 voix,
le bruit du tir et le bip, et les joue aux bons moments. La fréquence d'échantillonnage
(≈ 3,9 kHz) est déduite du nombre de cycles de la routine de lecture : si les voix semblent
trop aiguës ou trop graves, ajuste `CYCLES_PER_SAMPLE` dans
`src/erika_tools/sound.py`.

## Outils d'extraction

Ces commandes écrivent leurs résultats dans `extracted/`, qui est ignoré par git.

| Commande | Résultat |
|---|---|
| `uv run erika dump` | chaque disquette en image linéaire (`diskA.bin`, `diskB.bin`) |
| `uv run erika gfx` | les 62 images en PNG (512×160, et ×2 en hauteur) |
| `uv run erika text` | les textes (`text.tsv`), le vocabulaire, une fiche JSON par salle (textes et commandes) |
| `uv run erika fonts` | les deux polices du jeu (12×10 px) en PNG |
| `uv run erika sound` | les voix, le tir et le bip en WAV |
| `uv run erika disasm` | le désassemblage du programme principal (`main.asm`) |

## Vérification

Le moteur a été comparé à l'original émulé sous MAME : partie complète jusqu'à la fin A,
soit 61 saisies, avec comparaison de l'écran au pixel près et des drapeaux de progression
après chaque saisie. Ces outils servent au développement ; ils ne sont pas nécessaires pour
jouer.

- `uv run python tools/explore.py --json extracted/paths.json` explore automatiquement le
  jeu (salles, scripts, fins) et écrit des chemins rejouables, dont
  `extracted/paths_finA.json` et `extracted/paths_finB.json`.
- `uv run python tools/mame/compare.py --path extracted/paths_finA.json` rejoue un chemin
  dans MAME et dans le moteur, puis compare les deux.
  - Prérequis : MAME (`flatpak install flathub org.mamedev.MAME`) et les ROM BIOS du
    PC-8801mkII SR, à fournir soi-même dans `roms/pc8801mk2sr/`.
  - `uv run erika check-bios` les identifie par CRC et prépare `roms/mame/` pour MAME.

## Organisation

```
src/erika_tools/
  d88.py        lecture des images disque D88
  gfx.py        décodeur d'images (tracé RLE, fond, remplissages tramés)
  charset.py    polices et jeu de caractères (hiragana, katakana, 256 kanji)
  text.py       textes, vocabulaire, commandes des salles
  scripts.py    traduction des 255 scripts Z80 en opérations du moteur
  sound.py      décodeur des voix numérisées
  disasm.py     désassembleur Z80 (outil d'analyse)
  cli.py        commande `erika`
  game/         moteur : data.py, display.py, engine.py, romaji.py, save.py, i18n.py,
                fonts/6x10.bdf (police des traductions, domaine public)
tools/          exploration automatique, comparaison avec MAME
translations/   traductions .po (le modèle erika.pot est généré, non suivi par git)
notes/format.md formats et fonctionnement du jeu, adresse par adresse
```

Toute la rétro-ingénierie (chargement, formats, logique, adresses des routines) est
documentée dans [notes/format.md](notes/format.md).

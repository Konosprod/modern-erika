# Erika (JAST, PC-8801) : formats et fonctionnement

Toutes les adresses sont celles de la mémoire Z80 après le boot. Le code de référence se
régénère avec `uv run erika disasm` (programme principal 9000-BFFF) et
`uv run erika disasm --start 0xc000 --end 0xc400 -o boot.asm`.

## Image disque

`erika.d88` contient deux disquettes 2D concaténées (« DISK A » et « DISK B »). Chacune a
40 cylindres × 2 faces × 16 secteurs × 256 octets, sans système de fichiers.
Le jeu adresse le disque par **piste linéaire** (cylindre × 2 + face) et par secteur
(1 à 16). L'offset dans `extracted/diskX.bin` vaut donc `(piste × 16 + secteur − 1) × 256`.

## Chargement (boot sector A:0/1, exécuté en C000)

Routine de lecture `C078` : A = lecteur, C = nombre de secteurs, D = piste linéaire,
E = secteur, HL = destination. `C003` prend les mêmes paramètres via IX (lecteur, piste,
secteur, nombre).

| Source        | Secteurs | Destination | Contenu                                    |
|---------------|---------:|-------------|--------------------------------------------|
| A piste 0 s1  | 4        | C000        | boot, routines disque (sous-système FDD)   |
| A piste 2 s1  | 32       | C600-E5FF   | messages système, polices                  |
| A piste 7 s1  | 5        | 4000-44FF   | à identifier (appelé via B786)             |
| A piste 4 s1  | 48       | 9000-BFFF   | programme principal, point d'entrée 9000   |

Variables utiles : 8E00-8E03 = drapeaux de progression, 8E04 = salle courante.

## Salles

La table en **933B** contient 62 entrées de 6 octets : `lecteur, piste, secteur, nb_secteurs, msg_entrée, script_entrée`.
Le bloc d'une salle est chargé à l'adresse 0000 (RAM en mode 64K). La routine C057 ignore
le numéro de lecteur de la table (`XOR A`) : tout est lu depuis le lecteur 1. D'où le message
« フロッピー2をドライブ1に… » (script 17, avant la salle 31). Le moteur, lui, lit chaque
salle sur la bonne disquette. Il est structuré ainsi :

```
[image : tracé RLE + commandes de remplissage, finit par 00 00]
[textes : chaînes terminées par 00, puis un 00 final]
[N : 1 octet] [N commandes de 6 octets]
```

Une commande est `verbe, nom, salle, b3, message, script` (lue par A2BB). **Le jeu lit N + 1
commandes**, car A2BB teste le compteur après chaque entrée. La dernière est presque toujours
une commande par défaut (`もどる *`, `にげる *`, `やめる *`) ; en salle 10, c'est elle qui
fait avancer l'histoire (script 53).
- `verbe` et `nom` sont des index dans les tables de mots. FF = joker.
- Si `salle` ≠ 0 et diffère de la salle courante, le jeu change de salle : il charge
  la salle, dessine l'image, affiche le message d'entrée et lance le script d'entrée.
- Sinon il affiche `message` ; si `script` ≠ 0, il lance le script n°`script`.
- `b3` vaut 00 ou FF. Son rôle reste à déterminer (il n'est pas lu par A2BB).

Les salles 58 à 61 n'ont aucune commande : ce sont des séquences pilotées par les scripts
(fin de partie, etc.).

## Analyse de la saisie

Le joueur tape en kana dans le buffer 8400, terminé par CR. Pour chaque commande de la
salle, le jeu cherche les **3 premiers caractères** du verbe, puis ceux du nom, n'importe
où dans la saisie (routine A35B). La première commande qui correspond aux deux l'emporte.
Si aucune ne correspond, le jeu affiche le message 0.
- Verbes : table A3A2, 34 entrées de 4 octets.
- Noms : table A42A, 141 entrées de 4 octets.

## Messages

Le numéro de message est stocké en 9314 :
- 0-15 : messages système, chaînes successives à partir de C600 ;
- 0x10 + i : i-ème texte de la salle courante.

## Scripts

La table de sauts en A6BC contient environ 250 adresses (BAA8 = script vide). Ce sont de
petites routines Z80. En entrée, IX = 8E00 (drapeaux) et HL = 9314 (message). Leur jeu
d'instructions est limité :
- `LD (HL),n` : choisit le message ;
- `BIT/SET/RES b,(IX+d)` : teste ou modifie un drapeau ;
- `JP Z/NZ,A680` : affiche le message et revient à la saisie ;
- `JP B514`, `JP B4F7`, `JP B500` (avec A = n) : actions spéciales (changement de salle,
  game over, etc.), à documenter.

Avec un jeu d'instructions aussi réduit, on peut les **traduire statiquement** en données
pour le moteur, sans exécuter de Z80 : c'est le rôle de `scripts.py`, qui traduit les 255
scripts en opérations nommées (show, goto, goto_random, dispatch, say, pause, ask,
game_over, halt, patch_image, wait_key, disk_swap, freeze).

Routines appelées :
- B500 affiche le message puis change de salle (A) ;
- B4F7 fait de même vers la salle 11 ou 12, au hasard (registre R) ;
- B50B affiche le message ;
- B525 affiche le message puis « HIT ANY KEY » ;
- B514 fait un game over : message, pause, message 7, « GAME OVER », blocage ;
- B52B pose une question (réponses `615`, おるき ; えりか mène à la fin de la salle 61) ;
- B590 colore un rectangle de l'image ;
- 915C demande de changer de disquette ;
- `JR $` (script 248) est la **fin du jeu**, en deux variantes selon 8E02 bit 6.
  Exemple : 「…あなたは、みごとに任務を果たしました！おめでとう‼」.

Après chaque message, la table B617 (salle, message) → n° de clip déclenche la lecture d'une
**voix numérisée** : la table B70D indique les secteurs, B78B joue des deltas 4 bits sur le
port 0x10. L'overlay en 4000 est le bruit du tir (B786, verbe うつ + じゆう/れーざ).

## Texte et polices

Les glyphes font 12×10 px et occupent 15 octets chacun : 10 octets pour les 8 colonnes de
gauche, puis 5 octets de quartets pour les 4 colonnes de droite (deux lignes par octet,
quartet haut en premier).
- C800 : police normale. 0x20-0x5F = ASCII, 0x60-0x65 = traits de cadre,
  0x66-0x9F = katakana (disposition JIS X 0201 décalée de −0x40),
  0xA1-0xDF = hiragana (disposition JIS X 0201), 0xE0-0xE7 = symboles ♡♥〜⁉○●×‼.
  Les codes 0x00-0x1F contiennent le logo « Presented by JAST ».
- D700 : police kanji. `FF nn` affiche le kanji nn. La table Unicode est dans
  `charset.py` ; elle a été vérifiée sur tous les textes, sauf 0xAB (jamais utilisé).
- ゛ et ゜ sont des caractères séparés, recombinés en NFC à l'extraction.

L'écran de texte se trouve sous l'image : 44 colonnes de 12 px (B = 0x2C…), lignes de 10 px.

## Images (9D6F → 9D7C, 9E24 ; transcrites dans `gfx.py`)

1. **Tracé** : RLE 1 bpp écrit à l'identique dans les trois plans. `00 n` produit n fois
   0x00, `FF n` produit n fois 0xFF, tout autre octet est littéral. La zone fait 64 octets
   (512 px) de large avec un pas de 80 octets ; le tracé s'arrête quand l'adresse atteint F1B0.
2. **Fond** : 2 octets ignorés, puis un index de motif. Les 160 lignes sont ANDées avec ce motif.
3. **Remplissage** : `[00 y]` (optionnel) puis `x_hi, x_lo, motif`. La suite `00 00` termine
   l'image. L'algorithme remplit par segments horizontaux, avec une file circulaire de
   365 entrées en 8400. La frontière est un pixel noir sur les trois plans. Le résultat
   dépend de l'algorithme exact, car les motifs tramés contiennent du noir.
4. **Motifs** : 36 entrées de 6 octets en A1E3, au format (B, R, G) pour la ligne paire
   puis (B, R, G) pour la ligne impaire.

Le jeu ne modifie pas la palette : c'est la palette numérique 8 couleurs (G<<2 | R<<1 | B).
Les images font 512×160 px ; elles sont exportées telles quelles et en version ×2 en hauteur.

## Vérification avec MAME

ROM : `uv run erika check-bios`, qui crée `roms/mame/pc8801mk2sr/`, des liens par CRC vers
`roms/pc8801mk2sr/`. Pour lancer le jeu sans affichage, découper le D88 en deux images, une
par lecteur (348 848 octets chacune), puis :
`flatpak run org.mamedev.MAME pc8801mk2sr -rompath roms/mame -flop1 A.d88 -flop2 B.d88
-video none -nothrottle -seconds_to_run N -autoboot_script x.lua`.
Le dossier de travail doit être sous `$HOME`, car le sandbox Flatpak ne voit pas `/tmp`.
En Lua, utiliser `emu.register_periodic` : `add_machine_frame_notifier` cesse d'être
appelé vers t = 3 s.

Résultats :
- l'écran titre (salle 0) et la salle 1 rendus par `gfx.py` sont **identiques au pixel près**
  aux captures MAME (0 différence sur 512×160) ;
- le jeu dessine progressivement : tracé, puis remplissages un par un ; l'image suivante
  recouvre la précédente par bandes ;
- l'écran est organisé ainsi : image 512×160 en haut à gauche, texte sur les lignes du bas
  (pleine largeur, police 12×10, curseur ♡), panneau à droite. Ce panneau contient le
  menu de commandes (routine 9B08, table 9B65, couleur 1) : 前に行く 後ろに行く 左に行く
  右に行く 見る 行く 入る 探す 調べる 話す 取る あける やめる, avec « (C) JAST » en cyan
  dessous ;
- Entrée sur l'écran titre affiche la salle 1 et son texte d'entrée.
- Le parseur a été testé dans la salle 1 avec `tools/mame/type_commands.lua`. Ce script tape
  un caractère toutes les 0,2 s, car le jeu perd les touches envoyées plus vite par
  `natkeyboard:post`. Résultats, tous conformes à `rooms/room01.json` :
  こんぴ しらべる → コンピューターは、生きているようです。
  ひだり しらべる → 湖があります。
  そうじ なぐる → OK!でも、手が痛かっただけで、何も起こりません。
  ほげほげ → ここでは、できません。(aucune commande ne correspond : message 0)
  かーど しらべる → あなたは、それを持っていません。(script 4 : bit 3 de 8E00 à 0, donc message 5)

## Saisie (94AF)

La saisie s'affiche en vert après le curseur ♡. Le buffer 8400 accepte 50 caractères au maximum.
Les touches kana (0xA0-0xDF) sont prises telles quelles. Le jeu a aussi son propre
convertisseur romaji, qui met les lettres en majuscules :
- une voyelle seule donne あいうえお (96CB) ;
- une consonne est mise en attente (97D0) ; une deuxième consonne est ignorée, sans
  « NN » ni double consonne ;
- consonne + voyelle passe par la table 978A (lignes de 5) : K S T N H M Y R W G Z D B P ;
  G/Z/D/B ajoutent ゛ et P ajoute ゜ ;
- spécial : `WI` = ん, `WU` = ー, `YI`/`YE` = rien ; `WO` produit un ゛ isolé (bug :
  l'entrée vaut 00 et se trouve à la frontière de la zone dakuten) ;
- C, F, J, L, Q, V, X et les petits kana ne sont pas disponibles en romaji (seulement
  en kana) ;
- les chiffres, l'espace, la virgule et `-` sont gardés tels quels ; `-` (0x2D) ne
  correspond pas à ー (0xB0) dans les noms ;
- 0x7F = effacement, CR = validation, ESC = retour (vers 9177), `*` appelle 97D7.

## Validation complète (tools/explore.py, tools/mame/compare.py)

`tools/explore.py` explore les états (salle, drapeaux) avec le moteur sans affichage. Il
atteint 54 salles sur 62, exerce 217 routines de scripts sur 222 et trouve les deux fins.
Il écrit des chemins rejouables (`extracted/paths_finA.json`, …), où chaque commande est
suivie des saisies attendues : pauses, réponses, choix, changement de disquette.

`tools/mame/compare.py --path …` rejoue un chemin dans MAME et dans le moteur. Il compare
écran et drapeaux après chaque saisie et repère que le jeu attend une touche quand le Z80
reste en ROM. Sur la fin A (61 saisies), drapeaux et salles sont identiques partout, et
l'écran est identique au pixel près partout sauf deux captures : MAME, sans affichage,
rend parfois un écran en retard (la pile montre qu'il est déjà à l'invite).

## À faire (phase 2)

- Son : voix numérisées (B78B, tables B617/B70D), tir (overlay 4000), bip (965B).
- Rôle de l'octet b3 des commandes (00/FF, jamais lu par A2BB).
- Comparer avec MAME (`uv run erika check-bios`) : rendu du texte, mise en page de l'écran.

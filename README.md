# Erika (PC-8801): native port

A Python reimplementation of the adventure game **Erika** (JAST, 1986, NEC PC-8801), so
it can be played on a modern PC **without an emulator**. The engine reads the data
directly from the original disk image: pictures, texts, fonts, vocabulary, scripts and
digitized voices. It then reinterprets them in Python, without running the Z80 code.

The repository contains **no game data**: you must supply your own `erika.d88` disk image.

> Erika is an adult game: some scenes are explicit.

## Installation

You need [uv](https://docs.astral.sh/uv/) and Python 3.13 or later (uv can install it
for you).

```sh
git clone <this repository> erika && cd erika
cp /path/to/erika.d88 .   # 2D image with both floppies (DISK A + DISK B)
uv run erika play
```

`uv run` installs the dependencies automatically (pygame-ce, numpy, Pillow, z80dis).
To use an image stored elsewhere: `uv run erika --image /path/to/erika.d88 play`.

## Playing

On the title screen, press **Enter** once the text is displayed. The game starts in the
cockpit of a crashed fighter plane. Type your commands after the ♡, then press Enter.

A command combines a **verb** and a **noun**, in any order:
`konpyu-ta shiraberu` (examine the computer), `souzi deru` (leave the cockpit),
`hidari susumu` (go left). The game looks for the first three letters of each word
anywhere in the sentence.

### Keys

| Key | Effect |
|---|---|
| Enter | submit a command, dismiss a "HIT ANY KEY" |
| Backspace | delete |
| ESC (while typing) | save (Enter confirms, any other key cancels) |
| ESC (on the title screen) | load the saved game |
| F2 | switch input mode: translated (if a translation is loaded), modern romaji, original romaji |
| F11 | full screen |
| Any key while a picture is drawing | finish the drawing at once |

### Input

- **Modern** (default): standard romaji, converted as you type.
  - `shi`, `chi`, `tsu`, `fu`, `ja`, `kya`…
  - `nn` or `n'` give ん; a doubled consonant gives っ.
  - `-` gives ー: type `ka-do` for かーど (`kaado` gives かあど, which the game doesn't recognize).
  - Small kana are written full-size, as in the game's vocabulary: `uchuu` gives うちゆう.
- **Original** (`--input original` or F2): the 1986 game's own conversion, quirks included.
  - `WI` gives ん, `WU` gives ー.
  - There is no `SHI`, `CHI`, `TSU`, `FU`, and no small kana.
  - C, F, J, L, Q, V and X are rejected.
  - `WO` displays a lone ゛ (an original bug).
- A **Japanese IME** also works in both modes.

### Mouse menu

The right-hand panel (前に行く, 見る, 調べる…) is clickable.
- A direction or やめる sends the command right away.
- A verb is added to the input; you then type the noun.
- A click also dismisses "HIT ANY KEY" prompts.

### Playing in another language

```sh
uv run erika play --lang fr            # loads translations/fr.po
uv run erika play --translation other.po
```

Messages, the menu and the interface are shown in the translation's language, with a
6×10 pixel font. Text that isn't translated yet stays in Japanese. Input switches to
**translated** mode: type your commands freely (for the French translation, "examiner
l'ordinateur", "sortir du cockpit"). They are converted into the original Japanese words,
then parsed as in the game. **F2** then switches to modern romaji, then to original romaji.

### Saving

There is a single slot, as in the original. The file is `~/.local/share/erika/save.bin`
(`%APPDATA%\erika\save.bin` on Windows), in the format of the original save sector. Until
it exists, loading reads the save that may be present on the floppy. The `erika.d88`
image is never modified.

### Differences from the original

- Disk swap prompts are skipped: the engine reads both floppies.
- After a GAME OVER or an ending, a key press returns to the title screen (the original
  froze).
- Pictures draw faster than on a 4 MHz PC-88 (about 1 s instead of 4 to 5 s).
- Voice volume is normalized, because the recordings have very uneven levels.

## Translating the game

Translations are gettext `.po` files, editable with Poedit, Lokalize, Weblate…

1. `uv run erika i18n` generates `translations/erika.pot` from your disk image: about
   1,250 entries, with the original Japanese.
2. Create `translations/<language>.po` from this template (Poedit: "Create new translation"
   from a POT file), then translate.
3. Run `uv run erika i18n` again when the template changes: it updates every `.po` file in
   `translations/`.

Each entry's context (`msgctxt`) tells what it is:

| Context | Content | Note |
|---|---|---|
| `system 0xNN` | messages shared by the whole game | |
| `room NN 0xMM` | texts of room NN | a line holds 106 characters; a "press any key" every second line break |
| `menu NN` | lines of the right-hand menu | 14 characters at most |
| `ui …` | HIT ANY KEY, GAME OVER, save, load | one line |
| `verb 0xNN`, `noun 0xNN` | words the player can type (verbs, nouns) | several synonyms separated by `|` (`examine|search`) |
| `answer 0xNNNN` | answers to the game's questions (the hero's name…) | accepted forms separated by `|`; numbers such as `615` pass through as is |

In translated input, case and accents are ignored, a trailing "s" or "x" is tolerated,
and a synonym may contain several words (`à gauche`). The Japanese vocabulary words are
often truncated to three characters (こくぴ for "cockpit", こんぴ for "computer"): the
surrounding messages help identify them.

### Machine translation (DeepL)

`tools/translate_deepl.py` fills in the still-empty messages of a `.po` file using the
DeepL API. The free plan is enough: the game has about 23,000 characters, for a quota of
500,000 per month.

```sh
export DEEPL_AUTH_KEY=…                                     # DeepL API key
uv run python tools/translate_deepl.py --lang fr --dry-run  # count without sending anything
uv run python tools/translate_deepl.py --lang fr
```

The tool makes one call per room, with the room's other texts as context. It touches
neither existing translations nor the vocabulary, and marks each entry "DeepL, to review"
(translator comment). It saves after each room, so it can be interrupted and
restarted. The vocabulary (synonym lists) is translated by hand, because DeepL can't make
sense of truncated words such as こくぴ.

> A `.po` file contains the original Japanese text (as `msgid`), which belongs to JAST:
> think twice before publishing it in a public repository.

## Sound

The game sends its digitized voices to the PC-88's **printer port**, not to a sound
chip. They most likely went through JAST's "JAST SOUND" voice box. Without that box the
original game was silent, and so is MAME. The engine decodes the 30 voices, the gunshot
and the beep, and plays them at the right moments. The sample rate (≈ 3.9 kHz) is derived
from the cycle count of the playback routine: if the voices sound too high or too low,
adjust `CYCLES_PER_SAMPLE` in `src/erika_tools/sound.py`.

## Extraction tools

These commands write their output to `extracted/`, which git ignores.

| Command | Output |
|---|---|
| `uv run erika dump` | each floppy as a linear image (`diskA.bin`, `diskB.bin`) |
| `uv run erika gfx` | the 62 pictures as PNG (512×160, and ×2 in height) |
| `uv run erika text` | the texts (`text.tsv`), the vocabulary, one JSON file per room (texts and commands) |
| `uv run erika fonts` | the game's two fonts (12×10 px) as PNG |
| `uv run erika sound` | the voices, gunshot and beep as WAV |
| `uv run erika disasm` | the disassembly of the main program (`main.asm`) |

## Verification

The engine was compared with the original running under MAME: a full playthrough to
ending A, 61 inputs, comparing the screen pixel for pixel and the progress flags after
each input. These tools are for development; you don't need them to play.

- `uv run python tools/explore.py --json extracted/paths.json` explores the game
  automatically (rooms, scripts, endings) and writes replayable paths, including
  `extracted/paths_endingA.json` and `extracted/paths_endingB.json`.
- `uv run python tools/mame/compare.py --path extracted/paths_endingA.json` replays a path in
  MAME and in the engine, then compares the two.
  - Requirements: MAME (`flatpak install flathub org.mamedev.MAME`) and the PC-8801mkII SR
    BIOS ROMs, which you must supply yourself in `roms/pc8801mk2sr/`.
  - `uv run erika check-bios` identifies them by CRC and prepares `roms/mame/` for MAME.

## Layout

```
src/erika_tools/
  d88.py        D88 disk image reader
  gfx.py        picture decoder (RLE line art, background, dithered fills)
  charset.py    fonts and character set (hiragana, katakana, 256 kanji)
  text.py       texts, vocabulary, room commands
  scripts.py    translation of the 255 Z80 scripts into engine operations
  sound.py      digitized voice decoder
  disasm.py     Z80 disassembler (analysis tool)
  cli.py        the `erika` command
  game/         engine: data.py, display.py, engine.py, romaji.py, save.py, i18n.py,
                fonts/6x10.bdf (font for translations, public domain)
tools/          automatic exploration, comparison with MAME
translations/   .po translations (the erika.pot template is generated, not tracked by git)
notes/format.md formats and inner workings of the game, address by address
```

All the reverse engineering (loading, formats, logic, routine addresses) is documented in
[notes/format.md](notes/format.md).

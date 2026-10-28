# Erika (JAST, PC-8801): formats and inner workings

All addresses are Z80 memory addresses after boot. The reference code can be regenerated
with `uv run erika disasm` (main program 9000-BFFF) and
`uv run erika disasm --start 0xc000 --end 0xc400 -o boot.asm`.

## Disk image

`erika.d88` holds two concatenated 2D floppies ("DISK A" and "DISK B"). Each has
40 cylinders × 2 sides × 16 sectors × 256 bytes, with no file system.
The game addresses the disk by **linear track** (cylinder × 2 + side) and sector (1 to
16). The offset in `extracted/diskX.bin` is therefore `(track × 16 + sector − 1) × 256`.

## Loading (boot sector A:0/1, run at C000)

Read routine `C078`: A = drive, C = sector count, D = linear track, E = sector,
HL = destination. `C003` takes the same parameters through IX (drive, track, sector,
count).

| Source         | Sectors | Destination | Contents                                    |
|----------------|--------:|-------------|---------------------------------------------|
| A track 0 s1   | 4       | C000        | boot, disk routines (FDD subsystem)         |
| A track 2 s1   | 32      | C600-E5FF   | system messages, fonts                      |
| A track 7 s1   | 5       | 4000-44FF   | gunshot sound (played through B786)         |
| A track 4 s1   | 48      | 9000-BFFF   | main program, entry point 9000              |

Useful variables: 8E00-8E03 = progress flags, 8E04 = current room.

## Rooms

The table at **933B** holds 62 entries of 6 bytes:
`drive, track, sector, sector_count, entry_msg, entry_script`.
A room's block is loaded at address 0000 (RAM in 64K mode). Routine C057 ignores the
table's drive number (`XOR A`): everything is read from drive 1. Hence the message
"フロッピー2をドライブ1に…" (script 17, before room 31). The engine, for its part, reads
each room from the right floppy. A block is laid out as follows:

```
[picture: RLE line art + fill commands, ends with 00 00]
[texts: 00-terminated strings, then a final 00]
[N: 1 byte] [N + 1 commands of 6 bytes]
```

A command is `verb, noun, room, b3, message, script` (read by A2BB). **The game reads
N + 1 commands**, because A2BB tests the counter after each entry. The last one is almost
always a default command (`もどる *`, `にげる *`, `やめる *`); in room 10, it is the one
that moves the story forward (script 53).
- `verb` and `noun` are indexes into the word tables. FF = wildcard.
- If `room` ≠ 0 and differs from the current room, the game changes room: it loads the
  room, draws the picture, shows the entry message and runs the entry script.
- Otherwise it shows `message`; if `script` ≠ 0, it runs script number `script`.
- `b3` is 00 or FF. Its role is still unknown (A2BB does not read it).

Rooms 58 to 61 have N = 0, so a single command: they are sequences driven by scripts
(endings, etc.).

## Input parsing

The player types kana into the buffer at 8400, terminated by CR. For each command of the
room, the game looks for the **first 3 characters** of the verb, then those of the noun,
anywhere in the input (routine A35B). A dakuten (゛) counts as one character. The first
command matching both wins. If none matches, the game shows message 0.
- Verbs: table A3A2, 34 entries of 4 bytes.
- Nouns: table A42A, 141 entries of 4 bytes.

## Messages

The message number is stored at 9314:
- 0-15: system messages, consecutive strings from C600;
- 0x10 + i: i-th text of the current room.

## Scripts

The jump table at A6BC holds 255 addresses (BAA8 = empty script). They are small Z80
routines. On entry, IX = 8E00 (flags) and HL = 9314 (message). Their instruction set is
limited:
- `LD (HL),n`: picks the message;
- `BIT/SET/RES b,(IX+d)`: tests or changes a flag;
- `JP Z/NZ,A680`: shows the message and returns to input;
- `JP`/`CALL` to the game routines listed below, with A = parameter.

With such a small instruction set, they can be **translated statically** into data for
the engine, without running any Z80: that is the job of `scripts.py`, which translates the
255 scripts into named operations (show, goto, goto_random, dispatch, say, pause, ask,
game_over, halt, patch_image, wait_key, disk_swap, freeze).

Routines called:
- B500 shows the message, then changes room (A);
- B4F7 does the same towards room 11 or 12, at random (R register);
- B50B shows the message;
- B525 shows the message, then "HIT ANY KEY";
- B514 is a game over: message, pause, message 7, "GAME OVER", freeze;
- B52B asks a question (answers `615`, おるき; えりか leads to the room 61 ending);
- B590 colors a rectangle of the picture;
- 915C asks for a disk swap;
- `JR $` (script 248) is the **end of the game**, in two variants depending on 8E02 bit 6.
  Example: "…あなたは、みごとに任務を果たしました！おめでとう‼".

After each message, the table B617 (room, message) → clip number triggers a **digitized
voice**: the table B70D gives the sectors, and B78B plays 4-bit deltas on port 0x10. The
overlay at 4000 is the gunshot sound (B786, verb うつ + じゆう/れーざ).

## Text and fonts

Glyphs are 12×10 px and take 15 bytes each: 10 bytes for the 8 left columns, then 5 bytes
of nibbles for the 4 right columns (two rows per byte, high nibble first).
- C800: normal font. 0x20-0x5F = ASCII, 0x60-0x65 = box-drawing lines,
  0x66-0x9F = katakana (JIS X 0201 layout shifted by −0x40),
  0xA1-0xDF = hiragana (JIS X 0201 layout), 0xE0-0xE7 = symbols ♡♥〜⁉○●×‼.
  Codes 0x00-0x1F hold the "Presented by JAST" logo.
- D700: kanji font. `FF nn` displays kanji nn. The Unicode table is in `charset.py`;
  it was checked against every text, except 0xAB (never used).
- ゛ and ゜ are separate characters, recombined into NFC on extraction.

Text is written below the picture: 53 columns of 12 px, 10 px lines (rows 17 to 19,
scrolling). The right-hand menu starts at column 0x2C.

## Pictures (9D6F → 9D7C, 9E24; transcribed in `gfx.py`)

1. **Line art**: 1 bpp RLE written identically to the three planes. `00 n` produces n
   bytes 0x00, `FF n` produces n bytes 0xFF, any other byte is literal. The area is 64
   bytes (512 px) wide with an 80-byte stride; drawing stops when the address reaches F1B0.
2. **Background**: 2 bytes skipped, then a pattern index. The 160 lines are ANDed with
   this pattern.
3. **Fills**: `[00 y]` (optional) then `x_hi, x_lo, pattern`. The sequence `00 00` ends
   the picture. The algorithm fills horizontal spans, with a circular queue of 365 entries
   at 8400. The boundary is a pixel that is black on all three planes. The result depends
   on the exact algorithm, because the dithered patterns contain black.
4. **Patterns**: 36 entries of 6 bytes at A1E3, as (B, R, G) for the even line, then
   (B, R, G) for the odd line.

The game does not change the palette: it is the 8-color digital palette (G<<2 | R<<1 | B).
Pictures are 512×160 px; they are exported as is and at ×2 height.

## Checking against MAME

ROMs: `uv run erika check-bios`, which creates `roms/mame/pc8801mk2sr/`, links by CRC to
`roms/pc8801mk2sr/`. To run the game headless, split the D88 into two images, one per
drive (348,848 bytes each), then:
`flatpak run org.mamedev.MAME pc8801mk2sr -rompath roms/mame -flop1 A.d88 -flop2 B.d88
-video none -nothrottle -seconds_to_run N -autoboot_script x.lua`.
The working folder must be under `$HOME`, because the Flatpak sandbox can't see `/tmp`.
In Lua, use `emu.register_periodic`: `add_machine_frame_notifier` stops being called
around t = 3 s.

Results:
- the title screen (room 0) and room 1 rendered by `gfx.py` are **identical to the pixel**
  with the MAME captures (0 differences over 512×160);
- the game draws progressively: line art, then fills one by one; the next picture
  overwrites the previous one in bands;
- the screen is laid out as follows: 512×160 picture at the top left, text on the bottom
  lines (full width, 12×10 font, ♡ cursor), panel on the right. The panel holds the command
  menu (routine 9B08, table 9B65, color 1): 前に行く 後ろに行く 左に行く 右に行く 見る
  行く 入る 探す 調べる 話す 取る あける やめる, with "(C) JAST" in cyan below;
- Enter on the title screen shows room 1 and its entry text.
- The parser was tested in room 1 with `tools/mame/type_commands.lua`. This script types
  one character every 0.2 s, because the game drops keys sent faster by
  `natkeyboard:post`. Results, all matching `rooms/room01.json`:
  こんぴ しらべる → コンピューターは、生きているようです。
  ひだり しらべる → 湖があります。
  そうじ なぐる → OK!でも、手が痛かっただけで、何も起こりません。
  ほげほげ → ここでは、できません。(no command matches: message 0)
  かーど しらべる → あなたは、それを持っていません。(script 4: bit 3 of 8E00 is 0, so message 5)

## Input (94AF)

Input is shown in green after the ♡ cursor. The buffer at 8400 holds 50 characters at most.
Kana keys (0xA0-0xDF) are taken as is. The game also has its own romaji converter, which
uppercases letters:
- a lone vowel gives あいうえお (96CB);
- a consonant is put on hold (97D0); a second consonant is ignored, with no "NN" and no
  doubled consonant;
- consonant + vowel goes through the table at 978A (rows of 5): K S T N H M Y R W G Z D B P;
  G/Z/D/B add ゛ and P adds ゜;
- special: `WI` = ん, `WU` = ー, `YI`/`YE` = nothing; `WO` produces a lone ゛ (bug: the entry
  is 00 and sits on the boundary of the dakuten area);
- C, F, J, L, Q, V, X and small kana are not available in romaji (only as kana);
- digits, space, comma and `-` are kept as is; `-` (0x2D) does not match ー (0xB0) in
  nouns;
- 0x7F = delete, CR = submit, ESC = back (to 9177), `*` calls 97D7.

## Sound (sound.py, `uv run erika sound`)

- **Voices**: there are 30. The table B70D gives their location on disk (loaded at 6000)
  and the table B617 triggers them after certain (room, message) pairs. The game waits for
  the voice to end. Format: a stream of nibbles, high nibble first. Each block has a scale
  (nibble ≥ 8 = end) and 32 deltas; the 8-bit accumulator starts at 0x80, and the steps
  come from the tables at B803 (2^(n-1), sign on bit 3). The bytes are sent to port 0x10
  (the printer port), probably for the "JAST SOUND" box: without it, the original game was
  silent, and so is MAME. No comparison is therefore possible; the spectrograms clearly
  show speech.
- **Sample rate**: about 3,881 Hz. It is derived from the loop's cycle count (≈ 1,029
  cycles per sample at 3.9936 MHz); this is an estimate, in 4 MHz mode.
- **Gunshot**: the overlay at 4000 (same format), played by A2F0 for "うつ じゆう"
  (8E00 bit 4 or 8E02 bit 1) or "うつ れーざ" (8E00 bit 5).
- **Beep**: 965B. It sounds when an input is submitted, on a rejected key and on game over
  (≈ 25 ms at 2.4 kHz, the PC-88 buzzer; duration estimated).
- In the engine, each voice is normalized on playback, because the recorded levels are
  very uneven. The exported WAV files stay raw.

## Saving (9177, 910C; game/save.py)

- **ESC while typing**: "DATAをセーブします。 PUSH RETURN KEY". Enter writes the sector
  8E00-8EFF (flags + room) to track 0, sector 15 of floppy A; any other key cancels. In the
  floppy B phase (room ≥ 0x1F), the game asks for floppy 1, then floppy 2.
- **ESC on the title screen**: "DATAをロードします。…". Enter reads that sector back, and
  the game enters the saved room.
- **In the engine**: a file in the same format, `~/.local/share/erika/save.bin`
  (`%APPDATA%\erika` on Windows). If it doesn't exist, loading reads the save present on
  the original floppy (the supplied image has one: room 55). The `.d88` is never
  modified, and disk prompts are skipped.

## Full validation (tools/explore.py, tools/mame/compare.py)

`tools/explore.py` explores the states (room, flags) with the headless engine. It reaches
54 rooms out of 62, runs 217 script routines out of 222 and finds both endings. It writes
replayable paths (`extracted/paths_endingA.json`, …), where each command is followed by
the inputs the game expects next: pauses, answers, choices, disk swap.

`tools/mame/compare.py --path …` replays a path in MAME and in the engine. It compares the
screen and the flags after each input, and detects that the game is waiting for a key
when the Z80 stays in ROM. Over ending A (61 inputs), flags and rooms are identical
everywhere, and the screen is identical to the pixel everywhere except two captures: MAME,
when headless, sometimes renders a stale screen (the stack shows it is already back at the
prompt).

## Still to do

- Role of the commands' b3 byte (00/FF, never read by A2BB).
- Not checked against MAME: ending B, the room 61 ending, and the 5 script routines the
  explorer never reached.
- Meaning of the nouns でー (0x5C) and だい (0x5D), left untranslated.

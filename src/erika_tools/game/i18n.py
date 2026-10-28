"""Traduction : modèle .pot généré depuis l'image disque, fichiers .po (gettext).

Contextes (msgctxt) :
  system 0xNN         messages système (C600)
  room NN 0xMM        textes des salles
  menu NN             lignes du menu de droite (1-13)
  ui <nom>            textes d'interface (HIT ANY KEY, GAME OVER, sauvegarde…)
  verb 0xNN / noun 0xNN / answer 0xADDR
                      mots que le joueur peut taper, séparés par « | »

Les commandes tapées dans la langue de la traduction sont converties en mots japonais
d'origine, puis analysées par le moteur comme dans le jeu (A2BB) : la logique reste
celle de l'original.
"""

import os
import re
import unicodedata

import polib

from .. import charset, text

FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "6x10.bdf")
LATIN_WIDTH, LATIN_HEIGHT, LATIN_BASELINE = 6, 10, 8

UI_TEXTS = {  # nom -> attribut de GameData
    "hit_any_key": "hit_any_key",
    "pause": "pause_text",
    "game_over": "game_over",
    "save": "save_text",
    "load": "load_text",
}
ANSWERS = (0xB584, 0xB587, 0xB58A, 0xB58D)  # réponses attendues par B52B

VOCAB_COMMENT = ("Words the player can type for this {kind}, separated by '|' "
                 "(e.g. examine|search). The game only compares the first 3 characters "
                 "of the Japanese word, which is often truncated.")


class LatinFont:
    """Police bitmap BDF à chasse fixe (6×10)."""

    def __init__(self, path: str = FONT_PATH):
        self.glyphs: dict[int, list[int]] = {}
        cur = None
        with open(path, encoding="latin-1") as f:
            for line in f:
                w = line.split()
                if not w:
                    continue
                if w[0] == "ENCODING":
                    cur = {"code": int(w[1]), "rows": []}
                elif w[0] == "BBX" and cur is not None:
                    cur["bbx"] = [int(v) for v in w[1:5]]
                elif w[0] == "BITMAP" and cur is not None:
                    cur["bitmap"] = True
                elif w[0] == "ENDCHAR" and cur is not None:
                    self.glyphs[cur["code"]] = self._rows(cur)
                    cur = None
                elif cur is not None and cur.get("bitmap"):
                    cur["rows"].append(int(w[0], 16))

    @staticmethod
    def _rows(g) -> list[int]:
        """10 lignes de 6 bits (bit 5 = pixel de gauche), alignées sur la ligne de base."""
        width, height, ox, oy = g["bbx"]
        rows = [0] * LATIN_HEIGHT
        top = LATIN_BASELINE - height - oy
        for y, r in enumerate(g["rows"]):
            if 0 <= top + y < LATIN_HEIGHT:
                rows[top + y] = (r >> (8 - LATIN_WIDTH)) >> ox if ox >= 0 else r >> (8 - LATIN_WIDTH)
        return rows

    def glyph(self, ch: str) -> list[int]:
        return self.glyphs.get(ord(ch)) or self.glyphs.get(ord("?"), [0] * LATIN_HEIGHT)


def wrap(text_: str, width: int) -> list[str]:
    """Coupe un texte en lignes de `width` caractères au plus, aux espaces si possible."""
    lines = []
    for paragraph in text_.split("\n"):
        line = ""
        for word in paragraph.split(" "):
            while len(word) > width:
                if line:
                    lines.append(line)
                    line = ""
                lines.append(word[:width])
                word = word[width:]
            candidate = f"{line} {word}" if line else word
            if len(candidate) <= width:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


# --- modèle -----------------------------------------------------------------------


def message_key(room_index: int, index: int) -> str:
    if index < text.ROOM_MESSAGE_BASE:
        return f"system 0x{index:02X}"
    return f"room {room_index:02d} 0x{index:02X}"


def build_template(data, rooms: dict[int, list[bytes]]) -> polib.POFile:
    """Modèle .pot : le japonais d'origine en msgid, le contexte en msgctxt."""
    pot = polib.POFile()
    pot.metadata = {"Content-Type": "text/plain; charset=UTF-8", "Content-Transfer-Encoding": "8bit",
                    "Project-Id-Version": "Erika (JAST, PC-8801)"}

    def add(ctx: str, raw: bytes | str, comment: str = ""):
        msgid = raw if isinstance(raw, str) else charset.decode(raw)
        pot.append(polib.POEntry(msgctxt=ctx, msgid=msgid, msgstr="", comment=comment))

    for i, raw in enumerate(data.system):
        add(message_key(0, i), raw)
    for room, texts in sorted(rooms.items()):
        for i, raw in enumerate(texts):
            add(message_key(room, text.ROOM_MESSAGE_BASE + i), raw, f"Room {room}")
    for i, raw in enumerate(data.menu):
        if 1 <= i <= 13:
            add(f"menu {i:02d}", raw[1:-1].strip(b" "), "Right-hand menu: 14 characters at most.")
    for name, attr in UI_TEXTS.items():
        add(f"ui {name}", getattr(data, attr), "Interface text (one line).")
    for i, raw in enumerate(data.verbs):
        add(f"verb 0x{i:02X}", bytes(raw).rstrip(b"\0"), VOCAB_COMMENT.format(kind="verb"))
    for i, raw in enumerate(data.nouns):
        add(f"noun 0x{i:02X}", bytes(raw).rstrip(b"\0"), VOCAB_COMMENT.format(kind="noun"))
    for addr in ANSWERS:
        add(f"answer 0x{addr:04X}", data.answer(addr),
            "Answer to one of the game's questions (ID, name…). Accepted forms, separated by '|'.")
    return pot


# --- traduction chargée --------------------------------------------------------------


def normalize(s: str) -> list[str]:
    """Minuscules, sans accents, découpé en mots (apostrophes et tirets séparent)."""
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return [w for w in re.split(r"[^0-9a-z]+", s) if w]


class Translation:
    def __init__(self, path: str, data):
        po = polib.pofile(path)
        self.texts = {e.msgctxt: e.msgstr for e in po if e.msgstr and not e.fuzzy and not e.obsolete}
        # (mots normalisés du synonyme) -> codes japonais à insérer dans la saisie
        self.vocab: list[tuple[list[str], bytes]] = []
        sources = [(f"verb 0x{i:02X}", bytes(w).rstrip(b"\0")) for i, w in enumerate(data.verbs)]
        sources += [(f"noun 0x{i:02X}", bytes(w).rstrip(b"\0")) for i, w in enumerate(data.nouns)]
        sources += [(f"answer 0x{a:04X}", bytes(data.answer(a))) for a in ANSWERS]
        for ctx, codes in sources:
            for synonym in self.texts.get(ctx, "").split("|"):
                words = normalize(synonym)
                if words:
                    self.vocab.append((words, codes))
        self.vocab.sort(key=lambda v: -len(v[0]))  # les expressions longues d'abord

    def get(self, ctx: str) -> str | None:
        return self.texts.get(ctx)

    def first_word(self, ctx: str) -> str | None:
        value = self.texts.get(ctx)
        return value.split("|")[0].strip() if value else None

    def to_game_input(self, typed: str, kana_to_codes) -> bytes:
        """Convertit une commande tapée en mots japonais d'origine, séparés par des espaces.

        Les mots en kana passent tels quels (kana_to_codes), comme les nombres (réponse
        « 615 ») ; les autres sont cherchés dans le vocabulaire traduit."""
        parts: list[tuple[int, bytes]] = []
        latin = []
        for token in typed.split():
            if any(ord(c) >= 0x3000 for c in token):
                parts.append((len(latin), bytes(kana_to_codes(token))))
            else:
                latin.append(token)
        words = normalize(" ".join(latin))
        used = [False] * len(words)
        for synonym, codes in self.vocab:
            n = len(synonym)
            for i in range(len(words) - n + 1):
                if any(used[i : i + n]):
                    continue
                window = words[i : i + n]
                plural = n == 1 and window[0] in (synonym[0] + "s", synonym[0] + "x")
                if window == synonym or plural:
                    parts.append((i, codes))
                    used[i : i + n] = [True] * n
        for i, word in enumerate(words):
            if not used[i] and word.isdigit():
                parts.append((i, word.encode("ascii")))
        parts.sort(key=lambda p: p[0])
        return b" ".join(codes for _, codes in parts)

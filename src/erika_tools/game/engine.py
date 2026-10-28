"""Moteur d'Erika : réimplémentation de la boucle de jeu du programme principal (9000-A6BC).

La logique est un générateur : il cède FRAME pour laisser afficher une image (dessin
progressif) ou EVENT pour attendre une touche, que la boucle pygame lui renvoie.
"""

import random
import unicodedata

from .. import charset, gfx, sound
from . import i18n, romaji, save
from .data import ANSWER_ALT, ANSWER_ALT_ROOM16, GameData, Room
from .display import BLUE, COLS, CYAN, GREEN, MAGENTA, RED, TEXT_ROW, WHITE, YELLOW, Display, decode_codes

FRAME = "frame"
EVENT = "event"

PROMPT = 0xE0  # ♡
MENU_COL = 0x2C  # menu de droite (9B08), lignes 0-14

# Lignes du menu -> (texte inséré, envoi immédiat). 探す n'existe pas dans le vocabulaire
# du jeu : on le fait correspondre à しらべる.
MENU_ACTIONS = {
    1: ("まえ いく", True), 2: ("うしろ いく", True), 3: ("ひだり いく", True), 4: ("みぎ いく", True),
    5: ("みる", False), 6: ("いく", False), 7: ("はいる", False), 8: ("しらべる", False),
    9: ("しらべる", False), 10: ("はなす", False), 11: ("とる", False), 12: ("あける", False),
    13: ("やめる", True),
}
INPUT_MAX = 0x32
CR = 0x0D

# Dessin progressif : coût de chaque étape, budget par frame (60 i/s).
LINE_COST, FILL_COST, FRAME_BUDGET = 1, 3, 4

# Conversion romaji du jeu (96CB, 971B, 976F, table 978A).
VOWELS = "AIUEO"
CONSONANT_ROWS = {"K": 0, "S": 5, "T": 10, "N": 15, "H": 20, "M": 25, "Y": 30, "R": 35,
                  "W": 40, "G": 45, "Z": 50, "D": 55, "B": 60}  # toute autre consonne : 65 (P)
ROMAJI_TABLE = 0x978A
DAKUTEN_FROM, HANDAKUTEN_FROM = 0x97B6, 0x97CB
REJECTED = set("CFJLQVX[\\]^_")  # 94E3-951A : lettres refusées

# Kana Unicode (IME) -> codes du jeu (JIS X 0201, affichés en hiragana).
KANA_CODES = {}
for code, ch in charset.NORMAL.items():
    if 0xA6 <= code <= 0xDF and "ぁ" <= ch <= "ゖ":
        KANA_CODES[ch] = code
        KANA_CODES[chr(ord(ch) + 0x60)] = code  # katakana correspondant
KANA_CODES.update({"ー": 0xB0, "。": 0xA1, "「": 0xA2, "」": 0xA3, "、": 0xA4, "・": 0xA5,
                   "゙": 0xDE, "゚": 0xDF})


def kana_to_codes(text: str) -> list[int]:
    return [KANA_CODES[c] for c in unicodedata.normalize("NFD", text) if c in KANA_CODES]


def word_match(word: bytes | None, buf: bytes) -> bool:
    """Recherche d'un mot (3 premiers caractères) dans la saisie (A35B), défauts compris."""
    if word is None or word[0] == 0:
        return True
    i, tries, w, left = 0, INPUT_MAX, 0, 3
    while True:
        a = buf[i] if i < len(buf) else 0
        if a == CR:
            return False
        if a != word[w]:
            w, left = 0, 3
            i += 1
            tries -= 1
            if tries == 0:
                return False
            continue
        w += 1
        i += 1
        left -= 1
        if left == 0 or word[w] == 0:
            return True


LATIN_COLS = 640 // i18n.LATIN_WIDTH  # 106 caractères par ligne de texte traduit


class NullAudio:
    """Audio muet (outils, tests) : aucune attente."""

    def play(self, samples) -> float:
        return 0.0

    def beep(self):
        pass


class Engine:
    def __init__(self, data: GameData, audio=None):
        self.data = data
        self.audio = audio or NullAudio()
        self.display = Display(data.mem, data.patterns)
        self.room_index = 0  # 8E04
        self.flags = bytearray(4)  # 8E00-8E03
        self.room: Room = data.rooms[0]
        self.message = 0  # 9314
        self.last_command = None  # A39E
        self.input_mode = "original"  # « original », « modern » ou « translated »
        self.tr: i18n.Translation | None = None
        self.font: i18n.LatinFont | None = None
        self.menu_shown = False
        self.hover = None
        self.skip_drawing = False

    # --- primitives ------------------------------------------------------------

    def wait_event(self):
        while True:
            event = yield EVENT
            if event is not None:
                return event

    def draw_room(self, index: int):
        """Charge et dessine une salle (9319, 9D6F, 92BB)."""
        self.room_index = index
        self.room = self.data.rooms[index]
        steps = gfx.room_steps(self.display.screen, self.room.blob)
        self.skip_drawing = False
        budget = FRAME_BUDGET
        while True:
            try:
                kind, _ = next(steps)
            except StopIteration as done:
                end = done.value
                break
            self.display.dirty = True
            budget -= LINE_COST if kind == "line" else FILL_COST
            if budget <= 0 and not self.skip_drawing:
                budget = FRAME_BUDGET
                yield FRAME
        if self.room.texts is None:
            self.data.load_room_data(self.room, end)

    def set_translation(self, tr):
        self.tr = tr
        self.font = i18n.LatinFont() if tr else None

    def ui_text(self, col: int, name: str, color: int):
        """Texte d'interface (i18n.UI_TEXTS) sur la ligne de texte, traduit si possible."""
        translated = self.tr.get(f"ui {name}") if self.tr else None
        if translated:
            self.display.latin(col * 12, TEXT_ROW, translated, color, self.font)
        else:
            self.display.string(col, TEXT_ROW, getattr(self.data, i18n.UI_TEXTS[name]), color)

    def print_message(self, index: int):
        """Affiche un message dans la fenêtre de texte (92E4, 9C11)."""
        key = i18n.message_key(self.room_index, self.data.message_index(self.room, index))
        translated = self.tr.get(key) if self.tr else None
        if translated:
            lines = i18n.wrap(translated, LATIN_COLS)
        else:
            lines = None
        wrapped = False

        def line_full():
            # 9C4B-9C6D : retour à la ligne ; un « HIT ANY KEY » tous les deux retours
            nonlocal wrapped
            self.display.scroll()
            if wrapped:
                self.ui_text(5, "hit_any_key", RED)
                yield from self.wait_event()
                self.display.clear_line()
            wrapped = not wrapped

        if lines is not None:
            for i, line in enumerate(lines):
                self.display.latin(0, TEXT_ROW, line, WHITE, self.font)
                if i < len(lines) - 1:
                    yield from line_full()
        else:
            col = 0
            for code, kanji in decode_codes(self.data.message(self.room, index)):
                self.display.glyph(col, TEXT_ROW, code, kanji, WHITE)
                col += 1
                if col == COLS:
                    yield from line_full()
                    col = 0
        self.display.scroll()
        yield from self.voice_event(index)

    def voice_event(self, index: int):
        """B5CB : certaines paires (salle, message) déclenchent une voix ; le jeu attend la fin."""
        number = self.data.voice_events.get((self.room_index, index)) if index else None
        if number is not None:
            yield from self.play(self.data.voice(number))

    def play(self, samples):
        frames = int(self.audio.play(samples) * 60)
        for _ in range(frames):
            yield FRAME

    def read_command(self, allow_escape: bool = False):
        """Saisie au clavier (94AF) ; retourne le buffer.

        Deux conversions romaji : celle du jeu (input_mode « origine ») ou une saisie
        moderne (romaji.py). Les lettres en attente s'affichent après le texte, comme la
        consonne du jeu. Un clic sur le menu insère un mot (MENU_ACTIONS).
        ESC (9554) : retourne None si allow_escape (sauvegarde), sinon le buffer tel quel."""
        if self.input_mode == "translated" and self.tr:
            return (yield from self.read_translated(allow_escape))
        d = self.display
        buf: list[int] = []
        pending = ""  # lettres latines pas encore converties
        col = 0  # colonne du dernier caractère du buffer

        def put(code: int):
            nonlocal col
            col += 1
            buf.append(code)
            d.glyph(col, TEXT_ROW, code, False, GREEN)

        def set_pending(new: str):
            nonlocal pending
            for i in range(max(len(pending), len(new))):
                code = ord(new[i].upper()) if i < len(new) else 0x20
                d.glyph(col + 1 + i, TEXT_ROW, code, False, GREEN if i < len(new) else WHITE)
            pending = new

        def finish():
            if self.input_mode == "modern":
                kana = romaji.finish(pending)
                set_pending("")
                for code in romaji.to_codes(kana, KANA_CODES):
                    put(code)

        while True:
            kind, value = yield from self.wait_event()
            if kind == "key" and value == "return":
                finish()
                self.audio.beep()  # 9645 -> 9641 -> 965B
                return bytes(buf + [CR])
            if kind == "key" and value == "escape":
                return None if allow_escape else bytes(buf)
            if kind == "key" and value == "backspace":
                if pending:
                    set_pending(pending[:-1] if self.input_mode == "modern" else "")
                elif buf:
                    buf.pop()
                    d.glyph(col, TEXT_ROW, 0x20, False, WHITE)
                    col -= 1
                continue
            if kind == "click":
                text, submit = MENU_ACTIONS[value]
                set_pending("")
                if buf and buf[-1] != 0x20:
                    put(0x20)
                for i, word in enumerate(text.split(" ")):
                    if i:
                        put(0x20)
                    for code in kana_to_codes(word):
                        put(code)
                if submit:
                    self.audio.beep()
                    return bytes(buf + [CR])
                put(0x20)
                continue
            if kind != "text":
                continue
            for ch in value:
                if self.input_mode == "modern":
                    self._modern_char(ch, pending, put, set_pending)
                else:
                    self._original_char(ch, pending, put, set_pending)
                if len(buf) >= INPUT_MAX:
                    self.audio.beep()  # 9641
                    return bytes(buf)

    def _original_char(self, ch: str, pending: str, put, set_pending):
        """Conversion du jeu (95D6-9633) ; pending = consonne en attente (97D1)."""
        if ord(ch) >= 0x80:
            if not pending:
                for code in kana_to_codes(ch):
                    put(code)
            return
        c = ch.upper()
        if c in VOWELS:
            if pending:
                row = CONSONANT_ROWS.get(pending, 65)
                addr = ROMAJI_TABLE + row + VOWELS.index(c)
                set_pending("")
                put(self.data.mem[addr])  # remplace la consonne affichée
                if addr >= DAKUTEN_FROM:
                    put(0xDF if addr >= HANDAKUTEN_FROM else 0xDE)
            else:
                put(0xB1 + VOWELS.index(c))
        elif "A" <= c <= "Z":
            if pending or c in REJECTED:
                self.audio.beep()  # 956C
            else:
                set_pending(c)
        elif (c.isdigit() or c in " ,-") and not pending:
            put(ord(c))

    def _modern_char(self, ch: str, pending: str, put, set_pending):
        """Saisie moderne (romaji.py) ; les petits kana deviennent grands."""
        if ord(ch) >= 0x80:
            set_pending("")
            for code in romaji.to_codes(ch, KANA_CODES):
                put(code)
            return
        if ch.isalpha() or ch in "-'":
            kana, rest, rejected = romaji.feed(pending, ch)
            set_pending("")
            for code in romaji.to_codes(kana, KANA_CODES):
                put(code)
            set_pending(rest)
            if rejected:
                self.audio.beep()
        elif ch.isdigit() or ch in " ,":
            for code in romaji.to_codes(romaji.finish(pending), KANA_CODES):
                put(code)
            set_pending("")
            put(ord(ch))

    def read_translated(self, allow_escape: bool):
        """Saisie libre dans la langue de la traduction, convertie en mots japonais."""
        d = self.display
        typed = ""
        width = (640 - 12) // i18n.LATIN_WIDTH

        def show(old: str):
            d.latin(12, TEXT_ROW, typed.ljust(len(old)), GREEN, self.font)

        def converted() -> bytes:
            return self.tr.to_game_input(typed, kana_to_codes)

        while True:
            kind, value = yield from self.wait_event()
            old = typed
            if kind == "key" and value == "return":
                self.audio.beep()
                return converted() + bytes([CR])
            if kind == "key" and value == "escape":
                return None if allow_escape else converted()
            if kind == "key" and value == "backspace":
                typed = typed[:-1]
            elif kind == "click":
                text, submit = MENU_ACTIONS[value]
                words = [self.menu_word(w) for w in text.split(" ")]
                typed = (typed.rstrip() + " " if typed.strip() else "") + " ".join(words) + " "
                if submit:
                    show(old)
                    self.audio.beep()
                    return converted() + bytes([CR])
            elif kind == "text":
                typed = (typed + value)[:width]
            show(old)

    def menu_word(self, kana: str) -> str:
        """Mot traduit (premier synonyme) correspondant à un mot japonais du menu."""
        codes = bytes(kana_to_codes(kana))
        for kind, table in (("verb", self.data.verbs), ("noun", self.data.nouns)):
            for i, entry in enumerate(table):
                word = bytes(entry).rstrip(b"\0")
                if word and codes.startswith(word[:3]):
                    translated = self.tr.first_word(f"{kind} 0x{i:02X}")
                    if translated:
                        return translated
        return kana  # pas de traduction : le mot japonais est accepté tel quel

    def draw_menu_line(self, row: int, color: int):
        """Ligne du menu de droite ; traduite, elle garde le cadre d'origine."""
        line = self.data.menu[row]
        translated = self.tr.get(f"menu {row:02d}") if self.tr and 1 <= row <= 13 else None
        if not translated:
            self.display.string(MENU_COL, row, line, color if 1 <= row <= 13 else BLUE)
            return
        cells = sum(1 for _ in decode_codes(line))
        self.display.glyph(MENU_COL, row, line[0], False, BLUE)
        self.display.glyph(MENU_COL + cells - 1, row, line[-1], False, BLUE)
        inner = (cells - 2) * 12
        self.display.latin((MENU_COL + 1) * 12, row, " " * (inner // i18n.LATIN_WIDTH), color, self.font)
        self.display.latin((MENU_COL + 1) * 12 + 3, row, translated[: (inner - 3) // i18n.LATIN_WIDTH],
                           color, self.font)

    def set_hover(self, row: int | None):
        """Met en valeur la ligne du menu survolée par la souris."""
        if not self.menu_shown or row == self.hover:
            return
        for r, color in ((self.hover, BLUE), (row, WHITE)):
            if r is not None:
                if self.tr and self.tr.get(f"menu {r:02d}"):
                    self.draw_menu_line(r, color)
                else:
                    # le texte change de couleur, le cadre (premier et dernier caractère) reste bleu
                    self.display.string(MENU_COL + 1, r, self.data.menu[r][1:-1], color)
        self.hover = row

    # --- logique ---------------------------------------------------------------

    def find_command(self, buf: bytes):
        """Première commande de la salle dont le verbe et le nom sont dans la saisie (A2BB)."""
        for cmd in self.room.commands:
            verb = None if cmd.verb == 0xFF else self.data.verbs[cmd.verb]
            noun = None if cmd.noun == 0xFF else self.data.nouns[cmd.noun]
            if word_match(verb, buf) and word_match(noun, buf):
                return cmd
        return None

    # --- état : 8E00-8E03 (drapeaux), 8E04 (salle) ------------------------------

    def get_byte(self, offset: int) -> int:
        return self.room_index if offset == 4 else self.flags[offset]

    def set_byte(self, offset: int, value: int):
        if offset == 4:
            self.room_index = value  # seul le script 122 y touche (RES 6 : sans effet)
        else:
            self.flags[offset] = value

    # --- scripts (table A6BC, traduits par scripts.py) --------------------------

    def run_script(self, number: int):
        """Exécute un script traduit (A6A5). self.message vaut le message par défaut (9314)."""
        code = self.data.scripts["code"]
        pc = self.data.scripts["entries"][number]
        a, zero, carry, de = 0, False, False, 0
        while pc is not None:
            op = code[pc]
            kind = op["op"]
            nxt = op["next"]
            if kind == "msg":
                self.message = op["n"]
            elif kind == "bit":
                zero = not self.get_byte(op["byte"]) >> op["bit"] & 1
            elif kind == "set":
                self.set_byte(op["byte"], self.get_byte(op["byte"]) | 1 << op["bit"])
            elif kind == "res":
                self.set_byte(op["byte"], self.get_byte(op["byte"]) & ~(1 << op["bit"]))
            elif kind == "a":
                a = op["n"]
            elif kind == "a_var":
                if op["addr"] != 0x8E04:
                    raise ValueError(f"unsupported variable {op['addr']:#06x}")
                a = self.room_index
            elif kind == "cp":
                zero, carry = a == op["n"], a < op["n"]
            elif kind == "or_a":
                zero, carry = a == 0, False
            elif kind == "de":
                de = op["addr"]
            elif kind in ("jump", "call"):
                cond = op["cond"]
                taken = (cond is None or (cond == "z" and zero) or (cond == "nz" and not zero)
                         or (cond == "c" and carry) or (cond == "nc" and not carry))
                if taken:
                    if isinstance(op["to"], int):
                        nxt = op["to"]
                    else:
                        result = yield from self.special(op["to"], a, de)
                        if op["to"] == "wait_key":
                            a = result
                        elif op["to"] == "ask":
                            carry = result
                        if kind == "jump":
                            return
            else:
                raise ValueError(f"unknown operation {kind}")
            pc = nxt

    def special(self, name: str, a: int, de: int):
        """Routines du jeu appelées par les scripts (voir scripts.SPECIALS)."""
        d = self.display
        if name == "show":
            yield from self.print_message(self.message)
        elif name == "say":
            yield from self.print_message(self.message)
        elif name == "pause":
            yield from self.print_message(self.message)
            yield from self.pause()
        elif name == "goto":
            yield from self.print_message(self.message)
            yield from self.dispatch(a)
        elif name == "goto_random":
            yield from self.print_message(self.message)
            yield from self.dispatch(11 + random.getrandbits(1))
        elif name == "dispatch":
            yield from self.dispatch(a)
        elif name == "game_over":
            self.audio.beep()  # B522
            yield from self.print_message(self.message)
            yield from self.pause()
            yield from self.print_message(7)
            yield from self.halt()
        elif name == "halt":
            yield from self.halt()
        elif name == "ask":
            return (yield from self.ask(de))
        elif name == "patch_image":
            pattern = self.display.screen.pattern(1)
            for y in range(0x7A, 0x7A + 0x16):
                d.screen._paint_span(0xA8, 0xDF, y, pattern)
            d.dirty = True
        elif name == "wait_key":
            kind, value = yield from self.wait_event()
            if kind == "text":
                return ord(value[0]) & 0xFF
            return {"return": 0x0D, "escape": 0x1B, "backspace": 0x08}.get(value, 0)
        elif name == "freeze":
            # Fin de partie : l'original se fige (JR $). Ici une touche ramène au titre.
            yield from self.wait_event()
            raise Restart
        elif name == "disk_swap":
            pass  # « フロッピー2をドライブ1に… » : les deux disquettes sont déjà là
        else:
            raise ValueError(f"unknown routine {name}")

    def pause(self):
        """HIT ANY KEY en magenta, attente d'une touche (9147)."""
        self.display.clear_line()
        self.ui_text(1, "pause", MAGENTA)
        yield from self.wait_event()

    def halt(self):
        """GAME OVER (9139). L'original se bloque ; ici une touche ramène au titre."""
        self.ui_text(1, "game_over", MAGENTA)
        yield from self.wait_event()
        raise Restart

    def ask(self, answer_addr: int):
        """Question au joueur (B52B) ; retourne True (carry) si la réponse est fausse."""
        self.display.glyph(0, TEXT_ROW, PROMPT, False, MAGENTA)
        buf = yield from self.read_command()
        if contains(buf, self.data.answer(answer_addr)):
            self.display.clear_line()
            return False
        alt = ANSWER_ALT_ROOM16 if self.room_index == 0x10 else ANSWER_ALT
        if not contains(buf, self.data.answer(alt)):
            return True
        # Deuxième réponse : fin « salle 61 », puis blocage (B559-B568).
        self.display.clear_window()
        yield from self.draw_room(0x3D)
        yield from self.wait_event()
        raise Restart

    def dispatch(self, room: int):
        """A65E : change de salle, ou rejoue la commande reconnue si la salle ne change pas."""
        if room and room != self.room_index:
            yield from self.enter_room(room)
            return
        cmd = self.last_command
        self.message = cmd.message
        if cmd.script:
            yield from self.run_script(cmd.script)
        else:
            yield from self.print_message(self.message)

    def enter_room(self, index: int):
        """Changement de salle (A689)."""
        yield from self.draw_room(index)
        self.message = self.room.entry_message
        if self.room.entry_script:
            yield from self.run_script(self.room.entry_script)
        else:
            yield from self.print_message(self.message)

    # --- déroulement ---------------------------------------------------------------

    def run(self):
        while True:
            try:
                yield from self.session()
            except Restart:
                self.flags[:] = bytes(4)
                self.menu_shown, self.hover = False, None
                self.display.screen.planes = [bytearray(gfx.PLANE_SIZE) for _ in range(3)]
                self.display.dirty = True

    def session(self):
        d = self.display
        # Écran titre (9000-909B)
        for i, line in enumerate(self.data.logo):
            d.string(0x2D, 5 + i, line, CYAN)
        yield from self.draw_room(0)
        yield from self.print_message(self.room.entry_message)
        self.room_index = 1  # 9072 : 8E04 = 1 avant l'attente de touche
        if (yield from self.wait_event()) == ("key", "escape"):
            yield from self.load_game()
        for i in range(len(self.data.menu)):
            self.draw_menu_line(i, BLUE)
        d.string(MENU_COL, 15, self.data.copyright, CYAN)
        self.menu_shown = True
        yield from self.enter_room(self.room_index)

        # Boucle principale (909E)
        while True:
            d.glyph(0, TEXT_ROW, PROMPT, False, YELLOW)
            buf = yield from self.read_command(allow_escape=True)
            if buf is None:
                yield from self.save_game()
            else:
                yield from self.handle_command(buf)

    def load_game(self):
        """ESC sur l'écran titre (910C) : Entrée charge la sauvegarde, une autre touche annule."""
        d = self.display
        d.clear_window()
        self.ui_text(1, "load", MAGENTA)
        d.scroll()
        if (yield from self.wait_event()) != ("key", "return"):
            return
        saved = save.read(self.data.original_save, len(self.data.rooms))
        if saved:
            self.flags[:], self.room_index = saved

    def save_game(self):
        """ESC pendant la saisie (9177) : Entrée sauvegarde, une autre touche annule."""
        d = self.display
        d.clear_window()
        self.ui_text(1, "save", MAGENTA)
        d.scroll()
        if (yield from self.wait_event()) == ("key", "return"):
            save.write(self.flags, self.room_index)
            d.scroll()

    def handle_command(self, buf: bytes):
        """Traite une saisie validée (90B0-90D0)."""
        cmd = self.find_command(buf)
        if cmd is not None and cmd.verb == 0x0C and cmd.noun in (0x25, 0x26):
            # A2F0 : « うつ じゆう/れーざ » avec l'arme en main -> bruit du tir (B786)
            f = self.flags
            armed = (f[0] & 0x10 or f[2] & 0x02) if cmd.noun == 0x25 else f[0] & 0x20
            if armed:
                yield from self.play(self.data.shot())
        self.display.scroll()
        if cmd is None:
            yield from self.print_message(0)
            return
        self.last_command = cmd
        self.message = cmd.message
        if cmd.room or cmd.script:
            yield from self.dispatch(cmd.room)
        else:
            yield from self.print_message(self.message)


class Restart(Exception):
    """Retour à l'écran titre (après GAME OVER ou une fin bloquante)."""


def contains(buf: bytes, answer: bytes) -> bool:
    """Recherche de B56A : première occurrence du 1er caractère, puis les 2 suivants."""
    window = buf[:0x30]
    if answer[0] not in window:
        return False
    i = window.index(answer[0])
    return buf[i + 1 : i + 3] == answer[1:3]


class PygameAudio:
    """Joue les échantillons 8 bits du jeu (≈ 3,9 kHz) par maintien d'échantillon, comme un DAC."""

    RATE = 44100

    def __init__(self, pygame):
        import numpy as np

        self.np = np
        self.pygame = pygame
        pygame.mixer.init(frequency=self.RATE, size=-16, channels=1)
        self.channel = pygame.mixer.Channel(0)
        self._beep = self._sound(sound.beep(), normalize=False)

    def _sound(self, samples, normalize=True):
        np = self.np
        x = samples.astype(np.float32) - 128
        if normalize and np.abs(x).max() > 0:
            x *= 0.6 * 128 / np.abs(x).max()  # les voix sont enregistrées à des niveaux très inégaux
        idx = (np.arange(int(len(x) * self.RATE / sound.SAMPLE_RATE)) * sound.SAMPLE_RATE // self.RATE)
        pcm = (x[idx] * 256).clip(-32768, 32767).astype(np.int16)
        return self.pygame.mixer.Sound(buffer=pcm.tobytes())

    def play(self, samples) -> float:
        if len(samples) == 0:
            return 0.0
        self.channel.play(self._sound(samples))
        return len(samples) / sound.SAMPLE_RATE

    def beep(self):
        self._beep.play()


def menu_row(pos) -> int | None:
    """Ligne du menu sous la souris (coordonnées logiques 640×400), si elle est cliquable."""
    x, y = pos
    row = y // 20
    return row if MENU_COL * 12 <= x < (MENU_COL + 10) * 12 and row in MENU_ACTIONS else None


def main(image_path: str, input_mode: str | None = None, translation: str | None = None):
    import pygame

    pygame.init()
    window = pygame.display.set_mode((640, 400), pygame.SCALED | pygame.RESIZABLE)
    frame = pygame.Surface((640, 200))
    clock = pygame.time.Clock()
    pygame.key.start_text_input()

    def caption():
        pygame.display.set_caption(f"Erika — {engine.input_mode} input (F2 to switch)")

    try:
        audio = PygameAudio(pygame)
    except pygame.error as e:  # pas de périphérique audio : on joue sans le son
        print(f"sound disabled: {e}")
        audio = None
    engine = Engine(GameData(image_path), audio)
    if translation:
        engine.set_translation(i18n.Translation(translation, engine.data))
    modes = ["translated", "modern", "original"] if translation else ["modern", "original"]
    engine.input_mode = input_mode if input_mode in modes else modes[0]
    caption()
    flow = engine.run()
    request = next(flow)
    events: list = []
    keys = {pygame.K_RETURN: "return", pygame.K_KP_ENTER: "return",
            pygame.K_BACKSPACE: "backspace", pygame.K_ESCAPE: "escape"}

    while True:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                pygame.quit()
                return
            if e.type == pygame.KEYDOWN and e.key == pygame.K_F11:
                pygame.display.toggle_fullscreen()
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_F2:
                engine.input_mode = modes[(modes.index(engine.input_mode) + 1) % len(modes)]
                caption()
            elif e.type == pygame.MOUSEMOTION:
                engine.set_hover(menu_row(e.pos))
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                row = menu_row(e.pos)
                if row is not None and engine.menu_shown:
                    events.append(("click", row))
            elif e.type == pygame.KEYDOWN and e.key in keys:
                events.append(("key", keys[e.key]))
            elif e.type == pygame.TEXTINPUT:
                events.append(("text", e.text))

        if request == FRAME:
            if events:  # une touche pendant le dessin l'accélère
                engine.skip_drawing = True
                events.clear()
            request = flow.send(None)
        while request == EVENT and events:
            request = flow.send(events.pop(0))

        if engine.display.dirty:
            pygame.surfarray.blit_array(frame, engine.display.to_rgb())
            pygame.transform.scale(frame, (640, 400), window)
            engine.display.dirty = False
        pygame.display.flip()
        clock.tick(60)

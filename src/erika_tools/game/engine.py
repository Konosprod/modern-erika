"""Moteur d'Erika : réimplémentation de la boucle de jeu du programme principal (9000-A6BC).

La logique est un générateur : il cède FRAME pour laisser afficher une image (dessin
progressif) ou EVENT pour attendre une touche, que la boucle pygame lui renvoie.
"""

import random
import unicodedata

from .. import charset, gfx, sound
from . import save
from .data import ANSWER_ALT, ANSWER_ALT_ROOM16, GameData, Room
from .display import BLUE, COLS, CYAN, GREEN, MAGENTA, RED, TEXT_ROW, WHITE, YELLOW, Display, decode_codes

FRAME = "frame"
EVENT = "event"

PROMPT = 0xE0  # ♡
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

    def print_message(self, index: int):
        """Affiche un message dans la fenêtre de texte (92E4, 9C11)."""
        raw = self.data.message(self.room, index)
        col, wrapped = 0, False
        for code, kanji in decode_codes(raw):
            self.display.glyph(col, TEXT_ROW, code, kanji, WHITE)
            col += 1
            if col == COLS:
                self.display.scroll()
                if wrapped:
                    self.display.string(5, TEXT_ROW, self.data.hit_any_key, RED)
                    yield from self.wait_event()
                    self.display.clear_line()
                wrapped = not wrapped
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
        """Saisie au clavier avec la conversion romaji du jeu (94AF) ; retourne le buffer.

        ESC (9554) : retourne None si allow_escape (sauvegarde), sinon le buffer tel quel."""
        d = self.display
        buf: list[int] = []
        pending: str | None = None
        col = 0

        def put(code: int, color: int = GREEN):
            nonlocal col
            col += 1
            d.glyph(col, TEXT_ROW, code, False, color)

        while True:
            kind, value = yield from self.wait_event()
            if kind == "key" and value == "return":
                self.audio.beep()  # 9645 -> 9641 -> 965B
                return bytes(buf + [CR])
            if kind == "key" and value == "escape":
                return None if allow_escape else bytes(buf)
            if kind == "key" and value == "backspace":
                if pending:
                    pending = None
                elif buf:
                    buf.pop()
                else:
                    continue
                d.glyph(col, TEXT_ROW, 0x20, False, WHITE)
                col -= 1
                continue
            if kind != "text":
                continue
            for ch in value:
                if ord(ch) >= 0x80:
                    codes = kana_to_codes(ch)
                    if pending or not codes:
                        continue
                    for code in codes:
                        buf.append(code)
                        put(code)
                    continue
                c = ch.upper()
                if c in VOWELS:
                    if pending:
                        row = CONSONANT_ROWS.get(pending, 65)
                        addr = ROMAJI_TABLE + row + VOWELS.index(c)
                        code = self.data.mem[addr]
                        buf.append(code)
                        d.glyph(col, TEXT_ROW, code, False, GREEN)  # remplace la consonne
                        if addr >= DAKUTEN_FROM:
                            mark = 0xDF if addr >= HANDAKUTEN_FROM else 0xDE
                            buf.append(mark)
                            put(mark)
                        pending = None
                    else:
                        code = 0xB1 + VOWELS.index(c)
                        buf.append(code)
                        put(code)
                elif "A" <= c <= "Z":
                    if pending or c in REJECTED:
                        self.audio.beep()  # 956C
                        continue
                    pending = c
                    put(ord(c))
                elif c.isdigit() or c in " ,-":
                    if pending:
                        continue
                    buf.append(ord(c))
                    put(ord(c))
                else:
                    continue
                if len(buf) >= INPUT_MAX:
                    self.audio.beep()  # 9641
                    return bytes(buf)

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
                    raise ValueError(f"variable {op['addr']:#06x} non gérée")
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
                raise ValueError(f"opération inconnue {kind}")
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
            raise ValueError(f"routine inconnue {name}")

    def pause(self):
        """HIT ANY KEY en magenta, attente d'une touche (9147)."""
        self.display.clear_line()
        self.display.string(1, TEXT_ROW, self.data.pause_text, MAGENTA)
        yield from self.wait_event()

    def halt(self):
        """GAME OVER (9139). L'original se bloque ; ici une touche ramène au titre."""
        self.display.string(1, TEXT_ROW, self.data.game_over, MAGENTA)
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
        for i, line in enumerate(self.data.menu):
            d.string(0x2C, i, line, BLUE)
        d.string(0x2C, 15, self.data.copyright, CYAN)
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
        d.string(1, TEXT_ROW, self.data.load_text, MAGENTA)
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
        d.string(1, TEXT_ROW, self.data.save_text, MAGENTA)
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


def main(image_path: str):
    import pygame

    pygame.init()
    pygame.display.set_caption("Erika")
    window = pygame.display.set_mode((640, 400), pygame.SCALED | pygame.RESIZABLE)
    frame = pygame.Surface((640, 200))
    clock = pygame.time.Clock()
    pygame.key.start_text_input()

    try:
        audio = PygameAudio(pygame)
    except pygame.error as e:  # pas de périphérique audio : on joue sans le son
        print(f"son désactivé : {e}")
        audio = None
    engine = Engine(GameData(image_path), audio)
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

"""Données du jeu lues directement depuis l'image disque (aucun fichier extrait requis).

Les textes restent en codes du jeu (octets) : ils sont affichés avec les polices d'origine.
"""

from dataclasses import dataclass

from .. import cli, d88, gfx, scripts, text

MAIN_MENU = 0x9B65  # 15 lignes, colonne 0x2C, couleur 1 (9B08)
MENU_LINES = 15
TITLE_LOGO = 0x91E6  # « Presented by JAST », 4 lignes, colonne 0x2D (90DE)
COPYRIGHT = 0x9204  # « (C) JAST », colonne 0x2C, ligne 15 (90D3)
HIT_ANY_KEY = 0x9CC9  # message coupé (9C7C), en rouge, colonne 5
PAUSE_TEXT = 0x92AF  # « HIT ANY KEY » de pause/game over (9147), magenta, colonne 1
GAME_OVER = 0x92A5  # 9139, magenta, colonne 1
ANSWER_ALT, ANSWER_ALT_ROOM16 = 0xB58A, 0xB58D  # 2e réponse de B52B : mène à la fin « salle 61 »


def c_strings(mem: bytes, pos: int, count: int) -> list[bytes]:
    out = []
    for _ in range(count):
        end = mem.index(0, pos)
        out.append(bytes(mem[pos:end]))
        pos = end + 1
    return out


@dataclass
class Command:
    verb: int
    noun: int
    room: int
    b3: int
    message: int
    script: int


@dataclass
class Room:
    blob: bytes
    entry_message: int
    entry_script: int
    texts: list[bytes] | None = None
    commands: list[Command] | None = None


class GameData:
    def __init__(self, image_path: str):
        self.linear = [d.linear() for d in d88.load(image_path)]
        self.mem = bytes(cli.boot_memory(self.linear))
        self.patterns = self.mem[gfx.PATTERN_TABLE : gfx.PATTERN_TABLE + gfx.PATTERN_COUNT * 6]
        self.system = c_strings(self.mem, text.SYSTEM_MESSAGES, text.ROOM_MESSAGE_BASE)
        self.verbs = [self.mem[text.VERBS + 4 * i : text.VERBS + 4 * i + 4] for i in range(text.VERB_COUNT)]
        self.nouns = [self.mem[text.NOUNS + 4 * i : text.NOUNS + 4 * i + 4] for i in range(text.NOUN_COUNT)]
        self.menu = c_strings(self.mem, MAIN_MENU, MENU_LINES)
        self.logo = c_strings(self.mem, TITLE_LOGO, 4)
        self.copyright = c_strings(self.mem, COPYRIGHT, 1)[0]
        self.hit_any_key = c_strings(self.mem, HIT_ANY_KEY, 1)[0]
        self.pause_text = c_strings(self.mem, PAUSE_TEXT, 1)[0]
        self.game_over = c_strings(self.mem, GAME_OVER, 1)[0]
        self.scripts = scripts.translate(self.mem)
        self.rooms = []
        for i in range(cli.ROOM_COUNT):
            e = self.mem[cli.ROOM_TABLE + 6 * i : cli.ROOM_TABLE + 6 * i + 6]
            self.rooms.append(Room(cli.room_blob(self.linear, tuple(e[:4])), e[4], e[5]))

    def load_room_data(self, room: Room, image_end: int):
        """Textes et commandes qui suivent l'image (92BB)."""
        pos = image_end
        room.texts = []
        while room.blob[pos] != 0:
            end = room.blob.index(0, pos)
            room.texts.append(room.blob[pos:end])
            pos = end + 1
        pos += 1
        # A2BB teste le compteur après chaque entrée : le jeu lit N + 1 commandes.
        count = room.blob[pos] + 1
        pos += 1
        room.commands = [Command(*room.blob[pos + 6 * i : pos + 6 * i + 6]) for i in range(count)]

    def answer(self, addr: int) -> bytes:
        return self.mem[addr : addr + 3]

    def message(self, room: Room, index: int) -> bytes:
        """Résolution du numéro de message (92E4)."""
        if index >= text.ROOM_MESSAGE_BASE + len(room.texts):
            index = 0
        if index >= text.ROOM_MESSAGE_BASE:
            return room.texts[index - text.ROOM_MESSAGE_BASE]
        return self.system[index]

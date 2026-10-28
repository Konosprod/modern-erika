"""Extraction structurée du texte : messages système, vocabulaire, textes et commandes des salles.

Numérotation des messages (routine 92E4) : 0-15 = messages système en C600,
0x10 + i = i-ème texte de la salle courante.
"""

from . import charset

SYSTEM_MESSAGES = 0xC600
VERBS, VERB_COUNT = 0xA3A2, 0x22
NOUNS, NOUN_COUNT = 0xA42A, 0x8D
ROOM_MESSAGE_BASE = 0x10


def strings(data: bytes, pos: int) -> tuple[list[str], int]:
    """Lit des chaînes terminées par 00 jusqu'à un 00 00 ; retourne (chaînes, position après)."""
    out = []
    while data[pos] != 0:
        end = data.index(0, pos)
        out.append(charset.decode(data[pos:end]))
        pos = end + 1
    return out, pos + 1


def system_messages(mem: bytes) -> list[str]:
    return strings(mem, SYSTEM_MESSAGES)[0][:ROOM_MESSAGE_BASE]


def vocabulary(mem: bytes) -> dict[str, list[str]]:
    def table(base: int, count: int) -> list[str]:
        return [charset.decode(bytes(mem[base + 4 * i : base + 4 * i + 4]).rstrip(b"\0")) for i in range(count)]

    return {"verbs": table(VERBS, VERB_COUNT), "nouns": table(NOUNS, NOUN_COUNT)}


def room_data(blob: bytes, image_end: int, vocab: dict[str, list[str]]) -> dict:
    """Décode ce qui suit l'image : textes, puis [N] et N + 1 commandes de 6 octets (A2BB)."""
    texts, pos = strings(blob, image_end)
    count = blob[pos] + 1  # A2BB teste le compteur après chaque entrée : N + 1 commandes
    pos += 1
    commands = []
    for i in range(count):
        verb, noun, room, b3, message, script = blob[pos + 6 * i : pos + 6 * i + 6]
        commands.append({
            "verb": verb, "noun": noun,
            "verb_text": "*" if verb == 0xFF else vocab["verbs"][verb] if verb < VERB_COUNT else None,
            "noun_text": "*" if noun == 0xFF else vocab["nouns"][noun] if noun < NOUN_COUNT else None,
            "room": room, "b3": b3, "message": message, "script": script,
        })
    return {"texts": texts, "commands": commands, "trailing_bytes": len(blob) - pos - 6 * count}

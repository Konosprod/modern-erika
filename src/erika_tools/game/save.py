"""Sauvegarde : un emplacement unique, comme l'original (91B5 écrit 8E00 sur la piste 0,
secteur 15 de la disquette A). Ici on écrit un fichier au même format (256 octets depuis
8E00) ; l'image disque n'est jamais modifiée.
"""

import os
import sys

SECTOR_SIZE = 256


def path() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    return os.path.join(base, "erika", "save.bin")


def write(flags: bytes, room: int):
    os.makedirs(os.path.dirname(path()), exist_ok=True)
    data = bytes(flags) + bytes([room])
    with open(path(), "wb") as f:
        f.write(data.ljust(SECTOR_SIZE, b"\0"))


def read(original_sector: bytes, room_count: int) -> tuple[bytes, int] | None:
    """Drapeaux et salle sauvegardés : le fichier s'il existe, sinon la sauvegarde présente
    sur la disquette d'origine. None si rien de valide."""
    data = original_sector
    if os.path.exists(path()):
        with open(path(), "rb") as f:
            data = f.read(SECTOR_SIZE)
    if len(data) < 5 or not 1 <= data[4] < room_count:
        return None
    return data[:4], data[4]

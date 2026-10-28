"""Lecture des images disque D88 (format des émulateurs PC-88/PC-98).

Un fichier .d88 peut contenir plusieurs disquettes concaténées. Chaque disque :
  0x00  nom (17 octets, terminé par NUL)
  0x1a  protection en écriture
  0x1b  type de média (0x00 = 2D)
  0x1c  taille totale du disque (u32 LE)
  0x20  164 offsets de pistes (u32 LE, relatifs au début du disque)
Chaque secteur est précédé d'un en-tête de 16 octets (C, H, R, N, nb secteurs, ...,
taille des données en u16 LE à 0x0e).
"""

import struct
from dataclasses import dataclass, field

SECTOR_SIZE = 256
SECTORS_PER_TRACK = 16


@dataclass
class Sector:
    c: int
    h: int
    r: int
    n: int
    data: bytes
    file_offset: int  # offset des données dans le fichier .d88


@dataclass
class Disk:
    name: str
    media: int
    file_offset: int
    sectors: dict[tuple[int, int, int], Sector] = field(default_factory=dict)

    @property
    def cylinders(self) -> int:
        return max(c for c, _, _ in self.sectors) + 1

    @property
    def heads(self) -> int:
        return max(h for _, h, _ in self.sectors) + 1

    def read(self, c: int, h: int, r: int) -> bytes:
        return self.sectors[(c, h, r)].data

    def linear(self) -> bytes:
        """Image brute ordonnée piste par piste (C, H, R=1..16)."""
        out = bytearray()
        for c in range(self.cylinders):
            for h in range(self.heads):
                for r in range(1, SECTORS_PER_TRACK + 1):
                    s = self.sectors.get((c, h, r))
                    out += s.data if s else b"\xff" * SECTOR_SIZE
        return bytes(out)

    @staticmethod
    def linear_offset(c: int, h: int, r: int, heads: int = 2) -> int:
        return ((c * heads + h) * SECTORS_PER_TRACK + (r - 1)) * SECTOR_SIZE

    @staticmethod
    def chr_of(offset: int, heads: int = 2) -> tuple[int, int, int]:
        """Inverse de linear_offset : offset linéaire -> (C, H, R)."""
        idx = offset // SECTOR_SIZE
        track, r = divmod(idx, SECTORS_PER_TRACK)
        c, h = divmod(track, heads)
        return c, h, r + 1


def _parse_disk(buf: bytes, base: int) -> Disk:
    name = buf[base : base + 17].split(b"\0")[0].decode("ascii", "replace")
    media = buf[base + 0x1B]
    offsets = struct.unpack_from("<164I", buf, base + 0x20)
    disk = Disk(name, media, base)
    for off in offsets:
        if not off:
            continue
        p = base + off
        count = struct.unpack_from("<H", buf, p + 4)[0]
        for _ in range(count):
            c, h, r, n = buf[p : p + 4]
            size = struct.unpack_from("<H", buf, p + 0x0E)[0]
            disk.sectors[(c, h, r)] = Sector(c, h, r, n, buf[p + 16 : p + 16 + size], p + 16)
            p += 16 + size
    return disk


def load(path: str) -> list[Disk]:
    buf = open(path, "rb").read()
    disks = []
    base = 0
    while base < len(buf):
        size = struct.unpack_from("<I", buf, base + 0x1C)[0]
        if not size:
            break
        disks.append(_parse_disk(buf, base))
        base += size
    return disks

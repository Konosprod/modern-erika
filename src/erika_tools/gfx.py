"""Décodeur des images de salle (transcription des routines 9D7C-A1D1 du programme principal).

Une image se dessine en trois temps, sur les trois plans GVRAM (B, R, G) du PC-88,
80 octets par ligne, bit 7 = pixel le plus à gauche :

1. Tracé RLE 1 bpp, écrit à l'identique dans les trois plans (donc blanc ou noir),
   sur une zone de 64 octets (512 px) de large, jusqu'à l'adresse F1B0.
     00 nn -> nn octets 0x00 ; FF nn -> nn octets 0xFF ; autre -> octet littéral
2. Fond : 2 octets ignorés, puis un index de motif. Les 160 premières lignes sont
   ANDées avec ce motif (une ligne paire / une ligne impaire).
3. Commandes de remplissage jusqu'à 00 00 :
     [00 y] (optionnel, change la ligne courante) puis [x_hi, x_lo, motif]
   Remplissage par segments horizontaux depuis (x, y) ; la frontière est un pixel
   noir sur les trois plans. La file des segments est celle du jeu (365 entrées),
   ce qui reproduit son comportement avec les motifs tramés contenant du noir.
"""

from PIL import Image

WIDTH_BYTES = 80
LINES = 200
PLANE_SIZE = WIDTH_BYTES * LINES
IMAGE_W, IMAGE_H = 512, 160

# Table des 36 motifs en A1E3 : (B, R, G) ligne paire puis (B, R, G) ligne impaire.
PATTERN_TABLE = 0xA1E3
PATTERN_COUNT = 0x24

QUEUE_SLOTS = 365  # (0x8DF9 - 0x8400) / 7, file circulaire

# Palette numérique PC-88 : index = G<<2 | R<<1 | B
PALETTE = [
    (0, 0, 0), (0, 0, 255), (255, 0, 0), (255, 0, 255),
    (0, 255, 0), (0, 255, 255), (255, 255, 0), (255, 255, 255),
]


class Abort(Exception):
    """Débordement de la file de remplissage : le jeu abandonne le remplissage en cours."""


class Screen:
    def __init__(self, patterns: bytes):
        self.planes = [bytearray(PLANE_SIZE) for _ in range(3)]
        self.patterns = patterns
        self.y = 0  # (IX+2) en 9E75, conservé d'une image à l'autre dans le jeu

    def pattern(self, index: int) -> bytes:
        if index >= PATTERN_COUNT:
            index = 0
        return self.patterns[index * 6 : index * 6 + 6]

    # --- accès pixels -------------------------------------------------------

    def _or(self, offset: int) -> int:
        b, r, g = self.planes
        return b[offset] | r[offset] | g[offset]

    def lit(self, x: int, y: int) -> bool:
        """Vrai si le pixel n'est pas noir (au moins un plan à 1)."""
        return bool(self._or(y * WIDTH_BYTES + (x >> 3)) & (0x80 >> (x & 7)))

    # --- étape 1 : tracé RLE ------------------------------------------------

    def draw_rle(self, data: bytes, pos: int = 0) -> int:
        """Décode le tracé ; retourne la position du prochain octet non lu."""
        return _finish(self.draw_rle_steps(data, pos))

    def draw_rle_steps(self, data: bytes, pos: int = 0):
        """Comme draw_rle, mais cède ("line", y) à chaque nouvelle ligne écrite."""
        addr = 0xBFFF
        column = 0xFF

        def put(value: int):
            nonlocal addr, column
            addr += 1
            column = (column + 1) & 0xFF
            if column == 0x40:
                column = 0
                addr += 0x10
            off = addr - 0xC000
            if 0 <= off < PLANE_SIZE:
                for p in self.planes:
                    p[off] = value

        line = 0
        while addr < 0xF1B0:
            if (addr - 0xC000) // WIDTH_BYTES > line:
                line = (addr - 0xC000) // WIDTH_BYTES
                yield "line", line
            a = data[pos]
            if a in (0x00, 0xFF):
                count = data[pos + 1] or 256
                for _ in range(count):
                    put(a)
                pos += 2
            else:
                put(a)
                pos += 1
        return pos

    # --- étape 2 : fond -----------------------------------------------------

    def fill_background(self, index: int):
        pat = self.pattern(index)
        for line in range(160):
            row = pat[(line & 1) * 3 : (line & 1) * 3 + 3]
            base = line * WIDTH_BYTES
            for plane, mask in zip(self.planes, row):
                for i in range(base, base + 0x40):
                    plane[i] &= mask

    # --- étape 3 : remplissage ----------------------------------------------

    def _scan(self, x: int, y: int) -> tuple[int, int]:
        """Étend x à gauche et à droite tant que les pixels ne sont pas noirs (9FA9)."""
        xl = x
        while xl > 0 and self.lit(xl - 1, y):
            xl -= 1
        xr = x
        while xr < 0x27F and self.lit(xr + 1, y):
            xr += 1
        return xl, xr

    def _paint_span(self, xl: int, xr: int, y: int, pat: bytes):
        row = pat[(y & 1) * 3 : (y & 1) * 3 + 3]
        base = y * WIDTH_BYTES
        lb, rb = xl >> 3, xr >> 3
        lmask = 0xFF >> (xl & 7)
        rmask = ~(0xFF >> ((xr & 7) + 1)) & 0xFF

        def write(byte: int, mask: int):
            for plane, value in zip(self.planes, row):
                plane[base + byte] = (plane[base + byte] & ~mask & 0xFF) | (value & mask)

        if lb == rb:
            write(lb, lmask & rmask)
            return
        write(lb, lmask)
        write(rb, rmask)
        for byte in range(lb + 1, rb):
            for plane, value in zip(self.planes, row):
                plane[base + byte] = value

    def flood(self, x: int, y: int, index: int):
        if not self.lit(x, y):
            return
        pat = self.pattern(index)
        queue: list = [None] * QUEUE_SLOTS  # (xl, xr, y, parent)
        state = {"head": 0, "tail": 0}

        def push(sx: int, sy: int) -> int:
            xl, xr = self._scan(sx, sy)
            queue[state["tail"]] = (xl, xr, sy, state["head"])
            state["tail"] = (state["tail"] + 1) % QUEUE_SLOTS
            if state["tail"] == state["head"]:
                raise Abort
            self._paint_span(xl, xr, sy, pat)
            return xr

        def known(parent: int, line: int, cx: int):
            """Cherche un segment déjà en file contenant (cx, line) (A182)."""
            i = parent
            while i != state["tail"]:
                xl, xr, sy, _ = queue[i]
                if sy == line and xl <= cx <= xr:
                    return xr
                i = (i + 1) % QUEUE_SLOTS
            return None

        def neighbours(entry, line: int):
            xl, xr, _, parent = entry
            cx = xl
            while True:
                while not self.lit(cx, line):
                    cx += 1
                    if cx > xr:
                        return
                end = known(parent, line, cx)
                if end is None:
                    end = push(cx, line)
                cx = end + 2
                if cx > xr:
                    return

        try:
            push(x, y)
            while state["head"] != state["tail"]:
                entry = queue[state["head"]]
                sy = entry[2]
                if sy > 0:
                    neighbours(entry, sy - 1)
                if sy < 0xC7:
                    neighbours(entry, sy + 1)
                state["head"] = (state["head"] + 1) % QUEUE_SLOTS
        except Abort:
            pass

    def run_paint(self, data: bytes, pos: int) -> int:
        """Étapes 2 et 3. `pos` est la position laissée par draw_rle (DE du jeu)."""
        return _finish(self.run_paint_steps(data, pos))

    def run_paint_steps(self, data: bytes, pos: int):
        """Comme run_paint, mais cède ("fill", n) après le fond et après chaque remplissage."""
        pos += 2  # 9E85 : INC DE ×2
        self.fill_background(data[pos])
        yield "fill", 0
        while True:
            pos += 1
            a = data[pos]
            if a == 0:
                pos += 1
                if data[pos] == 0:
                    return pos + 1
                self.y = data[pos]
                pos += 1
                a = data[pos]
            x = ((a & 1) << 8) | data[pos + 1]
            pos += 2
            self.flood(x, self.y, data[pos])
            yield "fill", pos

    # --- sortie -------------------------------------------------------------

    def to_image(self, crop: bool = True) -> Image.Image:
        w, h = (IMAGE_W, IMAGE_H) if crop else (640, LINES)
        img = Image.new("P", (w, h))
        img.putpalette([c for rgb in PALETTE for c in rgb])
        px = bytearray(w * h)
        b, r, g = self.planes
        for y in range(h):
            for xb in range(w // 8):
                o = y * WIDTH_BYTES + xb
                bb, rr, gg = b[o], r[o], g[o]
                for bit in range(8):
                    m = 0x80 >> bit
                    px[y * w + xb * 8 + bit] = (
                        (1 if bb & m else 0) | (2 if rr & m else 0) | (4 if gg & m else 0)
                    )
        img.putdata(px)
        return img


def _finish(steps) -> int:
    """Exécute un générateur d'étapes jusqu'au bout et retourne sa valeur finale."""
    while True:
        try:
            next(steps)
        except StopIteration as done:
            return done.value


def room_steps(screen: Screen, blob: bytes):
    """Dessine l'image d'une salle étape par étape ; retourne l'offset de fin de l'image."""
    pos = yield from screen.draw_rle_steps(blob)
    return (yield from screen.run_paint_steps(blob, pos))


def decode_room(blob: bytes, patterns: bytes, screen: Screen | None = None) -> tuple[Screen, int]:
    """Dessine l'image d'une salle ; retourne l'écran et l'offset de fin de l'image."""
    screen = screen or Screen(patterns)
    return screen, _finish(room_steps(screen, blob))

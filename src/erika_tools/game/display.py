"""Écran PC-88 (3 plans B/R/G, 640×200) : image, texte avec les polices du jeu, rendu pygame."""

import numpy as np

from .. import charset, gfx

COLS = 53  # retour à la ligne des messages (9C4B : CP 0x35)
TEXT_ROW = 19  # ligne où s'écrit le texte (y = 190)
WINDOW_TOP = 170  # fenêtre de texte : lignes 170-199 (9CD4, 9D04)

BLUE, RED, MAGENTA, YELLOW, GREEN, CYAN, WHITE = 1, 2, 3, 6, 4, 5, 7
PALETTE = np.array(gfx.PALETTE, dtype=np.uint8)


class Display:
    def __init__(self, mem: bytes, patterns: bytes):
        self.mem = mem
        self.screen = gfx.Screen(patterns)  # les images se dessinent directement dans ces plans
        self.dirty = True
        self._glyphs: dict[tuple[int, bool], list[int]] = {}

    @property
    def planes(self):
        return self.screen.planes

    # --- texte -----------------------------------------------------------------

    def glyph(self, col: int, row: int, code: int, kanji: bool, color: int):
        """Écrit une case 12×10 : glyphe dans les plans du bit de couleur, 0 ailleurs (995C)."""
        key = (code, kanji)
        if key not in self._glyphs:
            self._glyphs[key] = charset.glyph(self.mem, code, kanji)
        x0, y0 = col * 12, row * 10
        for dy, bits in enumerate(self._glyphs[key]):
            base = (y0 + dy) * gfx.WIDTH_BYTES
            for dx in range(12):
                x = x0 + dx
                off, mask = base + (x >> 3), 0x80 >> (x & 7)
                on = bits & (0x800 >> dx)
                for p, plane in enumerate(self.planes):
                    if on and color & (1 << p):
                        plane[off] |= mask
                    else:
                        plane[off] &= ~mask & 0xFF
        self.dirty = True

    def string(self, col: int, row: int, raw: bytes, color: int):
        """Affiche une chaîne du jeu sans retour à la ligne (90FE) ; FF nn = kanji."""
        for code, kanji in decode_codes(raw):
            self.glyph(col, row, code, kanji, color)
            col += 1

    def scroll(self):
        """Fait remonter la fenêtre de texte d'une ligne et efface la dernière (9D04, 9D39)."""
        start = WINDOW_TOP * gfx.WIDTH_BYTES
        size = 20 * gfx.WIDTH_BYTES
        for plane in self.planes:
            plane[start : start + size] = plane[start + 10 * gfx.WIDTH_BYTES : start + 10 * gfx.WIDTH_BYTES + size]
        self.clear_line()

    def clear_line(self):
        start = TEXT_ROW * 10 * gfx.WIDTH_BYTES
        for plane in self.planes:
            plane[start : start + 10 * gfx.WIDTH_BYTES] = bytes(10 * gfx.WIDTH_BYTES)
        self.dirty = True

    def clear_window(self):
        start = WINDOW_TOP * gfx.WIDTH_BYTES
        for plane in self.planes:
            plane[start:] = bytes(len(plane) - start)
        self.dirty = True

    # --- rendu -----------------------------------------------------------------

    def to_rgb(self) -> np.ndarray:
        """Tableau (640, 200, 3) pour pygame.surfarray."""
        bits = [np.unpackbits(np.frombuffer(p, np.uint8).reshape(gfx.LINES, gfx.WIDTH_BYTES), axis=1)
                for p in self.planes]
        index = bits[0] | (bits[1] << 1) | (bits[2] << 2)
        return PALETTE[index].transpose(1, 0, 2)


def decode_codes(raw: bytes):
    """Produit (code, kanji) pour chaque caractère affiché."""
    i = 0
    while i < len(raw):
        if raw[i] == 0xFF and i + 1 < len(raw):
            yield raw[i + 1], True
            i += 2
        else:
            yield raw[i], False
            i += 1

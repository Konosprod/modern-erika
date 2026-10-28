"""Jeu de caractères du jeu (polices 12×10 px en C800 et D700, 15 octets par glyphe).

Police normale : disposition JIS X 0201, mais 0xA1-0xDF affiche du hiragana et
0x66-0x9F du katakana (code + 0x40 en JIS X 0201). FF nn sélectionne le glyphe nn
de la police kanji. Les dakuten (゛゜) sont des caractères séparés, recombinés ici.
"""

import unicodedata

FONT_NORMAL = 0xC800
FONT_KANJI = 0xD700
GLYPH_BYTES = 15

_KATA = "ヲァィゥェォャュョッーアイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワン"
_HIRA = "。「」、・をぁぃぅぇぉゃゅょっーあいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわん゙゚"

NORMAL: dict[int, str] = {c: chr(c) for c in range(0x20, 0x60)}
NORMAL[0x5C] = "¥"
NORMAL.update(zip(range(0x60, 0x66), "┌┐└┘│─"))
NORMAL.update(zip(range(0x66, 0x66 + len(_KATA)), _KATA))
NORMAL[0x70] = "ー"
NORMAL.update(zip(range(0xA1, 0xA1 + len(_HIRA)), _HIRA))
NORMAL.update(zip(range(0xE0, 0xE8), "♡♥〜⁉○●×‼"))

# Police kanji, lue sur les glyphes puis vérifiée dans le contexte des textes.
_KANJI_ROWS = [
    "　戦宇宙相闘機穴爆表示一入言行陸",
    "斧今銃上破壊任務弾男女激大落思配",
    "械船顔艦名手痛外二起格勝倒故金障",
    "登彼煙床感帰木気聞急波枚通面業近",
    "苦槍口下暗砲重普消当原潜高作好交",
    "後完声全心答込探果時自静射撃発食",
    "初小加速装車信効人井拾捨少捕生性",
    "終然草足牙違立体広他能惑星形建殺",
    "快誰荒地横流兵巨使怪冷古士色出天",
    "型従動雲突抱何正中直滅庫熱逃納敵",
    "可換反乗常平話死十早投異抵抗折必",
    "燃左料服分別方器本前待理閉開見湖",
    "右向問目持物森危山険部合題用要道",
    "光呼景脱汚角争緊態状悪基整備三知",
    "焚火回転無窓保着石売犯若路鳴調取",
    "始狙忘音多応嫌止責青空悲進強引室",
]
KANJI = "".join(_KANJI_ROWS)
assert len(KANJI) == 256
UNCERTAIN = {0xAB}  # jamais utilisé dans les textes


def decode(raw: bytes) -> str:
    """Décode une chaîne du jeu (sans le 00 final) en Unicode NFC."""
    out = []
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == 0xFF and i + 1 < len(raw):
            out.append(KANJI[raw[i + 1]])
            i += 2
            continue
        out.append(NORMAL.get(c, f"<{c:02X}>"))
        i += 1
    return unicodedata.normalize("NFC", "".join(out))


def glyph(mem: bytes, code: int, kanji: bool = False) -> list[int]:
    """Retourne 10 lignes de 12 bits (bit 11 = pixel de gauche)."""
    base = (FONT_KANJI if kanji else FONT_NORMAL) + code * GLYPH_BYTES
    g = mem[base : base + GLYPH_BYTES]
    return [(g[r] << 4) | ((g[10 + r // 2] >> 4) if r % 2 == 0 else (g[10 + r // 2] & 15)) for r in range(10)]

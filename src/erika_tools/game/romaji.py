"""Saisie romaji moderne (option du moteur, pas dans le jeu d'origine).

Romaji « wāpuro » courant : shi/si, chi/ti, tsu/tu, fu/hu, ji/zi, kya…, nn/n'/n + consonne
pour ん, consonne doublée pour っ, x/l + kana pour les petits kana, « - » pour ー.

Les petits kana sont convertis en grands : le vocabulaire du jeu n'en contient pas
(うちゆう pour 宇宙, すいつち pour « switch »), puisque la saisie d'origine ne pouvait pas
en produire.
"""

import unicodedata

_ROWS = {
    "": "あいうえお", "k": "かきくけこ", "s": "さしすせそ", "t": "たちつてと", "n": "なにぬねの",
    "h": "はひふへほ", "m": "まみむめも", "r": "らりるれろ", "g": "がぎぐげご", "z": "ざじずぜぞ",
    "d": "だぢづでど", "b": "ばびぶべぼ", "p": "ぱぴぷぺぽ",
}
_YOON = {"ky": "き", "sh": "し", "sy": "し", "ch": "ち", "ty": "ち", "cy": "ち", "ny": "に",
         "hy": "ひ", "my": "み", "ry": "り", "gy": "ぎ", "j": "じ", "jy": "じ", "zy": "じ",
         "dy": "ぢ", "by": "び", "py": "ぴ"}

TABLE: dict[str, str] = {}
for cons, kana in _ROWS.items():
    for vowel, k in zip("aiueo", kana):
        TABLE[cons + vowel] = k
for cons, base in _YOON.items():
    TABLE[cons + "a"], TABLE[cons + "u"], TABLE[cons + "o"] = base + "ゃ", base + "ゅ", base + "ょ"
    TABLE[cons + "e"] = base + "ぇ"
TABLE.update({
    "shi": "し", "chi": "ち", "tsu": "つ", "fu": "ふ", "ji": "じ", "ya": "や", "yu": "ゆ", "yo": "よ",
    "wa": "わ", "wo": "を", "wi": "うぃ", "we": "うぇ", "fa": "ふぁ", "fi": "ふぃ", "fe": "ふぇ",
    "fo": "ふぉ", "nn": "ん", "n'": "ん", "-": "ー",
    "xa": "ぁ", "xi": "ぃ", "xu": "ぅ", "xe": "ぇ", "xo": "ぉ", "xya": "ゃ", "xyu": "ゅ",
    "xyo": "ょ", "xtu": "っ", "xtsu": "っ",
})
for small in ("a", "i", "u", "e", "o", "ya", "yu", "yo", "tu", "tsu"):
    TABLE["l" + small] = TABLE["x" + small]

_PREFIXES = {key[:i] for key in TABLE for i in range(1, len(key) + 1)}
_DOUBLABLE = set("bcdfghjkmprstvwz")

_BIG = str.maketrans("ぁぃぅぇぉゃゅょっ", "あいうえおやゆよつ")


def to_codes(kana: str, kana_codes: dict[str, int]) -> list[int]:
    """Kana -> codes du jeu, petits kana remplacés par les grands, dakuten séparés."""
    text = unicodedata.normalize("NFD", kana.translate(_BIG))
    return [kana_codes[c] for c in text if c in kana_codes]


def feed(pending: str, ch: str) -> tuple[str, str, bool]:
    """Ajoute une lettre ; retourne (kana produits, lettres en attente, lettre refusée)."""
    p = pending + ch.lower()
    out = []
    rejected = False
    while p:
        if p in TABLE:
            out.append(TABLE[p])
            p = ""
        elif len(p) >= 2 and p[0] == p[1] and p[0] in _DOUBLABLE:
            out.append("っ")
            p = p[1:]
        elif p[0] == "n" and len(p) >= 2 and p[1] not in "aiueoyn'":
            out.append("ん")
            p = p[1:]
        elif p in _PREFIXES:
            break
        else:
            p = p[1:]  # lettre sans suite possible
            rejected = True
    return "".join(out), p, rejected


def finish(pending: str) -> str:
    """À la validation : un « n » final devient ん, le reste est abandonné."""
    return "ん" if pending.lower() == "n" else ""

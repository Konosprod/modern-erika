"""Traduction statique des scripts du jeu (table A6BC) en opérations de haut niveau.

Les scripts sont de petites routines Z80 exécutées avec IX = 8E00 (drapeaux) et
HL = 9314 (numéro du message à afficher). Elles n'utilisent qu'une poignée
d'instructions et de routines du jeu ; chacune est traduite en une opération nommée.
Une instruction non prévue lève une erreur plutôt que d'être devinée.

Format d'une opération : dict avec "op", éventuellement des paramètres, et "next"
(adresse de l'opération suivante, None si l'exécution s'arrête là).
"""

import re

from z80dis import z80

SCRIPT_TABLE = 0xA6BC
SCRIPT_COUNT = 255
CODE_START, CODE_END = 0xA8BA, 0xB4F7

# Routines du jeu appelées par les scripts (voir notes/format.md, « Scripts »).
SPECIALS = {
    0xA680: "show",  # affiche le message choisi, retour à la saisie
    0xB500: "goto",  # affiche le message puis A65E avec A (changement de salle)
    0xB4F7: "goto_random",  # A = 11 ou 12 au hasard, puis goto
    0xA65E: "dispatch",  # A65E avec A, sans afficher
    0xB514: "game_over",  # bip, message, HIT ANY KEY, message 7, GAME OVER, blocage
    0x9139: "halt",  # GAME OVER, blocage
    0xB50B: "say",  # affiche le message, continue
    0xB525: "pause",  # affiche le message, HIT ANY KEY, continue
    0xB52B: "ask",  # invite ♡, saisie, cherche la réponse DE (3 car.) ; carry = faux
    0xB590: "patch_image",  # remplit x 168-223, y 122-143 avec le motif 1
    0x915C: "disk_swap",  # « フロッピー2をドライブ1に… », attend Entrée
    0x3583: "wait_key",  # ROM : attend une touche
}
FREEZE = "freeze"  # JR $ : le jeu se fige (fin de partie, script 248)

_HEX = r"0x([0-9a-f]+)"


def _decode(mem: bytes, pc: int) -> tuple[str, int]:
    d = z80.decode(bytes(mem[pc : pc + 4]), pc)
    return z80.disasm(d), d.len


def _target(addr: int) -> int | str:
    if addr in SPECIALS:
        return SPECIALS[addr]
    if CODE_START <= addr < CODE_END:
        return addr
    raise ValueError(f"unknown target {addr:#06x}")


def translate_at(mem: bytes, pc: int) -> tuple[dict, int]:
    """Traduit l'instruction en pc ; retourne (opération sans "next", longueur)."""
    text, n = _decode(mem, pc)
    m = None

    def match(pattern: str):
        nonlocal m
        m = re.fullmatch(pattern, text)
        return m

    if match(rf"LD \(HL\),{_HEX}") or match(r"LD \(HL\),(\d+)"):
        return {"op": "msg", "n": int(m.group(1), 16 if "0x" in text else 10)}, n
    if match(r"(BIT|SET|RES) (\d),\(IX(?:\+(\d+))?\)"):
        return {"op": m.group(1).lower(), "byte": int(m.group(3) or 0), "bit": int(m.group(2))}, n
    if match(rf"LD A,{_HEX}") or match(r"LD A,(\d+)"):
        return {"op": "a", "n": int(m.group(1), 16 if "0x" in text else 10)}, n
    if match(rf"LD A,\({_HEX}\)"):
        return {"op": "a_var", "addr": int(m.group(1), 16)}, n
    if match(rf"LD DE,{_HEX}"):
        return {"op": "de", "addr": int(m.group(1), 16)}, n
    if match(rf"CP {_HEX}") or match(r"CP (\d+)"):
        return {"op": "cp", "n": int(m.group(1), 16 if "0x" in text else 10)}, n
    if text == "OR A":
        return {"op": "or_a"}, n
    if match(rf"(JP|JR|CALL)(?: (z|nz|c|nc),| ){_HEX}"):
        kind, cond, addr = m.group(1), m.group(2), int(m.group(3), 16)
        return {"op": "call" if kind == "CALL" else "jump", "cond": cond, "to": _target(addr)}, n
    raise ValueError(f"{pc:04X}: unexpected instruction '{text}'")


def translate(mem: bytes) -> dict:
    """Retourne {"entries": [adresse par script], "code": {adresse: opération}}."""
    entries = [int.from_bytes(mem[SCRIPT_TABLE + 2 * i : SCRIPT_TABLE + 2 * i + 2], "little")
               for i in range(SCRIPT_COUNT)]
    code: dict[int, dict] = {}
    todo = list(set(entries))
    while todo:
        pc = todo.pop()
        while pc not in code:
            op, n = translate_at(mem, pc)
            unconditional = op["op"] == "jump" and op["cond"] is None
            if unconditional and op["to"] == pc:
                op["to"] = FREEZE
            op["next"] = None if unconditional else pc + n
            code[pc] = op
            if op["op"] in ("jump", "call") and isinstance(op["to"], int):
                todo.append(op["to"])
            if unconditional:
                break
            pc += n
    return {"entries": entries, "code": code}

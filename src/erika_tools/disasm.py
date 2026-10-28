"""Désassemblage Z80 par parcours récursif à partir de points d'entrée.

Les octets jamais atteints par le flot de contrôle sont émis en `DB`, ce qui
évite de désassembler les données (texte, images) comme du code.
"""

import re

from z80dis import z80

_TARGET = re.compile(r"0x([0-9a-f]{4})\b")


def _is_unconditional_end(text: str) -> bool:
    if text in ("RET", "RETI", "RETN", "HALT") or text.startswith("JP ("):
        return True
    if text.startswith(("JP ", "JR ")):
        return "," not in text  # JP NZ,xxxx est conditionnel
    return False


def trace(data: bytes, base: int, entries: list[int]) -> dict[int, tuple[int, str]]:
    """Retourne {adresse: (longueur, texte)} pour chaque instruction atteinte."""
    code: dict[int, tuple[int, str]] = {}
    todo = list(entries)
    end = base + len(data)
    while todo:
        pc = todo.pop()
        while base <= pc < end and pc not in code:
            dec = z80.decode(data[pc - base : pc - base + 4], pc)
            if dec.len == 0:
                break
            text = z80.disasm(dec)
            code[pc] = (dec.len, text)
            if text.startswith(("JP ", "JR ", "CALL ", "DJNZ ", "RST ")):
                m = _TARGET.search(text)
                if m:
                    todo.append(int(m.group(1), 16))
            if _is_unconditional_end(text):
                break
            pc += dec.len
    return code


def listing(data: bytes, base: int, entries: list[int], comments: dict[int, str] | None = None) -> str:
    comments = comments or {}
    code = trace(data, base, entries)
    targets = set()
    for _, text in code.values():
        m = _TARGET.search(text)
        if m and text.split()[0] in ("JP", "JR", "CALL", "DJNZ"):
            targets.add(int(m.group(1), 16))
    lines = []
    pc = base
    end = base + len(data)
    while pc < end:
        if pc in targets or pc in entries:
            lines.append(f"\nL_{pc:04X}:")
        if pc in code:
            n, text = code[pc]
            raw = data[pc - base : pc - base + n].hex(" ")
            note = f"  ; {comments[pc]}" if pc in comments else ""
            lines.append(f"  {pc:04X}  {raw:<12}  {text}{note}")
            pc += n
        else:
            start = pc
            while pc < end and pc not in code and pc - start < 16 and (pc == start or pc not in targets):
                pc += 1
            chunk = data[start - base : pc - base]
            asc = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
            lines.append(f"  {start:04X}  DB {chunk.hex(' ')}  ; {asc}")
    return "\n".join(lines) + "\n"

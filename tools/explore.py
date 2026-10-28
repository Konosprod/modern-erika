"""Exploration automatique du jeu avec le moteur natif (sans affichage).

Parcours en largeur des états (salle, drapeaux 8E00-8E03) : depuis chaque état, on essaie
une saisie par commande de la salle. Produit les salles atteintes, les scripts exercés,
les game over, et un chemin (en romaji, rejouable dans MAME) vers chaque salle.

Usage : uv run python tools/explore.py [--json chemin.json]
"""

import argparse
import json
import os
import time
from collections import deque

from erika_tools import charset, gfx
from erika_tools.game.data import GameData
from erika_tools.game.display import COLS, decode_codes
from erika_tools.game.engine import CR, Engine, Restart

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
VOWELS = "AIUEO"
CONSONANTS = "KSTNHMYRWGZDB"  # rangées de la table 978A ; toute autre lettre = P
CHOICE_KEY = "2"  # script 123 : « 1 » mène au game over


class Ending(Exception):
    """Le script de fin (248) a figé le jeu."""


class Headless(Engine):
    """Moteur sans affichage : enregistre les messages et répond aux attentes de touche."""

    def __init__(self, data: GameData, random_bit: int = 0):
        super().__init__(data)
        self.random_bit = random_bit
        self.used_random = False
        self.messages: list[int] = []
        self.scripts_run: list[int] = []
        # Saisies attendues après la commande, dans l'ordre : "\r" (pause), réponse, touche.
        self.then: list[str | int] = []

    def draw_room(self, index: int):
        self.room_index = index
        self.room = self.data.rooms[index]
        if self.room.texts is None:
            _, end = gfx.decode_room(self.room.blob, self.data.patterns)
            self.data.load_room_data(self.room, end)
        return
        yield

    def print_message(self, index: int):
        self.messages.append(index)
        # print_message (9C11) fait une pause « HIT ANY KEY » tous les deux retours à la ligne.
        length = sum(1 for _ in decode_codes(self.data.message(self.room, index)))
        self.then.extend(["\r"] * (length // COLS // 2))
        return
        yield

    def pause(self):
        self.then.append("\r")
        return
        yield

    def halt(self):
        raise Restart
        yield

    def ask(self, answer_addr: int):
        self.then.append(answer_addr)  # converti en romaji + Entrée par l'explorateur
        return False
        yield

    def run_script(self, number: int):
        self.scripts_run.append(number)
        yield from super().run_script(number)

    def special(self, name: str, a: int, de: int):
        if name == "freeze":
            raise Ending
        if name == "disk_swap":
            self.then.append("SWAP")  # disquette B dans le lecteur 1, puis Entrée (915C)
            return None
        if name == "wait_key":
            self.then.append(CHOICE_KEY)
            return ord(CHOICE_KEY)
        if name == "goto_random":
            self.used_random = True
            yield from self.print_message(self.message)
            yield from self.dispatch(11 + self.random_bit)
            return None
        return (yield from super().special(name, a, de))


def drive(gen):
    try:
        while True:
            if next(gen) is not None:
                raise RuntimeError("attente inattendue en mode sans affichage")
    except StopIteration:
        pass


def romaji_table(mem: bytes) -> dict[tuple[int, int], str]:
    """(code, marque) -> romaji, d'après la table de conversion du jeu."""
    table = {(0xB1 + i, 0): v for i, v in enumerate(VOWELS)}
    for c in CONSONANTS + "P":
        row = CONSONANTS.index(c) * 5 if c in CONSONANTS else 65
        for i, v in enumerate(VOWELS):
            addr = 0x978A + row + i
            code = mem[addr]
            mark = 0xDF if addr >= 0x97CB else 0xDE if addr >= 0x97B6 else 0
            if code and (code, mark) not in table:
                table[(code, mark)] = c + v
    return table


def to_romaji(codes: bytes, table) -> str | None:
    out, i = [], 0
    while i < len(codes):
        c = codes[i]
        mark = codes[i + 1] if i + 1 < len(codes) and codes[i + 1] in (0xDE, 0xDF) else 0
        if (c, mark) in table:
            out.append(table[(c, mark)])
            i += 2 if mark else 1
        elif c < 0x80:
            out.append(chr(c))
            i += 1
        else:
            return None  # caractère impossible à taper en romaji
    return "".join(out)


def word(entry: bytes) -> bytes:
    return bytes(entry).rstrip(b"\0")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--json", help="écrit les chemins par salle dans ce fichier")
    p.add_argument("--max-seconds", type=float, default=0, help="arrêt propre après ce délai (0 = aucun)")
    p.add_argument("--flags", action="store_true", help="affiche les drapeaux vus à 1 dans chaque salle")
    p.add_argument("--per-room", type=int, default=300,
                   help="nombre maximal d'états (combinaisons de drapeaux) explorés par salle")
    args = p.parse_args()
    data = GameData(os.path.join(ROOT, "erika.d88"))
    table = romaji_table(data.mem)

    def start_state():
        eng = Headless(data)
        drive(eng.enter_room(1))
        return eng.room_index, bytes(eng.flags)

    input_cache: dict[int, list[bytes]] = {}

    def inputs(room_index: int) -> list[bytes]:
        if room_index not in input_cache:
            input_cache[room_index] = list(room_inputs(room_index))
        return input_cache[room_index]

    def room_inputs(room_index: int):
        """Une saisie par commande pouvant changer l'état (salle ou script) ; les autres
        commandes n'affichent qu'un message. On vérifie quelle commande la saisie
        déclenche vraiment (la première qui correspond)."""
        eng = Headless(data)
        drive(eng.draw_room(room_index))
        reached = set()
        for buf in candidate_inputs(eng):
            cmd = eng.find_command(buf + bytes([CR]))
            if cmd is not None and (cmd.room or cmd.script) and id(cmd) not in reached:
                reached.add(id(cmd))
                yield buf

    def candidate_inputs(eng):
        seen = set()
        for cmd in eng.room.commands:
            parts = []
            if cmd.noun != 0xFF:
                parts.append(word(data.nouns[cmd.noun]))
            if cmd.verb != 0xFF:
                parts.append(word(data.verbs[cmd.verb]))
            buf = b" ".join(parts)
            if buf not in seen:
                seen.add(buf)
                yield buf

    def step(state, buf: bytes, random_bit: int):
        eng = Headless(data, random_bit)
        drive(eng.draw_room(state[0]))
        eng.flags[:] = state[1]
        try:
            drive(eng.handle_command(buf + bytes([CR])))
            result = (eng.room_index, bytes(eng.flags))
            before, after = int.from_bytes(state[1], "little"), int.from_bytes(result[1], "little")
            if result[0] == state[0] and after != before and after & ~before == 0:
                return "loss", eng  # n'efface que des drapeaux sans bouger : jeter, abandonner…
            result = key(*result)
        except Restart:
            result = "game_over"
        except Ending:
            result = "ending"
        return result, eng

    tested = 0  # drapeaux lus par au moins un script (BIT) : les seuls qui comptent pour la suite
    for op in data.scripts["code"].values():
        if op["op"] == "bit" and op["byte"] < 4:
            tested |= 1 << (8 * op["byte"] + op["bit"])

    def key(room: int, flags: bytes):
        return room, (int.from_bytes(flags, "little") & tested).to_bytes(4, "little")

    start = start_state()
    start = key(*start)
    parent = {start: None}
    depth = {start: 0}
    per_room = {start[0]: 1}
    union = {start[0]: int.from_bytes(start[1], "little")}  # drapeaux déjà vus à 1, par salle
    queue = deque([start])

    def accept(state) -> bool:
        room = state[0]
        if per_room.get(room, 0) >= args.per_room:
            return False
        union[room] = union.get(room, 0) | int.from_bytes(state[1], "little")
        return True

    def path_to(state):
        moves = []
        while parent[state] is not None:
            state, move = parent[state]
            moves.append(move)
        return moves[::-1]

    scripts_seen, rooms_seen = set(), {start[0]}
    game_overs = unreplayable = expanded = 0
    endings: dict[int, list] = {}
    def best_states():
        best = {}
        for st, d in depth.items():
            if st[0] not in best or d < depth[best[st[0]]]:
                best[st[0]] = st
        return best

    def dump():
        if args.json:
            out = {str(r): path_to(st) for r, st in sorted(best_states().items())}
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=1)

    started = time.monotonic()
    while queue:
        if args.max_seconds and time.monotonic() - started > args.max_seconds:
            print("  (arrêt : délai atteint)")
            break
        state = queue.popleft()
        expanded += 1
        if expanded % 500 == 0:
            print(f"  … {expanded} états développés, {len(parent)} connus, file {len(queue)}", flush=True)
        for buf in inputs(state[0]):
            for bit in (0, 1):
                result, eng = step(state, buf, bit)
                scripts_seen.update(eng.scripts_run)
                text = to_romaji(buf, table)
                if text is None:
                    unreplayable += 1
                then = [to_romaji(data.answer(x), table) + "\r" if isinstance(x, int) else x
                        for x in eng.then]
                move = {"input": text, "kana": charset.decode(buf), "then": then,
                        "random": bit if eng.used_random else None}
                if result == "loss":
                    pass
                elif result == "ending":
                    flag = int.from_bytes(state[1], "little") >> 22 & 1  # 8E02 bit 6 : choix de la fin
                    if flag not in endings:
                        endings[flag] = path_to(state) + [move]
                        print(f"  FIN {'A' if flag else 'B'} atteinte en {len(endings[flag])} commandes", flush=True)
                        if args.json:
                            with open(args.json.replace(".json", f"_fin{'A' if flag else 'B'}.json"), "w",
                                      encoding="utf-8") as f:
                                json.dump(endings[flag], f, ensure_ascii=False, indent=1)
                elif result == "game_over":
                    game_overs += 1
                elif result not in parent and accept(result):
                    parent[result] = (state, move)
                    depth[result] = depth[state] + 1
                    per_room[result[0]] = per_room.get(result[0], 0) + 1
                    if result[0] not in rooms_seen:
                        rooms_seen.add(result[0])
                        print(f"  salle {result[0]} atteinte en {depth[result]} commandes", flush=True)
                        dump()
                    queue.append(result)
                if not eng.used_random:
                    break

    print(f"états atteints : {len(parent)}")
    print(f"salles atteintes ({len(rooms_seen)}/62) : {sorted(rooms_seen)}")
    distinct = set(data.scripts["entries"])
    covered = {data.scripts["entries"][n] for n in scripts_seen}
    print(f"scripts exercés : {len(scripts_seen)} numéros, {len(covered)}/{len(distinct)} routines distinctes")
    print(f"fins atteintes : {sorted('A' if f else 'B' for f in endings)}")
    print(f"game over atteignables : {game_overs} transitions ; saisies non tapables en romaji : {unreplayable}")
    best = best_states()
    far = max(best, key=lambda r: depth[best[r]])
    print(f"salle la plus lointaine : {far} ({depth[best[far]]} commandes)")
    dump()
    if args.json:
        print(f"chemins : {args.json}")


if __name__ == "__main__":
    main()

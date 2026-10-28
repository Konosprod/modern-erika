"""Compare the native engine with MAME over a sequence of commands.

Usage: uv run python tools/mame/compare.py "COMMAND 1" "COMMAND 2" ...
       uv run python tools/mame/compare.py --path extracted/paths_endingA.json
Commands are typed in romaji (the game's own conversion). After each input, the screen
(640×200) and the flags 8E00-8E04 are compared.
Requirements: MAME (Flatpak), ROMs via `uv run erika check-bios`.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image

from erika_tools.game.data import GameData, c_strings
from erika_tools.game.display import MAGENTA, TEXT_ROW
from erika_tools.game.engine import EVENT, FRAME, Engine


DISK_SWAP_TEXT = 0x924B  # « フロッピー2をドライブ1にセットしてください。  PUSH RETURN KEY »


class Follower(Engine):
    """Moteur qui suit le tirage au hasard fait par MAME (salle 11 ou 12, B4F7)."""

    hint = None  # salle où MAME se trouvait après la saisie en cours

    def special(self, name, a, de):
        if name == "disk_swap":
            # Comme l'original (915C) : le moteur, lui, saute cette demande.
            d = self.display
            d.scroll()
            d.string(1, TEXT_ROW, c_strings(self.data.mem, DISK_SWAP_TEXT, 1)[0], MAGENTA)
            while (yield from self.wait_event()) != ("key", "return"):
                pass
            d.scroll()
            return None
        if name == "goto_random" and self.hint in (11, 12):
            yield from self.print_message(self.message)
            yield from self.dispatch(self.hint)
            return None
        return (yield from super().special(name, a, de))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WORK = os.path.join(ROOT, "extracted", "mame", "compare")  # sous $HOME : visible du sandbox Flatpak
DISK_SIZE = 348848
KEY_RATE = 0.2  # le jeu perd les touches envoyées plus vite
IDLE = 1.0  # le jeu est prêt quand le Z80 reste dans la ROM (attente clavier) aussi longtemps
SETTLE = 0.5  # délai après la dernière touche avant de guetter l'état prêt
MAX_SECONDS = 3000

# Avant chaque saisie (et à la fin) : capture d'écran + drapeaux 8E00-8E04, quand le jeu
# attend une touche, c.-à-d. quand le PC reste < 0x8000 (ROM) pendant IDLE secondes.
LUA = """
local items = {ITEMS}
local cpu = manager.machine.devices[":maincpu"]
local mem = cpu.spaces["program"]
local log = io.open("{LOG}", "w")
local k, queue, next_key, not_before, last_busy, started = 1, "", 0, 1, 0, false
emu.register_periodic(function()
  local t = manager.machine.time.seconds
  local pc = cpu.state["PC"].value
  if pc >= 0x8000 then last_busy = t end
  if pc >= 0x9000 then started = true end  -- le BIOS tourne aussi en ROM au démarrage
  if not started then return end
  if #queue > 0 then
    if t >= next_key then
      manager.machine.natkeyboard:post(queue:sub(1, 1))
      queue = queue:sub(2); next_key = t + {RATE}
      not_before = t + {SETTLE}
    end
    return
  end
  if t < not_before or t - last_busy < {IDLE} then return end
  manager.machine.video:snapshot()
  local f = {}
  for a = 0x8e00, 0x8e04 do f[#f + 1] = string.format("%02x", mem:read_u8(a)) end
  log:write(table.concat(f, " "), "\\n"); log:flush()
  if k > #items then manager.machine:exit(); return end
  queue = items[k]; k = k + 1
  if queue:sub(1, 1) == "\\1" then
    -- Le jeu charge toujours depuis le lecteur 1 (C057) : on y insère la disquette B.
    manager.machine.images[":pc80s31:fdc:0:525sd"]:load("{DISK_B}")
    queue = queue:sub(2)
  end
end)
"""


def lua_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "\\r").replace("\1", "\\1") + '"'


def run_mame(items: list[str]) -> tuple[list[Image.Image], list[bytes]]:
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    image = open(os.path.join(ROOT, "erika.d88"), "rb").read()
    for i, name in enumerate(("A.d88", "B.d88")):
        open(os.path.join(WORK, name), "wb").write(image[i * DISK_SIZE : (i + 1) * DISK_SIZE])
    lua = (LUA.replace("{ITEMS}", "{" + ", ".join(lua_string(c) for c in items) + "}")
              .replace("{LOG}", os.path.join(WORK, "flags.txt"))
              .replace("{DISK_B}", os.path.join(WORK, "B.d88"))
              .replace("{RATE}", str(KEY_RATE)).replace("{SETTLE}", str(SETTLE))
              .replace("{IDLE}", str(IDLE)))
    open(os.path.join(WORK, "run.lua"), "w").write(lua)
    subprocess.run(["flatpak", "run", "org.mamedev.MAME", "pc8801mk2sr",
                    "-rompath", os.path.join(ROOT, "roms", "mame"),
                    "-flop1", os.path.join(WORK, "A.d88"), "-flop2", os.path.join(WORK, "B.d88"),
                    "-video", "none", "-sound", "none", "-speed", "10", "-frameskip", "0", "-skip_gameinfo", "-nowindow",
                    "-seconds_to_run", str(MAX_SECONDS),
                    "-snapshot_directory", os.path.join(WORK, "snap"),
                    "-autoboot_script", os.path.join(WORK, "run.lua")],
                   check=True, capture_output=True)
    snap_dir = os.path.join(WORK, "snap", "pc8801mk2sr")
    screens = [Image.open(os.path.join(snap_dir, f)).convert("RGB") for f in sorted(os.listdir(snap_dir))]
    flags = [bytes.fromhex(line) for line in open(os.path.join(WORK, "flags.txt"))]
    return screens, flags


def run_engine(items: list[str], mame_flags: list[bytes]) -> tuple[list[Image.Image], list[bytes]]:
    eng = Follower(GameData(os.path.join(ROOT, "erika.d88")))
    flow = eng.run()
    screens, flags = [], []

    def settle(request):
        while request == FRAME:
            request = flow.send(None)
        return request

    def capture():
        if request != EVENT:
            raise RuntimeError("the engine is not waiting for a key")
        screens.append(Image.fromarray(eng.display.to_rgb().transpose(1, 0, 2)))
        flags.append(bytes(eng.flags) + bytes([eng.room_index]))

    request = settle(next(flow))
    for i, item in enumerate(items):
        capture()
        Follower.hint = mame_flags[i + 1][4] if i + 1 < len(mame_flags) else None
        for ch in item.lstrip("\1"):
            event = ("key", "return") if ch == "\r" else ("text", ch)
            request = settle(flow.send(event))
    capture()
    return screens, flags


def path_items(path: str) -> tuple[list[str], list[str]]:
    """Saisies d'un chemin produit par tools/explore.py (réponses et touches comprises)."""
    items, labels = [], []
    for move in json.load(open(path, encoding="utf-8")):
        items.append(move["input"] + "\r")
        labels.append(move["input"])
        for typed in move["then"]:  # pauses, réponses, touches, dans l'ordre où le jeu les attend
            if typed == "SWAP":
                items.append("\1\r")
                labels.append("  (disk B)")
            else:
                items.append(typed)
                labels.append("  (Enter)" if typed == "\r" else f"  ({typed.strip()})")
    return items, labels


def main():
    p = argparse.ArgumentParser()
    p.add_argument("commands", nargs="*", help="commands in romaji; \"\" = Enter alone")
    p.add_argument("--path", help="JSON path produced by tools/explore.py")
    args = p.parse_args()
    out = os.path.join(WORK + "_result")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    if args.path:
        items, labels = path_items(args.path)
    else:
        items, labels = [cmd + "\r" for cmd in args.commands], list(args.commands)
    items = ["\r"] + items
    labels = ["(title)", "(room 1)"] + labels
    mame_screens, mame_flags = run_mame(items)
    eng_screens, eng_flags = run_engine(items, mame_flags)
    if len(mame_screens) != len(labels):
        print(f"MAME: {len(mame_screens)} captures instead of {len(labels)}")
    ok = True
    for i, label in enumerate(labels):
        if i >= min(len(mame_screens), len(mame_flags)):
            print(f"{label}: no MAME capture")
            ok = False
            continue
        a, b = eng_screens[i], mame_screens[i]
        diff = int(np.any(np.asarray(a) != np.asarray(b), axis=2).sum())
        same_flags = eng_flags[i] == mame_flags[i]
        status = "OK  " if diff == 0 and same_flags else "DIFF"
        ok &= diff == 0 and same_flags
        print(f"{status} {i:3d} {label:<26} pixels={diff:<6} flags engine={eng_flags[i].hex(' ')}"
              f" mame={mame_flags[i].hex(' ')}", flush=True)
        both = Image.new("RGB", (640, 410))
        both.paste(a, (0, 0))
        both.paste(b, (0, 210))
        both.save(os.path.join(out, f"{i:03d}.png"))
    print(f"side-by-side captures (engine on top, MAME below): {out}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

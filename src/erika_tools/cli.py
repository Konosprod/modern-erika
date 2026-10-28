import argparse
import json
import os
import re
import shutil
import subprocess
import zlib

from PIL import Image

from . import charset, d88, disasm, gfx, text

OUT = "extracted"

# Chargements effectués par le boot sector (voir notes/format.md) :
# (disque, piste linéaire, secteur, nb secteurs, adresse de destination)
BOOT_LOADS = [
    (0, 0, 1, 4, 0xC000),  # boot + routines disque
    (0, 2, 1, 0x20, 0xC600),
    (0, 7, 1, 5, 0x4000),
    (0, 4, 1, 0x30, 0x9000),  # programme principal, exécuté en 0x9000
]


def read_linear(disk: bytes, track: int, sector: int, count: int) -> bytes:
    start = (track * d88.SECTORS_PER_TRACK + sector - 1) * d88.SECTOR_SIZE
    return disk[start : start + count * d88.SECTOR_SIZE]


def boot_memory(disks: list[bytes]) -> bytearray:
    mem = bytearray(0x10000)
    for drive, track, sector, count, addr in BOOT_LOADS:
        blob = read_linear(disks[drive], track, sector, count)
        mem[addr : addr + len(blob)] = blob
    return mem


def cmd_dump(args, disks):
    os.makedirs(OUT, exist_ok=True)
    for disk in disks:
        name = "disk" + disk.name.split()[-1] + ".bin"
        data = disk.linear()
        open(os.path.join(OUT, name), "wb").write(data)
        print(f"{name}: {len(data)} octets ({disk.cylinders} cyl × {disk.heads} faces)")


def cmd_disasm(args, disks):
    os.makedirs(OUT, exist_ok=True)
    linear = [d.linear() for d in disks]
    if args.track is None:
        mem = boot_memory(linear)
        start, end = args.start, args.end
        data = bytes(mem[start:end])
    else:
        data = read_linear(linear[args.disk], args.track, args.sector, args.count)
        start = args.start
    entries = args.entry or [start]
    out = disasm.listing(data, start, entries)
    path = os.path.join(OUT, args.output)
    open(path, "w").write(out)
    print(f"{path}: {out.count(chr(10))} lignes")


def cmd_text(args, disks):
    linear = [d.linear() for d in disks]
    mem = boot_memory(linear)
    patterns = bytes(mem[gfx.PATTERN_TABLE : gfx.PATTERN_TABLE + gfx.PATTERN_COUNT * 6])
    vocab = text.vocabulary(mem)
    out = os.path.join(OUT, "rooms")
    os.makedirs(out, exist_ok=True)

    def dump(name, obj):
        with open(name, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)

    dump(os.path.join(OUT, "vocab.json"), vocab)
    dump(os.path.join(OUT, "system.json"), text.system_messages(mem))
    with open(os.path.join(OUT, "text.tsv"), "w", encoding="utf-8") as tsv:
        tsv.write("salle\tmessage\ttexte\n")
        for i, msg in enumerate(text.system_messages(mem)):
            tsv.write(f"-\t{i:02X}\t{msg}\n")
        for i, entry in enumerate(rooms(mem)):
            blob = room_blob(linear, entry)
            _, end = gfx.decode_room(blob, patterns)
            data = text.room_data(blob, end, vocab)
            data["disk"] = entry
            dump(os.path.join(out, f"room{i:02d}.json"), data)
            for j, t in enumerate(data["texts"]):
                tsv.write(f"{i:02d}\t{text.ROOM_MESSAGE_BASE + j:02X}\t{t}\n")
            print(f"room{i:02d}: {len(data['texts'])} textes, {len(data['commands'])} commandes")


def cmd_fonts(args, disks):
    mem = boot_memory([d.linear() for d in disks])
    os.makedirs(OUT, exist_ok=True)
    for name, kanji in (("font_normal", False), ("font_kanji", True)):
        img = Image.new("1", (16 * 12, 16 * 10))
        for code in range(256):
            for y, row in enumerate(charset.glyph(mem, code, kanji)):
                for x in range(12):
                    if row & (0x800 >> x):
                        img.putpixel(((code % 16) * 12 + x, (code // 16) * 10 + y), 1)
        img.save(os.path.join(OUT, name + ".png"))
    print("polices : 16×16 glyphes de 12×10 px")


ROOM_TABLE = 0x933B
ROOM_COUNT = 62


def rooms(mem: bytes) -> list[tuple[int, int, int, int]]:
    """Table des salles en 933B : (lecteur, piste linéaire, secteur, nb secteurs)."""
    return [tuple(mem[ROOM_TABLE + 6 * i : ROOM_TABLE + 6 * i + 4]) for i in range(ROOM_COUNT)]


def room_blob(linear: list[bytes], entry) -> bytes:
    drive, track, sector, count = entry
    return read_linear(linear[drive], track, sector, count)


def cmd_gfx(args, disks):
    linear = [d.linear() for d in disks]
    mem = boot_memory(linear)
    patterns = bytes(mem[gfx.PATTERN_TABLE : gfx.PATTERN_TABLE + gfx.PATTERN_COUNT * 6])
    out = os.path.join(OUT, "images")
    os.makedirs(out, exist_ok=True)
    screen = None
    for i, entry in enumerate(rooms(mem)):
        if args.room is not None and i != args.room:
            continue
        blob = room_blob(linear, entry)
        if screen is None or not args.keep_y:
            screen = gfx.Screen(patterns)
        screen.planes = [bytearray(gfx.PLANE_SIZE) for _ in range(3)]
        screen, end = gfx.decode_room(blob, patterns, screen)
        img = screen.to_image()
        img.save(os.path.join(out, f"room{i:02d}.png"))
        img.resize((img.width, img.height * 2), 0).save(os.path.join(out, f"room{i:02d}_x2.png"))
        print(f"room{i:02d}: disque {'AB'[entry[0]]} piste {entry[1]} secteur {entry[2]}, "
              f"image {end} / {len(blob)} octets")


def cmd_play(args, disks):
    from .game.engine import main as play

    play(args.image)


MAME_MACHINE = "pc8801mk2sr"
ROM_DIR = os.path.join("roms", MAME_MACHINE)


def mame_command() -> list[str]:
    mame = shutil.which("mame")
    return [mame] if mame else ["flatpak", "run", "org.mamedev.MAME"]


MAME_ROMPATH = os.path.join("roms", "mame")
_LISTROM = re.compile(r"^(\S+)\s+(\d+)\s+CRC\(([0-9a-f]{8})\)", re.M)


def link_roms():
    """Crée roms/mame/<machine>/ : liens aux noms attendus par MAME vers les ROM de ROM_DIR,
    identifiées par CRC (ROM_DIR n'est pas modifié)."""
    listing = subprocess.run(mame_command() + ["-listroms", MAME_MACHINE],
                             capture_output=True, text=True).stdout
    by_crc = {}
    for root, _, files in os.walk(ROM_DIR):
        for f in files:
            path = os.path.join(root, f)
            by_crc.setdefault(zlib.crc32(open(path, "rb").read()), path)
    target_dir = os.path.join(MAME_ROMPATH, MAME_MACHINE)
    os.makedirs(target_dir, exist_ok=True)
    for name, size, crc in _LISTROM.findall(listing):
        link = os.path.join(target_dir, name)
        source = by_crc.get(int(crc, 16))
        if os.path.islink(link):
            os.remove(link)
        if source:
            os.symlink(os.path.relpath(source, target_dir), link)
            print(f"{name:18s} -> {os.path.relpath(source, ROM_DIR)}")
        else:
            print(f"{name:18s} absent (CRC {crc})")


def cmd_check_bios(args, disks):
    if not os.path.isdir(ROM_DIR):
        print(f"Déposer les ROM dans {ROM_DIR}/")
        return
    try:
        link_roms()
        subprocess.run(mame_command() + ["-rompath", os.path.abspath(MAME_ROMPATH), "-verifyroms", MAME_MACHINE])
    except FileNotFoundError:
        print("MAME introuvable : flatpak install flathub org.mamedev.MAME")


def main():
    p = argparse.ArgumentParser(prog="erika")
    p.add_argument("--image", default="erika.d88")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("dump", help="exporte chaque disquette en image linéaire")

    s = sub.add_parser("disasm", help="désassemble la mémoire après boot ou une zone disque")
    s.add_argument("--start", type=lambda x: int(x, 0), default=0x9000)
    s.add_argument("--end", type=lambda x: int(x, 0), default=0xC000)
    s.add_argument("--entry", type=lambda x: int(x, 0), action="append")
    s.add_argument("--disk", type=int, default=0)
    s.add_argument("--track", type=int)
    s.add_argument("--sector", type=int, default=1)
    s.add_argument("--count", type=int, default=16)
    s.add_argument("-o", "--output", default="main.asm")

    sub.add_parser("text", help="extrait textes, vocabulaire et commandes des salles")
    sub.add_parser("fonts", help="exporte les deux polices du jeu en PNG")

    s = sub.add_parser("gfx", help="décode les images des salles en PNG")
    s.add_argument("--room", type=int)
    s.add_argument("--keep-y", action="store_true", help="conserve la ligne courante entre images")

    sub.add_parser("play", help="lance le jeu (moteur natif, sans émulateur)")

    sub.add_parser("check-bios", help="vérifie les ROM PC-88 dans roms/ avec MAME")

    args = p.parse_args()
    disks = d88.load(args.image)
    globals()["cmd_" + args.cmd.replace("-", "_")](args, disks)

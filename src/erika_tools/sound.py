"""Sons du jeu : voix numérisées (B78B), bruit du tir (overlay 4000, B786) et bip (965B).

Les voix sont envoyées octet par octet sur le port 0x10 (port imprimante) : probablement
pour le boîtier vocal « JAST SOUND » branché sur la prise imprimante.

Format (B791-B7FA) : flux de quartets, quartet fort d'abord. Chaque bloc commence par un
quartet d'échelle n (1-5 ; ≥ 8 = fin), suivi de 32 quartets de delta en signe/magnitude
(bit 3 = signe) multipliés par 2^(n-1) (tables en B803). L'accumulateur 8 bits part de
0x80 et déborde sans saturation (ADD A,(HL)).
"""

import wave

import numpy as np

# Boucle d'un échantillon : 818 cycles (CALL B7FB) + 132 (quartet) + 79 (reste) ≈ 1029
# cycles à 3,9936 MHz.
Z80_HZ = 3_993_600
CYCLES_PER_SAMPLE = 1029
SAMPLE_RATE = round(Z80_HZ / CYCLES_PER_SAMPLE)  # ≈ 3881 Hz

VOICE_TABLE = 0xB70D  # 30 entrées : lecteur, piste, secteur, nb secteurs (chargées en 6000)
VOICE_COUNT = 30
EVENT_TABLE = 0xB617  # salle, puis 3 × (message, n° de voix) ; 0 = fin (B5CB)
SHOT = 0x4000  # overlay chargé au démarrage (piste 7, 5 secteurs)
SHOT_SIZE = 0x500

BEEP_HZ = 2400  # buzzer du PC-88
BEEP_SECONDS = 0.025  # 965B : boucle de 0x0FFF × 24 cycles


STEP_TABLES = 0xB803


def decode(data: bytes, mem: bytes) -> np.ndarray:
    """Décode un flux de voix en échantillons 8 bits non signés.

    Les pas viennent des tables du jeu : DE = B803 + ((échelle - 1) × 16) & 0xFF (B7A6-B7B1),
    ce qui reproduit aussi les échelles inattendues (0, 6, 7).
    """
    nibbles = np.empty(len(data) * 2, dtype=np.uint8)
    raw = np.frombuffer(data, dtype=np.uint8)
    nibbles[0::2] = raw >> 4
    nibbles[1::2] = raw & 0x0F
    out = []
    acc = 0x80
    i = 0
    while i + 33 <= len(nibbles):
        scale = int(nibbles[i])
        if scale & 8:
            break
        table = STEP_TABLES + (((scale - 1) * 16) & 0xFF)
        for d in nibbles[i + 1 : i + 33].tolist():
            acc = (acc + mem[table + d]) & 0xFF
            out.append(acc)
        i += 33
    return np.array(out, dtype=np.uint8)


def beep(rate: int = SAMPLE_RATE) -> np.ndarray:
    n = int(rate * BEEP_SECONDS)
    t = np.arange(n)
    return np.where((t * 2 * BEEP_HZ // rate) % 2 == 0, 0xC0, 0x40).astype(np.uint8)


def voice_entries(mem: bytes) -> list[tuple[int, int, int, int]]:
    return [tuple(mem[VOICE_TABLE + 4 * i : VOICE_TABLE + 4 * i + 4]) for i in range(VOICE_COUNT)]


def events(mem: bytes) -> dict[tuple[int, int], int]:
    """(salle, message) -> n° de voix, d'après la table B617."""
    out = {}
    pos = EVENT_TABLE
    while mem[pos]:
        room = mem[pos]
        for k in range(3):
            message, voice = mem[pos + 1 + 2 * k], mem[pos + 2 + 2 * k]
            if message and (room, message) not in out:
                out[(room, message)] = voice
        pos += 7
    return out


def write_wav(path: str, samples: np.ndarray, rate: int = SAMPLE_RATE):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)  # 8 bits non signés, comme le DAC d'origine
        w.setframerate(rate)
        w.writeframes(samples.tobytes())

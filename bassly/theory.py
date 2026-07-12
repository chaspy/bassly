"""Deterministic music theory: pitch calculation and spelling.

No AI involved: every result here is computable and unit-testable. Later
stages (degree analysis, vocabulary classification) build on these facts.

Known simplification (v1): spelling picks flat or sharp names per pitch
class; it is not yet key-aware (e.g. Cb is spelled B, Fb is spelled E).
"""

from __future__ import annotations

import re
from typing import Literal, NamedTuple

FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
# 実務家スタイル: 理論の7文字帳簿 (Cb, E# など) を捨てて慣用名だけを使う。
# 度数計算は内部でピッチクラスベースなので表示にしか影響しない。
SIMPLE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

NotationStyle = Literal["flat", "sharp", "simple"]

# Standard tuning, low to high: B0 E1 A1 D2 G2 (scientific pitch notation).
# A 4-string bass simply never uses the B string.
OPEN_STRING_MIDI = {"B": 23, "E": 28, "A": 33, "D": 38, "G": 43}


class Pitch(NamedTuple):
    midi: int
    name: str  # pitch-class name, e.g. "Gb"
    octave: int  # scientific pitch notation


def pitch_at(
    string: str, fret: int, prefer: Literal["flat", "sharp"] = "flat"
) -> Pitch:
    if string not in OPEN_STRING_MIDI:
        raise ValueError(f"unknown string {string!r}, expected one of B/E/A/D/G")
    midi = OPEN_STRING_MIDI[string] + fret
    names = FLAT_NAMES if prefer == "flat" else SHARP_NAMES
    return Pitch(midi=midi, name=names[midi % 12], octave=midi // 12 - 1)


# --- note names and keys ----------------------------------------------------

_NATURAL_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_LETTERS = ["C", "D", "E", "F", "G", "A", "B"]
_MAJOR_STEPS = [2, 2, 1, 2, 2, 2, 1]


def parse_note_name(name: str) -> int:
    """Note name (with b/# accidentals) -> pitch class 0-11."""
    if not name or name[0] not in _NATURAL_PC:
        raise ValueError(f"bad note name {name!r}")
    pc = _NATURAL_PC[name[0]]
    for acc in name[1:]:
        if acc == "b":
            pc -= 1
        elif acc == "#":
            pc += 1
        else:
            raise ValueError(f"bad accidental in {name!r}")
    return pc % 12


def major_scale_spellings(key: str) -> dict[int, str]:
    """Pitch class -> correctly spelled name within the given major key.

    e.g. for Gb major, pc 11 is spelled "Cb" (not "B").
    """
    pc = parse_note_name(key)
    letter_idx = _LETTERS.index(key[0])
    spellings: dict[int, str] = {}
    for i, step in enumerate(_MAJOR_STEPS):
        letter = _LETTERS[(letter_idx + i) % 7]
        diff = (pc - _NATURAL_PC[letter]) % 12
        if diff > 6:
            diff -= 12
        spellings[pc % 12] = letter + {-2: "bb", -1: "b", 0: "", 1: "#", 2: "##"}[diff]
        pc += step
    return spellings


def spell_pc(pc: int, key: str | None = None, style: NotationStyle = "flat") -> str:
    """Spell a pitch class.

    "flat"  : key-aware theoretical spelling (Gb major -> Cb, not B)
    "sharp" : plain sharp names (F#, A#, D#)
    "simple": player-style common names (F#, B, Eb — no Cb/E#/Fb/B#)
    """
    if style == "sharp":
        return SHARP_NAMES[pc % 12]
    if style == "simple":
        return SIMPLE_NAMES[pc % 12]
    if key:
        spellings = major_scale_spellings(key)
        if pc % 12 in spellings:
            return spellings[pc % 12]
    return FLAT_NAMES[pc % 12]


def respell_text(text: str, key: str | None = None, style: NotationStyle = "flat") -> str:
    """Re-spell note names inside prose (summaries, notes) to the given style.

    Source spellings are assumed to be the key-aware flat style (how the data
    and AI summaries are written). Both "Cb" and "C♭" forms are handled.
    Names whose spelling doesn't change (Eb, Bb, ...) are left untouched, so
    the conversion is idempotent and user-written F#-style prose passes through.
    """
    if style == "flat":
        return text
    for pc in range(12):
        src = spell_pc(pc, key, "flat")
        dst = spell_pc(pc, key, style)
        if src != dst:
            text = text.replace(src, dst).replace(src.replace("b", "♭"), dst)
    return text


def respell_chord(
    symbol: str, key: str | None = None, style: NotationStyle = "flat"
) -> str:
    """Re-spell a chord symbol's root/bass in the given notation style."""
    chord = parse_chord(symbol)
    if chord is None:
        return symbol
    root = spell_pc(chord.root_pc, key, style)
    bass = f"/{spell_pc(chord.bass_pc, key, style)}" if chord.bass_pc is not None else ""
    return f"{root}{chord.quality}{bass}"


# --- chords -------------------------------------------------------------------

# Interval sets from the chord root. Longest symbols first for parsing.
CHORD_QUALITIES = {
    "maj7": (0, 4, 7, 11),
    "m7b5": (0, 3, 6, 10),
    "dim7": (0, 3, 6, 9),
    "add9": (0, 2, 4, 7),
    "sus4": (0, 5, 7),
    "sus2": (0, 2, 7),
    "dim": (0, 3, 6),
    "aug": (0, 4, 8),
    "m7": (0, 3, 7, 10),
    "m6": (0, 3, 7, 9),
    "6": (0, 4, 7, 9),
    "m": (0, 3, 7),
    "7": (0, 4, 7, 10),
    "": (0, 4, 7),
}

_CHORD_RE = re.compile(r"^([A-G](?:b|#)?)(.*)$")


class Chord(NamedTuple):
    symbol: str
    root_pc: int
    quality: str
    tone_pcs: frozenset[int]  # pitch classes of chord tones
    bass_pc: int | None  # slash-chord bass, if specified


def parse_chord(symbol: str) -> Chord | None:
    """Parse a chord symbol; returns None for N.C. Raises on unknown quality."""
    if symbol in ("N.C.", "NC", ""):
        return None
    main, _, bass = symbol.partition("/")
    m = _CHORD_RE.match(main)
    if not m:
        raise ValueError(f"bad chord symbol {symbol!r}")
    root_pc = parse_note_name(m.group(1))
    quality = m.group(2)
    if quality not in CHORD_QUALITIES:
        raise ValueError(f"unknown chord quality {quality!r} in {symbol!r}")
    tones = frozenset((root_pc + iv) % 12 for iv in CHORD_QUALITIES[quality])
    bass_pc = parse_note_name(bass) if bass else None
    return Chord(symbol, root_pc, quality, tones, bass_pc)


# --- degrees and scales -------------------------------------------------------

DEGREE_NAMES = ["R", "b2", "2", "b3", "3", "4", "b5", "5", "b6", "6", "b7", "7"]


def degree_name(pc: int, root_pc: int) -> str:
    return DEGREE_NAMES[(pc - root_pc) % 12]


def major_scale_pcs(key: str) -> frozenset[int]:
    root = parse_note_name(key)
    return frozenset((root + iv) % 12 for iv in (0, 2, 4, 5, 7, 9, 11))


def major_pentatonic_pcs(key: str) -> frozenset[int]:
    """Major pentatonic of the key == minor pentatonic of its relative minor."""
    root = parse_note_name(key)
    return frozenset((root + iv) % 12 for iv in (0, 2, 4, 7, 9))

"""Deterministic vocabulary analysis: degrees and rule-based tags per note.

No AI here. Every tag is computed from note/chord/key facts and the record
itself is the evidence (which chord, which degree, which neighbour note).
AI later turns these facts into memorable prose; humans can override both.
"""

from __future__ import annotations

from typing import NamedTuple

from . import theory
from .domain import ChordEvent, NoteEvent, Song
from .theory import Chord

# Tag vocabulary (Japanese labels used directly in output):
#   ルート / 3度 / 5度 / 7度 など: コードトーン (度数から導出)
#   指定ベース音: スラッシュコードのベース音そのもの
#   ペンタ: キーのメジャーペンタトニック (=平行短調のマイナーペンタ) 構成音
#   スケール外: キーのダイアトニックスケールに含まれない
#   半音アプローチ: 次の音へ半音で接続し、次の音がそのコードのコードトーン
#   先取り: 次のコードのルートを小節をまたぐ前に鳴らす
#   経過音: 非コードトーンで、前後を同方向のステップでつなぐ
#   オクターブ: 直前の音とオクターブ関係
#   ゴースト: ピッチのないゴーストノート


class NoteAnalysis(NamedTuple):
    event: NoteEvent
    beat: float
    chord: Chord | None
    name: str  # key-aware spelling, e.g. "Cb"
    degree: str | None  # vs current chord root, e.g. "R", "b7"
    is_chord_tone: bool
    tags: list[str]


def chords_by_bar(chords: list[ChordEvent], lo: int, hi: int) -> dict[int, str]:
    """Chord label per bar, carrying the last chord forward through gaps."""
    labels: dict[int, str] = {}
    current = ""
    for bar in range(1, hi + 1):
        in_bar = sorted((c for c in chords if c.bar == bar), key=lambda c: c.beat)
        if in_bar:
            if in_bar[0].beat > 1.0 and current:
                in_bar.insert(0, ChordEvent(bar=bar, beat=1.0, chord=current))
            current = in_bar[-1].chord
            labels[bar] = "  ".join(
                c.chord if c.beat == 1.0 else f"({c.beat:g}) {c.chord}" for c in in_bar
            )
        else:
            labels[bar] = current
    return {bar: label for bar, label in labels.items() if lo <= bar <= hi}


def chord_at(chords: list, bar: int, beat: float) -> Chord | None:
    """Active chord at a position (chord events carry forward)."""
    best = None
    for c in chords:
        if (c.bar, c.beat) <= (bar, beat):
            if best is None or (c.bar, c.beat) >= (best.bar, best.beat):
                best = c
    return theory.parse_chord(best.chord) if best else None


_CT_LABELS = {
    "R": "ルート",
    "b3": "3度(m)",
    "3": "3度",
    "5": "5度",
    "b7": "7度(b7)",
    "7": "7度(M7)",
    "6": "6度",
    "2": "9th",
    "4": "4度",
    "b5": "b5",
}


def analyze(song: Song, events: list[NoteEvent]) -> list[NoteAnalysis]:
    key = song.key
    scale_pcs = theory.major_scale_pcs(key) if key else frozenset()
    penta_pcs = theory.major_pentatonic_pcs(key) if key else frozenset()

    pitched = [e for e in events if not e.ghost]
    results: list[NoteAnalysis] = []
    j = 0  # index of the current event within `pitched`

    for e in events:
        beat = e.step / 4 + 1
        chord = chord_at(song.chords, e.bar, beat)
        if e.ghost:
            results.append(NoteAnalysis(e, beat, chord, "x", None, False, ["ゴースト"]))
            continue

        pitch = theory.pitch_at(e.string, e.fret)
        pc = pitch.midi % 12
        name = theory.spell_pc(pc, key, song.notation)
        prev = pitched[j - 1] if j > 0 else None
        nxt = pitched[j + 1] if j + 1 < len(pitched) else None
        j += 1

        degree = theory.degree_name(pc, chord.root_pc) if chord else None
        is_ct = bool(chord) and pc in chord.tone_pcs
        tags: list[str] = []

        if is_ct:
            tags.append(_CT_LABELS.get(degree, degree))
        if chord and chord.bass_pc is not None and pc == chord.bass_pc:
            tags.append("指定ベース音")

        def midi_of(ev: NoteEvent) -> int:
            return theory.pitch_at(ev.string, ev.fret).midi

        if prev is not None and abs(midi_of(prev) - pitch.midi) == 12:
            tags.append("オクターブ")

        if nxt is not None:
            nxt_beat = nxt.step / 4 + 1
            nxt_chord = chord_at(song.chords, nxt.bar, nxt_beat)
            nxt_midi = midi_of(nxt)
            if (
                abs(nxt_midi - pitch.midi) == 1
                and nxt_chord
                and nxt_midi % 12 in nxt_chord.tone_pcs
            ):
                to = theory.spell_pc(nxt_midi % 12, key, song.notation)
                tags.append(f"半音アプローチ→{to}")
            if (
                chord
                and nxt_chord
                and nxt.bar > e.bar
                and nxt_chord.root_pc != chord.root_pc
                and pc == nxt_chord.root_pc
                and not is_ct
            ):
                tags.append(f"先取り→{nxt_chord.symbol}")

        if (
            not is_ct
            and chord
            and prev is not None
            and nxt is not None
        ):
            pm, nm = midi_of(prev), midi_of(nxt)
            up = pm < pitch.midi < nm
            down = pm > pitch.midi > nm
            if (up or down) and abs(pitch.midi - pm) <= 2 and abs(nm - pitch.midi) <= 2:
                tags.append("経過音")

        if key:
            if pc in penta_pcs:
                tags.append("ペンタ")
            elif pc not in scale_pcs:
                tags.append("スケール外")

        for a in e.articulations:
            tags.append(
                {"slide_in": "スライド", "hammer": "ハンマリング",
                 "pull": "プリング", "fall": "フォール"}[a]
            )

        results.append(NoteAnalysis(e, beat, chord, name, degree, is_ct, tags))
    return results


def bar_category(analyses: list[NoteAnalysis]) -> str:
    """How much understanding compresses this bar: ルートのみ / コードトーン /
    語彙内 (ペンタ・経過音・アプローチで説明可能) / 要注意 (説明できない音あり)."""
    pitched = [a for a in analyses if a.degree is not None]
    if not pitched:
        return "休み"
    if all(a.degree == "R" for a in pitched):
        return "ルートのみ"
    if all(a.is_chord_tone for a in pitched):
        return "コードトーン"

    def explained(a: NoteAnalysis) -> bool:
        return (
            a.is_chord_tone
            or "指定ベース音" in a.tags
            or "ペンタ" in a.tags
            or "経過音" in a.tags
            or any(t.startswith(("半音アプローチ", "先取り")) for t in a.tags)
        )

    if all(explained(a) for a in pitched):
        return "語彙内"
    return "要注意"


def position_label(step: int) -> str:
    return f"{step // 4 + 1}{['', 'e', '&', 'a'][step % 4]}"


def _degree_token(a: NoteAnalysis, ref_midi: int | None) -> str:
    if a.event.ghost:
        base = "x"
    else:
        base = a.degree or "?"
        midi = theory.pitch_at(a.event.string, a.event.fret).midi
        if ref_midi is not None:
            if midi < ref_midi:
                base += "↓"
            elif midi - ref_midi >= 12:
                base += "↑"
    for art in a.event.articulations:
        base = {"slide_in": "/" + base, "hammer": "h" + base,
                "pull": "p" + base, "fall": base + "\\"}[art]
    if a.event.tied:
        base = f"({base})"
    return base


def bar_degree_line(analyses: list[NoteAnalysis]) -> str:
    """Playable degree sequence for one bar — the reconstruction layer.

    Straight-8th bars render as 8 slots (`.` = rest, `-` = still ringing):
    e.g. "R R . R R . R R". Bars with 16th placements fall back to
    position-labelled tokens: "1:R 1a:R 2&:R 3e:R".
    Direction marks are relative to the bar's first root: ↓ below, ↑ octave up.
    """
    if not analyses:
        return ""
    ref = next(
        (
            theory.pitch_at(a.event.string, a.event.fret).midi
            for a in analyses
            if a.degree == "R" and not a.event.ghost
        ),
        None,
    )
    if all(a.event.step % 2 == 0 for a in analyses):
        slots = ["."] * 8
        for a in analyses:
            start = a.event.step // 2
            slots[start] = _degree_token(a, ref)
            span_end = min((a.event.step + a.event.duration + 1) // 2, 8)
            for i in range(start + 1, span_end):
                slots[i] = "-"
        return " ".join(slots)
    return " ".join(
        f"{position_label(a.event.step)}:{_degree_token(a, ref)}" for a in analyses
    )


def bar_summary(analyses: list[NoteAnalysis]) -> str:
    """One compact line of what the bar is doing, from tag statistics."""
    pitched = [a for a in analyses if a.degree is not None]
    if not pitched:
        return "ゴーストのみ" if analyses else "休み"
    parts: list[str] = []
    roots = sum(1 for a in pitched if a.degree == "R")
    if roots == len(pitched):
        parts.append(f"ルート弾き×{roots}")
    elif roots:
        others = sorted({a.degree for a in pitched if a.degree != "R"})
        parts.append(f"ルート中心 (+{'/'.join(others)})")
    else:
        degrees = sorted({a.degree for a in pitched})
        parts.append("/".join(degrees))
    for a in pitched:
        for t in a.tags:
            if t.startswith(("半音アプローチ", "先取り")) or t in ("オクターブ", "経過音"):
                parts.append(t)
    return "、".join(dict.fromkeys(parts))

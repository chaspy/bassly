"""Level-2 sheet renderer — the sheet you actually practice from.

Combines deterministic facts (chords, bar summaries, risk categories) with
human/AI phrase interpretations (analysis/phrases.yaml) into one Markdown
document: 記憶の一文、暗記分類、危険箇所。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from . import analysis, theory
from .domain import NoteEvent, Phrase, Song

_BADGES = {
    "完全暗記": "🔴 完全暗記",
    "パターン暗記": "🟡 パターン暗記",
    "理論から再構成": "🟢 理論から再構成",
    "即興可": "🔵 即興可",
}


def load_phrases(song_dir: Path) -> list[Phrase]:
    path = song_dir / "analysis" / "phrases.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [Phrase.model_validate(p) for p in data.get("phrases", [])]


def _time(bar: int, song: Song) -> str:
    beats = int(song.time_signature.split("/")[0])
    sec = (bar - 1) * beats * 60 / song.bpm
    return f"{int(sec // 60)}:{int(sec % 60):02d}"


def render(song: Song, events: list[NoteEvent], phrases: list[Phrase]) -> str:
    if not phrases:
        return "(no phrases: analysis/phrases.yaml がありません)"
    lo = min(p.start_bar for p in phrases)
    hi = max(p.end_bar for p in phrases)
    in_range = [e for e in events if lo <= e.bar <= hi]
    results = analysis.analyze(song, in_range)
    by_bar: dict[int, list] = {}
    for a in results:
        by_bar.setdefault(a.event.bar, []).append(a)
    chord_labels = analysis.chords_by_bar(song.chords, lo, hi)

    lines = [
        f"# {song.title} — レベル2譜面",
        "",
        f"{song.artist} / キー {song.key or '?'} / ♩={song.bpm:g} / {song.tuning}",
        "",
        "凡例: 🟢 コード表から再構成できる / 🟡 形で覚える / 🔴 ここだけは丸暗記",
        "音単位の根拠が必要な時だけ `bassly analyze --bars X-Y` を見る。",
        "",
    ]
    section = None
    for p in sorted(phrases, key=lambda p: p.start_bar):
        if p.section != section:
            section = p.section
            first = min(q.start_bar for q in phrases if q.section == section)
            last = max(q.end_bar for q in phrases if q.section == section)
            lines += [
                f"## {section}  ({first}–{last}小節 / {_time(first, song)}–)",
                "",
            ]
        respell = lambda t: theory.respell_text(t, song.key, song.notation)  # noqa: E731
        role = f"「{respell(p.role)}」 " if p.role else ""
        lines.append(
            f"### {p.start_bar}–{p.end_bar}小節 {role}— {_BADGES[p.memorization]}"
        )
        lines.append("")
        lines.append(f"**{respell(p.summary)}**")
        lines.append("")
        chord_row = " | ".join(
            chord_labels.get(bar, "") for bar in range(p.start_bar, p.end_bar + 1)
        )
        lines.append(f"`| {chord_row} |`")
        notable = " / ".join(
            dict.fromkeys(
                f"{a.event.bar}: {t}"
                for bar in range(p.start_bar, p.end_bar + 1)
                for a in by_bar.get(bar, [])
                for t in a.tags
                if t.startswith(("半音アプローチ", "先取り"))
            )
        )
        if notable:
            lines.append(f"- 🎯 {notable}")
        warn_bars = [
            str(b)
            for b in range(p.start_bar, p.end_bar + 1)
            if by_bar.get(b) and analysis.bar_category(by_bar[b]) == "要注意"
        ]
        if p.notes:
            lines.append(f"- 📝 {respell(p.notes)}")
        if warn_bars:
            lines.append(
                f"- ⚠ {','.join(warn_bars)}小節にスケール外/未分類の音 — "
                f"`bassly analyze --bars {p.start_bar}-{p.end_bar}` で根拠を確認"
            )
        lines.append("")
    return "\n".join(lines)

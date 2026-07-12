"""Bassly CLI."""

from __future__ import annotations

from pathlib import Path

import typer
import yaml

from . import analysis, practice as practicemod, sheet as sheetmod, tabtext, theory
from .domain import NoteEvent, Song, UserProfile

app = typer.Typer(help="Bassly — translate bass TABs into musical vocabulary.")


@app.callback()
def main() -> None:
    """Bassly — translate bass TABs into musical vocabulary."""

# Duration labels for common note values, keyed by length in 16th steps.
_DURATION_LABELS = {
    1: "16th",
    2: "8th",
    3: "8th.",
    4: "4th",
    6: "4th.",
    8: "half",
    12: "half.",
    16: "whole",
}

_SUBDIVISION = ["", "e", "&", "a"]  # 16th positions within a beat: 1 1e 1& 1a


def load_user(song_dir: Path) -> UserProfile:
    """user.yaml を song_dir から上位へ探す (通常は data/user.yaml)。"""
    for base in (song_dir, song_dir.parent, song_dir.parent.parent):
        path = base / "user.yaml"
        if path.is_file():
            return UserProfile.model_validate(
                yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            )
    return UserProfile()


def load_song(song_dir: Path) -> Song:
    raw = yaml.safe_load((song_dir / "song.yaml").read_text(encoding="utf-8"))
    song = Song.model_validate(raw)
    if "notation" not in raw:  # 曲側で明示されない限りユーザープロファイルに従う
        song.notation = load_user(song_dir).notation
    if song.notation != "flat":
        for c in song.chords:
            c.chord = theory.respell_chord(c.chord, song.key, song.notation)
    return song


def load_events(song_dir: Path) -> list[NoteEvent]:
    return tabtext.parse((song_dir / "tab.txt").read_text(encoding="utf-8"))


def _parse_bar_range(bars: str | None) -> tuple[int, int]:
    if not bars:
        return (1, 10**6)
    lo, _, hi = bars.partition("-")
    return (int(lo), int(hi or lo))


_chords_by_bar = analysis.chords_by_bar


def _position_label(step: int) -> str:
    return f"{step // 4 + 1}{_SUBDIVISION[step % 4]}"


@app.command()
def show(
    song_dir: Path = typer.Argument(help="Song directory containing song.yaml and tab.txt"),
    bars: str = typer.Option(None, help="Bar range to show, e.g. 5-12"),
) -> None:
    """Show the parsed TAB with note names and chords."""
    song = load_song(song_dir)
    lo, hi = _parse_bar_range(bars)
    events = [e for e in load_events(song_dir) if lo <= e.bar <= hi]
    if not events:
        typer.echo(f"no notes in bars {bars or 'all'}")
        raise typer.Exit(1)

    hi = min(hi, max(e.bar for e in events))
    chord_labels = _chords_by_bar(song.chords, lo, hi)

    typer.echo(
        f"{song.title} — {song.artist}  "
        f"(♩={song.bpm:g}, {song.time_signature}, tuning {song.tuning}, key {song.key or '?'})"
    )
    for bar in range(lo, hi + 1):
        bar_events = [e for e in events if e.bar == bar]
        typer.echo(f"\nbar {bar}  [{chord_labels.get(bar, '')}]")
        if not bar_events:
            typer.echo("  (rest)")
            continue
        names = []
        for e in bar_events:
            pos = _position_label(e.step)
            dur = _DURATION_LABELS.get(e.duration, f"{e.duration}/16")
            if e.ghost:
                fret, name = "x", "(ghost)"
            else:
                pitch = theory.pitch_at(e.string, e.fret)
                fret, name = str(e.fret), f"{pitch.name}{pitch.octave}"
                names.append(pitch.name)
            marks = ",".join(e.articulations)
            extras = " ".join(filter(None, ["tie" if e.tied else "", marks]))
            typer.echo(
                f"  {pos:<3} {e.string}{fret:<3} {name:<8} {dur:<5} {extras}".rstrip()
            )
        if names:
            typer.echo(f"  » {' '.join(names)}")


@app.command()
def analyze(
    song_dir: Path = typer.Argument(help="Song directory containing song.yaml and tab.txt"),
    bars: str = typer.Option(None, help="Bar range to analyze, e.g. 5-12"),
) -> None:
    """Degrees and vocabulary tags per note (deterministic, no AI)."""
    song = load_song(song_dir)
    lo, hi = _parse_bar_range(bars)
    events = [e for e in load_events(song_dir) if lo <= e.bar <= hi]
    if not events:
        typer.echo(f"no notes in bars {bars or 'all'}")
        raise typer.Exit(1)
    hi = min(hi, max(e.bar for e in events))
    chord_labels = _chords_by_bar(song.chords, lo, hi)
    results = analysis.analyze(song, events)

    typer.echo(
        f"{song.title} — {song.artist}  (key {song.key or '?'}, ♩={song.bpm:g})"
    )
    for bar in range(lo, hi + 1):
        rows = [a for a in results if a.event.bar == bar]
        typer.echo(f"\nbar {bar}  [{chord_labels.get(bar, '')}]")
        if not rows:
            typer.echo("  (rest)")
            continue
        for a in rows:
            e = a.event
            pos = _position_label(e.step)
            if e.ghost:
                place, note = f"{e.string}x", "x"
            else:
                pitch = theory.pitch_at(e.string, e.fret)
                place, note = f"{e.string}{e.fret}", f"{a.name}{pitch.octave}"
            typer.echo(
                f"  {pos:<3} {place:<4} {note:<5} {a.degree or '-':<3} "
                f"{' '.join(a.tags)}".rstrip()
            )
        typer.echo(f"  » {analysis.bar_summary(rows)}")


@app.command()
def sheet(
    song_dir: Path = typer.Argument(help="Song directory containing song.yaml and tab.txt"),
    out: Path = typer.Option(None, help="出力先 (default: <song_dir>/output/level2.md)"),
) -> None:
    """レベル2譜面 (記憶の一文 + 暗記分類 + 危険箇所) を Markdown で生成."""
    song = load_song(song_dir)
    events = load_events(song_dir)
    phrases = sheetmod.load_phrases(song_dir)
    md = sheetmod.render(song, events, phrases)
    out = out or song_dir / "output" / "level2.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    typer.echo(md)
    typer.echo(f"→ {out}")


@app.command()
def practice(
    song_dir: Path = typer.Argument(help="Song directory containing song.yaml and tab.txt"),
    out: Path = typer.Option(None, help="出力先 (default: <song_dir>/output/practice.html)"),
) -> None:
    """フレーズ練習用ページ (ループ再生 + レベル2表示) を HTML で生成."""
    song = load_song(song_dir)
    events = load_events(song_dir)
    phrases = sheetmod.load_phrases(song_dir)
    stems = practicemod.stems_in(song_dir)
    if not stems:
        typer.echo("audio/ にステムが見つかりません", err=True)
    payload = practicemod.build_payload(
        song, events, phrases, stems, user=load_user(song_dir)
    )
    html = practicemod.render(payload)
    out = out or song_dir / "output" / "practice.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    typer.echo(f"→ {out}")


_TAB_STRINGS = ["G", "D", "A", "E", "B"]  # display order, top to bottom
_CELL = 3  # characters per 16th-note column


def _tab_cell(e: NoteEvent) -> str:
    if e.ghost:
        body = "x"
    elif e.tied:
        body = f"({e.fret})"
    else:
        body = str(e.fret)
        if "slide_in" in e.articulations:
            body = "/" + body
        if "hammer" in e.articulations:
            body = "h" + body
        if "pull" in e.articulations:
            body = "p" + body
        if "fall" in e.articulations:
            body = body + "\\"
    return body.ljust(_CELL, "-")[:_CELL]


@app.command()
def tab(
    song_dir: Path = typer.Argument(help="Song directory containing song.yaml and tab.txt"),
    bars: str = typer.Option(None, help="Bar range to show, e.g. 5-12"),
    per_row: int = typer.Option(2, help="Bars per row"),
) -> None:
    """Render the parsed TAB as ASCII tablature (level-1 view / verification)."""
    song = load_song(song_dir)
    lo, hi = _parse_bar_range(bars)
    events = [e for e in load_events(song_dir) if lo <= e.bar <= hi]
    if not events:
        typer.echo(f"no notes in bars {bars or 'all'}")
        raise typer.Exit(1)
    hi = min(hi, max(e.bar for e in events))
    chord_labels = _chords_by_bar(song.chords, lo, hi)

    beat_ruler = "".join(
        ("&" if i % 4 == 2 else str(i // 4 + 1) if i % 4 == 0 else "·").ljust(_CELL)
        for i in range(tabtext.GRID)
    )
    for row_start in range(lo, hi + 1, per_row):
        row_bars = [b for b in range(row_start, row_start + per_row) if b <= hi]
        header = " " + " ".join(
            f"bar {b} [{chord_labels.get(b, '')}]".ljust(tabtext.GRID * _CELL + 1)[:-1]
            for b in row_bars
        )
        typer.echo(header.rstrip())
        typer.echo("  " + ("" .join(beat_ruler) + " ") * len(row_bars))
        for s in _TAB_STRINGS:
            cells = {}
            for e in events:
                if e.bar in row_bars and e.string == s:
                    cells[(e.bar, e.step)] = _tab_cell(e)
            line = s + "|"
            for b in row_bars:
                for i in range(tabtext.GRID):
                    line += cells.get((b, i), "-" * _CELL)
                line += "|"
            typer.echo(line)
        typer.echo("")


if __name__ == "__main__":
    app()

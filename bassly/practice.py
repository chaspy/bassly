"""Practice page generator — the dogfooding loop UX.

聴く → 解釈(レベル2)を見る → 弾く → ループ/スロー再生 → 質問はチャットへ。
Self-contained local HTML, no server. Audio stems are referenced relatively
(../audio/*.m4a) and all play simultaneously; enabling/disabling a stem just
mutes it, so the stems never drift out of sync. playbackRate keeps pitch.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import analysis, theory
from .domain import NoteEvent, Phrase, Song, UserProfile

STEM_LABELS = {
    "bass": "ベース",
    "drums": "ドラム",
    "vocals": "ボーカル",
    "lead": "リード",
    "rhythm": "リズムG",
    "other": "その他",
    "metronome": "メトロノーム",
}

_BADGES = {
    "完全暗記": "🔴",
    "パターン暗記": "🟡",
    "理論から再構成": "🟢",
    "即興可": "🔵",
}

# ベース練習用の初期状態: ベースは全開、歌とドラムはガイド程度、他はオフ
STEM_DEFAULTS = {  # name -> (on, volume)
    "bass": (True, 1.0),
    "vocals": (True, 0.1),
    "drums": (True, 0.1),
}

# 語彙タグ → レッスン。曲の解釈にその語彙が出てきた時だけ 📚 が表示される
# (教則本のように順番に読ませない = just-in-time learning)。
_CT_TAGS = set(analysis._CT_LABELS.values())


def _lesson_for_tag(tag: str) -> str | None:
    if tag in _CT_TAGS:
        return "chord-tones"
    if tag == "ペンタ":
        return "pentatonic"
    if tag == "指定ベース音":
        return "slash-chords"
    if tag == "オクターブ":
        return "octaves"
    if tag in ("経過音", "スケール外") or tag.startswith(("半音アプローチ", "先取り")):
        return "chromatic-approach"
    return None


# レッスン相互リンク (Scrapbox風): 本文中にこの別名が現れたらリンク化する
LESSON_ALIASES = {
    "degrees": ["度数"],
    "chord-tones": ["コードトーン", "トライアド", "アルペジオ"],
    "pentatonic": [
        "メジャーペンタトニック", "マイナーペンタトニック",
        "ペンタトニック", "メジャーペンタ", "マイナーペンタ", "ペンタ",
    ],
    "chromatic-approach": ["半音アプローチ", "先取り", "経過音", "アンティシペーション"],
    "slash-chords": ["分数コード", "スラッシュコード", "オンコード"],
    "octaves": ["オクターブ"],
    "fourths-tuning": ["4度チューニング"],
    "pedal": ["ペダルポイント", "ペダル"],
}

# just-in-case 派 (順番に学びたい人) 向けの推奨パス。UIの主役は just-in-time の
# 📚 チップのままで、一覧は控えめな入口から開く
LESSON_ORDER = [
    "degrees",
    "fourths-tuning",
    "chord-tones",
    "octaves",
    "pentatonic",
    "chromatic-approach",
    "slash-chords",
    "pedal",
]


def load_strategy(song_dir: Path) -> dict | None:
    """コーチの作戦 (analysis/strategy.yaml)。ユーザーが自由に編集できる。"""
    import yaml

    path = song_dir / "analysis" / "strategy.yaml"
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8")) or None


def load_lessons() -> dict[str, dict]:
    lessons_dir = Path(__file__).resolve().parent.parent / "lessons"
    lessons: dict[str, dict] = {}
    if not lessons_dir.is_dir():
        return lessons
    for path in sorted(lessons_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        first, _, body = text.partition("\n")
        lessons[path.stem] = {
            "title": first.lstrip("# ").strip(),
            "body": body.strip(),
        }
    return lessons


def build_fretboard(
    key: str | None, style: str = "flat", frets: int = 16
) -> dict | None:
    """Key-scale map of the 5-string fretboard — instrument-side scaffolding.

    All chromatic positions are included; non-scale cells are hidden by the
    UI unless a phrase or the current chord actually uses them.
    """
    if not key:
        return None
    scale = theory.major_scale_pcs(key)
    penta = theory.major_pentatonic_pcs(key)
    root = theory.parse_note_name(key)
    rows = []
    for s in ["G", "D", "A", "E", "B"]:  # display order, top to bottom like TAB
        cells = []
        for f in range(frets + 1):
            pc = (theory.OPEN_STRING_MIDI[s] + f) % 12
            cells.append(
                {
                    "fret": f,
                    "pc": pc,
                    "pos": f"{s}{f}",
                    "name": theory.spell_pc(pc, key, style),
                    "root": pc == root,
                    "penta": pc in penta,
                    "scale": pc in scale,
                }
            )
        rows.append({"string": s, "cells": cells})
    key_label = theory.spell_pc(root, key, style)
    alias = None
    if key_label != key:
        alias = key
    elif "b" in key:
        alias = theory.SHARP_NAMES[root]
    return {
        "key": key_label,
        "alias": alias,
        "root_pc": root,
        "frets": frets,
        "rows": rows,
    }


def build_payload(
    song: Song,
    events: list[NoteEvent],
    phrases: list[Phrase],
    stems: list[str],
    user: UserProfile | None = None,
    strategy: dict | None = None,
) -> dict:
    user = user or UserProfile()
    results = analysis.analyze(song, events)
    by_bar: dict[int, list] = {}
    for a in results:
        by_bar.setdefault(a.event.bar, []).append(a)
    max_bar = max(by_bar) if by_bar else 1
    chord_labels = analysis.chords_by_bar(song.chords, 1, max_bar)

    lessons = load_lessons()
    phrase_dicts = []
    for p in sorted(phrases, key=lambda p: p.start_bar):
        bars = []
        slugs: list[str] = []
        positions: dict[str, list[str]] = {}  # "E2" -> degrees used there
        notes = []  # ピアノロール用: フレーズ頭からの16分位置と音高
        chords16 = [  # ピアノロールのコードレーン
            {
                "t": (c.bar - p.start_bar) * 16 + int((c.beat - 1) * 4),
                "label": c.chord,
            }
            for c in song.chords
            if p.start_bar <= c.bar <= p.end_bar
        ]
        for bar in range(p.start_bar, p.end_bar + 1):
            rows = by_bar.get(bar, [])
            for a in rows:
                for t in a.tags:
                    slug = _lesson_for_tag(t)
                    if slug and slug in lessons and slug not in slugs:
                        slugs.append(slug)
                t16 = (bar - p.start_bar) * 16 + a.event.step
                if a.event.ghost:
                    notes.append({"t": t16, "d": a.event.duration, "midi": None,
                                  "deg": "x", "cls": "ghost"})
                    continue
                midi = theory.pitch_at(a.event.string, a.event.fret).midi
                if a.is_chord_tone:
                    cls = "ct"
                elif "スケール外" in a.tags or any(
                    t.startswith("半音アプローチ") for t in a.tags
                ):
                    cls = "out"
                else:
                    cls = "oth"
                notes.append({
                    "t": t16, "d": a.event.duration, "midi": midi,
                    "deg": a.degree, "cls": cls,
                    "pos": f"{a.event.string}{a.event.fret}",
                })
                if a.degree is not None:
                    pos = f"{a.event.string}{a.event.fret}"
                    degs = positions.setdefault(pos, [])
                    if a.degree not in degs:
                        degs.append(a.degree)
            bars.append(
                {
                    "bar": bar,
                    "chord": chord_labels.get(bar, ""),
                    "line": analysis.bar_degree_line(rows) if rows else "(休み)",
                    "warn": bool(rows) and analysis.bar_category(rows) == "要注意",
                }
            )
        respell = lambda t: theory.respell_text(t, song.key, song.notation)  # noqa: E731
        phrase_dicts.append(
            {
                "start": p.start_bar,
                "end": p.end_bar,
                "section": p.section,
                "role": respell(p.role),
                "summary": respell(p.summary),
                "notes": respell(p.notes),
                "badge": _BADGES[p.memorization],
                "memorization": p.memorization,
                "bars": bars,
                "lessons": slugs,
                "positions": [
                    {"pos": pos, "deg": "/".join(degs)}
                    for pos, degs in positions.items()
                ],
                "roll": notes,  # ピアノロール用 (キー "notes" は📝メモで使用済み)
                "chords16": chords16,
            }
        )
    respell = lambda t: theory.respell_text(t, song.key, song.notation)  # noqa: E731
    if strategy:
        strategy = dict(strategy)
        strategy["characteristics"] = [
            respell(c) for c in strategy.get("characteristics", [])
        ]
        for s in strategy.get("steps", []):
            s["name"] = respell(s.get("name", ""))
            s["how"] = respell(s.get("how", ""))
        strategy["principles"] = [respell(p) for p in strategy.get("principles", [])]

    # 作戦ブロックに添えるデータ由来の事実
    cats = {"ルートのみ": 0, "コードトーン": 0, "語彙内": 0, "要注意": 0}
    for rows in by_bar.values():
        c = analysis.bar_category(rows)
        if c in cats:
            cats[c] += 1
    stats = {
        "bars": len(by_bar),
        "cats": cats,
        "red": [
            f"{p['start']}–{p['end']}"
            for p in phrase_dicts
            if p["memorization"] == "完全暗記"
        ],
    }

    # 情報圧縮: 同型フレーズの自動検出。「≒13–20と同型 (違い: 54小節)」なら
    # 差分だけ覚えればいい。曲中の全小節窓と照合し、小節同士はトークン単位の
    # あいまい一致 (方向マーク無視、70%以上一致で「同じ小節」とみなす)。
    def bar_tokens(bar: int) -> list[str]:
        rows = by_bar.get(bar, [])
        line = analysis.bar_degree_line(rows) if rows else ""
        return line.replace("↓", "").replace("↑", "").split()

    def bars_alike(a: int, b: int) -> bool | None:
        ta, tb = bar_tokens(a), bar_tokens(b)
        if not ta and not tb:
            return None  # 両方休み: 判定対象外
        n = max(len(ta), len(tb))
        same = sum(1 for k in range(n)
                   if k < len(ta) and k < len(tb) and ta[k] == tb[k])
        return same / n >= 0.7

    for pd in phrase_dicts:
        length = pd["end"] - pd["start"]
        best = None
        for w in range(1, pd["start"] - length):  # 完全に手前の窓のみ
            same, total, diffs = 0, 0, []
            for off in range(length + 1):
                alike = bars_alike(pd["start"] + off, w + off)
                if alike is None:
                    continue
                total += 1
                if alike:
                    same += 1
                else:
                    diffs.append(pd["start"] + off)
            if total >= 2 and same / total >= 0.6:
                cand = (same / total, w, diffs)
                if best is None or cand[0] > best[0]:
                    best = cand
        if best:
            ratio, w, diffs = best
            pd["like"] = {
                "ref": f"{w}–{w + length}",
                "ratio": round(ratio, 2),
                "diffs": diffs,
            }

    stats["likes"] = sum(1 for p in phrase_dicts if p.get("like"))

    # ルート通しチャート: 全小節について「実際に踏む音」を1枚に。
    # 分数コードは指定ベース音、拍途中の変化は (拍)音名 で表す。休みも明示
    last_bar = max(
        [max_bar]
        + [s.end_bar for s in song.sections]
        + [c.bar for c in song.chords]
    )
    chart_labels = analysis.chords_by_bar(song.chords, 1, last_bar)
    section_starts = {s.start_bar: s.name for s in song.sections}

    def target_name(symbol: str) -> str | None:
        ch = theory.parse_chord(symbol)
        if ch is None:
            return None
        pc = ch.bass_pc if ch.bass_pc is not None else ch.root_pc
        return theory.spell_pc(pc, song.key, song.notation)

    chart = []
    current_chord: str | None = None
    rest_run = 0
    for bar in range(1, last_bar + 1):
        evs = sorted(
            (c for c in song.chords if c.bar == bar), key=lambda c: c.beat
        )
        if (not evs or evs[0].beat > 1.0) and current_chord:
            evs.insert(0, type(song.chords[0])(bar=bar, beat=1.0, chord=current_chord))
        if evs:
            current_chord = evs[-1].chord
        # 連続する同じ音はまとめる: "B♭" / "C# (4)E♭"
        segments: list[str] = []
        prev = None
        for c in evs:
            name = target_name(c.chord)
            if name is None or name == prev:
                continue
            segments.append(name if c.beat == 1.0 else f"{c.beat:g}拍→{name}")
            prev = name
        rest = bar not in by_bar
        chart.append(
            {
                "bar": bar,
                "label": chart_labels.get(bar, ""),
                "play": " ".join(segments),
                "rest": rest,
                # 2小節以上の休みからの復帰 = 事故ポイントなので目立たせる
                "entry": (not rest) and rest_run >= 2,
                "sec": section_starts.get(bar),
            }
        )
        rest_run = rest_run + 1 if rest else 0

    return {
        "chart": chart,
        "strategy": strategy,
        "stats": stats,
        "title": song.title,
        "artist": song.artist,
        "bpm": song.bpm,
        "beats": int(song.time_signature.split("/")[0]),
        "key": song.key,
        "stems": [
            {
                "file": f"../audio/{s}.m4a",
                "name": s,
                "label": STEM_LABELS.get(s, s),
                "on": (
                    user.stem_defaults[s].on
                    if s in user.stem_defaults
                    else STEM_DEFAULTS.get(s, (False, 1.0))[0]
                ),
                "volume": (
                    user.stem_defaults[s].volume
                    if s in user.stem_defaults
                    else STEM_DEFAULTS.get(s, (False, 1.0))[1]
                ),
            }
            for s in stems
        ],
        "show_fretboard": user.show_fretboard,
        "pcnames": [
            theory.spell_pc(pc, song.key, song.notation) for pc in range(12)
        ],
        "aliases": {
            slug: names for slug, names in LESSON_ALIASES.items() if slug in lessons
        },
        "lesson_order": [s for s in LESSON_ORDER if s in lessons],
        "phrases": phrase_dicts,
        "fretboard": build_fretboard(song.key, song.notation),
        "lessons": lessons,
        # 進行の視覚化用: コードイベントごとにベースが狙う音 (スラッシュの指定
        # ベース音があればそちら) のピッチクラス
        "chords": [
            {
                "bar": c.bar,
                "beat": c.beat,
                "label": c.chord,
                "pc": (
                    (ch.bass_pc if ch.bass_pc is not None else ch.root_pc)
                    if (ch := theory.parse_chord(c.chord)) is not None
                    else None
                ),
            }
            for c in sorted(song.chords, key=lambda c: (c.bar, c.beat))
        ],
    }


def render(payload: dict) -> str:
    return _TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False))


def render_chart(payload: dict) -> str:
    """1枚モノのコードマップ (静的・印刷対応)。スタジオ当日に紙/スマホで見る用。"""
    parts = [
        "<!DOCTYPE html><html lang='ja'><head><meta charset='utf-8'>",
        f"<title>{payload['title']} — コードマップ</title>",
        "<style>",
        "body{font-family:-apple-system,'Hiragino Sans',sans-serif;background:#fff;"
        "color:#111;margin:20px;max-width:900px}",
        "h1{font-size:15px;margin:0 0 2px}",
        ".legend{color:#555;font-size:10.5px;margin:2px 0 12px;line-height:1.5}",
        ".sec{font-weight:bold;font-size:12px;margin:8px 0 3px;border-top:1px solid #ccc;"
        "padding-top:5px}",
        ".grid{display:grid;grid-template-columns:repeat(8,1fr);gap:3px}",
        ".cell{border:1px solid #bbb;border-radius:4px;text-align:center;padding:1px 1px 3px}",
        ".cell i{display:block;font-style:normal;color:#999;font-size:8px}",
        ".cell b{font-size:13px;font-weight:700}",
        ".cell b.long{font-size:9.5px}",
        ".cell.rest{background:#eee}.cell.rest b{color:#aaa}",
        ".cell.entry{border:2px solid #e8871e}",
        "@media print{body{margin:6mm}.cell b{font-size:11px}.sec{font-size:11px}}",
        "</style></head><body>",
        f"<h1>{payload['title']} — ルート通しコードマップ"
        f" (キー {payload.get('key') or '?'} / ♩={payload['bpm']:g})</h1>",
        "<div class='legend'>大きい字 = 踏む音。「B 4拍→Bb」= 1〜3拍はB、4拍目からBb。"
        "小さい字 = 元のコード名 (分数コードは右側を弾く)。灰色 = ベース休み。"
        "<b style='color:#e8871e'>オレンジ枠 = 休み明けの入り (要注意)</b></div>",
    ]
    open_grid = False
    for c in payload["chart"]:
        if c["sec"]:
            if open_grid:
                parts.append("</div>")
            parts.append(f"<div class='sec'>{c['sec']}</div><div class='grid'>")
            open_grid = True
        elif not open_grid:
            parts.append("<div class='grid'>")
            open_grid = True
        play = c["play"] or c["label"] or ""
        long = " class='long'" if len(play) > 5 else ""
        sub = (
            f"<small style='display:block;color:#999;font-size:7.5px'>{c['label']}</small>"
            if c["label"] and c["label"] != play
            else ""
        )
        cls = "cell" + (" rest" if c["rest"] else "") + (" entry" if c["entry"] else "")
        parts.append(
            f"<div class='{cls}'><i>{c['bar']}{' 休' if c['rest'] else ''}</i>"
            f"<b{long}>{play}</b>{sub}</div>"
        )
    if open_grid:
        parts.append("</div>")
    parts.append("</body></html>")
    return "".join(parts)


def stems_in(song_dir: Path) -> list[str]:
    audio = song_dir / "audio"
    if not audio.is_dir():
        return []
    order = list(STEM_LABELS)
    names = [p.stem for p in sorted(audio.glob("*.m4a"))]
    return sorted(names, key=lambda n: order.index(n) if n in order else 99)


_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>Bassly 練習ページ</title>
<style>
  :root { color-scheme: dark; }
  body { background:#111; color:#eee; font-family:-apple-system,'Hiragino Sans',sans-serif;
         margin:0; display:flex; height:100vh; }
  #side { width:270px; overflow-y:auto; border-right:1px solid #333; padding:12px; flex-shrink:0; }
  #main { flex:1; overflow-y:auto; padding:0 28px 40vh; }
  h1 { font-size:15px; margin:4px 0 10px; }
  .sec { color:#8a8; font-size:12px; margin:14px 0 4px; font-weight:bold; }
  .card { padding:7px 10px; border-radius:8px; cursor:pointer; margin:3px 0;
          border:1px solid #333; font-size:12.5px; }
  .card:hover { background:#1e2a1e; }
  .card.active { background:#1d3a26; border-color:#3c8; }
  #transport { position:sticky; top:0; background:#111e; backdrop-filter:blur(4px);
               padding:10px 0 10px; z-index:6; border-bottom:1px solid #333; }
  button { background:#2a2a2a; color:#eee; border:1px solid #444; border-radius:8px;
           padding:7px 14px; font-size:14px; cursor:pointer; }
  button.primary { background:#1d3a26; border-color:#3c8; font-size:17px; padding:7px 24px; }
  .stem { display:inline-block; margin:2px 4px 0 0; padding:3px 9px; border-radius:14px;
          border:1px solid #444; cursor:pointer; font-size:11.5px; user-select:none; }
  .stem.on { background:#1d3a26; border-color:#3c8; }
  #pos { font-variant-numeric:tabular-nums; color:#9c9; margin-left:10px; font-size:13px; }
  #chordnow { color:#fc8; font-size:16px; font-weight:bold; margin-left:10px; }
  #loopinfo { color:#9c9; font-size:12px; margin-left:6px; }
  input[type=range] { vertical-align:middle; }
  .sec2 { color:#8a8; font-weight:bold; margin:30px 0 4px; font-size:16px;
          border-top:1px solid #2a2a2a; padding-top:16px; }
  .phrase { margin:14px 0 24px; padding-left:10px; margin-left:-13px;
            border-left:3px solid transparent; scroll-margin-top:110px; }
  .phrase.active { border-left-color:#3c8; }
  .phead { cursor:pointer; color:#9c9; font-size:14px; margin-bottom:6px; }
  .phead:hover { color:#cfc; }
  .like { color:#fc8; font-size:12px; margin-left:8px; }
  .summary { font-size:15px; line-height:1.7; background:#1a1a1a; border-left:4px solid #3c8;
             padding:10px 14px; border-radius:6px; margin:8px 0; }
  .notes { color:#bba; font-size:12.5px; margin:6px 0; }
  details { margin-top:8px; color:#888; }
  details summary { cursor:pointer; font-size:12px; }
  table { border-collapse:collapse; margin-top:8px; }
  td { padding:4px 12px 4px 0; font-size:13px; vertical-align:top; color:#999; }
  td.line { font-family:ui-monospace,'SF Mono',monospace; letter-spacing:1px; }
  .fb { border-collapse:collapse; margin-top:4px; }
  .fb th { color:#666; font-size:9px; padding:1px 3px; font-weight:normal; }
  .fb th.mark { color:#bbb; font-weight:bold; }
  .fb td { border-left:1px solid #2a2a2a; min-width:30px; height:19px;
           text-align:center; padding:0 1px; }
  .note { display:inline-block; min-width:17px; padding:1px 3px; border-radius:8px;
          font-size:9.5px; color:#8a8; border:1px solid #2a3a2a; }
  .note.penta { color:#cec; border-color:#4a6; }
  .note.root { background:#1d3a26; border-color:#3c8; color:#dfd; font-weight:bold; }
  .note.chord { background:#4a3208; border-color:#fa0; color:#ffd; box-shadow:0 0 6px #fa06; }
  .note.off { visibility:hidden; }
  .note.off.chord, .note.off.phrase { visibility:visible; opacity:.95; }
  .note.phrase { outline:2px solid #6cf; box-shadow:0 0 6px #6cf6; }
  .lchip { display:inline-block; margin:8px 6px 0 0; padding:3px 11px; border-radius:14px;
           border:1px solid #557; color:#aac; cursor:pointer; font-size:12px; user-select:none; }
  .lchip:hover { background:#1e2233; }
  #lessonbox { display:none; position:sticky; top:96px; z-index:3; margin-top:12px;
               background:#161a24; border:1px solid #446; border-radius:8px; padding:14px 18px;
               max-height:55vh; overflow-y:auto; box-shadow:0 8px 30px #000a; }
  #lessonbox h3 { margin:0 0 10px; font-size:15px; color:#aac; }
  #lessonbox pre { white-space:pre-wrap; font-family:inherit; font-size:13.5px;
                   line-height:1.8; color:#ccd; margin:0; }
  #lessonclose { float:right; cursor:pointer; color:#667; }
  .wikilink { color:#8cf; cursor:pointer; border-bottom:1px dotted #468; }
  .backlinks { margin-top:12px; font-size:12px; color:#778; }
  .hint { color:#777; font-size:12px; margin-top:24px; line-height:1.8; }
  #fret { position:fixed; bottom:0; left:294px; right:0; background:#0f0f0fee;
          backdrop-filter:blur(4px); border-top:1px solid #333; margin:0;
          padding:4px 14px 6px; z-index:6; max-height:34vh; overflow:auto; }
  #fret summary { color:#8a8; font-size:11.5px; }
  #fret label { font-size:11px; color:#999; }
  #fret .hint { margin-top:4px; font-size:10.5px; line-height:1.5; }
  #fret .lchip { font-size:10.5px; padding:1px 8px; margin-top:2px; }
  #chart { display:none; position:fixed; top:0; left:294px; right:0; bottom:0;
           background:#101014fa; z-index:5; overflow-y:auto;
           padding:118px 22px 26vh; }
  #chart.on { display:block; }
  #chartclose { float:right; cursor:pointer; color:#667; font-size:14px; padding:4px 10px; }
  .chsec { color:#8a8; font-weight:bold; margin:9px 0 3px; font-size:12.5px; }
  .chgrid { display:grid; grid-template-columns:repeat(8, 1fr); gap:3px; }
  .chcell { border:1px solid #333; border-radius:5px; padding:2px 2px 4px; text-align:center; }
  .chcell i { display:block; font-style:normal; color:#556; font-size:8px; }
  .chcell b { font-size:14px; color:#dde; font-weight:600; }
  .chcell b.long { font-size:10px; }
  .chcell.entry { border-color:#e8871e; border-width:2px; }
  .chcell.rest { opacity:.35; }
  .chcell.now { background:#1d3a26; border-color:#3c8; }
  #strategy { margin:16px 0 4px; }
  #strategy summary { color:#fc8; font-size:14px; cursor:pointer; font-weight:bold; }
  .stbox { background:#141a14; border:1px solid #2a3a2a; border-radius:8px;
           padding:12px 18px; font-size:13.5px; line-height:1.9; margin-top:8px; }
  .stbox ul, .stbox ol { margin:6px 0 14px; padding-left:22px; }
  .stbox li { margin:4px 0; }
</style>
</head>
<body>
<div id="side">
  <h1 id="title"></h1>
  <div style="margin-bottom:6px"><span class="lchip" style="margin-top:0"
    onclick="showLessonIndex()">📚 レッスン一覧（順に学ぶ）</span></div>
  <div id="phraselist"></div>
</div>
<div id="main">
  <div id="transport">
    <button class="primary" id="play">▶</button>
    <button id="full">▶ 頭から通す</button>
    <button id="chartbtn">🗺 ルート通し</button>
    <a href="chart.html" target="_blank" style="text-decoration:none"><button>🖨 印刷用マップ</button></a>
    <label style="margin-left:8px">ループ <input type="checkbox" id="loop" checked></label>
    <span id="loopinfo"></span>
    <label style="margin-left:8px">速度 <input type="range" id="rate" min="40" max="100" value="100" style="width:100px">
      <span id="ratev">100%</span></label>
    <span id="pos"></span><span id="chordnow"></span>
    <div style="margin-top:6px" id="stems"></div>
  </div>
  <div id="lessonbox"><span id="lessonclose" onclick="hideLesson()">✕ 閉じる</span>
    <h3 id="lessontitle"></h3><pre id="lessonbody"></pre>
    <div class="backlinks" id="lessonlinks"></div></div>
  <div id="score"></div>
  <div id="chart"></div>
  <details id="fret">
    <summary id="fretsum">指板マップ</summary>
    <div style="margin-top:2px">
      <label><input type="radio" name="fbmode" value="name"> 音名</label>
      <label><input type="radio" name="fbmode" value="key"> 度数（キー基準）</label>
      <label><input type="radio" name="fbmode" value="chord" checked> 度数（コード追従）</label>
    </div>
    <div id="fretmap"></div>
    <div class="hint" id="frethint"></div>
  </details>
  <div class="hint">
    スペース=再生/停止 ・ ←→=フレーズ移動 ・ フレーズ見出しクリック=そこをループ ・
    ロールクリック=その位置へ ・ ロールをダブルクリック=その段(4小節)だけループ ・
    「頭から通す」=再生に合わせて自動スクロール。<br>
    説明が分からない時はフレーズ番号を添えてチャットへ。一文の修正は analysis/phrases.yaml へ。
  </div>
</div>
<script>
const D = __DATA__;
const spb = 60 / D.bpm * D.beats;
const spb16 = spb / 16;
const barTime = b => (b - 1) * spb;
const fmt = t => `${Math.floor(t/60)}:${String(Math.floor(t%60)).padStart(2,'0')}`;

document.getElementById('title').textContent = `${D.title} — ${D.artist}`;

const audios = D.stems.map(s => {
  const a = new Audio(s.file);
  a.preload = 'auto';
  a.muted = !s.on;
  a.volume = s.volume;
  return a;
});
const clock = audios[0];

const stemsDiv = document.getElementById('stems');
D.stems.forEach((s, i) => {
  const el = document.createElement('span');
  el.className = 'stem' + (s.on ? ' on' : '');
  el.textContent = s.volume < 1 ? `${s.label} ${Math.round(s.volume * 100)}%` : s.label;
  el.onclick = () => { audios[i].muted = !audios[i].muted; el.classList.toggle('on', !audios[i].muted); };
  stemsDiv.appendChild(el);
});

let loopStart = 0, loopEnd = clockDuration();
let current = -1;
let follow = false;  // 通しモード: 再生に合わせて自動スクロール
function clockDuration() { return isFinite(clock.duration) ? clock.duration : 9999; }
function phraseAt(bar) { return D.phrases.findIndex(p => bar >= p.start && bar <= p.end); }

function playing() { return !clock.paused; }
function playAll() { audios.forEach(a => a.play()); document.getElementById('play').textContent = '⏸'; }
function pauseAll() { audios.forEach(a => a.pause()); document.getElementById('play').textContent = '▶'; }

// m4aのシークはフレーム境界にスナップし数十ms手前に着地することがあるため、
// UI更新には意図した時刻を直接渡す。シーク完了までは音声由来の時刻を信用しない
let pendingSeek = null;
function seek(t) {
  pendingSeek = t;
  audios.forEach(a => a.currentTime = t);
  syncUI(t);
}

document.getElementById('play').onclick = () => playing() ? pauseAll() : playAll();
document.getElementById('full').onclick = () => {
  follow = true;
  loopStart = 0;
  loopEnd = clockDuration();
  document.getElementById('loopinfo').textContent = '🔁 通し';
  seek(0);
  playAll();
};
document.getElementById('rate').oninput = e => {
  const r = e.target.value / 100;
  audios.forEach(a => a.playbackRate = r);
  document.getElementById('ratev').textContent = e.target.value + '%';
};

// --- レッスン (Scrapbox風相互リンク) ---------------------------------------
const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const aliasItems = Object.entries(D.aliases || {})
  .flatMap(([slug, names]) => names.map(a => [a, slug]))
  .sort((x, y) => y[0].length - x[0].length);

function linkify(text, selfSlug) {
  let html = esc(text);
  aliasItems.forEach(([a, slug], i) => {
    if (slug === selfSlug) return;
    html = html.split(a).join(`\\u0001${i}\\u0002`);
  });
  aliasItems.forEach(([a, slug], i) => {
    html = html.split(`\\u0001${i}\\u0002`).join(
      `<a class="wikilink" onclick="showLesson('${slug}')">${a}</a>`);
  });
  return html;
}

const backlinks = {};
Object.keys(D.lessons || {}).forEach(slug => {
  backlinks[slug] = Object.entries(D.lessons)
    .filter(([other]) => other !== slug)
    .filter(([, l]) => (D.aliases[slug] || []).some(a => l.body.includes(a)))
    .map(([other]) => other);
});

function showLesson(slug) {
  const l = D.lessons[slug];
  if (!l) return;
  document.getElementById('lessontitle').textContent = '📚 ' + l.title;
  document.getElementById('lessonbody').innerHTML = linkify(l.body, slug);
  const back = backlinks[slug] || [];
  document.getElementById('lessonlinks').innerHTML = back.length
    ? '🔗 このページに触れている: ' + back.map(s =>
        `<a class="wikilink" onclick="showLesson('${s}')">${D.lessons[s].title.split(' — ')[0]}</a>`
      ).join(' ・ ')
    : '';
  document.getElementById('lessonbox').style.display = 'block';
}
function hideLesson() {
  document.getElementById('lessonbox').style.display = 'none';
}
function showLessonIndex() {
  const items = (D.lesson_order || []).map((s, i) => {
    const parts = D.lessons[s].title.split(' — ');
    return `<div style="margin:7px 0">${i + 1}. ` +
      `<a class="wikilink" onclick="showLesson('${s}')">${parts[0]}</a>` +
      (parts[1] ? ` <span style="color:#778">— ${parts[1]}</span>` : '') + '</div>';
  }).join('');
  document.getElementById('lessontitle').textContent = '📚 レッスン一覧 — おすすめの順番';
  document.getElementById('lessonbody').innerHTML =
    '<div style="color:#778;margin-bottom:8px">上から順に読むと積み上がる構成。' +
    'ただし飛ばして必要な時に読んでも成立するように書いてある。</div>' + items;
  document.getElementById('lessonlinks').innerHTML = '';
  document.getElementById('lessonbox').style.display = 'block';
}

// --- ピアノロール (4小節=1段の段組み、全曲縦積み) ---------------------------
const ROLL_CELL = 11, ROLL_SEMI = 9, ROLL_GUT = 36, ROLL_TOP = 30;
const SYS_BARS = 4, SYS_CELLS = SYS_BARS * 16;
function buildRoll(p) {
  const pitched = (p.roll || []).filter(n => n.midi !== null);
  if (!pitched.length) return '';
  const hi = Math.max(...pitched.map(n => n.midi)) + 1;
  const lo = Math.min(...pitched.map(n => n.midi)) - 1;
  const H = (hi - lo + 1) * ROLL_SEMI + ROLL_TOP + 6;
  const rowY = m => (hi - m) * ROLL_SEMI + ROLL_TOP;
  const colors = {ct: '#2a9d6a', oth: '#4a6fa5', out: '#c77d1a'};
  const used = new Set(pitched.map(n => n.midi));  // 実際に踏む音のレーン
  const nSys = Math.ceil((p.end - p.start + 1) / SYS_BARS);
  let out = '';
  for (let sys = 0; sys < nSys; sys++) {
    const cell0 = sys * SYS_CELLS;
    const t0cell = (p.start - 1 + sys * SYS_BARS) * 16;  // 曲頭からの絶対16分位置
    const barsHere = Math.min(SYS_BARS, p.end - p.start + 1 - sys * SYS_BARS);
    const cells = barsHere * 16;
    const W = ROLL_GUT + cells * ROLL_CELL;
    let s = `<svg class="rollsvg" data-t0cell="${t0cell}" data-cells="${cells}" width="${W}" height="${H}" style="display:block;margin-bottom:4px;background:#0d0d12;border:1px solid #223;border-radius:8px;cursor:pointer">`;
    for (let m = lo; m <= hi; m++) {
      const name = D.pcnames[((m % 12) + 12) % 12];
      if (used.has(m))
        s += `<rect x="${ROLL_GUT}" y="${rowY(m)}" width="${W-ROLL_GUT}" height="${ROLL_SEMI}" fill="#1b2334"/>`;
      s += `<text x="${ROLL_GUT-4}" y="${rowY(m)+ROLL_SEMI-2}" fill="${used.has(m) ? '#9ac' : '#445'}" font-size="8" text-anchor="end">${name}${Math.floor(m/12)-1}</text>`;
      s += `<line x1="${ROLL_GUT}" y1="${rowY(m)+ROLL_SEMI}" x2="${W}" y2="${rowY(m)+ROLL_SEMI}" stroke="#14141c"/>`;
    }
    for (let c = 0; c <= cells; c += 4) {
      const major = c % 16 === 0;
      const x = ROLL_GUT + c * ROLL_CELL;
      s += `<line x1="${x}" y1="0" x2="${x}" y2="${H}" stroke="${major ? '#334' : '#1a1f2a'}"/>`;
      if (major && c < cells)
        s += `<text x="${x+3}" y="11" fill="#667" font-size="10">${p.start + sys*SYS_BARS + c/16}</text>`;
    }
    (p.chords16 || []).filter(c => c.t >= cell0 && c.t < cell0 + cells).forEach(c => {
      s += `<text x="${ROLL_GUT + (c.t-cell0)*ROLL_CELL + 3}" y="${ROLL_TOP-6}" fill="#fc8" font-size="11" font-weight="bold">${c.label}</text>`;
    });
    p.roll.filter(n => n.t >= cell0 && n.t < cell0 + cells).forEach(n => {
      const x = ROLL_GUT + (n.t - cell0) * ROLL_CELL;
      if (n.midi === null) {
        s += `<text x="${x+2}" y="${H-5}" fill="#667" font-size="10">x</text>`;
        return;
      }
      const y = rowY(n.midi);
      const w = Math.max(n.d * ROLL_CELL - 2, ROLL_CELL - 3);
      s += `<rect x="${x}" y="${y}" width="${w}" height="${ROLL_SEMI-1}" rx="3" fill="${colors[n.cls]}"/>`;
      s += `<text x="${x+3}" y="${y+ROLL_SEMI-2}" fill="#eef" font-size="8">${n.deg}</text>`;
    });
    s += `<line class="rollhead" x1="-10" y1="0" x2="-10" y2="${H}" stroke="#e55" stroke-width="1.5"/></svg>`;
    out += s;
  }
  return out;
}

// --- スコア: 全フレーズを縦一列に (全体が見える) ----------------------------
const list = document.getElementById('phraselist');
let scoreHtml = '';
// 🎯 作戦: コーチの提案 (analysis/strategy.yaml) + データ由来の事実
if (D.strategy) {
  const st = D.strategy;
  const chip = b => {
    const i = D.phrases.findIndex(p => p.start === b);
    return i >= 0
      ? ` <span class="lchip" onclick="select(${i})">▶ ${D.phrases[i].start}–${D.phrases[i].end}</span>`
      : '';
  };
  const steps = (st.steps || []).map(s =>
    `<li><b>${s.when ? s.when + '： ' : ''}${s.name}</b> — ${linkify(s.how || '', null)}${(s.phrases || []).map(chip).join('')}</li>`
  ).join('');
  const stats = D.stats
    ? `<div class="notes">データの裏付け: 演奏${D.stats.bars}小節のうち ` +
      `ルートのみ${D.stats.cats['ルートのみ']} ・ コードトーン${D.stats.cats['コードトーン']} ・ ` +
      `語彙で説明可能${D.stats.cats['語彙内']} ・ 要注意${D.stats.cats['要注意']}。` +
      `🔴完全暗記は ${D.stats.red.join('、')} だけ。同型検出 ${D.stats.likes} 組</div>`
    : '';
  scoreHtml += `<details id="strategy" open><summary>🎯 作戦 — ${st.title || ''}</summary>
    <div class="stbox">
      <b>この曲のベースの特徴</b>
      <ul>${(st.characteristics || []).map(c => `<li>${linkify(c, null)}</li>`).join('')}</ul>
      <b>練習の順番</b>
      <ol>${steps}</ol>
      <div class="notes">原則: ${(st.principles || []).join(' ／ ')}</div>
      ${stats}
      <div class="notes">✏️ この作戦は analysis/strategy.yaml で編集できます</div>
    </div></details>`;
}
let lastSection = null;
D.phrases.forEach((p, i) => {
  if (p.section !== lastSection) {
    lastSection = p.section;
    const s = document.createElement('div');
    s.className = 'sec';
    s.textContent = p.section;
    list.appendChild(s);
    scoreHtml += `<div class="sec2">${p.section}</div>`;
  }
  const c = document.createElement('div');
  c.className = 'card';
  c.id = 'card' + i;
  c.textContent = `${p.badge} ${p.start}–${p.end}  ${p.role || ''}`;
  c.onclick = () => select(i);
  list.appendChild(c);

  const like = p.like
    ? `<span class="like">≒ ${p.like.ref} と同型${p.like.diffs.length ? ` (違い: ${p.like.diffs.join(',')})` : ''}</span>`
    : '';
  const hint = p.bars.map(b =>
    `<tr><td>${b.bar}</td><td class="line">|${b.line}|</td></tr>`).join('');
  const chips = p.lessons.map(s =>
    `<span class="lchip" onclick="showLesson('${s}')">📚 ${D.lessons[s].title.split(' — ')[0]}</span>`
  ).join('');
  scoreHtml += `<div class="phrase" id="ph${i}">
    <div class="phead" onclick="select(${i})">${p.badge} <b>${p.start}–${p.end}</b>
      「${p.role}」 <span style="color:#667">${p.memorization} / ${fmt(barTime(p.start))}</span>${like}</div>
    <div class="summary">${linkify(p.summary, null)}</div>
    ${p.notes ? `<div class="notes">📝 ${linkify(p.notes, null)}</div>` : ''}
    ${buildRoll(p)}
    <details><summary>ヒント（度数列）— 思い出せない時だけ開く</summary><table>${hint}</table></details>
    ${chips ? `<div>${chips}</div>` : ''}
  </div>`;
});
document.getElementById('score').innerHTML = scoreHtml;

// 🗺 ルート通しチャート: 全小節のコードを1枚に。演奏中に見る用
let chartHtml = '';
let chartGridOpen = false;
D.chart.forEach(c => {
  if (c.sec) {
    if (chartGridOpen) chartHtml += '</div>';
    chartHtml += `<div class="chsec">${c.sec}</div><div class="chgrid">`;
    chartGridOpen = true;
  } else if (!chartGridOpen) {
    chartHtml += '<div class="chgrid">';
    chartGridOpen = true;
  }
  const play = c.play || c.label || '';
  const long = play.length > 5;
  const sub = c.label && c.label !== play
    ? `<small style="display:block;color:#556;font-size:8.5px">${c.label}</small>` : '';
  chartHtml += `<div class="chcell${c.rest ? ' rest' : ''}${c.entry ? ' entry' : ''}" data-bar="${c.bar}"
    onclick="seek(barTime(${c.bar}))" title="クリックでこの小節へ">
    <i>${c.bar}${c.rest ? ' 休' : ''}</i><b${long ? ' class="long"' : ''}>${play}</b>${sub}</div>`;
});
if (chartGridOpen) chartHtml += '</div>';
document.getElementById('chart').innerHTML =
  '<span id="chartclose" onclick="toggleChart()">✕ 閉じる (Esc)</span>' +
  '<div class="notes" style="margin:2px 0 6px">読み方: 大きい字 = 踏む音。' +
  '「B 4拍→Bb」= 1〜3拍はB、4拍目からBb。小さい字 = 元のコード名。薄いマス = ベース休み</div>' +
  chartHtml;
function toggleChart() { document.getElementById('chart').classList.toggle('on'); }
document.getElementById('chartbtn').onclick = toggleChart;

document.querySelectorAll('.rollsvg').forEach(svg => {
  const t0 = Number(svg.dataset.t0cell), cells = Number(svg.dataset.cells);
  svg.onclick = ev =>
    seek((t0 + Math.max(0, ev.offsetX - ROLL_GUT) / ROLL_CELL) * spb16);
  svg.ondblclick = () => {
    loopStart = t0 * spb16;
    loopEnd = (t0 + cells) * spb16;
    document.getElementById('loopinfo').textContent =
      `🔁 bar ${t0/16 + 1}–${(t0 + cells)/16}`;
    seek(loopStart);
  };
});

function setActive(i) {
  current = i;
  document.querySelectorAll('.card').forEach(c => c.classList.remove('active'));
  document.querySelectorAll('.phrase').forEach(c => c.classList.remove('active'));
  const card = document.getElementById('card' + i);
  const block = document.getElementById('ph' + i);
  if (card) { card.classList.add('active'); card.scrollIntoView({block: 'nearest'}); }
  if (block) block.classList.add('active');
  const p = D.phrases[i];
  document.querySelectorAll('.note.phrase').forEach(n => {
    n.classList.remove('phrase');
    n.removeAttribute('title');
  });
  (p.positions || []).forEach(q => {
    const n = document.querySelector(`.note[data-pos="${q.pos}"]`);
    if (n) { n.classList.add('phrase'); n.title = q.deg; }
  });
}

function select(i) {
  follow = false;
  setActive(i);
  const p = D.phrases[i];
  loopStart = barTime(p.start);
  loopEnd = barTime(p.end + 1);
  document.getElementById('loopinfo').textContent = `🔁 ${p.start}–${p.end}`;
  seek(loopStart);
  const block = document.getElementById('ph' + i);
  if (block) block.scrollIntoView({block: 'start', behavior: 'smooth'});
}

// --- 再生同期 ----------------------------------------------------------------
const chordEvents = D.chords.map(c => ({
  ...c, t: ((c.bar - 1) * D.beats + (c.beat - 1)) * 60 / D.bpm,
}));
let lastChord = null;
let lastScrollT0 = null;
let lastChartBar = 0;

function syncUI(tOverride) {
  const t = typeof tOverride === 'number' ? tOverride : clock.currentTime;
  if (t >= loopEnd - 0.03 && playing()) {
    if (document.getElementById('loop').checked) { seek(loopStart); return; }
    pauseAll();
  }
  const bar = Math.floor(t / spb) + 1;
  document.getElementById('pos').textContent = `${fmt(t)} / bar ${bar}`;
  const pi = phraseAt(bar);
  if (pi >= 0 && pi !== current) setActive(pi);
  // ルート通しチャートの現在小節ハイライト + 追従スクロール
  const chartEl = document.getElementById('chart');
  if (chartEl.classList.contains('on') && bar !== lastChartBar) {
    lastChartBar = bar;
    chartEl.querySelectorAll('.chcell').forEach(el =>
      el.classList.toggle('now', Number(el.dataset.bar) === bar));
    const cur = chartEl.querySelector('.chcell.now');
    if (cur && playing()) cur.scrollIntoView({block: 'center', behavior: 'smooth'});
  }
  // ロールの再生線 (該当する段だけに表示) + 通しモードの自動スクロール
  const rel = t / spb16;
  document.querySelectorAll('.rollhead').forEach(head => {
    const svg = head.parentElement;
    const t0 = Number(svg.dataset.t0cell), cells = Number(svg.dataset.cells);
    const local = rel - t0;
    const visible = local >= 0 && local < cells;
    head.setAttribute('x1', visible ? ROLL_GUT + local * ROLL_CELL : -10);
    head.setAttribute('x2', visible ? ROLL_GUT + local * ROLL_CELL : -10);
    if (visible && follow && playing() && lastScrollT0 !== t0) {
      lastScrollT0 = t0;
      svg.scrollIntoView({block: 'center', behavior: 'smooth'});
    }
  });
  // いまのコードのベース音を指板上でハイライト
  let active = null;
  for (const c of chordEvents) { if (c.t <= t + 0.06) active = c; else break; }
  if (active !== lastChord) {
    lastChord = active;
    document.getElementById('chordnow').textContent = active ? active.label : '';
    document.querySelectorAll('.note').forEach(n =>
      n.classList.toggle('chord', active != null && active.pc !== null
        && Number(n.dataset.pc) === active.pc));
    if (fbMode === 'chord') relabelFretboard();
  }
}
clock.addEventListener('seeked', () => { pendingSeek = null; });
clock.addEventListener('timeupdate', () => {
  if (pendingSeek !== null) return;
  if (playing()) syncUI();
});

// --- 指板マップ ----------------------------------------------------------------
if (D.fretboard) {
  const fb = D.fretboard;
  const marks = new Set([3, 5, 7, 9, 12, 15]);
  document.getElementById('fretsum').textContent =
    `指板マップ — キー ${fb.key}${fb.alias ? ` (=${fb.alias})` : ''} メジャースケール` +
    ' (緑=ルート、明るい丸=ペンタ)';
  let html = '<table class="fb"><tr><th></th>' +
    Array.from({length: fb.frets + 1}, (_, f) =>
      `<th class="${marks.has(f) ? 'mark' : ''}">${f}</th>`).join('') + '</tr>';
  fb.rows.forEach(r => {
    const m = Object.fromEntries(r.cells.map(c => [c.fret, c]));
    html += `<tr><th>${r.string}</th>` +
      Array.from({length: fb.frets + 1}, (_, f) => {
        const c = m[f];
        if (!c) return '<td></td>';
        const cls = 'note' + (c.root ? ' root' : '') + (c.penta ? ' penta' : '')
          + (c.scale ? '' : ' off');
        return `<td><span class="${cls}" data-pc="${c.pc}" data-pos="${c.pos}" data-name="${c.name}">${c.name}</span></td>`;
      }).join('') + '</tr>';
  });
  document.getElementById('fretmap').innerHTML = html + '</table>';
  document.getElementById('frethint').innerHTML =
    '5弦のコツ: B弦はE弦と同じ並びが5フレット右にずれたもの (B弦7f = E弦2f)。' +
    '明るい丸はそのまま E♭マイナーペンタでもある (平行調なので同じ音)。' +
    '「度数（コード追従）」にすると、再生中のコードのルートを基準に全ラベルが動く。' +
    (D.lessons['degrees'] ? ' <span class="lchip" onclick="showLesson(\\'degrees\\')">📚 度数とは</span>' : '') +
    (D.lessons['pentatonic'] ? ' <span class="lchip" onclick="showLesson(\\'pentatonic\\')">📚 ペンタとは</span>' : '') +
    (D.lessons['fourths-tuning'] ? ' <span class="lchip" onclick="showLesson(\\'fourths-tuning\\')">📚 4度チューニング</span>' : '') +
    ' <span class="lchip" onclick="showLessonIndex()">📚 レッスン一覧（順に学ぶ）</span>';
}

const DEG = ['R','♭2','2','♭3','3','4','♭5','5','♭6','6','♭7','7'];
let fbMode = 'chord';
function relabelFretboard() {
  const base = fbMode === 'chord'
    ? (lastChord && lastChord.pc !== null ? lastChord.pc : (D.fretboard ? D.fretboard.root_pc : 0))
    : (D.fretboard ? D.fretboard.root_pc : 0);
  document.querySelectorAll('.note').forEach(n => {
    n.textContent = fbMode === 'name'
      ? n.dataset.name
      : DEG[((Number(n.dataset.pc) - base) % 12 + 12) % 12];
  });
}
document.querySelectorAll('input[name=fbmode]').forEach(r =>
  r.onchange = () => { fbMode = r.value; relabelFretboard(); });
if (D.fretboard) relabelFretboard();
if (D.show_fretboard !== false) document.getElementById('fret').setAttribute('open', '');

document.addEventListener('keydown', e => {
  if (e.code === 'Space' && e.target.tagName !== 'INPUT') {
    e.preventDefault();
    playing() ? pauseAll() : playAll();
  }
  if (e.code === 'Escape') document.getElementById('chart').classList.remove('on');
  if (e.code === 'ArrowRight' && current < D.phrases.length - 1) select(current + 1);
  if (e.code === 'ArrowLeft' && current > 0) select(current - 1);
});
</script>
</body>
</html>
"""

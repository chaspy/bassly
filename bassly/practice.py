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
    "chord-tones": ["コードトーン"],
    "pentatonic": [
        "メジャーペンタトニック", "マイナーペンタトニック",
        "ペンタトニック", "メジャーペンタ", "マイナーペンタ", "ペンタ",
    ],
    "chromatic-approach": ["半音アプローチ", "先取り", "経過音", "アンティシペーション"],
    "slash-chords": ["分数コード", "スラッシュコード"],
    "octaves": ["オクターブ"],
    "fourths-tuning": ["4度チューニング"],
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
]


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
        for bar in range(p.start_bar, p.end_bar + 1):
            rows = by_bar.get(bar, [])
            for a in rows:
                for t in a.tags:
                    slug = _lesson_for_tag(t)
                    if slug and slug in lessons and slug not in slugs:
                        slugs.append(slug)
                if not a.event.ghost and a.degree is not None:
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
            }
        )
    return {
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
  #side { width:290px; overflow-y:auto; border-right:1px solid #333; padding:12px; flex-shrink:0; }
  #main { flex:1; overflow-y:auto; padding:20px 28px; }
  h1 { font-size:16px; margin:4px 0 12px; }
  .sec { color:#8a8; font-size:12px; margin:14px 0 4px; font-weight:bold; }
  .card { padding:8px 10px; border-radius:8px; cursor:pointer; margin:3px 0;
          border:1px solid #333; font-size:13px; }
  .card:hover { background:#1e2a1e; }
  .card.active { background:#1d3a26; border-color:#3c8; }
  #transport { position:sticky; top:0; background:#111; padding:10px 0 14px; z-index:2;
               border-bottom:1px solid #333; margin-bottom:16px; }
  button { background:#2a2a2a; color:#eee; border:1px solid #444; border-radius:8px;
           padding:8px 16px; font-size:15px; cursor:pointer; }
  button.primary { background:#1d3a26; border-color:#3c8; font-size:18px; padding:8px 26px; }
  .stem { display:inline-block; margin:2px 4px 2px 0; padding:4px 10px; border-radius:14px;
          border:1px solid #444; cursor:pointer; font-size:12px; user-select:none; }
  .stem.on { background:#1d3a26; border-color:#3c8; }
  #pos { font-variant-numeric:tabular-nums; color:#9c9; margin-left:12px; font-size:14px; }
  input[type=range] { vertical-align:middle; }
  .summary { font-size:16px; line-height:1.7; background:#1a1a1a; border-left:4px solid #3c8;
             padding:12px 16px; border-radius:6px; margin:10px 0; }
  .notes { color:#bba; font-size:13px; margin:6px 0; }
  .bars { display:flex; flex-wrap:wrap; gap:6px; margin-top:14px; }
  .barcell { border:1px solid #333; border-radius:8px; padding:6px 12px; min-width:64px;
             cursor:pointer; }
  .barcell:hover { border-color:#6cf; }
  .barcell i { display:block; font-style:normal; color:#666; font-size:10px; }
  .barcell b { font-size:17px; font-weight:600; color:#cde; }
  .barcell.now { background:#20301f; border-color:#3c8; }
  .barcell.warn b::after { content:" ⚠"; font-size:12px; }
  details { margin-top:14px; color:#888; }
  details summary { cursor:pointer; font-size:12px; }
  .fb { border-collapse:collapse; margin-top:10px; }
  .fb th { color:#666; font-size:10px; padding:2px 4px; font-weight:normal; }
  .fb th.mark { color:#bbb; font-weight:bold; }
  .fb td { border-left:1px solid #2a2a2a; min-width:40px; height:26px;
           text-align:center; padding:1px 2px; }
  .note { display:inline-block; min-width:22px; padding:2px 4px; border-radius:10px;
          font-size:11px; color:#8a8; border:1px solid #2a3a2a; }
  .note.penta { color:#cec; border-color:#4a6; }
  .note.root { background:#1d3a26; border-color:#3c8; color:#dfd; font-weight:bold; }
  .note.chord { background:#4a3208; border-color:#fa0; color:#ffd; box-shadow:0 0 6px #fa06; }
  .note.off { visibility:hidden; }
  .note.off.chord, .note.off.phrase { visibility:visible; opacity:.95; }
  .note.phrase { outline:2px solid #6cf; box-shadow:0 0 6px #6cf6; }
  #chordnow { color:#fc8; font-size:16px; font-weight:bold; margin-left:12px; }
  .lchip { display:inline-block; margin:10px 6px 0 0; padding:4px 12px; border-radius:14px;
           border:1px solid #557; color:#aac; cursor:pointer; font-size:12px; user-select:none; }
  .lchip:hover { background:#1e2233; }
  #lessonbox { display:none; margin-top:14px; background:#161a24; border:1px solid #334;
               border-radius:8px; padding:16px 20px; }
  #lessonbox h3 { margin:0 0 10px; font-size:15px; color:#aac; }
  #lessonbox pre { white-space:pre-wrap; font-family:inherit; font-size:13.5px;
                   line-height:1.8; color:#ccd; margin:0; }
  #lessonclose { float:right; cursor:pointer; color:#667; }
  .wikilink { color:#8cf; cursor:pointer; border-bottom:1px dotted #468; }
  .backlinks { margin-top:12px; font-size:12px; color:#778; }
  table { border-collapse:collapse; margin-top:8px; }
  td { padding:4px 12px 4px 0; font-size:13px; vertical-align:top; color:#999; }
  td.line { font-family:ui-monospace,'SF Mono',monospace; letter-spacing:1px; }
  .hint { color:#777; font-size:12px; margin-top:24px; line-height:1.8; }
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
    <button id="restart">⟲ フレーズ頭</button>
    <label style="margin-left:10px">ループ <input type="checkbox" id="loop" checked></label>
    <label style="margin-left:10px">速度 <input type="range" id="rate" min="50" max="100" value="100" style="width:110px">
      <span id="ratev">100%</span></label>
    <span id="pos"></span><span id="chordnow"></span>
    <div style="margin-top:8px" id="stems"></div>
  </div>
  <div id="detail"><p style="color:#888">左のフレーズを選ぶと、その区間だけループ再生されます。</p></div>
  <div id="lessonbox"><span id="lessonclose" onclick="hideLesson()">✕ 閉じる</span>
    <h3 id="lessontitle"></h3><pre id="lessonbody"></pre>
    <div class="backlinks" id="lessonlinks"></div></div>
  <details id="fret" open>
    <summary id="fretsum">指板マップ</summary>
    <div style="margin-top:8px">
      表示:
      <label><input type="radio" name="fbmode" value="name"> 音名</label>
      <label><input type="radio" name="fbmode" value="key"> 度数（キー基準）</label>
      <label><input type="radio" name="fbmode" value="chord" checked> 度数（コード追従）</label>
    </div>
    <div id="fretmap"></div>
    <div class="hint" id="frethint"></div>
  </details>
  <div class="hint">
    スペース=再生/停止 ・ ←→=フレーズ移動 ・ 「頭から通す」=解釈が再生に追従。<br>
    ベースを消すとカラオケ練習、ベースだけにすると耳コピ確認。<br>
    説明が分からない・言葉がしっくりこない時は、そのフレーズ番号を添えてチャットで質問してください。
    一文の修正は analysis/phrases.yaml へ。
  </div>
</div>
<script>
const D = __DATA__;
const spb = 60 / D.bpm * D.beats;
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
let follow = false;  // 通しモード: 再生位置に合わせて解釈を自動で切替
function clockDuration() { return isFinite(clock.duration) ? clock.duration : 9999; }
function phraseAt(bar) { return D.phrases.findIndex(p => bar >= p.start && bar <= p.end); }

// m4aのシークはフレーム境界にスナップし数十ms手前に着地することがあるため、
// UI更新には意図した時刻を直接渡す (音声の着地誤差でコード判定をずらさない)。
// さらにシーク完了までは音声由来の時刻を信用しない (pendingSeek)
let pendingSeek = null;
function seek(t) {
  pendingSeek = t;
  audios.forEach(a => a.currentTime = t);
  syncUI(t);
}
function playing() { return !clock.paused; }
function playAll() { audios.forEach(a => a.play()); document.getElementById('play').textContent = '⏸'; }
function pauseAll() { audios.forEach(a => a.pause()); document.getElementById('play').textContent = '▶'; }

document.getElementById('play').onclick = () => playing() ? pauseAll() : playAll();
document.getElementById('restart').onclick = () => seek(loopStart);
document.getElementById('full').onclick = () => {
  follow = true;
  loopStart = 0;
  loopEnd = clockDuration();
  document.querySelectorAll('.card').forEach(c => c.classList.remove('active'));
  document.getElementById('detail').innerHTML =
    '<p style="color:#888">通し再生中 — 再生位置のフレーズを自動表示します。</p>';
  current = -1;
  seek(0);
  playAll();
};
document.getElementById('rate').oninput = e => {
  const r = e.target.value / 100;
  audios.forEach(a => a.playbackRate = r);
  document.getElementById('ratev').textContent = e.target.value + '%';
};

const chordEvents = D.chords.map(c => ({
  ...c, t: ((c.bar - 1) * D.beats + (c.beat - 1)) * 60 / D.bpm,
}));
let lastChord = null;

function syncUI(tOverride) {
  const t = typeof tOverride === 'number' ? tOverride : clock.currentTime;
  if (t >= loopEnd - 0.03 && playing()) {
    if (document.getElementById('loop').checked) { seek(loopStart); return; }
    pauseAll();
  }
  const bar = Math.floor(t / spb) + 1;
  document.getElementById('pos').textContent = `${fmt(t)} / bar ${bar}`;
  if (follow) {
    const i = phraseAt(bar);
    if (i >= 0 && i !== current) showDetail(i);
  }
  document.querySelectorAll('[data-bar]').forEach(el =>
    el.classList.toggle('now', Number(el.dataset.bar) === bar));
  // 進行の視覚化: いまのコードのベース音を指板上でハイライト
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
// 停止中は seek() が渡す意図時刻だけを信じる。シーク処理中に音声側から
// 古い currentTime で timeupdate が飛んできて UI を上書きするのを防ぐ
clock.addEventListener('seeked', () => { pendingSeek = null; });
clock.addEventListener('timeupdate', () => {
  if (pendingSeek !== null) return;
  if (playing()) syncUI();
});

function seekBar(bar) {
  // クリックは「見る」操作: シークと表示の切替だけ行い、再生は始めない
  seek(barTime(bar));
}

const list = document.getElementById('phraselist');
let lastSection = null;
D.phrases.forEach((p, i) => {
  if (p.section !== lastSection) {
    lastSection = p.section;
    const s = document.createElement('div');
    s.className = 'sec';
    s.textContent = p.section;
    list.appendChild(s);
  }
  const c = document.createElement('div');
  c.className = 'card';
  c.id = 'card' + i;
  c.textContent = `${p.badge} ${p.start}–${p.end}  ${p.role || ''}`;
  c.onclick = () => select(i);
  list.appendChild(c);
});

function showDetail(i) {
  current = i;
  const p = D.phrases[i];
  document.querySelectorAll('.card').forEach(c => c.classList.remove('active'));
  const card = document.getElementById('card' + i);
  card.classList.add('active');
  card.scrollIntoView({block: 'nearest'});
  const cells = p.bars.map(b =>
    `<span class="barcell ${b.warn ? 'warn' : ''}" data-bar="${b.bar}"
       onclick="seekBar(${b.bar})" title="この小節へジャンプ">
       <i>${b.bar}</i><b>${b.chord}</b></span>`
  ).join('');
  const hint = p.bars.map(b =>
    `<tr><td>${b.bar}</td><td class="line">|${b.line}|</td></tr>`
  ).join('');
  const chips = p.lessons.map(s =>
    `<span class="lchip" onclick="showLesson('${s}')">📚 ${D.lessons[s].title.split(' — ')[0]}</span>`
  ).join('');
  document.getElementById('detail').innerHTML = `
    <h2 style="font-size:15px;color:#9c9">${p.section} ${p.start}–${p.end}小節
      「${p.role}」 ${p.badge} ${p.memorization}</h2>
    <div class="summary">${linkify(p.summary, null)}</div>
    ${p.notes ? `<div class="notes">📝 ${linkify(p.notes, null)}</div>` : ''}
    <div class="bars">${cells}</div>
    <details><summary>ヒント（度数列）— 思い出せない時だけ開く</summary>
      <table>${hint}</table></details>
    ${chips ? `<div>${chips}</div>` : ''}`;
  // このフレーズが実際に使うポジションを指板マップにハイライト
  document.querySelectorAll('.note.phrase').forEach(n => {
    n.classList.remove('phrase');
    n.removeAttribute('title');
  });
  (p.positions || []).forEach(q => {
    const n = document.querySelector(`.note[data-pos="${q.pos}"]`);
    if (n) { n.classList.add('phrase'); n.title = q.deg; }
  });
}

// Scrapbox風の相互リンク: 本文中の用語を他レッスンへのリンクにする
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

// just-in-case 派向け: 推奨順のレッスン一覧 (基礎 -> 応用)
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

function select(i) {
  follow = false;
  showDetail(i);
  const p = D.phrases[i];
  loopStart = barTime(p.start);
  loopEnd = barTime(p.end + 1);
  seek(loopStart);  // 再生はスペース or ▶ で明示的に
}

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
if (D.show_fretboard === false) document.getElementById('fret').removeAttribute('open');

document.addEventListener('keydown', e => {
  if (e.code === 'Space' && e.target.tagName !== 'INPUT') {
    e.preventDefault();
    playing() ? pauseAll() : playAll();
  }
  if (e.code === 'ArrowRight' && current < D.phrases.length - 1) select(current + 1);
  if (e.code === 'ArrowLeft' && current > 0) select(current - 1);
});
</script>
</body>
</html>
"""

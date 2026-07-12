"""転記と分離音源の照合 — 音源が真実、TABは仮説。

各ノートイベントの期待ピッチと、その時刻の実測f0 (自己相関、サブハーモニック
補正付き) を比較して match / octave / mismatch / no_signal に分類する。
--track では16分グリッドごとの実測ピッチを出し、リズムずれの調査に使う。
要 ffmpeg (音源のデコード)。
"""

from __future__ import annotations

import subprocess
import tempfile
import wave
from pathlib import Path
from typing import NamedTuple

import numpy as np

from . import theory
from .domain import NoteEvent, Song

SR = 44100
MATCH_CENTS = 70  # これ以内なら一致

_SIMPLE = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def load_stem(song_dir: Path, stem: str = "bass") -> np.ndarray:
    src = song_dir / "audio" / f"{stem}.m4a"
    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(src),
             "-ac", "1", "-ar", str(SR), tmp.name],
            check=True,
        )
        w = wave.open(tmp.name)
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(float)


def f0(seg: np.ndarray, lo: float = 25, hi: float = 250) -> float | None:
    """自己相関によるf0推定。低音のサブハーモニック誤検出はオクターブ上を優先して補正。"""
    seg = seg - seg.mean()
    if len(seg) < 800 or np.abs(seg).max() < 60:
        return None
    ac = np.fft.irfft(np.abs(np.fft.rfft(seg * np.hanning(len(seg)), 1 << 17)) ** 2)
    lmin, lmax = int(SR / hi), int(SR / lo)
    lag = lmin + int(ac[lmin:lmax].argmax())
    if lag // 2 >= lmin and ac[lag // 2] > 0.85 * ac[lag]:
        lag //= 2
    return SR / lag


def hz_to_name(hz: float) -> str:
    midi = int(round(69 + 12 * np.log2(hz / 440)))
    return f"{_SIMPLE[midi % 12]}{midi // 12 - 1}"


class Check(NamedTuple):
    bar: int
    step: int
    pos: str
    expected_midi: int
    measured_hz: float | None
    cents: float | None
    verdict: str  # match | octave | mismatch | no_signal


def classify(cents: float | None) -> str:
    if cents is None:
        return "no_signal"
    if abs(cents) < MATCH_CENTS:
        return "match"
    if abs(abs(cents) - 1200) < MATCH_CENTS:
        return "octave"
    return "mismatch"


def check_events(song: Song, events: list[NoteEvent], x: np.ndarray) -> list[Check]:
    spb = int(song.time_signature.split("/")[0]) * 60 / song.bpm
    out: list[Check] = []
    for e in events:
        if e.ghost:
            continue
        t0 = (e.bar - 1) * spb + e.step * spb / 16
        dur = min(e.duration, 8) * spb / 16
        s = int((t0 + 0.02) * SR)
        en = int((t0 + max(dur * 0.9, 0.10)) * SR)
        if en > len(x):
            break
        got = f0(x[s:en])
        exp_midi = theory.pitch_at(e.string, e.fret).midi
        exp_hz = 440 * 2 ** ((exp_midi - 69) / 12)
        cents = None if got is None else 1200 * float(np.log2(got / exp_hz))
        out.append(
            Check(e.bar, e.step, f"{e.string}{e.fret}", exp_midi, got, cents,
                  classify(cents))
        )
    return out


def track_grid(song: Song, x: np.ndarray, lo_bar: int, hi_bar: int) -> list[tuple]:
    """16分グリッドごとの実測ピッチ (リズムずれ・省略音の調査用)。"""
    spb = int(song.time_signature.split("/")[0]) * 60 / song.bpm
    step_s = spb / 16
    rows = []
    for bar in range(lo_bar, hi_bar + 1):
        for step in range(16):
            t0 = (bar - 1) * spb + step * step_s
            s = int((t0 + 0.01) * SR)
            en = int((t0 + step_s * 1.9) * SR)  # 16分2個分の窓で安定させる
            if en > len(x):
                return rows
            rows.append((bar, step, f0(x[s:en])))
    return rows

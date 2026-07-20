"""Core data model.

Structured facts only: no prose, no AI output. Everything that came from an
uncertain source (PDF extraction, Moises, AI analysis) carries `source` and/or
`confidence` so later stages can show their evidence.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

StringName = Literal["B", "E", "A", "D", "G"]
Articulation = Literal["slide_in", "hammer", "pull", "fall"]


class NoteEvent(BaseModel):
    bar: int = Field(ge=1)
    step: int = Field(ge=0, le=15)  # position on the 16th-note grid within the bar
    string: StringName
    fret: int | None = Field(default=None, ge=0, le=24)  # None only for ghost notes
    duration: int = Field(default=1, ge=1)  # in 16th steps
    ghost: bool = False
    tied: bool = False  # continuation of the previous note, not re-attacked
    articulations: list[Articulation] = []
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _fret_or_ghost(self) -> "NoteEvent":
        if self.fret is None and not self.ghost:
            raise ValueError("fret is required unless the note is a ghost note")
        return self


class ChordEvent(BaseModel):
    bar: int = Field(ge=1)
    beat: float = Field(default=1.0, ge=1.0)
    chord: str
    source: Literal["user", "moises", "ai"] = "user"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class Section(BaseModel):
    name: str
    start_bar: int = Field(ge=1)
    end_bar: int = Field(ge=1)
    source: Literal["user", "moises", "ai"] = "user"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


Memorization = Literal["完全暗記", "パターン暗記", "理論から再構成", "即興可"]


class Phrase(BaseModel):
    """A human/AI interpretation of a 2-4 bar phrase — the level-2 material.

    Deterministic facts live in analysis; this holds the memorable words.
    Users are expected to rewrite summaries that don't stick.
    """

    start_bar: int = Field(ge=1)
    end_bar: int = Field(ge=1)
    section: str = ""
    role: str = ""
    summary: str  # 記憶の一文
    memorization: Memorization
    notes: str = ""
    source: Literal["user", "ai"] = "ai"
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class StemDefault(BaseModel):
    on: bool = True
    volume: float = Field(default=1.0, ge=0.0, le=1.0)


class UserProfile(BaseModel):
    """ユーザープロファイル — 曲に依存しない設定と現在地 (data/user.yaml)。

    将来の OSS/SaaS 分離では「ユーザーモデル」としてエンジンから独立する層。
    プロダクトの既定値を上書きしたいものだけを書く。
    """

    notation: Literal["flat", "sharp", "simple"] = "flat"
    show_fretboard: bool = True
    stem_defaults: dict[str, StemDefault] = {}
    # 習熟度の自己申告 (語彙・技術 -> 状態)。練習メニュー生成の入力になる
    skills: dict[str, str] = {}


class SourceRef(BaseModel):
    type: str  # tab_pdf | audio_stems | url | ...
    path: str
    note: str | None = None


class Song(BaseModel):
    title: str
    artist: str
    bpm: float = Field(gt=0)
    time_signature: str = "4/4"
    tuning: str = "EADG"  # low to high
    key: str | None = None
    # 表示の音名スタイル。通常は user.yaml (UserProfile) からロード時に注入される。
    # song.yaml に明示した場合のみ曲単位で上書きできる
    notation: Literal["flat", "sharp", "simple"] = "flat"
    sections: list[Section] = []
    chords: list[ChordEvent] = []
    sources: list[SourceRef] = []
    # 演奏者クレジット (例: {bass: やまもとひかる})。将来のプレイヤー軸
    # (手癖の曲横断検出・次にコピーする曲の推薦) の土台
    credits: dict[str, str] = {}

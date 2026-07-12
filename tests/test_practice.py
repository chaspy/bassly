import json

from bassly import practice, tabtext
from bassly.domain import ChordEvent, Phrase, Song, StemDefault, UserProfile


def test_payload_and_render():
    song = Song(
        title="sample",
        artist="me",
        bpm=120,
        key="C",
        chords=[ChordEvent(bar=1, chord="C")],
    )
    events = tabtext.parse("bar 1: A3 - A3 - . . . . . . . . . . . .")
    phrases = [
        Phrase(
            start_bar=1,
            end_bar=1,
            section="イントロ",
            summary="ルートを刻む",
            memorization="理論から再構成",
        )
    ]
    payload = practice.build_payload(song, events, phrases, ["bass"])
    assert payload["phrases"][0]["bars"][0]["line"] == "R R . . . . . ."
    assert payload["stems"][0]["file"] == "../audio/bass.m4a"

    html = practice.render(payload)
    assert "ルートを刻む" in html
    assert json.dumps("ルートを刻む", ensure_ascii=False)[1:-1] in html
    assert "__DATA__" not in html


def test_lessons_linked_by_tags():
    lessons = practice.load_lessons()
    assert "pentatonic" in lessons and lessons["pentatonic"]["title"]
    song = Song(
        title="s", artist="a", bpm=120, key="C",
        chords=[ChordEvent(bar=1, chord="C")],
    )
    events = tabtext.parse("bar 1: A3 - A3 - . . . . . . . . . . . .")
    phrases = [
        Phrase(start_bar=1, end_bar=1, summary="x", memorization="即興可")
    ]
    payload = practice.build_payload(song, events, phrases, [])
    # フレーズが使う実ポジションが度数付きで入る (指板ハイライト用)
    assert payload["phrases"][0]["positions"] == [{"pos": "A3", "deg": "R"}]
    # ルート (コードトーン) タグ -> chord-tones レッスンが just-in-time で付く
    assert "chord-tones" in payload["phrases"][0]["lessons"]
    assert "slash-chords" not in payload["phrases"][0]["lessons"]
    # 相互リンク用の別名辞書が入る
    assert "ペンタトニック" in payload["aliases"]["pentatonic"]


def test_user_profile_overrides():
    song = Song(title="s", artist="a", bpm=120)
    user = UserProfile(
        show_fretboard=False,
        stem_defaults={"bass": StemDefault(on=True, volume=0.5)},
    )
    payload = practice.build_payload(song, [], [], ["bass", "drums"], user=user)
    bass = next(s for s in payload["stems"] if s["name"] == "bass")
    drums = next(s for s in payload["stems"] if s["name"] == "drums")
    assert bass["volume"] == 0.5  # ユーザー上書き
    assert drums["volume"] == 0.1  # プロダクト既定のまま
    assert payload["show_fretboard"] is False

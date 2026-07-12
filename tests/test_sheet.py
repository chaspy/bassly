from bassly import sheet, tabtext
from bassly.domain import ChordEvent, Phrase, Song

# Self-made snippet: no copyrighted material.


def test_render_combines_phrase_and_facts():
    song = Song(
        title="sample",
        artist="me",
        bpm=120,
        key="C",
        chords=[ChordEvent(bar=1, chord="C"), ChordEvent(bar=2, chord="F")],
    )
    events = tabtext.parse(
        "bar 1: A3 - A3 - A3 - A3 - . . . . . . . .\n"
        "bar 2: D3 - D3 - D3 - D3 - . . . . . . . ."
    )
    phrases = [
        Phrase(
            start_bar=1,
            end_bar=2,
            section="イントロ",
            role="土台",
            summary="ルートを刻むだけ",
            memorization="理論から再構成",
        )
    ]
    md = sheet.render(song, events, phrases)
    assert "ルートを刻むだけ" in md
    assert "🟢 理論から再構成" in md
    assert "`| C | F |`" in md  # chord row, not a note-by-note degree line
    assert "R R R R" not in md  # degree lines stay out of the practice sheet
    assert "## イントロ" in md
    assert "0:00" in md


def test_render_flags_risky_bars():
    song = Song(
        title="s",
        artist="a",
        bpm=120,
        key="C",
        chords=[ChordEvent(bar=1, chord="C")],
    )
    # F# over C in C major: not chord tone, not penta, not passing -> 要注意
    events = tabtext.parse("bar 1: A3 - D4 - . . . . . . . . . . . .")
    phrases = [
        Phrase(start_bar=1, end_bar=1, summary="x", memorization="完全暗記")
    ]
    md = sheet.render(song, events, phrases)
    assert "⚠" in md


def test_render_without_phrases():
    song = Song(title="s", artist="a", bpm=120)
    assert "phrases" in sheet.render(song, [], [])

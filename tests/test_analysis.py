from bassly import analysis, tabtext
from bassly.domain import ChordEvent, Song


def make_song(chords):
    return Song(
        title="t",
        artist="a",
        bpm=120,
        key="Gb",
        chords=[ChordEvent(bar=b, chord=c) for b, c in chords],
    )


def tags_of(results, bar, step):
    return next(a for a in results if a.event.bar == bar and a.event.step == step).tags


def test_root_and_fifth_are_chord_tones():
    song = make_song([(1, "Gb")])
    events = tabtext.parse("bar 1: E2 - A4 - . . . . . . . . . . . .")
    r = analysis.analyze(song, events)
    assert r[0].degree == "R" and r[0].is_chord_tone and "ルート" in r[0].tags
    assert r[1].degree == "5" and "5度" in r[1].tags
    assert r[0].name == "Gb" and r[1].name == "Db"


def test_key_aware_spelling_cb():
    song = make_song([(1, "Cb")])
    events = tabtext.parse("bar 1: A2 - . . . . . . . . . . . . . .")
    r = analysis.analyze(song, events)
    assert r[0].name == "Cb"  # not "B" — spelled within Gb major
    assert r[0].degree == "R"


def test_chromatic_approach_and_out_of_scale():
    song = make_song([(1, "Gb"), (2, "Db")])
    events = tabtext.parse(
        "bar 1: E2 - - - - - - - - - - - - - A3 -\n"
        "bar 2: A4 - . . . . . . . . . . . . . ."
    )
    r = analysis.analyze(song, events)
    c_note = tags_of(r, 1, 14)
    assert any(t.startswith("半音アプローチ→Db") for t in c_note)
    assert "スケール外" in c_note


def test_anticipation_of_next_chord():
    song = make_song([(1, "Bbm"), (2, "Cb")])
    events = tabtext.parse(
        "bar 1: A1 - - - - - - - - - - - - - A2 -\n"
        "bar 2: A2 - . . . . . . . . . . . . . ."
    )
    r = analysis.analyze(song, events)
    assert any(t.startswith("先取り→Cb") for t in tags_of(r, 1, 14))


def test_octave_jump_and_ghost():
    song = make_song([(1, "Gb")])
    events = tabtext.parse("bar 1: E2 - D4 - Ax - . . . . . . . . . .")
    r = analysis.analyze(song, events)
    assert "オクターブ" in tags_of(r, 1, 2)
    assert tags_of(r, 1, 4) == ["ゴースト"]


def test_passing_tone():
    song = make_song([(1, "Gb")])
    # Gb (R) -> Ab (passing) -> Bb (3rd): stepwise, same direction
    events = tabtext.parse("bar 1: E2 - E4 - E6 - . . . . . . . . . .")
    r = analysis.analyze(song, events)
    assert "経過音" in tags_of(r, 1, 2)


def test_pentatonic_membership():
    song = make_song([(1, "Gb")])
    events = tabtext.parse("bar 1: E2 - A1 - . . . . . . . . . . . .")
    r = analysis.analyze(song, events)
    assert "ペンタ" in r[0].tags  # Gb
    assert "ペンタ" in r[1].tags  # Bb


def test_degree_line_straight_eighths_with_rests():
    song = make_song([(1, "Gb")])
    events = tabtext.parse("bar 1: E2 - E2 - . . A4 - E2 - . . E2 - E4 -")
    r = analysis.analyze(song, events)
    assert analysis.bar_degree_line(r) == "R R . 5 R . R 2"


def test_degree_line_direction_and_sustain():
    song = make_song([(1, "Cb")])
    # root Cb, then the low Gb below it, then a held root
    events = tabtext.parse("bar 1: A2 - E2 - A2 - - - . . . . . . . .")
    r = analysis.analyze(song, events)
    assert analysis.bar_degree_line(r) == "R 5↓ R - . . . ."


def test_degree_line_sixteenth_fallback():
    song = make_song([(1, "Db")])
    # dotted-8th chain: onsets at 1, 1a, 2&, 3e
    events = tabtext.parse("bar 1: A4 - - A4 - - A4 - - A4 - . . . . .")
    r = analysis.analyze(song, events)
    assert analysis.bar_degree_line(r) == "1:R 1a:R 2&:R 3e:R"


def test_degree_line_articulations():
    song = make_song([(1, "Cb")])
    events = tabtext.parse("bar 1: /G6 - G8\\ - Ax . . . . . . . . . . .")
    r = analysis.analyze(song, events)
    # no root in this bar -> no direction reference -> plain degrees
    assert analysis.bar_degree_line(r) == "/2 3\\ x . . . . ."


def test_bar_summary_root_only():
    song = make_song([(1, "Gb")])
    events = tabtext.parse("bar 1: E2 - E2 - E2 - E2 - . . . . . . . .")
    r = analysis.analyze(song, events)
    assert analysis.bar_summary(r) == "ルート弾き×4"

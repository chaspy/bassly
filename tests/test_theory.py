import pytest

from bassly.theory import (
    degree_name,
    major_pentatonic_pcs,
    major_scale_spellings,
    parse_chord,
    parse_note_name,
    pitch_at,
    spell_pc,
)


def test_open_strings():
    assert pitch_at("B", 0) == (23, "B", 0)
    assert pitch_at("E", 0) == (28, "E", 1)
    assert pitch_at("A", 0) == (33, "A", 1)
    assert pitch_at("D", 0) == (38, "D", 2)
    assert pitch_at("G", 0) == (43, "G", 2)


def test_low_b_string():
    assert pitch_at("B", 2) == (25, "Db", 1)  # low Db, below 4-string range


def test_flat_spelling_default():
    assert pitch_at("E", 2).name == "Gb"  # polaris intro riff root
    assert pitch_at("A", 4) == (37, "Db", 2)
    assert pitch_at("A", 1).name == "Bb"


def test_sharp_spelling():
    assert pitch_at("E", 2, prefer="sharp").name == "F#"


def test_octaves():
    assert pitch_at("G", 6) == (49, "Db", 3)  # octave above A string fret 4
    assert pitch_at("E", 12) == (40, "E", 2)


def test_unknown_string():
    with pytest.raises(ValueError):
        pitch_at("C", 0)


def test_parse_note_name():
    assert parse_note_name("Cb") == 11
    assert parse_note_name("F#") == 6
    assert parse_note_name("Gb") == 6


def test_key_aware_spelling():
    assert major_scale_spellings("Gb")[11] == "Cb"
    assert spell_pc(11, "Gb") == "Cb"
    assert spell_pc(11) == "B"
    assert spell_pc(0, "Gb") == "C"  # not diatonic to Gb -> fallback spelling


def test_parse_chord_qualities():
    gb = parse_chord("Gb")
    assert gb.root_pc == 6 and gb.tone_pcs == frozenset({6, 10, 1})
    assert parse_chord("Ebm").tone_pcs == frozenset({3, 6, 10})
    cbmaj7 = parse_chord("Cbmaj7")
    assert cbmaj7.root_pc == 11 and cbmaj7.tone_pcs == frozenset({11, 3, 6, 10})
    assert parse_chord("Bb7").tone_pcs == frozenset({10, 2, 5, 8})
    assert parse_chord("Cm7b5").tone_pcs == frozenset({0, 3, 6, 10})
    assert parse_chord("Gb/Bb").bass_pc == 10
    assert parse_chord("N.C.") is None
    with pytest.raises(ValueError):
        parse_chord("Gbwat")


def test_degree_names():
    assert degree_name(10, 6) == "3"  # Bb over Gb
    assert degree_name(1, 6) == "5"  # Db over Gb
    assert degree_name(11, 1) == "b7"  # Cb over Db
    assert degree_name(6, 6) == "R"


def test_pentatonic():
    assert major_pentatonic_pcs("Gb") == frozenset({6, 8, 10, 1, 3})


def test_notation_styles():
    assert spell_pc(11, "Gb", "flat") == "Cb"
    assert spell_pc(11, "Gb", "simple") == "B"
    assert spell_pc(6, "Gb", "simple") == "F#"
    assert spell_pc(3, "Gb", "simple") == "Eb"  # Ebはそのまま
    assert spell_pc(3, "Gb", "sharp") == "D#"


def test_respell_text():
    from bassly.theory import respell_text

    src = "コードの階段 G♭→C♭→D♭→E♭m を覚える。B♭はそのまま"
    out = respell_text(src, "Gb", "simple")
    assert out == "コードの階段 F#→B→C#→E♭m を覚える。B♭はそのまま"
    # idempotent: 変換済み・ユーザーがF#式で書いた文はそのまま通る
    assert respell_text(out, "Gb", "simple") == out
    assert respell_text(src, "Gb", "flat") == src


def test_respell_chord():
    from bassly.theory import respell_chord

    assert respell_chord("Cb", "Gb", "simple") == "B"
    assert respell_chord("Cbmaj7", "Gb", "simple") == "Bmaj7"
    assert respell_chord("Gb/Bb", "Gb", "simple") == "F#/Bb"
    assert respell_chord("Ebm", "Gb", "simple") == "Ebm"
    assert respell_chord("N.C.", "Gb", "simple") == "N.C."

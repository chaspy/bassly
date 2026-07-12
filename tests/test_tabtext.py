import pytest

from bassly.tabtext import TabParseError, parse

# Self-made snippets only: no copyrighted material in tests.


def test_basic_bar_with_sustains_and_rests():
    events = parse("bar 1: E2 - E2 - . . A4 - - - E2 . E4 - - -")
    assert [(e.step, e.string, e.fret, e.duration) for e in events] == [
        (0, "E", 2, 2),
        (2, "E", 2, 2),
        (6, "A", 4, 4),
        (10, "E", 2, 1),
        (12, "E", 4, 4),
    ]
    assert all(e.bar == 1 for e in events)


def test_ghost_tie_and_articulations():
    events = parse("bar 3: Ax . (A4) - /D6 - hD8 - pD6 - A6\\ - . . . .")
    ghost, tie, slide, hammer, pull, fall = events
    assert ghost.ghost and ghost.fret is None
    assert tie.tied and tie.fret == 4
    assert slide.articulations == ["slide_in"]
    assert hammer.articulations == ["hammer"]
    assert pull.articulations == ["pull"]
    assert fall.articulations == ["fall"]


def test_comments_and_blank_lines():
    text = """
# intro riff
bar 5: E2 - - - - - - - - - - - - - - -  # whole-ish note
"""
    events = parse(text)
    assert len(events) == 1
    assert events[0].duration == 16


def test_wrong_token_count():
    with pytest.raises(TabParseError, match="expected 16"):
        parse("bar 1: E2 - E2")


def test_sustain_without_note():
    with pytest.raises(TabParseError, match="no preceding note"):
        parse("bar 1: - E2 - - - - - - - - - - - - - -")


def test_bad_token():
    with pytest.raises(TabParseError, match="bad token"):
        parse("bar 1: E2 - Q9 - - - - - - - - - - - - -")


def test_rest_breaks_sustain_chain():
    with pytest.raises(TabParseError, match="no preceding note"):
        parse("bar 1: E2 - . - - - - - - - - - - - - -")

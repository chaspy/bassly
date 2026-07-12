"""Parser for the bassly text TAB format (v1).

One line per bar, 16 tokens per 4/4 bar (one token per 16th note):

    bar 5: E2 - E2 - E2 - E2 - E2 - A4 - E2 - A4 -

Tokens:
    E2, A13   note onset: string letter (BEADG) + fret number
    Ax        ghost note on that string (no pitch)
    -         previous note keeps sounding (extends duration)
    .         rest / silence
    /A4       slide into this onset;  hA4 hammer-on;  pA4 pull-off
    A6\\       onset followed by a slide-out / fall
    (A4)      tie continuation from the previous bar (not re-attacked)

`#` starts a comment (whole line or trailing). Blank lines are ignored.
Sustains do not cross barlines; use a tie token in the next bar instead.
"""

from __future__ import annotations

import re

from .domain import NoteEvent

GRID = 16  # tokens per 4/4 bar

_TOKEN_RE = re.compile(
    r"^(?P<tie>\()?"
    r"(?P<mod>[/hp])?"
    r"(?P<string>[BEADG])"
    r"(?P<fret>x|\d{1,2})"
    r"(?P<fall>\\)?"
    r"(?(tie)\))$"
)
_BAR_RE = re.compile(r"^bar\s+(\d+)\s*:\s*(.+)$")

_MODS = {"/": "slide_in", "h": "hammer", "p": "pull"}


class TabParseError(ValueError):
    pass


def parse(text: str) -> list[NoteEvent]:
    events: list[NoteEvent] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = _BAR_RE.match(line)
        if not m:
            raise TabParseError(f"line {lineno}: expected 'bar N: <tokens>'")
        bar = int(m.group(1))
        tokens = m.group(2).split()
        if len(tokens) != GRID:
            raise TabParseError(
                f"line {lineno}: bar {bar} has {len(tokens)} tokens, expected {GRID}"
            )
        current: NoteEvent | None = None
        for step, token in enumerate(tokens):
            if token == "-":
                if current is None:
                    raise TabParseError(
                        f"line {lineno}: bar {bar} step {step}: "
                        "'-' has no preceding note to sustain"
                    )
                current.duration += 1
            elif token == ".":
                current = None
            else:
                tm = _TOKEN_RE.match(token)
                if not tm:
                    raise TabParseError(
                        f"line {lineno}: bar {bar} step {step}: bad token {token!r}"
                    )
                ghost = tm["fret"] == "x"
                articulations = []
                if tm["mod"]:
                    articulations.append(_MODS[tm["mod"]])
                if tm["fall"]:
                    articulations.append("fall")
                current = NoteEvent(
                    bar=bar,
                    step=step,
                    string=tm["string"],
                    fret=None if ghost else int(tm["fret"]),
                    ghost=ghost,
                    tied=bool(tm["tie"]),
                    articulations=articulations,
                )
                events.append(current)
    return events

import numpy as np

from bassly.verify import SR, classify, f0, hz_to_name


def sine(hz, seconds=0.25, amp=8000):
    t = np.arange(int(SR * seconds)) / SR
    return amp * np.sin(2 * np.pi * hz * t)


def test_f0_detects_bass_frequencies():
    for hz in (34.65, 55.0, 69.3, 110.0):  # C#1, A1, C#2, A2
        got = f0(sine(hz))
        assert got is not None
        assert abs(1200 * np.log2(got / hz)) < 30


def test_f0_prefers_fundamental_with_harmonics():
    x = sine(55.0) + 0.6 * sine(110.0) + 0.3 * sine(165.0)
    got = f0(x)
    assert abs(1200 * np.log2(got / 55.0)) < 30


def test_f0_silence_returns_none():
    assert f0(np.zeros(int(SR * 0.2))) is None


def test_classify():
    assert classify(None) == "no_signal"
    assert classify(10) == "match"
    assert classify(-1195) == "octave"
    assert classify(1210) == "octave"
    assert classify(400) == "mismatch"


def test_hz_to_name():
    assert hz_to_name(34.65) == "C#1"
    assert hz_to_name(69.3) == "C#2"
    assert hz_to_name(55.0) == "A1"

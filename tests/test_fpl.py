from src.fpl import sparkline


def test_sparkline_basic():
    s = sparkline([0, 1, 2, 3, 4, 5, 6, 7])
    assert len(s) == 8
    assert s[0] == "▁"  # min
    assert s[-1] == "█"  # max


def test_sparkline_handles_constant():
    s = sparkline([5, 5, 5, 5])
    assert len(s) == 4
    # all values equal → all should map to lowest block (no variance)
    assert all(c == s[0] for c in s)


def test_sparkline_truncates_to_width():
    s = sparkline(list(range(50)), width=10)
    assert len(s) == 10


def test_sparkline_empty():
    assert sparkline([]) == ""

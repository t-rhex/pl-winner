import pytest

from src.value import breakeven_odds, ev_per_unit, implied_probs


def test_implied_probs_normalize_to_one():
    p = implied_probs(2.0, 3.5, 4.0)
    assert pytest.approx(sum(p), abs=1e-9) == 1.0


def test_implied_probs_overround_adjusted():
    # 1/2 + 1/3.5 + 1/4 = 0.5 + 0.286 + 0.25 = 1.036 (3.6% overround)
    p = implied_probs(2.0, 3.5, 4.0)
    # the highest implied should match the lowest odds (home @ 2.0 here)
    assert p[0] > p[1] and p[0] > p[2]


def test_ev_per_unit_break_even():
    # at exact fair odds, EV should be 0
    p = 0.5
    fair_odds = 1 / p
    assert pytest.approx(ev_per_unit(p, fair_odds), abs=1e-9) == 0.0


def test_ev_per_unit_positive_when_odds_above_fair():
    # 60% chance, odds 2.0 → EV = 0.6 * 1.0 - 0.4 = 0.2
    assert pytest.approx(ev_per_unit(0.6, 2.0), abs=1e-9) == 0.2


def test_ev_per_unit_negative_when_odds_below_fair():
    # 40% chance at odds 2.0 → EV = 0.4 * 1.0 - 0.6 = -0.2
    assert pytest.approx(ev_per_unit(0.4, 2.0), abs=1e-9) == -0.2


def test_breakeven_odds():
    assert pytest.approx(breakeven_odds(0.25), abs=1e-9) == 4.0
    assert pytest.approx(breakeven_odds(0.5), abs=1e-9) == 2.0
    assert breakeven_odds(0.0) == float("inf")

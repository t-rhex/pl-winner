import numpy as np

from src.elo import EloConfig, elo_outcome_probs, fit_elo, hybrid_outcome_probs
from src.model import fit_dixon_coles
from tests.test_model import _synthetic_matches


def test_elo_fits_and_ratings_sum_drift_is_bounded():
    matches = _synthetic_matches(n_seasons=2)
    elo = fit_elo(matches, EloConfig(k=20))
    # All teams should have a rating
    assert set(elo.ratings) == set(matches.HomeTeam) | set(matches.AwayTeam)
    # Ratings should differentiate (not all equal)
    vals = list(elo.ratings.values())
    assert max(vals) - min(vals) > 30


def test_elo_expected_home_in_unit_interval():
    matches = _synthetic_matches(n_seasons=2)
    elo = fit_elo(matches)
    for h in matches.HomeTeam.unique()[:3]:
        for a in matches.AwayTeam.unique()[:3]:
            if h == a:
                continue
            e = elo.expected_home(h, a)
            assert 0.0 < e < 1.0


def test_elo_outcome_probs_sum_to_one():
    matches = _synthetic_matches(n_seasons=2)
    teams = tuple(sorted(set(matches.HomeTeam) | set(matches.AwayTeam)))
    dc = fit_dixon_coles(matches, half_life_days=365, teams=teams)
    elo = fit_elo(matches)
    probs = elo_outcome_probs(elo, dc, "A", "B")
    np.testing.assert_allclose(sum(probs.values()), 1.0, atol=1e-6)
    probs_h = hybrid_outcome_probs(elo, dc, "A", "B")
    np.testing.assert_allclose(sum(probs_h.values()), 1.0, atol=1e-6)

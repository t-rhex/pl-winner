import numpy as np
import pandas as pd
import pytest

from src.model import _score_matrix, fit_dixon_coles


def _synthetic_matches(n_seasons: int = 3, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    teams = list("ABCDEF")  # 6 teams
    strength = {t: float(rng.normal()) for t in teams}
    rows = []
    base = pd.Timestamp("2022-08-01")
    for s in range(n_seasons):
        season_label = f"{2022 + s}-{(2023 + s) % 100:02d}"
        for h in teams:
            for a in teams:
                if h == a:
                    continue
                lam = max(0.1, 1.5 + 0.6 * strength[h] - 0.6 * strength[a] + 0.3)
                mu = max(0.1, 1.2 - 0.6 * strength[h] + 0.6 * strength[a])
                hg = int(rng.poisson(lam))
                ag = int(rng.poisson(mu))
                if hg > ag:
                    ftr = "H"
                elif hg == ag:
                    ftr = "D"
                else:
                    ftr = "A"
                rows.append(
                    {
                        "Date": base + pd.Timedelta(days=10 * len(rows)),
                        "HomeTeam": h,
                        "AwayTeam": a,
                        "FTHG": hg,
                        "FTAG": ag,
                        "FTR": ftr,
                        "Season": season_label,
                    }
                )
    return pd.DataFrame(rows)


def test_score_matrix_sums_to_one():
    m = _score_matrix(lam=1.5, mu=1.2, rho=-0.1, max_goals=10)
    assert m.shape == (11, 11)
    assert m.min() >= 0
    np.testing.assert_allclose(m.sum(), 1.0, atol=1e-10)


def test_score_matrix_handles_high_rates():
    for lam, mu in [(0.2, 0.3), (3.0, 2.5), (0.05, 0.05)]:
        m = _score_matrix(lam=lam, mu=mu, rho=-0.1, max_goals=10)
        assert m.min() >= 0
        np.testing.assert_allclose(m.sum(), 1.0, atol=1e-6)


def test_dixon_coles_fits_synthetic_data():
    matches = _synthetic_matches()
    teams = tuple(sorted(set(matches.HomeTeam) | set(matches.AwayTeam)))
    model = fit_dixon_coles(matches, half_life_days=365, teams=teams)
    # attack ratings should sum to ~0 (the constraint)
    assert abs(float(model.attack.sum())) < 1e-4
    # outcome probs sum to 1
    p = model.outcome_probs("A", "B")
    np.testing.assert_allclose(sum(p.values()), 1.0, atol=1e-6)
    # home advantage should be positive
    assert model.home > 0


def test_dixon_coles_home_advantage_effect():
    matches = _synthetic_matches(n_seasons=4, seed=42)
    teams = tuple(sorted(set(matches.HomeTeam) | set(matches.AwayTeam)))
    model = fit_dixon_coles(matches, half_life_days=365, teams=teams)
    # P(home win) when A hosts B should differ from when B hosts A
    p_ab = model.outcome_probs("A", "B")
    p_ba = model.outcome_probs("B", "A")
    # The "home win" side flipped: home of A vs B vs home of B vs A
    assert p_ab["H"] != pytest.approx(p_ba["H"])

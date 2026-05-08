import numpy as np
import pandas as pd

from src.data import SeasonState
from src.model import fit_dixon_coles
from src.simulate import simulate_season
from tests.test_model import _synthetic_matches


def _state_from_synthetic() -> SeasonState:
    df = _synthetic_matches(n_seasons=2)
    teams = tuple(sorted(set(df.HomeTeam) | set(df.AwayTeam)))
    # mark all matches as "played" except a few we leave as remaining
    remaining = pd.DataFrame(
        [{"HomeTeam": "A", "AwayTeam": "B"}, {"HomeTeam": "C", "AwayTeam": "D"}]
    )
    return SeasonState(played=df, remaining=remaining, teams=teams)


def test_simulate_returns_valid_distribution():
    state = _state_from_synthetic()
    model = fit_dixon_coles(state.played, half_life_days=365, teams=state.teams)
    result = simulate_season(state, model, n_runs=500, seed=42, show_progress=False)
    # title probabilities sum to ~1
    np.testing.assert_allclose(result.title.sum(), 1.0, atol=1e-9)
    # top4: each entry between 0 and 1, total ~ 4 (since 4 spots * n_teams = 4 totals)
    assert (result.top4 >= 0).all() and (result.top4 <= 1).all()
    np.testing.assert_allclose(result.top4.sum(), 4.0, atol=1e-9)
    # each team appears
    assert set(result.title.index) == set(state.teams)


def test_simulate_deterministic_with_seed():
    state = _state_from_synthetic()
    model = fit_dixon_coles(state.played, half_life_days=365, teams=state.teams)
    a = simulate_season(state, model, n_runs=200, seed=123, show_progress=False)
    b = simulate_season(state, model, n_runs=200, seed=123, show_progress=False)
    np.testing.assert_array_equal(a.title.to_numpy(), b.title.to_numpy())


def test_simulate_with_no_remaining_returns_certainty():
    df = _synthetic_matches(n_seasons=1)
    teams = tuple(sorted(set(df.HomeTeam) | set(df.AwayTeam)))
    state = SeasonState(played=df, remaining=pd.DataFrame(columns=["HomeTeam", "AwayTeam"]), teams=teams)
    model = fit_dixon_coles(df, half_life_days=365, teams=teams)
    result = simulate_season(state, model, n_runs=100, seed=1, show_progress=False)
    # title should be concentrated on a single team (the actual leader)
    assert result.title.max() == 1.0

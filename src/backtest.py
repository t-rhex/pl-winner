"""Walk-forward backtests of the Dixon-Coles + simulation pipeline."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import SeasonState, compute_standings, load_season, load_seasons
from .model import fit_dixon_coles
from .simulate import simulate_season


@dataclass(frozen=True)
class TitleBacktestRow:
    season: str
    cutoff_played: int
    actual_champion: str
    predicted_champion: str
    p_actual: float
    p_predicted: float
    leader_at_cutoff: str
    correct: bool


def freeze_at(season_df: pd.DataFrame, n_played: int) -> SeasonState:
    """Take the first n_played matches as 'played'; rest become 'remaining'."""
    season_df = season_df.sort_values("Date").reset_index(drop=True)
    played = season_df.iloc[:n_played].reset_index(drop=True)
    rest = season_df.iloc[n_played:].reset_index(drop=True)
    teams = tuple(sorted(set(season_df.HomeTeam) | set(season_df.AwayTeam)))
    remaining = rest[["HomeTeam", "AwayTeam"]].reset_index(drop=True)
    return SeasonState(played=played, remaining=remaining, teams=teams)


def actual_champion(season_df: pd.DataFrame) -> str:
    teams = tuple(sorted(set(season_df.HomeTeam) | set(season_df.AwayTeam)))
    table = compute_standings(season_df, teams)
    return table.iloc[0]["Team"]


def title_backtest(
    seasons: Iterable[int],
    history: int = 4,
    cutoff_played: int = 349,
    half_life_days: float = 180.0,
    n_runs: int = 5000,
    seed: int = 7,
) -> pd.DataFrame:
    """For each season, freeze at cutoff_played matches and predict the champion.

    Trains Dixon-Coles on the prior `history` seasons plus the played portion of
    the target season, then Monte-Carlo-simulates the rest.
    """
    rows: list[TitleBacktestRow] = []
    for year in seasons:
        target = load_season(year)
        truth = actual_champion(target)
        state = freeze_at(target, cutoff_played)
        leader = state.standings.iloc[0]["Team"]

        train_years = list(range(year - history, year + 1))
        hist = load_seasons(train_years)
        hist = hist[hist.HomeTeam.isin(state.teams) & hist.AwayTeam.isin(state.teams)]
        # only matches strictly before the cutoff date stay in training
        cutoff_date = state.played.Date.max()
        hist = hist[(hist.Season != f"{year}-{(year + 1) % 100:02d}") | (hist.Date <= cutoff_date)]

        model = fit_dixon_coles(
            hist, half_life_days=half_life_days, ref_date=cutoff_date, teams=state.teams
        )
        result = simulate_season(state, model, n_runs=n_runs, seed=seed, show_progress=False)
        predicted = result.title.idxmax()
        p_pred = float(result.title.max())
        p_actual = float(result.title.get(truth, 0.0))
        rows.append(
            TitleBacktestRow(
                season=f"{year}-{(year + 1) % 100:02d}",
                cutoff_played=cutoff_played,
                actual_champion=truth,
                predicted_champion=predicted,
                p_actual=p_actual,
                p_predicted=p_pred,
                leader_at_cutoff=leader,
                correct=(predicted == truth),
            )
        )
    return pd.DataFrame(rows).set_index("season")


def match_logloss_backtest(
    seasons: Iterable[int],
    history: int = 4,
    cutoff_played: int = 349,
    half_life_days: float = 180.0,
) -> pd.DataFrame:
    """Score Dixon-Coles vs a base-rate baseline on the matches after the cutoff.

    Baseline: empirical H/D/A frequencies from the played portion of each season.
    """
    rows = []
    for year in seasons:
        target = load_season(year).sort_values("Date").reset_index(drop=True)
        played = target.iloc[:cutoff_played]
        held = target.iloc[cutoff_played:]
        teams = tuple(sorted(set(target.HomeTeam) | set(target.AwayTeam)))

        train_years = list(range(year - history, year + 1))
        hist = load_seasons(train_years)
        hist = hist[hist.HomeTeam.isin(teams) & hist.AwayTeam.isin(teams)]
        cutoff_date = played.Date.max()
        hist = hist[(hist.Season != f"{year}-{(year + 1) % 100:02d}") | (hist.Date <= cutoff_date)]

        model = fit_dixon_coles(
            hist, half_life_days=half_life_days, ref_date=cutoff_date, teams=teams
        )

        baseline = played.FTR.value_counts(normalize=True).reindex(["H", "D", "A"]).fillna(1e-3)
        baseline = baseline / baseline.sum()

        dc_loss = []
        bl_loss = []
        for m in held.itertuples(index=False):
            probs = model.outcome_probs(m.HomeTeam, m.AwayTeam)
            actual = m.FTR
            dc_loss.append(-np.log(max(probs[actual], 1e-12)))
            bl_loss.append(-np.log(max(float(baseline[actual]), 1e-12)))

        rows.append(
            {
                "season": f"{year}-{(year + 1) % 100:02d}",
                "n_matches": len(held),
                "dixon_coles_logloss": float(np.mean(dc_loss)) if dc_loss else float("nan"),
                "baseline_logloss": float(np.mean(bl_loss)) if bl_loss else float("nan"),
            }
        )
    return pd.DataFrame(rows).set_index("season")

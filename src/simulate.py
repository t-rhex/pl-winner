"""Monte Carlo season simulation built on top of a fitted Dixon-Coles model."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from tqdm import tqdm

from .data import SeasonState
from .model import MAX_GOALS, DixonColesModel, _score_matrix


@dataclass(frozen=True)
class SimulationResult:
    title: pd.Series  # P(champion) by team
    top4: pd.Series  # P(top 4 finish)
    relegation: pd.Series  # P(bottom 3)
    expected_points: pd.Series
    expected_position: pd.Series
    n_runs: int

    def summary(self) -> pd.DataFrame:
        return (
            pd.DataFrame(
                {
                    "P(Champion)": self.title,
                    "P(Top 4)": self.top4,
                    "P(Relegation)": self.relegation,
                    "ExpPts": self.expected_points,
                    "ExpPos": self.expected_position,
                }
            )
            .sort_values("P(Champion)", ascending=False)
            .round({"P(Champion)": 4, "P(Top 4)": 4, "P(Relegation)": 4, "ExpPts": 1, "ExpPos": 2})
        )


def _flatten_pmf(matrix: np.ndarray) -> np.ndarray:
    flat = matrix.ravel()
    flat = np.clip(flat, 0, None)
    return flat / flat.sum()


def _precompute_fixture_pmfs(
    model: DixonColesModel, fixtures: pd.DataFrame
) -> list[np.ndarray]:
    """One flat pmf over (max_goals+1)^2 outcomes per remaining fixture."""
    pmfs = []
    cache: dict[tuple[str, str], np.ndarray] = {}
    for h, a in zip(fixtures.HomeTeam, fixtures.AwayTeam):
        key = (h, a)
        if key not in cache:
            lam, mu = model.expected_goals(h, a)
            cache[key] = _flatten_pmf(_score_matrix(lam, mu, model.rho))
        pmfs.append(cache[key])
    return pmfs


def simulate_season(
    state: SeasonState,
    model: DixonColesModel,
    n_runs: int = 10_000,
    seed: int = 7,
    relegation_slots: int = 3,
    top_slots: int = 4,
    show_progress: bool = True,
) -> SimulationResult:
    """Simulate the rest of the season many times and aggregate outcomes."""
    teams = list(state.teams)
    n_teams = len(teams)
    team_idx = {t: i for i, t in enumerate(teams)}

    base_table = state.standings.set_index("Team").reindex(teams)
    base_pts = base_table["Pts"].to_numpy(dtype=float)
    base_gd = base_table["GD"].to_numpy(dtype=float)
    base_gf = base_table["GF"].to_numpy(dtype=float)

    fixtures = state.remaining.reset_index(drop=True)
    n_fix = len(fixtures)
    home_ix = fixtures.HomeTeam.map(team_idx).to_numpy()
    away_ix = fixtures.AwayTeam.map(team_idx).to_numpy()

    rng = np.random.default_rng(seed)
    if n_fix > 0:
        pmfs = np.stack(_precompute_fixture_pmfs(model, fixtures))  # (n_fix, S)
        cdfs = np.cumsum(pmfs, axis=1)
        size = MAX_GOALS + 1
    else:
        cdfs = None
        size = MAX_GOALS + 1

    title_count = np.zeros(n_teams, dtype=np.int64)
    top4_count = np.zeros(n_teams, dtype=np.int64)
    releg_count = np.zeros(n_teams, dtype=np.int64)
    pts_sum = np.zeros(n_teams, dtype=np.float64)
    pos_sum = np.zeros(n_teams, dtype=np.float64)

    iterator = range(n_runs)
    if show_progress:
        iterator = tqdm(iterator, desc="simulating", unit="season")

    for _ in iterator:
        pts = base_pts.copy()
        gd = base_gd.copy()
        gf = base_gf.copy()

        if n_fix > 0:
            r = rng.random(n_fix)
            picks = (cdfs < r[:, None]).sum(axis=1)  # index into flat pmf
            home_goals = picks // size
            away_goals = picks % size

            for k in range(n_fix):
                h, a = home_ix[k], away_ix[k]
                hg, ag = home_goals[k], away_goals[k]
                gf[h] += hg
                gf[a] += ag
                gd[h] += hg - ag
                gd[a] += ag - hg
                if hg > ag:
                    pts[h] += 3
                elif hg < ag:
                    pts[a] += 3
                else:
                    pts[h] += 1
                    pts[a] += 1

        # rank: higher pts > higher gd > higher gf
        order = np.lexsort((gf, gd, pts))[::-1]
        positions = np.empty(n_teams, dtype=np.int64)
        positions[order] = np.arange(1, n_teams + 1)

        title_count[order[0]] += 1
        for t in order[:top_slots]:
            top4_count[t] += 1
        for t in order[-relegation_slots:]:
            releg_count[t] += 1
        pts_sum += pts
        pos_sum += positions

    title = pd.Series(title_count / n_runs, index=teams, name="P(Champion)")
    top4 = pd.Series(top4_count / n_runs, index=teams, name="P(Top 4)")
    rel = pd.Series(releg_count / n_runs, index=teams, name="P(Relegation)")
    exp_pts = pd.Series(pts_sum / n_runs, index=teams, name="ExpPts")
    exp_pos = pd.Series(pos_sum / n_runs, index=teams, name="ExpPos")
    return SimulationResult(
        title=title,
        top4=top4,
        relegation=rel,
        expected_points=exp_pts,
        expected_position=exp_pos,
        n_runs=n_runs,
    )


def standings_with_simulation(state: SeasonState, result: SimulationResult) -> pd.DataFrame:
    table = state.standings.set_index("Team")
    return table.join(result.summary()).sort_values(
        ["P(Champion)", "Pts"], ascending=False
    )

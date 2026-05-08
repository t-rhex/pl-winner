"""Dixon-Coles bivariate Poisson model for football match scores.

Reference: Dixon & Coles (1997), "Modelling Association Football Scores and
Inefficiencies in the Football Betting Market".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln

MAX_GOALS = 10


@dataclass(frozen=True)
class DixonColesModel:
    teams: tuple[str, ...]
    attack: np.ndarray
    defense: np.ndarray
    home: float
    rho: float

    @property
    def team_index(self) -> dict[str, int]:
        return {t: i for i, t in enumerate(self.teams)}

    def expected_goals(self, home_team: str, away_team: str) -> tuple[float, float]:
        idx = self.team_index
        i, j = idx[home_team], idx[away_team]
        lam = float(np.exp(self.attack[i] + self.defense[j] + self.home))
        mu = float(np.exp(self.attack[j] + self.defense[i]))
        return lam, mu

    def score_matrix(self, home_team: str, away_team: str) -> np.ndarray:
        """Joint pmf over (home_goals, away_goals) with Dixon-Coles correction."""
        lam, mu = self.expected_goals(home_team, away_team)
        return _score_matrix(lam, mu, self.rho)

    def outcome_probs(self, home_team: str, away_team: str) -> dict[str, float]:
        m = self.score_matrix(home_team, away_team)
        home_win = float(np.tril(m, -1).sum())
        draw = float(np.trace(m))
        away_win = float(np.triu(m, 1).sum())
        return {"H": home_win, "D": draw, "A": away_win}

    def ratings_table(self) -> pd.DataFrame:
        return (
            pd.DataFrame({"Team": self.teams, "Attack": self.attack, "Defense": self.defense})
            .assign(Strength=lambda d: d.Attack - d.Defense)
            .sort_values("Strength", ascending=False)
            .reset_index(drop=True)
        )


def _score_matrix(lam: float, mu: float, rho: float, max_goals: int = MAX_GOALS) -> np.ndarray:
    g = np.arange(max_goals + 1)
    log_h = g * np.log(lam) - lam - gammaln(g + 1)
    log_a = g * np.log(mu) - mu - gammaln(g + 1)
    m = np.exp(log_h[:, None] + log_a[None, :])
    m[0, 0] *= 1 - lam * mu * rho
    m[0, 1] *= 1 + lam * rho
    m[1, 0] *= 1 + mu * rho
    m[1, 1] *= 1 - rho
    m = np.clip(m, 0, None)
    return m / m.sum()


def fit_dixon_coles(
    matches: pd.DataFrame,
    half_life_days: float = 180.0,
    ref_date: Optional[pd.Timestamp] = None,
    teams: Optional[tuple[str, ...]] = None,
) -> DixonColesModel:
    """Fit attack, defense, home advantage, and rho via weighted MLE.

    Time-decay weight: w(t) = 0.5 ** ((ref_date - t) / half_life_days).
    Constrained so attack ratings sum to zero (identifiability).
    """
    if teams is None:
        teams = tuple(sorted(set(matches.HomeTeam) | set(matches.AwayTeam)))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)

    work = matches[matches.HomeTeam.isin(teams) & matches.AwayTeam.isin(teams)].copy()
    home_idx = work.HomeTeam.map(idx).to_numpy()
    away_idx = work.AwayTeam.map(idx).to_numpy()
    hg = work.FTHG.astype(int).to_numpy()
    ag = work.FTAG.astype(int).to_numpy()

    ref = pd.Timestamp(ref_date) if ref_date is not None else work.Date.max()
    days = (ref - work.Date).dt.days.to_numpy().astype(float)
    xi = np.log(2.0) / half_life_days
    weights = np.exp(-xi * days)

    def unpack(p):
        return p[:n], p[n : 2 * n], p[2 * n], p[2 * n + 1]

    log_hg_fact = gammaln(hg + 1)
    log_ag_fact = gammaln(ag + 1)

    def neg_log_lik(p):
        a, d, h, rho = unpack(p)
        log_lam = a[home_idx] + d[away_idx] + h
        log_mu = a[away_idx] + d[home_idx]
        lam = np.exp(log_lam)
        mu = np.exp(log_mu)
        ll = hg * log_lam - lam - log_hg_fact + ag * log_mu - mu - log_ag_fact
        tau = np.ones_like(lam)
        m00 = (hg == 0) & (ag == 0)
        m01 = (hg == 0) & (ag == 1)
        m10 = (hg == 1) & (ag == 0)
        m11 = (hg == 1) & (ag == 1)
        tau[m00] = 1 - lam[m00] * mu[m00] * rho
        tau[m01] = 1 + lam[m01] * rho
        tau[m10] = 1 + mu[m10] * rho
        tau[m11] = 1 - rho
        tau = np.clip(tau, 1e-10, None)
        ll = ll + np.log(tau)
        return -float(np.sum(weights * ll))

    p0 = np.concatenate([np.zeros(n), np.zeros(n), [0.25, -0.05]])
    cons = ({"type": "eq", "fun": lambda p: float(np.sum(p[:n]))},)
    bounds = [(-3, 3)] * n + [(-3, 3)] * n + [(-0.5, 1.5), (-0.2, 0.2)]
    res = minimize(
        neg_log_lik,
        p0,
        method="SLSQP",
        constraints=cons,
        bounds=bounds,
        options={"maxiter": 300, "ftol": 1e-7},
    )
    if not res.success:
        raise RuntimeError(f"Dixon-Coles fit failed: {res.message}")
    a, d, h, rho = unpack(res.x)
    return DixonColesModel(
        teams=tuple(teams),
        attack=np.array(a),
        defense=np.array(d),
        home=float(h),
        rho=float(rho),
    )

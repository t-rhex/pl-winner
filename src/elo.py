"""Elo rating model for football, blended with Dixon-Coles for outcome probabilities.

- Each team has a single rating r_i. Home advantage is a fixed bonus h.
- Match expectation: E_h = 1 / (1 + 10^(-(r_h + h - r_a) / 400))
- After the match, ratings update by k * (S - E), where S is the actual score
  (1 win, 0.5 draw, 0 loss) and the k-factor is scaled by goal difference.
- Between seasons, ratings regress to the mean by `regression`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .model import DixonColesModel

DEFAULT_RATING = 1500.0


@dataclass
class EloConfig:
    k: float = 20.0
    home_advantage: float = 70.0  # Elo points
    gd_multiplier: float = 1.0  # extra k-factor per goal of margin
    season_regression: float = 0.25  # 25% pull toward the mean between seasons


@dataclass
class EloModel:
    ratings: dict[str, float] = field(default_factory=dict)
    home_advantage: float = 70.0

    def get(self, team: str) -> float:
        return self.ratings.get(team, DEFAULT_RATING)

    def expected_home(self, home: str, away: str) -> float:
        diff = self.get(home) + self.home_advantage - self.get(away)
        return 1.0 / (1.0 + 10 ** (-diff / 400.0))


def fit_elo(matches: pd.DataFrame, cfg: EloConfig | None = None) -> EloModel:
    """Walk through matches chronologically and update ratings."""
    cfg = cfg or EloConfig()
    matches = matches.sort_values("Date").reset_index(drop=True)
    ratings: dict[str, float] = {}
    last_season = None

    for m in matches.itertuples(index=False):
        season = getattr(m, "Season", None)
        if last_season is not None and season != last_season:
            for t in ratings:
                ratings[t] = DEFAULT_RATING + (1 - cfg.season_regression) * (ratings[t] - DEFAULT_RATING)
        last_season = season

        h, a = m.HomeTeam, m.AwayTeam
        ratings.setdefault(h, DEFAULT_RATING)
        ratings.setdefault(a, DEFAULT_RATING)
        diff = ratings[h] + cfg.home_advantage - ratings[a]
        e_home = 1.0 / (1.0 + 10 ** (-diff / 400.0))
        try:
            hg, ag = int(m.FTHG), int(m.FTAG)
        except (ValueError, TypeError):
            continue
        s_home = 1.0 if hg > ag else (0.5 if hg == ag else 0.0)
        gd = abs(hg - ag)
        k = cfg.k * (1.0 + cfg.gd_multiplier * np.log1p(gd))
        delta = k * (s_home - e_home)
        ratings[h] += delta
        ratings[a] -= delta

    return EloModel(ratings=ratings, home_advantage=cfg.home_advantage)


def elo_outcome_probs(elo: EloModel, dc: DixonColesModel, home: str, away: str) -> dict[str, float]:
    """Convert Elo win expectation into H/D/A probabilities.

    Elo gives a single home-win expectation E ∈ [0,1] but no draw mechanism.
    We borrow the draw probability from Dixon-Coles' joint score matrix (which
    already accounts for scoring rates), then split (1 - P(draw)) according to E.
    """
    e_home = elo.expected_home(home, away)
    p_draw = float(np.trace(dc.score_matrix(home, away)))
    p_home = (1 - p_draw) * e_home
    p_away = (1 - p_draw) * (1 - e_home)
    return {"H": p_home, "D": p_draw, "A": p_away}


def hybrid_outcome_probs(
    elo: EloModel, dc: DixonColesModel, home: str, away: str, w_dc: float = 0.6
) -> dict[str, float]:
    """Weighted average of Dixon-Coles and Elo-derived match probabilities."""
    p_dc = dc.outcome_probs(home, away)
    p_elo = elo_outcome_probs(elo, dc, home, away)
    return {
        k: w_dc * p_dc[k] + (1 - w_dc) * p_elo[k]
        for k in ("H", "D", "A")
    }


def ratings_table(elo: EloModel) -> pd.DataFrame:
    return (
        pd.DataFrame({"Team": list(elo.ratings.keys()), "Elo": list(elo.ratings.values())})
        .sort_values("Elo", ascending=False)
        .reset_index(drop=True)
    )

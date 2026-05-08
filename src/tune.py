"""Hyperparameter cross-validation for Dixon-Coles."""
from __future__ import annotations

import pandas as pd

from .calibration import brier_score, collect_predictions, logloss


def sweep_half_life(
    seasons: list[int],
    half_lives: list[float],
    history: int = 4,
    cutoff_played: int = 200,
) -> pd.DataFrame:
    """Walk through several half-life choices and compare Brier / log-loss.

    Returns one row per half-life with the model's predictive accuracy.
    """
    rows = []
    for hl in half_lives:
        preds = collect_predictions(
            seasons,
            history=history,
            cutoff_played=cutoff_played,
            half_life_days=hl,
        )
        occ = preds["occurred"].to_numpy()
        p_model = preds["model_p"].to_numpy()
        p_book = preds["book_p"].to_numpy()
        rows.append(
            {
                "half_life_days": hl,
                "n": len(preds),
                "brier_model": round(brier_score(p_model, occ), 4),
                "brier_book": round(brier_score(p_book, occ), 4),
                "logloss_model": round(logloss(p_model, occ), 4),
                "logloss_book": round(logloss(p_book, occ), 4),
            }
        )
    return pd.DataFrame(rows).sort_values("logloss_model").reset_index(drop=True)


def best_half_life(
    seasons: list[int],
    candidates: list[float] | None = None,
    history: int = 4,
    cutoff_played: int = 200,
) -> tuple[float, pd.DataFrame]:
    """Return the half-life with the lowest log-loss, plus the full sweep."""
    if candidates is None:
        candidates = [60.0, 90.0, 120.0, 180.0, 270.0, 365.0, 540.0, 730.0, 1095.0]
    sweep = sweep_half_life(seasons, candidates, history=history, cutoff_played=cutoff_played)
    best = float(sweep.iloc[0]["half_life_days"])
    return best, sweep

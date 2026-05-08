"""Odds-based value betting analysis.

Given decimal bookmaker odds and our model's probabilities, compute:
- implied probabilities (overround-adjusted)
- expected value (EV) per £1 stake
- break-even odds (the minimum odds at which a bet is +EV under our model)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import load_season, load_season_full, load_seasons, split_current_season
from .model import DixonColesModel, fit_dixon_coles

# Common bookmaker columns in football-data.co.uk CSVs
BOOKIE_COLS = {
    "B365": ("B365H", "B365D", "B365A"),
    "PS": ("PSH", "PSD", "PSA"),  # Pinnacle (sharpest book)
    "Avg": ("AvgH", "AvgD", "AvgA"),
    "Max": ("MaxH", "MaxD", "MaxA"),  # best price across books
}


def implied_probs(odds_h: float, odds_d: float, odds_a: float) -> tuple[float, float, float]:
    """Convert decimal odds to overround-adjusted implied probabilities."""
    raw = np.array([1.0 / odds_h, 1.0 / odds_d, 1.0 / odds_a])
    return tuple((raw / raw.sum()).tolist())


def ev_per_unit(p_model: float, decimal_odds: float) -> float:
    """Expected return on a £1 stake at the given odds under our model."""
    if decimal_odds <= 1.0:
        return -1.0
    return p_model * (decimal_odds - 1.0) - (1.0 - p_model)


def breakeven_odds(p_model: float) -> float:
    """Minimum decimal odds for a model probability to break even."""
    if p_model <= 0.0:
        return float("inf")
    return 1.0 / p_model


@dataclass(frozen=True)
class EdgeRow:
    date: str
    home: str
    away: str
    side: str  # 'H' / 'D' / 'A'
    model_p: float
    book_p: float
    book_odds: float
    breakeven: float
    edge_pp: float  # percentage-point edge (model_p - book_p) * 100
    ev: float
    actual: str | None = None
    pnl: float | None = None  # if outcome known


def remaining_fixtures_table(model: DixonColesModel | None = None) -> pd.DataFrame:
    """Break-even odds for every remaining 2025-26 fixture."""
    cur = load_season(2025)
    state = split_current_season(cur)
    if model is None:
        hist = load_seasons(range(2021, 2026))
        hist = hist[hist.HomeTeam.isin(state.teams) & hist.AwayTeam.isin(state.teams)]
        model = fit_dixon_coles(hist, half_life_days=180, ref_date=cur.Date.max(), teams=state.teams)
    rows = []
    for h, a in zip(state.remaining.HomeTeam, state.remaining.AwayTeam):
        probs = model.outcome_probs(h, a)
        rows.append(
            {
                "Home": h,
                "Away": a,
                "P(H)": probs["H"],
                "P(D)": probs["D"],
                "P(A)": probs["A"],
                "BE_H": breakeven_odds(probs["H"]),
                "BE_D": breakeven_odds(probs["D"]),
                "BE_A": breakeven_odds(probs["A"]),
            }
        )
    return pd.DataFrame(rows)


def find_edges_in_history(
    seasons: list[int],
    history: int = 4,
    cutoff_played: int = 200,
    half_life_days: float = 180.0,
    bookie: str = "B365",
    edge_pp_threshold: float = 5.0,
) -> pd.DataFrame:
    """For each season, fit the model at a mid-season cutoff, then evaluate every
    subsequent match against bookmaker closing odds.

    Returns one row per (match, side) where the model thought the price was +EV
    by at least `edge_pp_threshold` percentage points.
    """
    cols = BOOKIE_COLS[bookie]
    edges: list[dict] = []

    for year in seasons:
        target = load_season(year).sort_values("Date").reset_index(drop=True)
        played = target.iloc[:cutoff_played]
        teams = tuple(sorted(set(target.HomeTeam) | set(target.AwayTeam)))

        train_years = list(range(year - history, year + 1))
        hist = load_seasons(train_years)
        hist = hist[hist.HomeTeam.isin(teams) & hist.AwayTeam.isin(teams)]
        cutoff_date = played.Date.max()
        season_label = f"{year}-{(year + 1) % 100:02d}"
        hist = hist[(hist.Season != season_label) | (hist.Date <= cutoff_date)]

        model = fit_dixon_coles(hist, half_life_days=half_life_days, ref_date=cutoff_date, teams=teams)

        full = load_season_full(year).sort_values("Date").reset_index(drop=True)
        held_full = full.iloc[cutoff_played:]

        for m in held_full.itertuples(index=False):
            try:
                oh, od, oa = float(getattr(m, cols[0])), float(getattr(m, cols[1])), float(getattr(m, cols[2]))
            except (ValueError, TypeError, AttributeError):
                continue
            if not (oh > 1 and od > 1 and oa > 1):
                continue
            probs = model.outcome_probs(m.HomeTeam, m.AwayTeam)
            book_h, book_d, book_a = implied_probs(oh, od, oa)
            for side, mp, bp, odds in [
                ("H", probs["H"], book_h, oh),
                ("D", probs["D"], book_d, od),
                ("A", probs["A"], book_a, oa),
            ]:
                edge = (mp - bp) * 100.0
                if edge < edge_pp_threshold:
                    continue
                won = (m.FTR == side)
                pnl = (odds - 1.0) if won else -1.0
                edges.append(
                    {
                        "season": season_label,
                        "date": pd.Timestamp(m.Date).strftime("%Y-%m-%d"),
                        "home": m.HomeTeam,
                        "away": m.AwayTeam,
                        "side": side,
                        "model_p": round(mp, 3),
                        "book_p": round(bp, 3),
                        "book_odds": round(odds, 2),
                        "edge_pp": round(edge, 1),
                        "ev": round(ev_per_unit(mp, odds), 3),
                        "actual": m.FTR,
                        "won": int(won),
                        "pnl": round(pnl, 2),
                    }
                )
    return pd.DataFrame(edges)


def summarize_edges(edges: pd.DataFrame) -> dict:
    """ROI summary for a set of recommended bets."""
    if edges.empty:
        return {"n_bets": 0, "total_pnl": 0.0, "roi": 0.0, "hit_rate": 0.0}
    n = len(edges)
    total = float(edges["pnl"].sum())
    hits = float(edges["won"].mean())
    return {
        "n_bets": n,
        "total_pnl": round(total, 2),
        "roi_pct": round(100.0 * total / n, 2),
        "hit_rate": round(hits, 3),
        "avg_odds": round(float(edges["book_odds"].mean()), 2),
        "avg_model_p": round(float(edges["model_p"].mean()), 3),
        "avg_book_p": round(float(edges["book_p"].mean()), 3),
        "avg_edge_pp": round(float(edges["edge_pp"].mean()), 2),
    }

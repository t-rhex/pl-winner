"""Calibration analysis: are predicted probabilities actually right?

For each backtest season, walk forward at a chosen cutoff, predict every match
played after that, and collect (model_prob, book_prob, outcome) triples. Then:

- Brier score: mean squared error of probability vector vs one-hot outcome
- Reliability table: bucket predictions by confidence, compare predicted vs actual
- Log-loss: mean -log(predicted prob of actual outcome)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import load_season_full, load_seasons
from .elo import fit_elo, hybrid_outcome_probs
from .model import fit_dixon_coles
from .value import BOOKIE_COLS, implied_probs


@dataclass(frozen=True)
class CalibrationResult:
    n_predictions: int
    brier_model: float
    brier_book: float
    logloss_model: float
    logloss_book: float
    reliability: pd.DataFrame  # one row per probability bucket


def _outcome_vec(ftr: str) -> np.ndarray:
    return {"H": np.array([1, 0, 0]), "D": np.array([0, 1, 0]), "A": np.array([0, 0, 1])}[ftr]


def collect_predictions(
    seasons: list[int],
    history: int = 4,
    cutoff_played: int = 200,
    half_life_days: float = 180.0,
    bookie: str = "B365",
    include_hybrid: bool = False,
) -> pd.DataFrame:
    """Build a long table of one row per (match, side) with model + book probs.

    If `include_hybrid` is True, also adds a `hybrid_p` column that blends
    Dixon-Coles with an Elo model (60/40).
    """
    cols = BOOKIE_COLS[bookie]
    rows = []
    for year in seasons:
        target = load_season_full(year).sort_values("Date").reset_index(drop=True)
        teams = tuple(sorted(set(target.HomeTeam) | set(target.AwayTeam)))
        played = target.iloc[:cutoff_played]
        held = target.iloc[cutoff_played:]
        cutoff_date = played.Date.max()
        season_label = f"{year}-{(year + 1) % 100:02d}"

        train_years = list(range(year - history, year + 1))
        hist = load_seasons(train_years)
        hist = hist[hist.HomeTeam.isin(teams) & hist.AwayTeam.isin(teams)]
        hist = hist[(hist.Season != season_label) | (hist.Date <= cutoff_date)]

        model = fit_dixon_coles(hist, half_life_days=half_life_days, ref_date=cutoff_date, teams=teams)
        elo = fit_elo(hist) if include_hybrid else None

        for m in held.itertuples(index=False):
            try:
                oh, od, oa = float(getattr(m, cols[0])), float(getattr(m, cols[1])), float(getattr(m, cols[2]))
            except (ValueError, TypeError, AttributeError):
                continue
            if not (oh > 1 and od > 1 and oa > 1):
                continue
            mp = model.outcome_probs(m.HomeTeam, m.AwayTeam)
            hp = hybrid_outcome_probs(elo, model, m.HomeTeam, m.AwayTeam) if include_hybrid else None
            bp_h, bp_d, bp_a = implied_probs(oh, od, oa)
            actual = m.FTR
            for side, p_m, p_b in [("H", mp["H"], bp_h), ("D", mp["D"], bp_d), ("A", mp["A"], bp_a)]:
                row = {
                    "season": season_label,
                    "match": f"{m.HomeTeam} v {m.AwayTeam}",
                    "side": side,
                    "model_p": p_m,
                    "book_p": p_b,
                    "occurred": int(actual == side),
                    "actual": actual,
                }
                if include_hybrid:
                    row["hybrid_p"] = hp[side]
                rows.append(row)
    return pd.DataFrame(rows)


def reliability_table(probs: np.ndarray, occurred: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    """Bucket by predicted probability and report observed frequency."""
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(probs, edges) - 1, 0, n_bins - 1)
    rows = []
    for b in range(n_bins):
        mask = idx == b
        if not mask.any():
            continue
        rows.append(
            {
                "bin": f"{edges[b]:.1f}-{edges[b + 1]:.1f}",
                "n": int(mask.sum()),
                "predicted": float(probs[mask].mean()),
                "observed": float(occurred[mask].mean()),
                "diff": float(occurred[mask].mean() - probs[mask].mean()),
            }
        )
    return pd.DataFrame(rows)


def brier_score(probs: np.ndarray, occurred: np.ndarray) -> float:
    return float(np.mean((probs - occurred) ** 2))


def logloss(probs: np.ndarray, occurred: np.ndarray, eps: float = 1e-12) -> float:
    p = np.clip(probs, eps, 1 - eps)
    # binary log-loss for "this outcome occurred or not" — averaged across all sides
    ll = -(occurred * np.log(p) + (1 - occurred) * np.log(1 - p))
    return float(np.mean(ll))


def evaluate(predictions: pd.DataFrame, n_bins: int = 10) -> CalibrationResult:
    p_model = predictions.model_p.to_numpy()
    p_book = predictions.book_p.to_numpy()
    occurred = predictions.occurred.to_numpy()
    return CalibrationResult(
        n_predictions=len(predictions),
        brier_model=brier_score(p_model, occurred),
        brier_book=brier_score(p_book, occurred),
        logloss_model=logloss(p_model, occurred),
        logloss_book=logloss(p_book, occurred),
        reliability=reliability_table(p_model, occurred, n_bins=n_bins),
    )


def bootstrap_ci(
    metric_fn,
    probs: np.ndarray,
    occurred: np.ndarray,
    n_boot: int = 1000,
    confidence: float = 0.95,
    seed: int = 7,
) -> tuple[float, float, float]:
    """Bootstrap resample (probs, occurred) and return (point, low, high)."""
    rng = np.random.default_rng(seed)
    n = len(probs)
    point = float(metric_fn(probs, occurred))
    samples = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        samples[i] = metric_fn(probs[idx], occurred[idx])
    alpha = (1 - confidence) / 2
    return point, float(np.quantile(samples, alpha)), float(np.quantile(samples, 1 - alpha))


def compare_with_ci(predictions: pd.DataFrame, n_boot: int = 1000) -> pd.DataFrame:
    """Side-by-side CIs for model and bookmaker. Tells us whether the gap is real."""
    p_model = predictions["model_p"].to_numpy()
    p_book = predictions["book_p"].to_numpy()
    occ = predictions["occurred"].to_numpy()
    rows = []
    for label, metric in [("Brier", brier_score), ("LogLoss", logloss)]:
        m_pt, m_lo, m_hi = bootstrap_ci(metric, p_model, occ, n_boot=n_boot)
        b_pt, b_lo, b_hi = bootstrap_ci(metric, p_book, occ, n_boot=n_boot)
        # Paired bootstrap of the difference
        diff_samples = []
        rng = np.random.default_rng(11)
        n = len(occ)
        for _ in range(n_boot):
            idx = rng.integers(0, n, size=n)
            diff_samples.append(metric(p_model[idx], occ[idx]) - metric(p_book[idx], occ[idx]))
        d_pt = m_pt - b_pt
        d_lo, d_hi = float(np.quantile(diff_samples, 0.025)), float(np.quantile(diff_samples, 0.975))
        rows.append(
            {
                "metric": label,
                "model": round(m_pt, 4),
                "model_95ci": f"[{m_lo:.4f}, {m_hi:.4f}]",
                "book": round(b_pt, 4),
                "book_95ci": f"[{b_lo:.4f}, {b_hi:.4f}]",
                "diff": round(d_pt, 4),
                "diff_95ci": f"[{d_lo:.4f}, {d_hi:.4f}]",
                "diff_significant": "YES" if (d_lo > 0 or d_hi < 0) else "no",
            }
        )
    return pd.DataFrame(rows)


def compare_bookmakers(
    seasons: list[int],
    history: int = 4,
    cutoff_played: int = 200,
    half_life_days: float = 180.0,
) -> pd.DataFrame:
    """Score the model vs every bookmaker column we have. Returns one row per book."""
    from .value import BOOKIE_COLS, ev_per_unit

    rows = []
    for bookie in BOOKIE_COLS:
        preds = collect_predictions(
            seasons, history=history, cutoff_played=cutoff_played, half_life_days=half_life_days, bookie=bookie
        )
        if preds.empty:
            continue
        occ = preds.occurred.to_numpy()
        p_book = preds.book_p.to_numpy()
        p_model = preds.model_p.to_numpy()
        # ROI: bet every model edge >= 5pp at this bookie's odds
        odds = 1.0 / p_book.clip(min=1e-6)
        edge = (p_model - p_book) * 100
        bet_mask = edge >= 5.0
        if bet_mask.any():
            ev_vec = np.array([
                ev_per_unit(float(p_model[i]), float(odds[i])) for i in np.where(bet_mask)[0]
            ])
            won = occ[bet_mask].astype(int)
            pnl = won * (odds[bet_mask] - 1.0) - (1 - won)
            n_bets = int(bet_mask.sum())
            roi = float(pnl.mean()) * 100
            hit = float(won.mean())
            ev = float(ev_vec.mean())
        else:
            n_bets, roi, hit, ev = 0, 0.0, 0.0, 0.0
        rows.append(
            {
                "bookie": bookie,
                "brier_book": brier_score(p_book, occ),
                "brier_model": brier_score(p_model, occ),
                "logloss_book": logloss(p_book, occ),
                "logloss_model": logloss(p_model, occ),
                "edges_n": n_bets,
                "edge_roi_pct": round(roi, 2),
                "edge_hit_rate": round(hit, 3),
                "edge_avg_ev": round(ev, 3),
            }
        )
    return pd.DataFrame(rows).sort_values("edge_roi_pct", ascending=False).reset_index(drop=True)

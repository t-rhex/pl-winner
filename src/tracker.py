"""Persistent log of model predictions, scored against actual results.

Schema:
- predictions(prediction_id PK, fitted_at, gameweek, season, home, away,
              p_h, p_d, p_a, model_label)
- results(home, away, season, played_at, ftr, fthg, ftag) — UNIQUE on
  (home, away, season)

When `score` is called, predictions are joined with results to produce a
calibration / Brier / log-loss summary across all stored runs.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .paths import predictions_db_path

DB_PATH = predictions_db_path()


@dataclass
class Tracker:
    db_path: Path = DB_PATH

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with closing(self.connect()) as conn, conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS predictions (
                    prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fitted_at TEXT NOT NULL,
                    gameweek INTEGER,
                    season TEXT NOT NULL,
                    home TEXT NOT NULL,
                    away TEXT NOT NULL,
                    p_h REAL NOT NULL,
                    p_d REAL NOT NULL,
                    p_a REAL NOT NULL,
                    model_label TEXT NOT NULL DEFAULT 'dixon-coles'
                );
                CREATE INDEX IF NOT EXISTS idx_predictions_match
                    ON predictions(season, home, away);

                CREATE TABLE IF NOT EXISTS results (
                    home TEXT NOT NULL,
                    away TEXT NOT NULL,
                    season TEXT NOT NULL,
                    played_at TEXT,
                    ftr TEXT NOT NULL,
                    fthg INTEGER NOT NULL,
                    ftag INTEGER NOT NULL,
                    PRIMARY KEY (home, away, season)
                );
                """
            )

    def record_predictions(
        self, predictions: pd.DataFrame, season: str, gameweek: int | None = None,
        model_label: str = "dixon-coles",
    ) -> int:
        """`predictions` must have columns: home, away, p_h, p_d, p_a."""
        self.init()
        now = datetime.utcnow().isoformat(timespec="seconds")
        rows = [
            (
                now, gameweek, season, r.home, r.away,
                float(r.p_h), float(r.p_d), float(r.p_a), model_label,
            )
            for r in predictions.itertuples(index=False)
        ]
        with closing(self.connect()) as conn, conn:
            conn.executemany(
                "INSERT INTO predictions(fitted_at, gameweek, season, home, away, p_h, p_d, p_a, model_label)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        return len(rows)

    def record_results(self, results: pd.DataFrame, season: str) -> int:
        """`results` must have columns: home, away, ftr, fthg, ftag, played_at (optional)."""
        self.init()
        rows = []
        for r in results.itertuples(index=False):
            played = getattr(r, "played_at", None)
            if played is None or pd.isna(played):
                played = ""
            rows.append(
                (r.home, r.away, season, str(played), r.ftr, int(r.fthg), int(r.ftag))
            )
        with closing(self.connect()) as conn, conn:
            conn.executemany(
                "INSERT OR REPLACE INTO results(home, away, season, played_at, ftr, fthg, ftag)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        return len(rows)

    def scored(self) -> pd.DataFrame:
        """Join predictions with known results."""
        self.init()
        with closing(self.connect()) as conn:
            return pd.read_sql_query(
                """
                SELECT p.prediction_id, p.fitted_at, p.gameweek, p.season, p.home, p.away,
                       p.p_h, p.p_d, p.p_a, p.model_label,
                       r.ftr, r.fthg, r.ftag
                FROM predictions p
                JOIN results r
                  ON p.home = r.home AND p.away = r.away AND p.season = r.season
                ORDER BY p.fitted_at, p.gameweek
                """,
                conn,
            )

    def report(self) -> dict:
        """Aggregate Brier / log-loss / hit rate across all scored predictions."""
        df = self.scored()
        if df.empty:
            return {"n": 0}

        probs = df[["p_h", "p_d", "p_a"]].to_numpy()
        actuals = df["ftr"].map({"H": 0, "D": 1, "A": 2}).to_numpy()
        chosen = probs.argmax(axis=1)

        # Brier across the 3-way distribution
        target = np.zeros_like(probs)
        target[np.arange(len(actuals)), actuals] = 1.0
        brier = float(((probs - target) ** 2).mean())

        # log-loss of the actual outcome
        actual_p = probs[np.arange(len(actuals)), actuals].clip(min=1e-12)
        ll = float(-np.log(actual_p).mean())

        hit_rate = float((chosen == actuals).mean())
        return {
            "n": int(len(df)),
            "brier": round(brier, 4),
            "logloss": round(ll, 4),
            "hit_rate": round(hit_rate, 3),
            "by_gw": (
                df.assign(actual=actuals, chosen=chosen, hit=lambda d: (d["chosen"] == d["actual"]).astype(int))
                  .groupby("gameweek")
                  .agg(n=("hit", "size"), hit_rate=("hit", "mean"))
                  .round(3)
                  .reset_index()
                  .to_dict(orient="records")
            ),
        }


def predictions_for_remaining_fixtures(state, model) -> pd.DataFrame:
    """Build a (home, away, p_h, p_d, p_a) frame for all remaining fixtures."""
    rows = []
    for h, a in zip(state.remaining.HomeTeam, state.remaining.AwayTeam):
        p = model.outcome_probs(h, a)
        rows.append({"home": h, "away": a, "p_h": p["H"], "p_d": p["D"], "p_a": p["A"]})
    return pd.DataFrame(rows)


def results_from_played(played: pd.DataFrame) -> pd.DataFrame:
    """Convert the `played` DataFrame to the schema expected by `record_results`."""
    return pd.DataFrame(
        {
            "home": played["HomeTeam"],
            "away": played["AwayTeam"],
            "ftr": played["FTR"],
            "fthg": played["FTHG"].astype(int),
            "ftag": played["FTAG"].astype(int),
            "played_at": played["Date"].astype(str),
        }
    )

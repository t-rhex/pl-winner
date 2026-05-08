from pathlib import Path

import pandas as pd

from src.tracker import Tracker


def test_tracker_round_trip(tmp_path: Path):
    db = tmp_path / "p.db"
    t = Tracker(db_path=db)
    t.init()

    preds = pd.DataFrame(
        [
            {"home": "A", "away": "B", "p_h": 0.5, "p_d": 0.3, "p_a": 0.2},
            {"home": "C", "away": "D", "p_h": 0.2, "p_d": 0.3, "p_a": 0.5},
        ]
    )
    n = t.record_predictions(preds, season="2024-25", gameweek=10)
    assert n == 2

    results = pd.DataFrame(
        [
            {"home": "A", "away": "B", "ftr": "H", "fthg": 2, "ftag": 1, "played_at": "2024-12-01"},
            {"home": "C", "away": "D", "ftr": "A", "fthg": 0, "ftag": 1, "played_at": "2024-12-02"},
        ]
    )
    t.record_results(results, season="2024-25")

    rep = t.report()
    assert rep["n"] == 2
    assert rep["hit_rate"] == 1.0  # both predictions had the right argmax


def test_tracker_handles_no_results(tmp_path: Path):
    t = Tracker(db_path=tmp_path / "p.db")
    rep = t.report()
    assert rep == {"n": 0}


def test_tracker_results_idempotent(tmp_path: Path):
    t = Tracker(db_path=tmp_path / "p.db")
    df = pd.DataFrame(
        [{"home": "X", "away": "Y", "ftr": "D", "fthg": 1, "ftag": 1, "played_at": ""}]
    )
    t.record_results(df, season="2024-25")
    t.record_results(df, season="2024-25")  # second call should overwrite, not duplicate
    scored = t.scored()
    # no predictions yet → empty join
    assert scored.empty

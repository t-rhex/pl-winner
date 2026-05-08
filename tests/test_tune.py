"""Lightweight test for the tune sweep — uses a synthetic predictions DataFrame
to avoid pulling real CSVs. We monkey-patch collect_predictions for speed.
"""
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.tune import sweep_half_life


def _fake_predictions(half_life_days: float):
    """Predictions get marginally better as half_life moves toward 200 days."""
    rng = np.random.default_rng(int(half_life_days))
    n = 300
    p = rng.uniform(0.1, 0.9, size=n)
    # noise scales with distance from optimum 200
    err = abs(half_life_days - 200) / 1000
    occ = (p + rng.normal(0, 0.1 + err, size=n) > 0.5).astype(int)
    return pd.DataFrame({"model_p": p, "book_p": p, "occurred": occ})


def test_sweep_half_life_returns_one_row_per_candidate():
    candidates = [60.0, 180.0, 365.0]
    with patch("src.tune.collect_predictions", side_effect=lambda *a, **kw: _fake_predictions(kw.get("half_life_days", 180))):
        df = sweep_half_life([2024], candidates)
    assert set(df["half_life_days"]) == set(candidates)
    assert "logloss_model" in df.columns
    assert "brier_model" in df.columns

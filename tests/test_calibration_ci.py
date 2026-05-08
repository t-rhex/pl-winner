import numpy as np
import pandas as pd

from src.calibration import bootstrap_ci, brier_score, compare_with_ci


def test_bootstrap_ci_returns_sorted_bounds():
    rng = np.random.default_rng(0)
    n = 300
    p = rng.uniform(0, 1, size=n)
    o = rng.binomial(1, p)
    point, lo, hi = bootstrap_ci(brier_score, p, o, n_boot=200)
    assert lo <= point <= hi


def test_bootstrap_ci_narrows_with_more_data():
    rng = np.random.default_rng(0)
    p_small = rng.uniform(0, 1, size=100)
    o_small = rng.binomial(1, p_small)
    p_big = rng.uniform(0, 1, size=2000)
    o_big = rng.binomial(1, p_big)
    _, lo_s, hi_s = bootstrap_ci(brier_score, p_small, o_small, n_boot=300)
    _, lo_b, hi_b = bootstrap_ci(brier_score, p_big, o_big, n_boot=300)
    assert (hi_b - lo_b) < (hi_s - lo_s)


def test_compare_with_ci_columns():
    rng = np.random.default_rng(1)
    n = 500
    df = pd.DataFrame({
        "model_p": rng.uniform(0, 1, size=n),
        "book_p": rng.uniform(0, 1, size=n),
        "occurred": rng.binomial(1, 0.4, size=n),
    })
    out = compare_with_ci(df, n_boot=200)
    assert set(out["metric"]) == {"Brier", "LogLoss"}
    assert "diff_significant" in out.columns
    for col in ("model_95ci", "book_95ci", "diff_95ci"):
        assert col in out.columns

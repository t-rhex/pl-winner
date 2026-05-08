import numpy as np

from src.calibration import brier_score, logloss, reliability_table


def test_brier_score_perfect():
    p = np.array([1.0, 0.0, 1.0, 0.0])
    o = np.array([1, 0, 1, 0])
    assert brier_score(p, o) == 0.0


def test_brier_score_uniform_50_50():
    p = np.array([0.5] * 1000)
    o = np.zeros(1000)
    assert brier_score(p, o) == 0.25


def test_logloss_perfect_is_zero():
    p = np.array([1.0 - 1e-12, 1e-12])
    o = np.array([1, 0])
    assert logloss(p, o) < 1e-6


def test_reliability_table_buckets():
    rng = np.random.default_rng(0)
    p = rng.uniform(0, 1, size=1000)
    o = rng.binomial(1, p)
    rt = reliability_table(p, o, n_bins=10)
    # within each bin, predicted ~ observed (well-calibrated by construction)
    assert (rt["n"] > 0).all()
    # max diff should be small (this is a calibrated source)
    assert rt["diff"].abs().max() < 0.1

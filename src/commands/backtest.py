"""`pl-winner backtest` — walk-forward title + match log-loss backtest."""
from __future__ import annotations

import math

import pandas as pd


def main(args) -> int:
    from ..backtest import match_logloss_backtest, title_backtest

    pd.set_option("display.width", 140)

    print(f"Title prediction backtest @ {args.cutoff}/380 played:")
    title = title_backtest(
        args.seasons,
        history=args.history,
        cutoff_played=args.cutoff,
        half_life_days=args.half_life,
        n_runs=args.runs,
    )
    cols = ["actual_champion", "predicted_champion", "p_predicted", "p_actual",
            "leader_at_cutoff", "correct"]
    print(title[cols].to_string())
    hits = int(title["correct"].sum())
    print(f"\n  Hit rate: {hits}/{len(title)}  mean P(actual champion) = {title['p_actual'].mean():.2%}")

    print(f"\nMatch outcome log-loss on the held-out final {380 - args.cutoff} matches per season:")
    ll = match_logloss_backtest(
        args.seasons,
        history=args.history,
        cutoff_played=args.cutoff,
        half_life_days=args.half_life,
    )
    print(ll.to_string())
    uniform = -math.log(1 / 3)
    print(
        f"\n  Mean — Dixon-Coles: {ll['dixon_coles_logloss'].mean():.3f}   "
        f"baseline: {ll['baseline_logloss'].mean():.3f}   "
        f"(lower is better; uniform = {uniform:.3f})"
    )
    return 0

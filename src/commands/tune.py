"""`pl-winner tune` — half-life cross-validation."""
from __future__ import annotations

import pandas as pd


def main(args) -> int:
    from ..tune import best_half_life

    pd.set_option("display.width", 140)
    print(f"Sweeping half-life {args.candidates} on seasons {args.seasons} ...")
    best, sweep = best_half_life(
        args.seasons, candidates=args.candidates, history=args.history, cutoff_played=args.cutoff,
    )
    print(sweep.to_string(index=False))
    print(f"\nBest half-life by log-loss: {best:.0f} days")
    return 0

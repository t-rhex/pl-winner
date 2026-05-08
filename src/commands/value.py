"""`pl-winner value` — calibration, ROI vs Bet365, break-even odds."""
from __future__ import annotations

import pandas as pd


def main(args) -> int:
    from ..calibration import collect_predictions, compare_bookmakers, compare_with_ci, evaluate
    from ..value import find_edges_in_history, remaining_fixtures_table, summarize_edges

    pd.set_option("display.width", 160)
    pd.set_option("display.max_rows", 50)

    print(f"Collecting predictions across {args.seasons} (fitting at game {args.cutoff}/380) ...")
    preds = collect_predictions(
        args.seasons, history=args.history, cutoff_played=args.cutoff,
        half_life_days=args.half_life, bookie=args.bookie,
    )
    print(f"  {len(preds)} probability triples\n")

    cal = evaluate(preds, n_bins=args.bins)
    print("=== Probabilistic accuracy (lower is better) ===")
    print(f"  Brier   model {cal.brier_model:.4f}   Bet365 {cal.brier_book:.4f}   "
          f"diff {cal.brier_book - cal.brier_model:+.4f}")
    print(f"  LogLoss model {cal.logloss_model:.4f}   Bet365 {cal.logloss_book:.4f}   "
          f"diff {cal.logloss_book - cal.logloss_model:+.4f}\n")

    print("=== Bootstrap 95% CIs (1000 resamples) ===")
    ci = compare_with_ci(preds, n_boot=1000)
    print(ci.to_string(index=False))
    print()

    print(f"=== Reliability ({args.bins} bins) ===")
    print(cal.reliability.to_string(index=False))
    print()

    print(f"=== ROI of betting model edges ≥ {args.edge}pp at {args.bookie} ===")
    edges = find_edges_in_history(
        args.seasons, history=args.history, cutoff_played=args.cutoff,
        half_life_days=args.half_life, bookie=args.bookie, edge_pp_threshold=args.edge,
    )
    summary = summarize_edges(edges)
    if summary["n_bets"] == 0:
        print("  No bets met the threshold.")
    else:
        print(f"  {summary['n_bets']} bets   PnL £{summary['total_pnl']:+.2f}   "
              f"ROI {summary['roi_pct']:+.2f}%   hit rate {summary['hit_rate']:.1%}")
    print()

    print("=== Multi-bookmaker comparison ===")
    comp = compare_bookmakers(args.seasons, history=args.history, cutoff_played=args.cutoff,
                              half_life_days=args.half_life)
    print(comp.round(4).to_string(index=False))
    print()

    print("=== Break-even odds for remaining 2025-26 fixtures ===")
    rem = remaining_fixtures_table()
    if rem.empty:
        print("  No remaining fixtures.")
        return 0
    rem_fmt = rem.copy()
    for c in ["P(H)", "P(D)", "P(A)"]:
        rem_fmt[c] = rem_fmt[c].apply(lambda x: f"{x:.0%}")
    for c in ["BE_H", "BE_D", "BE_A"]:
        rem_fmt[c] = rem_fmt[c].apply(lambda x: f"{x:.2f}")
    print(rem_fmt.to_string(index=False))
    return 0

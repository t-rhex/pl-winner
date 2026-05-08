"""`pl-winner fixtures` — every remaining fixture with H/D/A probabilities."""
from __future__ import annotations

import pandas as pd


def main(args) -> int:
    from ..data import load_season, load_seasons, split_current_season
    from ..model import fit_dixon_coles

    pd.set_option("display.width", 140)
    pd.set_option("display.max_rows", 100)

    cur = load_season(args.current_year, league=args.league)
    if cur.empty:
        print("No matches available for this season.")
        return 2
    state = split_current_season(cur)
    if state.remaining.empty:
        print("No remaining fixtures — the season is complete.")
        return 0

    train_years = list(range(args.current_year - args.history, args.current_year + 1))
    history = load_seasons(train_years, league=args.league)
    history = history[history.HomeTeam.isin(state.teams) & history.AwayTeam.isin(state.teams)]
    model = fit_dixon_coles(history, half_life_days=180, ref_date=cur.Date.max(), teams=state.teams)

    rows = []
    for h, a in zip(state.remaining.HomeTeam, state.remaining.AwayTeam):
        lam, mu = model.expected_goals(h, a)
        p = model.outcome_probs(h, a)
        rows.append(
            {
                "Home": h, "Away": a,
                "xG_H": round(lam, 2), "xG_A": round(mu, 2),
                "P(H)": f"{p['H']:.0%}", "P(D)": f"{p['D']:.0%}", "P(A)": f"{p['A']:.0%}",
            }
        )
    print(f"{len(rows)} remaining fixtures:\n")
    print(pd.DataFrame(rows).to_string(index=False))
    return 0

"""`pl-winner league` — simulate an FPL mini-league."""
from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)


def main(args) -> int:
    from ..data import load_season, load_seasons, split_current_season
    from ..fpl import fetch_fpl
    from ..league import fetch_league, simulate_league
    from ..model import fit_dixon_coles

    pd.set_option("display.width", 140)
    if not (args.entry_ids or args.league_id):
        log.error("Provide either --league-id or --entry-ids.")
        return 2

    if args.league_id:
        league = fetch_league(args.league_id)
        entries = [e["entry"] for e in league["standings"]["results"][: args.top]]
        label = league["league"]["name"]
    else:
        entries = list(args.entry_ids)
        label = "custom selection"

    print(f"League: {label} — simulating {len(entries)} managers")
    cur = load_season(2025)
    state = split_current_season(cur)
    hist = load_seasons(range(2021, 2026))
    hist = hist[hist.HomeTeam.isin(state.teams) & hist.AwayTeam.isin(state.teams)]
    model = fit_dixon_coles(hist, half_life_days=180, ref_date=cur.Date.max(), teams=state.teams)
    fpl = fetch_fpl()
    table = simulate_league(fpl, model, entries, n_runs=args.runs)
    print(table.to_string(index=False))
    return 0

"""`pl-winner predict` — title race + simulation projections."""
from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)


def main(args) -> int:
    from ..data import LEAGUES, load_season, load_seasons, split_current_season
    from ..model import fit_dixon_coles
    from ..simulate import simulate_season, standings_with_simulation

    pd.set_option("display.width", 140)
    pd.set_option("display.max_rows", 30)

    log.info(f"Loading {LEAGUES[args.league]} {args.current_year}-{(args.current_year + 1) % 100:02d}")
    current = load_season(args.current_year, force=args.refresh, league=args.league)
    if current.empty:
        log.error(f"No data available for {args.current_year} — has the season started?")
        return 2
    state = split_current_season(current)
    log.info(f"{len(state.played)} played, {len(state.remaining)} remaining, {len(state.teams)} teams")

    train_years = list(range(args.current_year - args.history, args.current_year + 1))
    history = load_seasons(train_years, force=args.refresh, league=args.league)
    history = history[history.HomeTeam.isin(state.teams) & history.AwayTeam.isin(state.teams)]
    if history.empty:
        log.error("No training history available — try --history 0 or check the league code.")
        return 2

    log.info("Fitting Dixon-Coles ...")
    model = fit_dixon_coles(
        history,
        half_life_days=args.half_life,
        ref_date=current.Date.max(),
        teams=state.teams,
    )
    log.info(f"Simulating {args.runs} seasons ...")
    result = simulate_season(state, model, n_runs=args.runs, seed=args.seed)
    final = standings_with_simulation(state, result).head(20)
    print(final.to_string())
    print(f"\nPredicted champion: {result.title.idxmax()}  (P = {result.title.max():.1%})")
    return 0

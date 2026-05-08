"""`pl-winner track` — record / score / report / backfill predictions."""
from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)


def _state_and_model(year: int, history: int):
    from ..data import load_season, load_seasons, split_current_season
    from ..model import fit_dixon_coles
    cur = load_season(year)
    state = split_current_season(cur)
    hist = load_seasons(range(year - history, year + 1))
    hist = hist[hist.HomeTeam.isin(state.teams) & hist.AwayTeam.isin(state.teams)]
    model = fit_dixon_coles(hist, half_life_days=180, ref_date=cur.Date.max(), teams=state.teams)
    return cur, state, model


def main(args) -> int:
    from ..data import season_label
    from ..tracker import (
        Tracker,
        predictions_for_remaining_fixtures,
        results_from_played,
    )

    pd.set_option("display.width", 140)
    op = args.track_op
    tracker = Tracker()

    if op == "record":
        cur, state, model = _state_and_model(args.year, args.history)
        preds = predictions_for_remaining_fixtures(state, model)
        n = tracker.record_predictions(preds, season=season_label(args.year), gameweek=args.gameweek)
        print(f"Recorded {n} predictions for {season_label(args.year)} (GW={args.gameweek}).")
        if args.also_results:
            n2 = tracker.record_results(results_from_played(state.played), season=season_label(args.year))
            print(f"Recorded {n2} match results.")
        return 0

    if op == "score":
        cur, state, _ = _state_and_model(args.year, args.history)
        n = tracker.record_results(results_from_played(state.played), season=season_label(args.year))
        print(f"Refreshed {n} match results in the tracker DB.")
        return 0

    if op == "report":
        rep = tracker.report()
        if rep.get("n", 0) == 0:
            print("No scored predictions yet. Run `record` first, then `score`.")
            return 0
        print(f"Scored predictions: {rep['n']}")
        print(f"  Brier:    {rep['brier']:.4f}")
        print(f"  LogLoss:  {rep['logloss']:.4f}")
        print(f"  Hit rate: {rep['hit_rate']:.1%}")
        if rep.get("by_gw"):
            print("\nBy gameweek:")
            print(pd.DataFrame(rep["by_gw"]).to_string(index=False))
        return 0

    if op == "backfill":
        from ..calibration import collect_predictions
        from ..data import load_season_full

        preds = collect_predictions(args.seasons, history=args.history, cutoff_played=args.cutoff)
        if preds.empty:
            print("No predictions produced.")
            return 1

        pivoted = (
            preds.pivot_table(index=["season", "match"], columns="side", values="model_p")
            .reset_index()
        )
        pivoted[["home", "away"]] = pivoted["match"].str.split(" v ", expand=True)
        pivoted = pivoted.rename(columns={"H": "p_h", "D": "p_d", "A": "p_a"})

        full_actuals = []
        for season_lbl in pivoted["season"].unique():
            year = int(season_lbl[:4])
            full = load_season_full(year)[["HomeTeam", "AwayTeam", "FTR", "FTHG", "FTAG", "Date"]].rename(
                columns={"HomeTeam": "home", "AwayTeam": "away", "FTR": "ftr",
                         "FTHG": "fthg", "FTAG": "ftag", "Date": "played_at"},
            )
            full["season"] = season_lbl
            full_actuals.append(full)
        full_actuals = pd.concat(full_actuals, ignore_index=True)

        n_p = 0
        for season_lbl, group in pivoted.groupby("season"):
            n_p += tracker.record_predictions(
                group[["home", "away", "p_h", "p_d", "p_a"]],
                season=str(season_lbl), gameweek=None, model_label="dixon-coles-backfill",
            )
        n_r = 0
        for season_lbl, group in full_actuals.groupby("season"):
            n_r += tracker.record_results(group, season=str(season_lbl))
        print(f"Backfilled {n_p} predictions and {n_r} results across {args.seasons}.")
        return 0

    log.error(f"Unknown track operation: {op}")
    return 1

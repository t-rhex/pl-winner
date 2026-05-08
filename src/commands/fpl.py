"""`pl-winner fpl` — top picks, captains, ILP squad, differentials, chips."""
from __future__ import annotations

import pandas as pd


def _fmt(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in ("price", "proj_pts", "proj_per_million", "team_xg", "team_xga",
              "exp_clean_sheets", "proj_gw", "match_xg", "match_xga"):
        if c in out:
            out[c] = pd.to_numeric(out[c], errors="coerce").round(2)
    return out


def main(args) -> int:
    from ..chips import chip_advice
    from ..data import load_season, load_seasons, split_current_season
    from ..fpl import (
        captain_picks,
        differential_picks,
        fetch_fpl,
        project_player_points,
        top_picks,
    )
    from ..fpl_optimizer import optimize_squad
    from ..model import fit_dixon_coles

    pd.set_option("display.width", 160)
    pd.set_option("display.max_rows", 50)

    print("Fetching live FPL data ...")
    fpl = fetch_fpl(force=args.refresh)
    print(f"  next gameweek: GW{fpl.next_gw}, {len(fpl.players)} players, {len(fpl.fixtures)} upcoming fixtures")

    cur = load_season(2025)
    state = split_current_season(cur)
    history = load_seasons(range(2021, 2026))
    history = history[history.HomeTeam.isin(state.teams) & history.AwayTeam.isin(state.teams)]
    model = fit_dixon_coles(history, half_life_days=180, ref_date=cur.Date.max(), teams=state.teams)

    print(f"\nProjecting points for the next {args.gameweeks} gameweeks ...\n")
    proj = project_player_points(fpl, model, gameweeks=args.gameweeks)

    cols = ["web_name", "team_name", "pos", "price", "n_fix", "form_f",
            "team_xg", "team_xga", "exp_clean_sheets", "proj_pts", "proj_per_million"]
    picks = top_picks(proj, by="proj_pts", n=8)
    for pos, df in picks.items():
        print(f"=== Top {pos} ===")
        print(_fmt(df[cols]).to_string(index=False))
        print()

    print("=== Best value (proj pts per £m) ===")
    value = proj[proj["available"]].sort_values("proj_per_million", ascending=False).head(15)
    print(_fmt(value[cols]).to_string(index=False))
    print()

    print("=== Captain candidates by gameweek ===")
    cap = captain_picks(fpl, model, n_per_gw=5)
    print(_fmt(cap).to_string(index=False))
    print()

    print("=== Differentials (ownership ≤ 5%) ===")
    diffs = differential_picks(proj, max_ownership_pct=5.0, n=12)
    cols_d = ["web_name", "team_name", "pos", "price", "selected_pct", "n_fix", "proj_pts"]
    print(_fmt(diffs[cols_d]).to_string(index=False))
    print()

    print(f"=== ILP-optimal 15-man squad (£{args.budget:.0f}m, max 3 per club) ===")
    opt = optimize_squad(proj, budget=args.budget)
    print(f"  cost £{opt.cost:.1f}m   squad pts {opt.proj_pts_squad:.1f}   "
          f"XI pts {opt.proj_pts_xi:.1f}   captain {opt.captain}   vice {opt.vice_captain}")
    print("\n  Starting XI:")
    print(_fmt(opt.starting_xi[["web_name", "team_name", "pos", "price", "n_fix", "proj_pts"]]).to_string(index=False))
    print("\n  Bench:")
    print(_fmt(opt.bench[["web_name", "team_name", "pos", "price", "n_fix", "proj_pts"]]).to_string(index=False))

    print("\n=== Chip strategy ===")
    ca = chip_advice(fpl, model, proj)
    print("  " + ca.summary.replace("\n", "\n  "))
    return 0

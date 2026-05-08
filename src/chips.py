"""FPL chip strategy advisor.

Scores each remaining gameweek for the value of playing each chip:
- Triple Captain: 3x captain instead of 2x → bonus = best_player_proj_gw
- Bench Boost: bench points all count → bonus = sum of bench projections that GW
- Free Hit: temporary squad replacement (limit assumed unused) → flag if
  upcoming GW has unusually weak fixtures for our base squad
- Wildcard: full re-pick at no cost — best when our base squad is far from
  optimal for the run-in (gap between current proj and optimal proj)
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .fpl import FPLData
from .fpl_optimizer import optimize_squad
from .model import DixonColesModel


@dataclass(frozen=True)
class ChipAdvice:
    triple_captain: pd.DataFrame
    bench_boost: pd.DataFrame
    summary: str


def _gw_player_pts(fpl: FPLData, model: DixonColesModel, gw: int) -> pd.DataFrame:
    """Single-GW expected points for every available player from the fixture data."""
    import numpy as np

    from .fpl import (
        APPEARANCE_60,
        ASSIST_PTS,
        CLEANSHEET_PTS,
        CONCEDE_2_PTS,
        GOAL_PTS,
    )

    players = fpl.players.copy()
    appearances = (players["minutes"].astype(float) / 90.0).clip(lower=0.5)
    team_goals = players.groupby("team_fd")["goals_scored"].transform("sum")
    games_played_team = (players["minutes"] / 90.0).groupby(players["team_fd"]).transform("sum") / 11.0
    games_played_team = games_played_team.clip(lower=1.0)
    on_pitch_share = (appearances / games_played_team).clip(0.05, 1.0)
    goal_share = (
        players["goals_scored"].astype(float) / team_goals.clip(lower=1.0) / on_pitch_share
    ).fillna(0.0).clip(0, 1.0)
    assist_share = (
        players["assists"].astype(float) / team_goals.clip(lower=1.0) / on_pitch_share
    ).fillna(0.0).clip(0, 1.0)

    gw_fix = fpl.fixtures[fpl.fixtures.event == gw]
    team_xg, team_xga = {}, {}
    for f in gw_fix.itertuples(index=False):
        lam, mu = model.expected_goals(f.home_fd, f.away_fd)
        team_xg[f.home_fd] = lam
        team_xga[f.home_fd] = mu
        team_xg[f.away_fd] = mu
        team_xga[f.away_fd] = lam

    out = players.copy()
    out["match_xg"] = out["team_fd"].map(team_xg)
    out["match_xga"] = out["team_fd"].map(team_xga)
    out["plays_gw"] = out["match_xg"].notna()
    out["match_p_cs"] = (-out["match_xga"]).where(out["plays_gw"]).apply(lambda x: 0 if pd.isna(x) else float(np.exp(x)))

    pts_g = goal_share * out["match_xg"].fillna(0) * out["element_type"].map(GOAL_PTS).fillna(0)
    pts_a = assist_share * out["match_xg"].fillna(0) * ASSIST_PTS
    pts_cs = out["match_p_cs"] * out["element_type"].map(CLEANSHEET_PTS).fillna(0)
    pts_concede = out["match_xga"].fillna(0) / 2.0 * out["element_type"].map(CONCEDE_2_PTS).fillna(0)
    pts_appear = APPEARANCE_60 * out["plays_gw"].astype(int)
    out["proj_gw"] = pts_g + pts_a + pts_cs + pts_concede + pts_appear
    out.loc[~out["plays_gw"], "proj_gw"] = 0.0
    return out[["id", "web_name", "team_name", "pos", "price", "match_xg", "match_xga",
                "plays_gw", "proj_gw", "status"]]


def chip_advice(
    fpl: FPLData, model: DixonColesModel, projections: pd.DataFrame
) -> ChipAdvice:
    """Score chip plays for each remaining gameweek."""
    end_event = fpl.next_gw + 2
    tc_rows = []
    bb_rows = []

    # build the optimal 15 from current projections (proxy for the actual squad)
    opt = optimize_squad(projections)
    bench_ids = set(opt.bench["id"].astype(int).tolist())

    for gw in range(fpl.next_gw, end_event + 1):
        gw_pts = _gw_player_pts(fpl, model, gw)
        # Triple captain: top expected scorer this GW
        cands = gw_pts[gw_pts["plays_gw"]].sort_values("proj_gw", ascending=False).head(5).copy()
        cands["GW"] = gw
        tc_rows.append(cands[["GW", "web_name", "team_name", "pos", "price", "proj_gw"]])

        # Bench boost: sum of projected pts from our optimal bench this GW
        bench_proj = gw_pts[gw_pts["id"].isin(bench_ids)]["proj_gw"].sum()
        bb_rows.append(
            {
                "GW": gw,
                "bench_pts": round(float(bench_proj), 2),
                "bench_players": ", ".join(opt.bench["web_name"].tolist()),
            }
        )

    tc = pd.concat(tc_rows, ignore_index=True)
    bb = pd.DataFrame(bb_rows)
    best_tc = tc.sort_values("proj_gw", ascending=False).iloc[0]
    best_bb = bb.sort_values("bench_pts", ascending=False).iloc[0]
    summary = (
        f"Best Triple Captain: GW{int(best_tc['GW'])} → {best_tc['web_name']} "
        f"({best_tc['team_name']}, +{best_tc['proj_gw']:.1f} pts beyond regular captain).\n"
        f"Best Bench Boost: GW{int(best_bb['GW'])} → bench projects {best_bb['bench_pts']:.1f} pts."
    )
    return ChipAdvice(triple_captain=tc, bench_boost=bb, summary=summary)

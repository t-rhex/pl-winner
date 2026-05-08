"""Fantasy Premier League recommender.

Pulls live data from the public FPL API, then ranks players by projected points
across the remaining gameweeks. Fixture difficulty comes from our Dixon-Coles
model so a Man City forward facing weak defenses is upweighted vs the same
forward facing Liverpool away.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .http_utils import FetchError, cached_fetch_json, fetch_json
from .model import DixonColesModel
from .paths import fpl_cache_dir

log = logging.getLogger(__name__)

# How long to trust the bootstrap cache before re-fetching (FPL prices update overnight)
BOOTSTRAP_TTL_SECONDS = 6 * 3600  # 6 hours
PLAYER_HISTORY_TTL_SECONDS = 24 * 3600

FPL_BOOTSTRAP = "https://fantasy.premierleague.com/api/bootstrap-static/"
FPL_FIXTURES = "https://fantasy.premierleague.com/api/fixtures/?future=1"
FPL_ELEMENT_SUMMARY = "https://fantasy.premierleague.com/api/element-summary/{player_id}/"

# Resolve at attribute-access time so tests / containers can override via env var.
CACHE = fpl_cache_dir()

# FPL team name -> football-data.co.uk team name
FPL_TO_FD = {
    "Man Utd": "Man United",
    "Spurs": "Tottenham",
}

POSITION_NAME = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}

# FPL scoring (simplified, used to project points from xG / clean-sheet probs)
GOAL_PTS = {1: 6, 2: 6, 3: 5, 4: 4}  # goal scored
ASSIST_PTS = 3
CLEANSHEET_PTS = {1: 4, 2: 4, 3: 1, 4: 0}
CONCEDE_2_PTS = {1: -1, 2: -1, 3: 0, 4: 0}  # per 2 goals conceded (GK/DEF only)
APPEARANCE_60 = 2  # 60+ mins = 2 pts (otherwise 1 pt; we assume regular starters)

# Set-piece bonuses: per match, expected pts gain if first-choice taker
# (rough empirical priors — penalties ~0.3/match converted, FK ~0.05, corners
# converted indirectly via assists are already in xG share, so smaller bonus)
PEN_TAKER_BONUS = 0.7  # per game expected from being on penalties
FK_TAKER_BONUS = 0.25  # per game from direct freekicks
CORNER_TAKER_BONUS = 0.10  # per game from corner involvements


def parse_news_discount(status: str, news: str) -> float:
    """Multiplier (0..1) applied to a player's projection based on FPL news/status.

    `chance_of_playing_next_round` already gives the headline number, but the
    `news` field sometimes carries information that hasn't propagated yet:
    suspensions, doubts, "lack of match fitness", etc.
    """
    s = (news or "").lower()
    if status in ("u", "n"):  # unavailable / not in squad
        return 0.0
    if status == "s":  # suspended
        return 0.0
    # Suspension wording sometimes shows up in news only
    if "suspended" in s or "suspension" in s or "red card" in s:
        return 0.0
    if "transferred" in s or "left the club" in s:
        return 0.0
    if "season" in s and "out" in s:
        return 0.0
    return 1.0


@dataclass(frozen=True)
class FPLData:
    players: pd.DataFrame
    teams: pd.DataFrame
    fixtures: pd.DataFrame
    next_gw: int


def _fetch_json(url: str) -> dict | list:
    """Backwards-compat shim — prefer http_utils.fetch_json directly."""
    return fetch_json(url)


def fetch_player_history(player_id: int, force: bool = False) -> pd.DataFrame:
    """Per-gameweek points history for one player. Cached on disk with a 24h TTL."""
    path = CACHE / f"player_{player_id}.json"
    try:
        data = cached_fetch_json(
            FPL_ELEMENT_SUMMARY.format(player_id=player_id),
            cache_path=path,
            force=force,
            ttl_seconds=PLAYER_HISTORY_TTL_SECONDS,
        )
    except FetchError as e:
        log.warning(f"Could not fetch player {player_id} history: {e}")
        return pd.DataFrame(columns=["round", "total_points", "minutes", "goals_scored", "assists"])
    history = pd.DataFrame(data.get("history", []))
    if history.empty:
        return history
    keep = [c for c in ("round", "total_points", "minutes", "goals_scored", "assists",
                        "clean_sheets", "bonus", "value", "selected") if c in history.columns]
    return history[keep].copy()


def sparkline(values: list[int] | list[float], width: int = 20) -> str:
    """Unicode block sparkline for a sequence of numbers."""
    if not values:
        return ""
    blocks = "▁▂▃▄▅▆▇█"
    lo, hi = min(values), max(values)
    span = hi - lo if hi > lo else 1.0
    chars = []
    for v in values[-width:]:
        idx = int((v - lo) / span * (len(blocks) - 1))
        chars.append(blocks[max(0, min(len(blocks) - 1, idx))])
    return "".join(chars)


def fetch_fpl(force: bool = False) -> FPLData:
    boot_path = CACHE / "bootstrap.json"
    fix_path = CACHE / "fixtures.json"
    boot = cached_fetch_json(FPL_BOOTSTRAP, boot_path, force=force, ttl_seconds=BOOTSTRAP_TTL_SECONDS)
    fix_raw = cached_fetch_json(FPL_FIXTURES, fix_path, force=force, ttl_seconds=BOOTSTRAP_TTL_SECONDS)

    teams = pd.DataFrame(boot["teams"])[["id", "name", "short_name"]]
    teams["fd_name"] = teams["name"].map(lambda n: FPL_TO_FD.get(n, n))

    elements = pd.DataFrame(boot["elements"])
    elements["pos"] = elements["element_type"].map(POSITION_NAME)
    elements["price"] = elements["now_cost"] / 10.0
    elements["form_f"] = pd.to_numeric(elements["form"], errors="coerce").fillna(0.0)
    elements["ppg_f"] = pd.to_numeric(elements["points_per_game"], errors="coerce").fillna(0.0)
    elements["selected_pct"] = pd.to_numeric(elements["selected_by_percent"], errors="coerce").fillna(0.0)
    elements["ep_next_f"] = pd.to_numeric(elements["ep_next"], errors="coerce").fillna(0.0)
    # Set-piece order columns: 1 = first taker, 2 = second, etc. NaN if not on the list.
    elements["pen_order"] = pd.to_numeric(elements["penalties_order"], errors="coerce")
    elements["fk_order"] = pd.to_numeric(elements["direct_freekicks_order"], errors="coerce")
    elements["corner_order"] = pd.to_numeric(elements["corners_and_indirect_freekicks_order"], errors="coerce")
    # Continuous availability: 100 = certain to play, 0 = ruled out
    elements["availability_pct"] = pd.to_numeric(
        elements["chance_of_playing_next_round"], errors="coerce"
    ).fillna(100.0) / 100.0
    elements = elements.merge(
        teams[["id", "name", "fd_name"]].rename(columns={"id": "team", "name": "team_name", "fd_name": "team_fd"}),
        on="team",
        how="left",
    )

    fixtures = pd.DataFrame(fix_raw)
    if not fixtures.empty:
        fixtures = fixtures[fixtures["finished"] == False].copy()  # noqa: E712
        fixtures = fixtures.merge(
            teams[["id", "fd_name"]].rename(columns={"id": "team_h", "fd_name": "home_fd"}), on="team_h"
        ).merge(
            teams[["id", "fd_name"]].rename(columns={"id": "team_a", "fd_name": "away_fd"}), on="team_a"
        )

    next_gw = next((e["id"] for e in boot["events"] if e.get("is_next")), None)
    if next_gw is None:
        next_gw = next((e["id"] for e in boot["events"] if e.get("is_current")), 1)
    return FPLData(players=elements, teams=teams, fixtures=fixtures, next_gw=int(next_gw))


def project_player_points(
    fpl: FPLData,
    model: DixonColesModel,
    gameweeks: int = 3,
) -> pd.DataFrame:
    """Estimate expected FPL points per player over the next `gameweeks` GWs."""
    end_event = fpl.next_gw + gameweeks - 1
    upcoming = fpl.fixtures[(fpl.fixtures.event >= fpl.next_gw) & (fpl.fixtures.event <= end_event)].copy()

    rows = []
    cache: dict[tuple[str, bool], dict[str, float]] = {}
    for f in upcoming.itertuples(index=False):
        for is_home in (True, False):
            team_fd = f.home_fd if is_home else f.away_fd
            opp_fd = f.away_fd if is_home else f.home_fd
            key = (team_fd, opp_fd, is_home)
            if key not in cache:
                if is_home:
                    lam, mu = model.expected_goals(team_fd, opp_fd)
                else:
                    lam, mu = model.expected_goals(opp_fd, team_fd)
                    lam, mu = mu, lam  # team's own xG = away expected goals here
                # poisson clean sheet prob = exp(-mu) where mu = goals against
                ga = mu
                gf = lam
                p_cs = float(np.exp(-ga))
                cache[key] = {"gf": gf, "ga": ga, "p_cs": p_cs}
            cdat = cache[key]
            rows.append({"team_fd": team_fd, "event": f.event, **cdat})
    fixt = pd.DataFrame(rows)

    fixt_agg = fixt.groupby("team_fd").agg(
        n_fix=("event", "size"),
        team_xg=("gf", "sum"),
        team_xga=("ga", "sum"),
        exp_clean_sheets=("p_cs", "sum"),
    ).reset_index()

    p = fpl.players.merge(fixt_agg, left_on="team_fd", right_on="team_fd", how="left").fillna(
        {"n_fix": 0, "team_xg": 0, "team_xga": 0, "exp_clean_sheets": 0}
    )

    starts = p["starts"].astype(float).clip(lower=0.0)
    appearances = (p["minutes"].astype(float) / 90.0).clip(lower=0.5)

    # team-level scoring totals (used to derive each player's share)
    team_goals_so_far = p.groupby("team_fd")["goals_scored"].transform("sum")
    games_played_team = (p["minutes"] / 90.0).groupby(p["team_fd"]).transform("sum") / 11.0
    games_played_team = games_played_team.clip(lower=1.0)

    # share of team goals when on the pitch
    on_pitch_share = (appearances / games_played_team).clip(0.05, 1.0)
    player_goal_share = (p["goals_scored"].astype(float) / team_goals_so_far.clip(lower=1.0)) / on_pitch_share
    player_assist_share = (p["assists"].astype(float) / team_goals_so_far.clip(lower=1.0)) / on_pitch_share
    player_goal_share = player_goal_share.fillna(0.0).clip(0, 1.0)
    player_assist_share = player_assist_share.fillna(0.0).clip(0, 1.0)

    pts_goals = player_goal_share * p["team_xg"] * p["pos"].map(GOAL_PTS).fillna(0)
    pts_assists = player_assist_share * p["team_xg"] * ASSIST_PTS
    pts_cs = p["exp_clean_sheets"] * p["pos"].map(CLEANSHEET_PTS).fillna(0)
    pts_concede = p["team_xga"] / 2.0 * p["pos"].map(CONCEDE_2_PTS).fillna(0)
    pts_appear = APPEARANCE_60 * p["n_fix"] * (starts / appearances.replace(0, np.nan)).clip(upper=1.0).fillna(1.0)

    # Set-piece bonuses (only first-choice taker gets the full bonus)
    pen_bonus = (p["pen_order"].eq(1).astype(float) * PEN_TAKER_BONUS) * p["n_fix"]
    fk_bonus = (p["fk_order"].eq(1).astype(float) * FK_TAKER_BONUS) * p["n_fix"]
    corner_bonus = (p["corner_order"].eq(1).astype(float) * CORNER_TAKER_BONUS) * p["n_fix"]

    p["proj_pts_model"] = pts_goals + pts_assists + pts_cs + pts_concede + pts_appear + pen_bonus + fk_bonus + corner_bonus

    # Hybrid blend with FPL's own form-based projection (helps for set-piece takers,
    # penalty earners, defensive contribution etc. our goal-share model misses)
    p["proj_pts_form"] = p["form_f"] * p["n_fix"]
    p["proj_pts"] = 0.6 * p["proj_pts_model"] + 0.4 * p["proj_pts_form"]
    # Continuous availability: discount projection by chance_of_playing_next_round
    p["proj_pts"] = p["proj_pts"] * p["availability_pct"]

    # News-based discount on top of availability_pct (catches suspensions etc. that
    # FPL hasn't reflected in the headline number yet)
    news_mult = p.apply(
        lambda r: parse_news_discount(str(r.get("status", "")), str(r.get("news", ""))),
        axis=1,
    )
    p["news_mult"] = news_mult
    p["proj_pts"] = p["proj_pts"] * news_mult
    p["proj_per_million"] = p["proj_pts"] / p["price"]

    # Filter out clearly unavailable players: status outside {a, d} OR
    # availability_pct == 0 OR news indicates they're out.
    available = p["status"].isin(["a", "d"]) & (p["availability_pct"] > 0) & (news_mult > 0)
    p["available"] = available

    keep = [
        "id",
        "web_name",
        "team_name",
        "pos",
        "price",
        "n_fix",
        "form_f",
        "ppg_f",
        "ep_next_f",
        "selected_pct",
        "minutes",
        "total_points",
        "team_xg",
        "team_xga",
        "exp_clean_sheets",
        "pen_order",
        "fk_order",
        "corner_order",
        "availability_pct",
        "proj_pts",
        "proj_per_million",
        "available",
        "status",
        "news",
    ]
    return p[keep].copy()


def top_picks(
    projections: pd.DataFrame, by: str = "proj_pts", n: int = 10
) -> dict[str, pd.DataFrame]:
    out = {}
    for pos in ("GK", "DEF", "MID", "FWD"):
        out[pos] = (
            projections[projections["pos"].eq(pos) & projections["available"]]
            .sort_values(by, ascending=False)
            .head(n)
            .reset_index(drop=True)
        )
    return out


def captain_picks(fpl: FPLData, model: DixonColesModel, n_per_gw: int = 5) -> pd.DataFrame:
    """For each upcoming GW, the top expected scorers based on that GW's specific fixture."""
    players = fpl.players.copy()
    appearances = (players["minutes"].astype(float) / 90.0).clip(lower=0.5)
    team_goals_so_far = players.groupby("team_fd")["goals_scored"].transform("sum")
    games_played_team = (players["minutes"] / 90.0).groupby(players["team_fd"]).transform("sum") / 11.0
    games_played_team = games_played_team.clip(lower=1.0)
    on_pitch_share = (appearances / games_played_team).clip(0.05, 1.0)
    goal_share = (
        players["goals_scored"].astype(float) / team_goals_so_far.clip(lower=1.0) / on_pitch_share
    ).fillna(0.0).clip(0, 1.0)
    assist_share = (
        players["assists"].astype(float) / team_goals_so_far.clip(lower=1.0) / on_pitch_share
    ).fillna(0.0).clip(0, 1.0)
    players["_goal_share"] = goal_share
    players["_assist_share"] = assist_share

    rows = []
    end_event = fpl.next_gw + 2
    for gw in range(fpl.next_gw, end_event + 1):
        gw_fix = fpl.fixtures[fpl.fixtures.event == gw]
        team_xg, team_xga = {}, {}
        for f in gw_fix.itertuples(index=False):
            lam, mu = model.expected_goals(f.home_fd, f.away_fd)
            team_xg[f.home_fd] = lam
            team_xga[f.home_fd] = mu
            team_xg[f.away_fd] = mu
            team_xga[f.away_fd] = lam
        teams_playing = set(team_xg)
        slate = players[
            players["team_fd"].isin(teams_playing) & players["status"].isin(["a", "d"])
        ].copy()
        slate["match_xg"] = slate["team_fd"].map(team_xg)
        slate["match_xga"] = slate["team_fd"].map(team_xga)
        slate["match_p_cs"] = np.exp(-slate["match_xga"])

        pts_goals = slate["_goal_share"] * slate["match_xg"] * slate["element_type"].map(GOAL_PTS).fillna(0)
        pts_assists = slate["_assist_share"] * slate["match_xg"] * ASSIST_PTS
        pts_cs = slate["match_p_cs"] * slate["element_type"].map(CLEANSHEET_PTS).fillna(0)
        pts_concede = slate["match_xga"] / 2.0 * slate["element_type"].map(CONCEDE_2_PTS).fillna(0)
        pts_appear = APPEARANCE_60
        slate["proj_gw"] = pts_goals + pts_assists + pts_cs + pts_concede + pts_appear

        # blend with FPL's own next-GW expected pts, halving its weight for GW36+
        slate["proj_gw"] = 0.7 * slate["proj_gw"] + 0.3 * slate["form_f"]

        top = slate.sort_values("proj_gw", ascending=False).head(n_per_gw)
        rows.append(
            top.assign(GW=gw, opponent=top.apply(
                lambda r: _opp_label(r["team_fd"], gw_fix), axis=1
            ))[["GW", "web_name", "team_name", "pos", "price", "opponent", "match_xg", "match_xga", "proj_gw"]]
        )
    return pd.concat(rows, ignore_index=True)


def _opp_label(team_fd: str, gw_fix: pd.DataFrame) -> str:
    home = gw_fix[gw_fix.home_fd == team_fd]
    if len(home):
        return f"vs {home.iloc[0].away_fd} (H)"
    away = gw_fix[gw_fix.away_fd == team_fd]
    if len(away):
        return f"@ {away.iloc[0].home_fd}"
    return ""


def differential_picks(
    projections: pd.DataFrame, max_ownership_pct: float = 10.0, n: int = 15
) -> pd.DataFrame:
    """High projected points × low ownership — useful for chasing rank."""
    df = projections[
        projections["available"] & (projections["selected_pct"] <= max_ownership_pct)
    ].copy()
    df["diff_score"] = df["proj_pts"] / (1.0 + df["selected_pct"] / 10.0)
    return (
        df.sort_values("diff_score", ascending=False)
        .head(n)
        .reset_index(drop=True)
    )


def build_squad(
    projections: pd.DataFrame,
    budget: float = 100.0,
    max_per_club: int = 3,
) -> pd.DataFrame:
    """Greedy 15-man squad: 2 GK / 5 DEF / 5 MID / 3 FWD, max 3 per club, under budget."""
    quotas = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
    pool = projections[projections["available"]].copy()
    pool["score"] = pool["proj_per_million"]
    pool = pool.sort_values(["score", "proj_pts"], ascending=False).reset_index(drop=True)

    chosen: list[int] = []
    spent = 0.0
    by_pos = {p: 0 for p in quotas}
    by_team: dict[str, int] = {}
    needed = sum(quotas.values())

    # Pass 1: take cheapest "fillers" so we can afford expensive stars elsewhere.
    # We pick top by proj_per_million while leaving enough budget for the remaining slots
    # (budget guard = avg remaining seats * 4.0 minimum-price assumption).
    for idx, row in pool.iterrows():
        if len(chosen) == needed:
            break
        pos = row["pos"]
        if by_pos[pos] >= quotas[pos]:
            continue
        if by_team.get(row["team_name"], 0) >= max_per_club:
            continue
        seats_left_after = needed - len(chosen) - 1
        floor_for_rest = 4.0 * seats_left_after
        if spent + row["price"] + floor_for_rest > budget:
            continue
        chosen.append(idx)
        spent += row["price"]
        by_pos[pos] += 1
        by_team[row["team_name"]] = by_team.get(row["team_name"], 0) + 1

    # Pass 2: fill remaining slots with cheapest available eligible players
    if len(chosen) < needed:
        cheap = pool.sort_values("price").index.tolist()
        for idx in cheap:
            if len(chosen) == needed:
                break
            if idx in chosen:
                continue
            row = pool.loc[idx]
            pos = row["pos"]
            if by_pos[pos] >= quotas[pos]:
                continue
            if by_team.get(row["team_name"], 0) >= max_per_club:
                continue
            if spent + row["price"] > budget:
                continue
            chosen.append(idx)
            spent += row["price"]
            by_pos[pos] += 1
            by_team[row["team_name"]] = by_team.get(row["team_name"], 0) + 1

    squad = pool.loc[chosen].assign(spent=spent).reset_index(drop=True)
    return squad


def starting_xi(squad: pd.DataFrame) -> pd.DataFrame:
    """Pick best XI from a 15-man squad (1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD)."""
    by_pos = {p: squad[squad.pos == p].sort_values("proj_pts", ascending=False) for p in ["GK", "DEF", "MID", "FWD"]}
    xi = pd.concat(
        [
            by_pos["GK"].head(1),
            by_pos["DEF"].head(3),
            by_pos["MID"].head(3),
            by_pos["FWD"].head(1),
        ]
    )
    remaining = squad.drop(xi.index).sort_values("proj_pts", ascending=False)
    while len(xi) < 11:
        # add highest-projected remaining player respecting position caps
        for _, cand in remaining.iterrows():
            counts = xi["pos"].value_counts()
            max_for = {"GK": 1, "DEF": 5, "MID": 5, "FWD": 3}
            if counts.get(cand["pos"], 0) < max_for[cand["pos"]]:
                xi = pd.concat([xi, cand.to_frame().T])
                remaining = remaining.drop(cand.name)
                break
    bench = squad.drop(xi.index)
    xi = xi.assign(role="XI")
    bench = bench.assign(role="BENCH")
    out = pd.concat([xi, bench]).reset_index(drop=True)
    for col in ("price", "proj_pts", "proj_per_million", "n_fix"):
        if col in out:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out

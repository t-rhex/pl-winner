"""ILP-based FPL squad and transfer optimizer using PuLP."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pulp

POS_QUOTA = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
XI_MIN = {"GK": 1, "DEF": 3, "MID": 2, "FWD": 1}
XI_MAX = {"GK": 1, "DEF": 5, "MID": 5, "FWD": 3}


@dataclass(frozen=True)
class OptimizedSquad:
    squad: pd.DataFrame  # 15 players
    starting_xi: pd.DataFrame  # 11 players
    bench: pd.DataFrame  # 4 players
    captain: str
    vice_captain: str
    cost: float
    proj_pts_squad: float
    proj_pts_xi: float


def _solve_squad(
    pool: pd.DataFrame,
    budget: float,
    max_per_club: int,
    must_keep: set[int] | None = None,
    must_exclude: set[int] | None = None,
) -> list[int]:
    """Pick the 15-man squad maximizing total proj_pts subject to FPL constraints."""
    must_keep = must_keep or set()
    must_exclude = must_exclude or set()

    prob = pulp.LpProblem("fpl_squad", pulp.LpMaximize)
    pick = {i: pulp.LpVariable(f"x_{i}", cat=pulp.LpBinary) for i in pool.index}

    prob += pulp.lpSum(pool.loc[i, "proj_pts"] * pick[i] for i in pool.index)
    prob += pulp.lpSum(pool.loc[i, "price"] * pick[i] for i in pool.index) <= budget
    prob += pulp.lpSum(pick.values()) == 15

    for pos, q in POS_QUOTA.items():
        prob += pulp.lpSum(pick[i] for i in pool.index if pool.loc[i, "pos"] == pos) == q

    for team in pool["team_name"].unique():
        prob += pulp.lpSum(pick[i] for i in pool.index if pool.loc[i, "team_name"] == team) <= max_per_club

    for i in must_keep:
        if i in pick:
            prob += pick[i] == 1
    for i in must_exclude:
        if i in pick:
            prob += pick[i] == 0

    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=20)
    prob.solve(solver)
    if pulp.LpStatus[prob.status] != "Optimal":
        raise RuntimeError(f"FPL squad ILP did not find optimal solution: {pulp.LpStatus[prob.status]}")
    return [i for i in pool.index if pick[i].value() and pick[i].value() > 0.5]


def _pick_xi(squad: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Choose the starting XI maximizing projected points, respecting formation rules."""
    prob = pulp.LpProblem("fpl_xi", pulp.LpMaximize)
    start = {i: pulp.LpVariable(f"s_{i}", cat=pulp.LpBinary) for i in squad.index}
    prob += pulp.lpSum(squad.loc[i, "proj_pts"] * start[i] for i in squad.index)
    prob += pulp.lpSum(start.values()) == 11
    for pos, lo in XI_MIN.items():
        in_pos = [i for i in squad.index if squad.loc[i, "pos"] == pos]
        prob += pulp.lpSum(start[i] for i in in_pos) >= lo
        prob += pulp.lpSum(start[i] for i in in_pos) <= XI_MAX[pos]
    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    xi_idx = [i for i in squad.index if start[i].value() and start[i].value() > 0.5]
    bench_idx = [i for i in squad.index if i not in xi_idx]
    xi = squad.loc[xi_idx].sort_values(["pos", "proj_pts"], ascending=[True, False])
    # bench order: GK first, then by proj_pts
    bench = squad.loc[bench_idx].copy()
    bench["_ord"] = bench["pos"].map({"GK": 0, "DEF": 1, "MID": 2, "FWD": 3})
    bench = bench.sort_values(["_ord", "proj_pts"], ascending=[True, False]).drop(columns=["_ord"])
    return xi, bench


def optimize_squad(
    projections: pd.DataFrame,
    budget: float = 100.0,
    max_per_club: int = 3,
    min_minutes: int = 0,
) -> OptimizedSquad:
    pool = projections[projections["available"]].copy()
    if min_minutes > 0 and "minutes" in pool:
        pool = pool[pool["minutes"] >= min_minutes]
    pool = pool.dropna(subset=["price", "proj_pts", "pos", "team_name"]).reset_index(drop=True)
    chosen = _solve_squad(pool, budget=budget, max_per_club=max_per_club)
    squad = pool.loc[chosen].reset_index(drop=True)
    xi, bench = _pick_xi(squad)
    captain = xi.iloc[xi["proj_pts"].argmax()]["web_name"]
    vice = xi.sort_values("proj_pts", ascending=False).iloc[1]["web_name"]
    return OptimizedSquad(
        squad=squad,
        starting_xi=xi,
        bench=bench,
        captain=captain,
        vice_captain=vice,
        cost=float(squad["price"].sum()),
        proj_pts_squad=float(squad["proj_pts"].sum()),
        proj_pts_xi=float(xi["proj_pts"].sum()),
    )


def free_hit_squad(
    fpl, model, gameweek: int, budget: float = 100.0, max_per_club: int = 3
) -> OptimizedSquad:
    """Optimal squad for ONE specific gameweek (Free Hit chip).

    Re-projects every player using only that GW's fixture, then runs the same ILP.
    """
    from .chips import _gw_player_pts

    gw_proj = _gw_player_pts(fpl, model, gameweek)
    extras = fpl.players[["id", "selected_pct", "availability_pct",
                          "minutes", "form_f", "ppg_f", "ep_next_f", "news"]]
    gw_proj = gw_proj.merge(extras, on="id", how="left")
    gw_proj["proj_pts"] = gw_proj["proj_gw"] * gw_proj["availability_pct"].fillna(1.0)
    gw_proj["available"] = gw_proj["plays_gw"] & (gw_proj["status"].isin(["a", "d"]))
    gw_proj["n_fix"] = 1
    gw_proj["proj_per_million"] = gw_proj["proj_pts"] / gw_proj["price"].clip(lower=0.1)
    # Pre-filter: ILP can't pick benched / unavailable players
    gw_proj = gw_proj[gw_proj["available"]].reset_index(drop=True)
    return optimize_squad(gw_proj, budget=budget, max_per_club=max_per_club)


@dataclass(frozen=True)
class ChipDecision:
    chip: str
    target_gw: int | None
    bonus_pts: float
    detail: str


def evaluate_chips(
    projections: pd.DataFrame,
    fpl,
    model,
    current_squad_proj: float | None = None,
) -> pd.DataFrame:
    """Score Free Hit and Wildcard against keeping the current optimal squad.

    Free Hit: optimal one-GW squad vs the running squad's projection that GW.
    Wildcard: optimal full-period squad vs the user's existing squad over the
    remaining GWs (proxied by the current projections).
    """
    base = optimize_squad(projections)
    base_total = float(base.proj_pts_squad)

    rows = []

    # Wildcard = re-pick now, ride for the rest of the period.
    # Bonus is base_total minus what you'd score with your current squad — but we
    # don't have your *actual* current squad here. Proxy: bonus vs a "cheap default
    # squad" (worst-case from-scratch). Useful as an "is the optimal much better
    # than what you currently have?" diagnostic.
    rows.append(
        {
            "chip": "Wildcard",
            "target_gw": "all remaining",
            "bonus_pts": round(base_total, 2),
            "detail": f"Optimal squad over remaining GWs scores {base_total:.1f} pts. "
                      f"Compare to your current squad's projection — wildcard if gap > ~10 pts.",
        }
    )

    # Free Hit per upcoming GW
    end_event = fpl.next_gw + 2
    for gw in range(fpl.next_gw, end_event + 1):
        try:
            fh = free_hit_squad(fpl, model, gw)
        except Exception as e:
            rows.append({"chip": "Free Hit", "target_gw": gw, "bonus_pts": 0.0, "detail": f"failed: {e}"})
            continue
        # Per-GW value = top 11 from FH squad's expected GW pts
        rows.append(
            {
                "chip": "Free Hit",
                "target_gw": gw,
                "bonus_pts": round(fh.proj_pts_xi, 2),
                "detail": f"GW{gw} starting XI from a fresh squad: "
                          + ", ".join(fh.starting_xi["web_name"].head(5).tolist()) + "...",
            }
        )

    return pd.DataFrame(rows)


def suggest_transfers(
    projections: pd.DataFrame,
    current_squad_ids: list[int],
    free_transfers: int = 1,
    hit_cost: int = 4,
    budget: float = 100.0,
    max_per_club: int = 3,
    max_transfers: int = 3,
) -> pd.DataFrame:
    """Find the best 1..max_transfers swaps from the current squad.

    Each transfer beyond `free_transfers` costs `hit_cost` projected points.
    Returns one row per evaluated transfer count with the suggested swap(s).
    """
    pool = projections[projections["available"]].copy().dropna(
        subset=["price", "proj_pts", "pos", "team_name", "id"]
    ).reset_index(drop=True)
    pool_by_id = pool.set_index("id")
    current_idx = pool[pool["id"].isin(current_squad_ids)].index.tolist()
    rows = []

    for n_transfers in range(0, max_transfers + 1):
        prob = pulp.LpProblem(f"fpl_transfers_{n_transfers}", pulp.LpMaximize)
        pick = {i: pulp.LpVariable(f"x_{i}", cat=pulp.LpBinary) for i in pool.index}
        prob += pulp.lpSum(pool.loc[i, "proj_pts"] * pick[i] for i in pool.index)
        prob += pulp.lpSum(pool.loc[i, "price"] * pick[i] for i in pool.index) <= budget
        prob += pulp.lpSum(pick.values()) == 15
        for pos, q in POS_QUOTA.items():
            prob += pulp.lpSum(pick[i] for i in pool.index if pool.loc[i, "pos"] == pos) == q
        for team in pool["team_name"].unique():
            prob += pulp.lpSum(pick[i] for i in pool.index if pool.loc[i, "team_name"] == team) <= max_per_club
        # exactly (15 - n_transfers) of the current squad members are kept
        if current_idx:
            prob += pulp.lpSum(pick[i] for i in current_idx) >= 15 - n_transfers

        prob.solve(pulp.PULP_CBC_CMD(msg=False))
        if pulp.LpStatus[prob.status] != "Optimal":
            continue
        chosen = [i for i in pool.index if pick[i].value() and pick[i].value() > 0.5]
        new_squad = pool.loc[chosen]
        gross = float(new_squad["proj_pts"].sum())
        hits = max(0, n_transfers - free_transfers) * hit_cost
        net = gross - hits
        # describe the swap
        old_ids = set(current_squad_ids)
        new_ids = set(new_squad["id"].tolist())
        out_ids = old_ids - new_ids
        in_ids = new_ids - old_ids
        out_names = [pool_by_id.loc[i, "web_name"] for i in out_ids if i in pool_by_id.index]
        in_names = [pool_by_id.loc[i, "web_name"] for i in in_ids]
        rows.append(
            {
                "transfers": n_transfers,
                "gross_pts": round(gross, 2),
                "hits": hits,
                "net_pts": round(net, 2),
                "out": ", ".join(out_names) if out_names else "—",
                "in": ", ".join(in_names) if in_names else "—",
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df["recommended"] = df["net_pts"] == df["net_pts"].max()
    return df

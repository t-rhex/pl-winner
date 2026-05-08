"""FPL mini-league simulator.

For a list of FPL manager IDs (entry IDs), pulls each manager's current squad
and current total points, then Monte-Carlo-simulates each manager's score over
the remaining gameweeks using our player-level projections (with their actual
captain choice if available, else the highest-projecting player).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .chips import _gw_player_pts
from .fpl import CACHE, FPLData
from .http_utils import FetchError, cached_fetch_json

log = logging.getLogger(__name__)

FPL_ENTRY = "https://fantasy.premierleague.com/api/entry/{entry_id}/"
FPL_ENTRY_HISTORY = "https://fantasy.premierleague.com/api/entry/{entry_id}/history/"
FPL_ENTRY_PICKS = "https://fantasy.premierleague.com/api/entry/{entry_id}/event/{event}/picks/"
FPL_LEAGUE_CLASSIC = "https://fantasy.premierleague.com/api/leagues-classic/{league_id}/standings/"

# Mid-gameweek squads can change once chips/transfers process; refetch frequently
ENTRY_TTL_SECONDS = 30 * 60
LEAGUE_TTL_SECONDS = 6 * 3600


def fetch_entry(entry_id: int, force: bool = False) -> dict:
    return cached_fetch_json(
        FPL_ENTRY.format(entry_id=entry_id),
        CACHE / f"entry_{entry_id}.json",
        force=force, ttl_seconds=ENTRY_TTL_SECONDS,
    )


def fetch_entry_history(entry_id: int, force: bool = False) -> dict:
    return cached_fetch_json(
        FPL_ENTRY_HISTORY.format(entry_id=entry_id),
        CACHE / f"entry_{entry_id}_history.json",
        force=force, ttl_seconds=ENTRY_TTL_SECONDS,
    )


def fetch_entry_picks(entry_id: int, event: int, force: bool = False) -> dict:
    try:
        return cached_fetch_json(
            FPL_ENTRY_PICKS.format(entry_id=entry_id, event=event),
            CACHE / f"entry_{entry_id}_gw{event}_picks.json",
            force=force, ttl_seconds=ENTRY_TTL_SECONDS,
        )
    except FetchError as e:
        log.warning(f"Could not fetch picks for entry {entry_id} GW{event}: {e}")
        return {"picks": [], "active_chip": None}


def fetch_league(league_id: int, force: bool = False) -> dict:
    return cached_fetch_json(
        FPL_LEAGUE_CLASSIC.format(league_id=league_id),
        CACHE / f"league_{league_id}.json",
        force=force, ttl_seconds=LEAGUE_TTL_SECONDS,
    )


@dataclass
class ManagerState:
    entry_id: int
    name: str
    total_points: int
    squad_ids: list[int]
    bench_ids: list[int]
    captain_id: int | None
    vice_captain_id: int | None


def manager_state(fpl: FPLData, entry_id: int, gw: int | None = None) -> ManagerState:
    entry = fetch_entry(entry_id)
    name = f"{entry.get('player_first_name', '')} {entry.get('player_last_name', '')}".strip()
    total_points = int(entry.get("summary_overall_points", 0))
    if gw is None:
        gw = max(1, fpl.next_gw - 1)  # last completed GW
    picks_data = fetch_entry_picks(entry_id, gw)
    picks = picks_data.get("picks", [])
    if not picks:
        return ManagerState(entry_id, name, total_points, [], [], None, None)
    starters = [p["element"] for p in picks if p.get("position", 16) <= 11]
    bench = [p["element"] for p in picks if p.get("position", 0) > 11]
    cap = next((p["element"] for p in picks if p.get("is_captain")), None)
    vice = next((p["element"] for p in picks if p.get("is_vice_captain")), None)
    return ManagerState(
        entry_id=entry_id,
        name=name or f"Manager {entry_id}",
        total_points=total_points,
        squad_ids=starters,
        bench_ids=bench,
        captain_id=cap,
        vice_captain_id=vice,
    )


def simulate_league(
    fpl: FPLData,
    model,
    entry_ids: list[int],
    n_runs: int = 5000,
    seed: int = 7,
    gameweeks: int | None = None,
) -> pd.DataFrame:
    """Monte Carlo each manager's remaining-GW score and compute finish positions."""
    rng = np.random.default_rng(seed)
    if gameweeks is None:
        # default: every remaining GW (typically 3 or 4)
        gw_min = fpl.next_gw
        gw_max = max(int(e["id"]) for e in [{"id": fpl.next_gw + 2}])
        gw_range = list(range(gw_min, gw_max + 1))
    else:
        gw_range = list(range(fpl.next_gw, fpl.next_gw + gameweeks))

    managers = [manager_state(fpl, eid) for eid in entry_ids]

    # For each upcoming GW, pre-compute every player's expected pts and a sigma
    gw_proj_tables = {}
    for gw in gw_range:
        df = _gw_player_pts(fpl, model, gw).set_index("id")
        # Approximate per-GW std-dev from Poisson goal scoring + appearance variance
        # Crude but adequate: sigma ~ sqrt(proj + 1)
        df["sigma"] = np.sqrt(df["proj_gw"].clip(lower=0.5) + 1.0)
        gw_proj_tables[gw] = df

    # Simulate
    n = len(managers)
    final_pts = np.zeros((n_runs, n), dtype=np.float64)
    starts = np.array([m.total_points for m in managers], dtype=np.float64)
    final_pts += starts[None, :]

    for gw, table in gw_proj_tables.items():
        means = table["proj_gw"].to_dict()
        sigmas = table["sigma"].to_dict()
        for i, m in enumerate(managers):
            # Cap player gets 2x; if not provided, use highest-mean from squad
            cap = m.captain_id
            squad_means = []
            squad_sigmas = []
            for pid in m.squad_ids:
                squad_means.append(means.get(pid, 0.0))
                squad_sigmas.append(sigmas.get(pid, 1.0))
            squad_means = np.asarray(squad_means)
            squad_sigmas = np.asarray(squad_sigmas)
            # captain index: argmax if not specified
            if cap is None and m.squad_ids:
                cap_idx = int(squad_means.argmax())
            else:
                try:
                    cap_idx = m.squad_ids.index(cap) if cap is not None else int(squad_means.argmax())
                except ValueError:
                    cap_idx = int(squad_means.argmax()) if len(squad_means) else 0

            # sample each player normally, captain doubled
            samples = rng.normal(squad_means, squad_sigmas, size=(n_runs, len(squad_means)))
            samples = np.clip(samples, 0, None)
            if len(squad_means):
                samples[:, cap_idx] *= 2
                final_pts[:, i] += samples.sum(axis=1)

    # Compute finish-position distribution
    ranks = (-final_pts).argsort(axis=1).argsort(axis=1) + 1  # 1 = best
    rows = []
    for i, m in enumerate(managers):
        rows.append(
            {
                "entry_id": m.entry_id,
                "name": m.name,
                "current_pts": m.total_points,
                "exp_final": float(final_pts[:, i].mean()),
                "p_first": float((ranks[:, i] == 1).mean()),
                "p_top3": float((ranks[:, i] <= 3).mean()),
                "p_last": float((ranks[:, i] == n).mean()),
                "exp_rank": float(ranks[:, i].mean()),
            }
        )
    return (
        pd.DataFrame(rows)
        .assign(
            exp_final=lambda d: d["exp_final"].round(1),
            p_first=lambda d: d["p_first"].round(3),
            p_top3=lambda d: d["p_top3"].round(3),
            p_last=lambda d: d["p_last"].round(3),
            exp_rank=lambda d: d["exp_rank"].round(2),
        )
        .sort_values("p_first", ascending=False)
        .reset_index(drop=True)
    )

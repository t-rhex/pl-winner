import pandas as pd

from src.fpl_optimizer import POS_QUOTA, optimize_squad


def _toy_pool() -> pd.DataFrame:
    rows = []
    pid = 1
    # build a balanced pool: enough at each position from many clubs
    for pos, qty in [("GK", 6), ("DEF", 12), ("MID", 12), ("FWD", 8)]:
        for i in range(qty):
            rows.append(
                {
                    "id": pid,
                    "web_name": f"{pos}{i}",
                    "team_name": f"Club{i % 8}",
                    "pos": pos,
                    "price": 4.0 + (i % 6),
                    "proj_pts": 5.0 + (i * 0.7) + (10 if pos == "MID" else 0),
                    "available": True,
                    "minutes": 1000,
                    "n_fix": 3,
                    "form_f": 5.0,
                    "selected_pct": 5.0,
                    "team_xg": 4.0,
                    "team_xga": 4.0,
                    "exp_clean_sheets": 0.7,
                    "ppg_f": 4.0,
                    "ep_next_f": 5.0,
                    "total_points": 100,
                    "proj_per_million": 1.0,
                    "status": "a",
                    "news": "",
                }
            )
            pid += 1
    return pd.DataFrame(rows)


def test_optimize_squad_respects_quotas_and_budget():
    pool = _toy_pool()
    opt = optimize_squad(pool, budget=100.0, max_per_club=3)
    counts = opt.squad["pos"].value_counts().to_dict()
    for pos, q in POS_QUOTA.items():
        assert counts.get(pos, 0) == q
    assert opt.cost <= 100.0 + 1e-6
    # max 3 per club
    assert opt.squad["team_name"].value_counts().max() <= 3


def test_optimize_squad_picks_higher_projected_when_cheap():
    pool = _toy_pool()
    opt = optimize_squad(pool, budget=100.0, max_per_club=3)
    # projection of the 15 picks should beat a random 15
    pool_sample = pool.sample(15, random_state=0)
    assert opt.proj_pts_squad > pool_sample["proj_pts"].sum()


def test_optimize_squad_starting_xi_is_eleven():
    pool = _toy_pool()
    opt = optimize_squad(pool, budget=100.0, max_per_club=3)
    assert len(opt.starting_xi) == 11
    assert len(opt.bench) == 4
    # XI must include at least 1 GK
    assert (opt.starting_xi["pos"] == "GK").sum() == 1

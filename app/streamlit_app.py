"""Streamlit web UI mirror of the TUI.

Run with:
    streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# Support both layouts:
#   - Installed (Docker / pip install): import as `pl_winner.*`
#   - Dev checkout without install:    add ../src to sys.path and import as `src.*`
try:
    from pl_winner.tui import load_everything
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from tui import load_everything  # type: ignore[no-redef]


@st.cache_resource(show_spinner="Loading data, fitting Dixon-Coles, simulating 10k seasons...")
def get_data():
    return load_everything(runs=10_000)


def title_race_page(d):
    st.subheader(f"Predicted champion: **{d.sim.title.idxmax()}** (P = {d.sim.title.max():.1%})")
    standings = d.state.standings.set_index("Team").join(d.sim.summary()).reset_index()
    fig = px.bar(
        standings.sort_values("P(Champion)", ascending=True).query("`P(Champion)` > 0"),
        x="P(Champion)", y="Team", orientation="h",
        title="Title probabilities",
    )
    fig.update_layout(height=400)
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(
        standings.assign(
            **{c: standings[c].apply(lambda x: f"{x:.1%}") for c in
               ["P(Champion)", "P(Top 4)", "P(Relegation)"]}
        )[["Team", "P", "W", "D", "L", "GF", "GA", "GD", "Pts",
           "P(Champion)", "P(Top 4)", "P(Relegation)", "ExpPts", "ExpPos"]],
        height=750, use_container_width=True,
    )


def fixtures_page(d):
    st.subheader("All remaining fixtures with model probabilities")
    df = d.fixtures_table.copy()
    st.dataframe(df, height=750, use_container_width=True)


def fpl_page(d):
    st.subheader("FPL projections — next 3 GWs")
    pos = st.selectbox("Position", ["GK", "DEF", "MID", "FWD"], index=2)
    cols = ["web_name", "team_name", "price", "n_fix", "form_f",
            "team_xg", "team_xga", "exp_clean_sheets", "proj_pts", "proj_per_million"]
    df = d.proj[d.proj.pos.eq(pos) & d.proj.available].sort_values("proj_pts", ascending=False).head(20)
    st.dataframe(df[cols].round(2), use_container_width=True, height=500)
    st.caption("Sorted by projected points across remaining gameweeks.")


def captains_page(d):
    st.subheader("Captain candidates by gameweek")
    df = d.captains.copy()
    for c in ("price", "match_xg", "match_xga", "proj_gw"):
        df[c] = pd.to_numeric(df[c], errors="coerce").round(2)
    st.dataframe(df, use_container_width=True, height=600)


def squad_page(d):
    o = d.optimal
    st.subheader(f"ILP-optimal 15 — cost £{o.cost:.1f}m, {o.proj_pts_squad:.1f} squad pts, {o.proj_pts_xi:.1f} XI pts")
    st.markdown(f"**Captain:** {o.captain}   **Vice:** {o.vice_captain}")
    cols = ["web_name", "team_name", "pos", "price", "n_fix", "form_f", "proj_pts"]
    st.markdown("##### Starting XI")
    st.dataframe(o.starting_xi[cols].round(2), use_container_width=True, height=420)
    st.markdown("##### Bench")
    st.dataframe(o.bench[cols].round(2), use_container_width=True, height=200)


def differentials_page(d):
    st.subheader("Differential picks (ownership ≤ 10%)")
    st.dataframe(
        d.differentials[["web_name", "team_name", "pos", "price", "selected_pct", "n_fix", "proj_pts"]].round(2),
        use_container_width=True, height=600,
    )


def chips_page(d):
    ca = d.chips
    st.subheader("Chip strategy")
    st.success(ca.summary)
    st.markdown("##### Triple Captain candidates per GW")
    st.dataframe(ca.triple_captain.round(2), use_container_width=True, height=440)
    st.markdown("##### Bench Boost projection per GW")
    st.dataframe(ca.bench_boost, use_container_width=True)


def value_page(d):
    cal = d.calibration
    es = d.edges_summary
    c1, c2, c3 = st.columns(3)
    c1.metric("Brier (model)", f"{cal.brier_model:.4f}", f"{cal.brier_book - cal.brier_model:+.4f} vs Bet365")
    c2.metric("LogLoss (model)", f"{cal.logloss_model:.4f}", f"{cal.logloss_book - cal.logloss_model:+.4f} vs Bet365")
    c3.metric("ROI of edges (≥5pp)", f"{es.get('roi_pct', 0):+.2f}%", f"{es.get('n_bets', 0)} bets")

    st.markdown("##### Reliability (predicted vs observed frequency)")
    fig = px.scatter(cal.reliability, x="predicted", y="observed", size="n",
                     hover_data=["bin", "n", "diff"], title="Calibration plot")
    fig.add_shape(type="line", x0=0, y0=0, x1=1, y1=1,
                  line=dict(color="gray", width=1, dash="dash"))
    fig.update_layout(height=420, xaxis_range=[0, 1], yaxis_range=[0, 1])
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("##### Break-even odds for remaining fixtures")
    df = d.breakeven.copy()
    for c in ["P(H)", "P(D)", "P(A)"]:
        df[c] = df[c].apply(lambda x: f"{x:.0%}")
    for c in ["BE_H", "BE_D", "BE_A"]:
        df[c] = df[c].round(2)
    st.dataframe(df, use_container_width=True, height=600)


def league_page(d):
    st.subheader("FPL mini-league simulator")
    st.caption("Pulls real squads via the public FPL API and Monte-Carlo-simulates the rest.")
    league_id = st.text_input("League ID (classic)", placeholder="e.g. 314 for the global Overall league")
    entry_ids = st.text_input("...or comma-separated entry IDs", placeholder="3027768, 5798417, ...")
    top = st.number_input("Top N entries (if league ID)", value=10, min_value=2, max_value=50)
    runs = st.number_input("Simulation runs", value=2000, min_value=500, max_value=20000, step=500)
    if st.button("Simulate"):
        try:
            from pl_winner.league import fetch_league, simulate_league
        except ModuleNotFoundError:
            from league import fetch_league, simulate_league  # type: ignore[no-redef]
        if league_id:
            league = fetch_league(int(league_id))
            entries = [e["entry"] for e in league["standings"]["results"][:top]]
            label = league["league"]["name"]
        elif entry_ids:
            entries = [int(x.strip()) for x in entry_ids.split(",") if x.strip()]
            label = "custom selection"
        else:
            st.error("Provide a league ID or entry IDs.")
            return
        with st.spinner(f"Pulling {len(entries)} squads and running {runs} sims..."):
            table = simulate_league(d.fpl, d.model, entries, n_runs=int(runs))
        st.markdown(f"**{label}** — {len(entries)} managers")
        st.dataframe(table, use_container_width=True, height=500)


PAGES = {
    "🏆 Title Race": title_race_page,
    "📅 Fixtures": fixtures_page,
    "🧑 FPL Picks": fpl_page,
    "🎯 Captains": captains_page,
    "👕 Squad": squad_page,
    "💎 Differentials": differentials_page,
    "🃏 Chips": chips_page,
    "💰 Value": value_page,
    "🥇 Mini-league": league_page,
}


def main():
    st.set_page_config(page_title="Premier League 2025-26 Predictor", layout="wide")
    st.title("Premier League 2025-26 Predictor")
    st.caption("Dixon-Coles + Monte Carlo + FPL recommender")
    page = st.sidebar.radio("Section", list(PAGES.keys()))
    data = get_data()
    PAGES[page](data)
    with st.sidebar:
        st.divider()
        st.caption(f"Predicted champion: **{data.sim.title.idxmax()}** ({data.sim.title.max():.0%})")
        st.caption(f"Next FPL deadline: GW{data.fpl.next_gw}")


if __name__ == "__main__":
    main()

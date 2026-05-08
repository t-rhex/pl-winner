"""Textual TUI for the Premier League predictor + FPL recommender."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Static,
    TabbedContent,
    TabPane,
)

from .calibration import CalibrationResult, collect_predictions, evaluate
from .chips import ChipAdvice, chip_advice
from .data import SeasonState, load_season, load_seasons, split_current_season
from .fpl import (
    FPLData,
    captain_picks,
    differential_picks,
    fetch_fpl,
    fetch_player_history,
    project_player_points,
    sparkline,
    top_picks,
)
from .fpl_optimizer import OptimizedSquad, optimize_squad
from .model import DixonColesModel, fit_dixon_coles
from .simulate import SimulationResult, simulate_season
from .value import find_edges_in_history, remaining_fixtures_table, summarize_edges


@dataclass
class AppData:
    state: SeasonState
    model: DixonColesModel
    sim: SimulationResult
    fpl: FPLData
    proj: pd.DataFrame
    captains: pd.DataFrame
    fixtures_table: pd.DataFrame
    breakeven: pd.DataFrame
    calibration: CalibrationResult
    edges_summary: dict
    optimal: OptimizedSquad
    differentials: pd.DataFrame
    chips: ChipAdvice


def _build_fixtures_table(state: SeasonState, model: DixonColesModel) -> pd.DataFrame:
    rows = []
    for h, a in zip(state.remaining.HomeTeam, state.remaining.AwayTeam):
        lam, mu = model.expected_goals(h, a)
        p = model.outcome_probs(h, a)
        rows.append(
            {
                "Home": h,
                "Away": a,
                "xG_H": f"{lam:.2f}",
                "xG_A": f"{mu:.2f}",
                "P(H)": f"{p['H']:.0%}",
                "P(D)": f"{p['D']:.0%}",
                "P(A)": f"{p['A']:.0%}",
            }
        )
    return pd.DataFrame(rows)


def load_everything(history: int = 4, runs: int = 10_000, force_fpl: bool = False) -> AppData:
    cur = load_season(2025)
    state = split_current_season(cur)
    train_years = list(range(2025 - history, 2026))
    hist = load_seasons(train_years)
    hist = hist[hist.HomeTeam.isin(state.teams) & hist.AwayTeam.isin(state.teams)]
    model = fit_dixon_coles(hist, half_life_days=180, ref_date=cur.Date.max(), teams=state.teams)
    sim = simulate_season(state, model, n_runs=runs, seed=7, show_progress=False)
    fpl = fetch_fpl(force=force_fpl)
    proj = project_player_points(fpl, model, gameweeks=3)
    cap = captain_picks(fpl, model, n_per_gw=5)
    fixtures = _build_fixtures_table(state, model)
    breakeven = remaining_fixtures_table(model)
    preds = collect_predictions([2021, 2022, 2023, 2024], history=history, cutoff_played=200)
    cal = evaluate(preds, n_bins=10)
    edges = find_edges_in_history([2021, 2022, 2023, 2024], history=history, cutoff_played=200)
    edges_summary = summarize_edges(edges)
    optimal = optimize_squad(proj)
    diffs = differential_picks(proj, max_ownership_pct=10.0, n=15)
    ca = chip_advice(fpl, model, proj)
    return AppData(
        state=state, model=model, sim=sim, fpl=fpl, proj=proj,
        captains=cap, fixtures_table=fixtures,
        breakeven=breakeven, calibration=cal, edges_summary=edges_summary,
        optimal=optimal, differentials=diffs, chips=ca,
    )


def _df_to_table(table: DataTable, df: pd.DataFrame, columns: list[str], style_fn=None) -> None:
    """Populate a DataTable from a DataFrame slice."""
    table.clear(columns=True)
    table.add_columns(*columns)
    for _, row in df.iterrows():
        cells = []
        for c in columns:
            v = row[c]
            text = "" if pd.isna(v) else (f"{v:.2f}" if isinstance(v, float) else str(v))
            if style_fn is not None:
                styled = style_fn(c, v, row)
                if styled is not None:
                    cells.append(styled)
                    continue
            cells.append(text)
        table.add_row(*cells)


def _color_prob(c, v, row):
    """Highlight probability cells: green high, red low."""
    if c not in ("P(H)", "P(D)", "P(A)", "P(Champion)", "P(Top 4)", "P(Relegation)"):
        return None
    try:
        pct = float(str(v).rstrip("%")) / 100.0
    except (ValueError, AttributeError):
        return None
    if pct >= 0.6:
        style = "bold green"
    elif pct >= 0.35:
        style = "yellow"
    elif pct >= 0.10:
        style = "white"
    else:
        style = "dim"
    return Text(f"{pct:.0%}", style=style)


class TitleRaceTab(Container):
    def __init__(self, data: AppData):
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        champ = self.data.sim.title.idxmax()
        p = self.data.sim.title.max()
        summary = (
            f"[b cyan]Predicted champion:[/] [b yellow]{champ}[/]  "
            f"P = [b]{p:.1%}[/]\n"
            f"[dim]Played: {len(self.data.state.played)}/380   "
            f"Remaining: {len(self.data.state.remaining)}   "
            f"Sim runs: {self.data.sim.n_runs:,}   "
            f"Next FPL deadline: GW{self.data.fpl.next_gw}[/]"
        )
        yield Static(summary, classes="summary")
        yield DataTable(id="title_table", zebra_stripes=True, cursor_type="row")

    def on_mount(self) -> None:
        table = self.query_one("#title_table", DataTable)
        df = self.data.state.standings.set_index("Team")
        merged = df.join(self.data.sim.summary()).reset_index()
        merged["P(Champion)"] = merged["P(Champion)"].apply(lambda x: f"{x:.1%}")
        merged["P(Top 4)"] = merged["P(Top 4)"].apply(lambda x: f"{x:.1%}")
        merged["P(Relegation)"] = merged["P(Relegation)"].apply(lambda x: f"{x:.1%}")
        merged["ExpPts"] = merged["ExpPts"].apply(lambda x: f"{x:.1f}")
        merged["ExpPos"] = merged["ExpPos"].apply(lambda x: f"{x:.1f}")
        cols = ["Team", "P", "W", "D", "L", "GF", "GA", "GD", "Pts",
                "P(Champion)", "P(Top 4)", "P(Relegation)", "ExpPts", "ExpPos"]
        _df_to_table(table, merged, cols, style_fn=_color_prob)


class FixturesTab(Container):
    def __init__(self, data: AppData):
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        yield Static(
            f"[b]All {len(self.data.fixtures_table)} remaining fixtures[/]  "
            f"[dim]xG = expected goals; P(H/D/A) = home win / draw / away win[/]",
            classes="summary",
        )
        yield DataTable(id="fixtures_dt", zebra_stripes=True)

    def on_mount(self) -> None:
        t = self.query_one("#fixtures_dt", DataTable)
        cols = ["Home", "Away", "xG_H", "xG_A", "P(H)", "P(D)", "P(A)"]
        _df_to_table(t, self.data.fixtures_table, cols, style_fn=_color_prob)


class FplPicksTab(Container):
    def __init__(self, data: AppData):
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        yield Static(
            "[b]Top FPL picks by projected points (next 3 GWs)[/]  "
            "[dim]xG/xGA aggregated across remaining fixtures, "
            "blended with FPL form (60/40)[/]",
            classes="summary",
        )
        with Vertical():
            yield Static("[b cyan]Goalkeepers[/]")
            yield DataTable(id="gk_dt", zebra_stripes=True)
            yield Static("[b cyan]Defenders[/]")
            yield DataTable(id="def_dt", zebra_stripes=True)
            yield Static("[b cyan]Midfielders[/]")
            yield DataTable(id="mid_dt", zebra_stripes=True)
            yield Static("[b cyan]Forwards[/]")
            yield DataTable(id="fwd_dt", zebra_stripes=True)

    def on_mount(self) -> None:
        picks = top_picks(self.data.proj, by="proj_pts", n=8)
        cols = ["web_name", "team_name", "price", "n_fix", "form_f",
                "team_xg", "team_xga", "exp_clean_sheets", "proj_pts", "proj_per_million"]
        for pos, table_id in [("GK", "gk_dt"), ("DEF", "def_dt"), ("MID", "mid_dt"), ("FWD", "fwd_dt")]:
            t = self.query_one(f"#{table_id}", DataTable)
            df = picks[pos][cols].copy()
            for c in ("price", "form_f", "team_xg", "team_xga", "exp_clean_sheets",
                      "proj_pts", "proj_per_million"):
                df[c] = df[c].astype(float).round(2)
            _df_to_table(t, df, cols)


class CaptainsTab(Container):
    def __init__(self, data: AppData):
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        yield Static(
            "[b]Captain candidates by gameweek[/]  "
            "[dim]Highest single-match expected points based on opponent strength + player form[/]",
            classes="summary",
        )
        yield DataTable(id="captains_dt", zebra_stripes=True)

    def on_mount(self) -> None:
        t = self.query_one("#captains_dt", DataTable)
        df = self.data.captains.copy()
        for c in ("price", "match_xg", "match_xga", "proj_gw"):
            df[c] = pd.to_numeric(df[c], errors="coerce").round(2)
        cols = ["GW", "web_name", "team_name", "pos", "price", "opponent",
                "match_xg", "match_xga", "proj_gw"]
        _df_to_table(t, df, cols)


class SquadTab(Container):
    def __init__(self, data: AppData):
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        opt = self.data.optimal
        yield Static(
            f"[b]ILP-optimal 15-man squad[/]  "
            f"cost: [yellow]£{opt.cost:.1f}m[/] / £100m   "
            f"squad pts: [green]{opt.proj_pts_squad:.1f}[/]   "
            f"starting XI: [green]{opt.proj_pts_xi:.1f}[/]   "
            f"captain: [b yellow]{opt.captain}[/]   vice: [yellow]{opt.vice_captain}[/]\n"
            f"[dim]Maximizes total projected points subject to £100m budget, "
            f"2/5/5/3 position quotas, max 3 per club. PuLP CBC solver.[/]",
            classes="summary",
        )
        yield Static("[b cyan]Starting XI[/]")
        yield DataTable(id="xi_dt", zebra_stripes=True)
        yield Static("[b cyan]Bench[/]")
        yield DataTable(id="bench_dt", zebra_stripes=True)

    def on_mount(self) -> None:
        cols = ["web_name", "team_name", "pos", "price", "n_fix", "form_f", "proj_pts"]
        for table_id, df_src in [
            ("xi_dt", self.data.optimal.starting_xi),
            ("bench_dt", self.data.optimal.bench),
        ]:
            t = self.query_one(f"#{table_id}", DataTable)
            df = df_src.copy()
            for c in ("price", "proj_pts", "n_fix", "form_f"):
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df["price"] = df["price"].round(1)
            df["proj_pts"] = df["proj_pts"].round(2)
            df["form_f"] = df["form_f"].round(1)
            _df_to_table(t, df, cols)


class DifferentialsTab(Container):
    def __init__(self, data: AppData):
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        yield Static(
            "[b]Differential picks[/] (ownership ≤ 10%)\n"
            "[dim]High projected points × low template overlap. "
            "Useful for chasing rank or playing differentials in your final mini-league push.[/]",
            classes="summary",
        )
        yield DataTable(id="diff_dt", zebra_stripes=True)

    def on_mount(self) -> None:
        t = self.query_one("#diff_dt", DataTable)
        df = self.data.differentials.copy()
        for c in ("price", "proj_pts", "selected_pct", "n_fix"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["price"] = df["price"].round(1)
        df["proj_pts"] = df["proj_pts"].round(2)
        df["selected_pct"] = df["selected_pct"].round(1).astype(str) + "%"
        cols = ["web_name", "team_name", "pos", "price", "selected_pct", "n_fix", "proj_pts"]
        _df_to_table(t, df, cols)


class ChipsTab(Container):
    def __init__(self, data: AppData):
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        ca = self.data.chips
        yield Static(
            f"[b]Chip strategy[/]\n[green]{ca.summary}[/]\n"
            f"[dim]Triple Captain bonus = player's GW projection (since TC adds +1× on top of 2×). "
            f"Bench Boost = projected points from your bench that GW.[/]",
            classes="summary",
        )
        yield Static("[b cyan]Triple Captain candidates per GW[/]")
        yield DataTable(id="tc_dt", zebra_stripes=True)
        yield Static("[b cyan]Bench Boost projection per GW[/]")
        yield DataTable(id="bb_dt", zebra_stripes=True)

    def on_mount(self) -> None:
        tc = self.query_one("#tc_dt", DataTable)
        df = self.data.chips.triple_captain.copy()
        df["price"] = pd.to_numeric(df["price"], errors="coerce").round(1)
        df["proj_gw"] = pd.to_numeric(df["proj_gw"], errors="coerce").round(2)
        _df_to_table(tc, df, ["GW", "web_name", "team_name", "pos", "price", "proj_gw"])

        bb = self.query_one("#bb_dt", DataTable)
        _df_to_table(bb, self.data.chips.bench_boost, ["GW", "bench_pts", "bench_players"])


class PlayerDetailScreen(ModalScreen):
    """Modal popup with details for a single player."""

    BINDINGS = [Binding("escape", "app.pop_screen", "Close")]

    DEFAULT_CSS = """
    PlayerDetailScreen { align: center middle; }
    #detail_box { width: 90; height: 28; border: heavy $accent; padding: 1 2;
                  background: $surface; }
    #detail_title { text-align: center; }
    """

    def __init__(self, player_row: pd.Series, fixtures: pd.DataFrame):
        super().__init__()
        self.player = player_row
        self.fixtures = fixtures

    def compose(self) -> ComposeResult:
        with Container(id="detail_box"):
            yield Static(self._title(), id="detail_title")
            yield Static(self._body())
            yield Static("[dim]Press Esc to close[/]")

    def _title(self) -> str:
        p = self.player
        return f"[b yellow]{p.get('web_name','?')}[/] — {p.get('team_name','?')} ({p.get('pos','?')})"

    def _body(self) -> str:
        p = self.player
        price = float(p.get("price", 0))
        form = float(p.get("form_f", 0))
        ppg = float(p.get("ppg_f", 0))
        proj = float(p.get("proj_pts", 0))
        n_fix = int(p.get("n_fix", 0))
        own = float(p.get("selected_pct", 0))
        status = str(p.get("status", "?"))
        news = str(p.get("news", "")).strip() or "—"
        avail = float(p.get("availability_pct", 1.0))
        pen = "✓" if p.get("pen_order") == 1 else "·"
        fk = "✓" if p.get("fk_order") == 1 else "·"
        ck = "✓" if p.get("corner_order") == 1 else "·"

        # Real per-GW points history from FPL element-summary endpoint
        try:
            history = fetch_player_history(int(p["id"]))
        except Exception:
            history = None
        if history is not None and not history.empty:
            recent = history.sort_values("round").tail(20)
            pts_spark = sparkline(recent["total_points"].tolist(), width=20)
            mins_spark = sparkline(recent["minutes"].tolist(), width=20)
            recent_avg = recent["total_points"].tail(5).mean()
            history_line = (
                f"recent pts: [yellow]{pts_spark}[/]  (last 5 avg: [b]{recent_avg:.1f}[/])\n"
                f"minutes:    [cyan]{mins_spark}[/]"
            )
        else:
            history_line = "no per-GW history available"

        strength = self._spark(p.get("team_xg", 0), p.get("team_xga", 0))
        return (
            f"price [b]£{price:.1f}m[/]   form [b]{form:.1f}[/]   "
            f"ppg [b]{ppg:.1f}[/]   ownership [b]{own:.1f}%[/]   "
            f"availability [b]{avail:.0%}[/]\n"
            f"set-pieces — pen {pen}  fk {fk}  ck {ck}\n"
            f"projected pts (next {n_fix} GWs): [b green]{proj:.2f}[/]\n"
            f"team xG total: [b]{float(p.get('team_xg', 0)):.2f}[/]   "
            f"team xGA total: [b]{float(p.get('team_xga', 0)):.2f}[/]   "
            f"clean sheets: [b]{float(p.get('exp_clean_sheets', 0)):.2f}[/]\n"
            f"strength: {strength}\n"
            f"\n{history_line}\n"
            f"\nstatus: {status}   news: {news}"
        )

    def _spark(self, xg: float, xga: float) -> str:
        bar_len = 40
        try:
            xg = float(xg or 0)
            xga = float(xga or 0)
        except (TypeError, ValueError):
            return ""
        total = xg + xga or 1.0
        n_xg = int(round(bar_len * xg / total))
        n_xga = bar_len - n_xg
        return f"[green]{'█' * n_xg}[/][red]{'█' * n_xga}[/]  attack vs concede"


class ValueTab(Container):
    def __init__(self, data: AppData):
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        cal = self.data.calibration
        es = self.data.edges_summary
        brier_better = "green" if cal.brier_model < cal.brier_book else "red"
        ll_better = "green" if cal.logloss_model < cal.logloss_book else "red"
        roi_color = "green" if es.get("roi_pct", 0) > 0 else "red"
        roi = es.get("roi_pct", 0.0)
        n_bets = es.get("n_bets", 0)
        summary = (
            f"[b]Backtest calibration[/]   ({cal.n_predictions} probability triples across "
            f"{[2021, 2022, 2023, 2024]} from match 200/380)\n"
            f"  Brier   model [b {brier_better}]{cal.brier_model:.4f}[/]   "
            f"Bet365 [b]{cal.brier_book:.4f}[/]   diff {cal.brier_book - cal.brier_model:+.4f}\n"
            f"  LogLoss model [b {ll_better}]{cal.logloss_model:.4f}[/]   "
            f"Bet365 [b]{cal.logloss_book:.4f}[/]   diff {cal.logloss_book - cal.logloss_model:+.4f}\n"
            f"\n[b]ROI of betting model edges ≥ 5pp at Bet365 closing[/]   "
            f"{n_bets} bets   PnL £{es.get('total_pnl', 0):+.2f}   "
            f"ROI [b {roi_color}]{roi:+.2f}%[/]   hit rate {es.get('hit_rate', 0):.1%}\n"
            f"\n[b]Reliability table[/]  predicted = avg model probability in bin; "
            f"observed = actual frequency. Closer means better calibrated."
        )
        yield Static(summary, classes="summary")
        yield DataTable(id="reliability_dt", zebra_stripes=True)
        yield Static(
            "\n[b]Break-even odds for remaining 2025-26 fixtures[/]   "
            "[dim](minimum decimal odds at which the model says a side has +EV — "
            "compare to live bookmaker prices)[/]",
            classes="summary",
        )
        yield DataTable(id="breakeven_dt", zebra_stripes=True)

    def on_mount(self) -> None:
        rel = self.query_one("#reliability_dt", DataTable)
        df = self.data.calibration.reliability.copy()
        df["predicted"] = df["predicted"].apply(lambda x: f"{x:.3f}")
        df["observed"] = df["observed"].apply(lambda x: f"{x:.3f}")
        df["diff"] = df["diff"].apply(lambda x: f"{x:+.3f}")
        _df_to_table(rel, df, ["bin", "n", "predicted", "observed", "diff"])

        be = self.query_one("#breakeven_dt", DataTable)
        df2 = self.data.breakeven.copy()
        for c in ["P(H)", "P(D)", "P(A)"]:
            df2[c] = df2[c].apply(lambda x: f"{x:.0%}")
        for c in ["BE_H", "BE_D", "BE_A"]:
            df2[c] = df2[c].apply(lambda x: f"{x:.2f}")
        _df_to_table(
            be, df2,
            ["Home", "Away", "P(H)", "P(D)", "P(A)", "BE_H", "BE_D", "BE_A"],
            style_fn=_color_prob,
        )


class PLWinnerApp(App):
    CSS = """
    Screen { background: $surface; }
    .summary { padding: 1 2; height: auto; background: $boost; color: $text; }
    DataTable { height: 1fr; }
    TabbedContent { height: 1fr; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("1", "show_tab('title')", "Title"),
        Binding("2", "show_tab('fixtures')", "Fixtures"),
        Binding("3", "show_tab('fpl')", "FPL"),
        Binding("4", "show_tab('captains')", "Captains"),
        Binding("5", "show_tab('squad')", "Squad"),
        Binding("6", "show_tab('diffs')", "Diffs"),
        Binding("7", "show_tab('chips')", "Chips"),
        Binding("8", "show_tab('value')", "Value"),
    ]

    TITLE = "Premier League 2025-26 Predictor"
    SUB_TITLE = "Dixon-Coles + Monte Carlo + FPL"

    def __init__(self, data: AppData):
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="title"):
            with TabPane("Title Race", id="title"):
                yield TitleRaceTab(self.data)
            with TabPane("Fixtures", id="fixtures"):
                yield FixturesTab(self.data)
            with TabPane("FPL Picks", id="fpl"):
                yield FplPicksTab(self.data)
            with TabPane("Captains", id="captains"):
                yield CaptainsTab(self.data)
            with TabPane("Squad", id="squad"):
                yield SquadTab(self.data)
            with TabPane("Diffs", id="diffs"):
                yield DifferentialsTab(self.data)
            with TabPane("Chips", id="chips"):
                yield ChipsTab(self.data)
            with TabPane("Value", id="value"):
                yield ValueTab(self.data)
        yield Footer()

    def action_show_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab

    def action_refresh(self) -> None:
        """Reload FPL + projections without quitting (model fit is reused)."""
        self.notify("Refreshing FPL data and projections...", timeout=2)
        try:
            new = load_everything(force_fpl=True)
        except Exception as e:  # noqa: BLE001
            self.notify(f"Refresh failed: {e}", severity="error", timeout=5)
            return
        self.data = new
        # The cleanest way to re-render with new data: pop & repush tabs.
        tc = self.query_one(TabbedContent)
        active = tc.active
        # Replace the App in place is intrusive; simpler is to update each tab's data
        # and call the on_mount methods again. We do that by querying tab containers.
        for tab_cls, tab_id in [
            (TitleRaceTab, "title"),
            (FixturesTab, "fixtures"),
            (FplPicksTab, "fpl"),
            (CaptainsTab, "captains"),
            (SquadTab, "squad"),
            (DifferentialsTab, "diffs"),
            (ChipsTab, "chips"),
            (ValueTab, "value"),
        ]:
            try:
                container = self.query_one(f"TabPane#{tab_id}", TabPane)
                # remove children, mount fresh tab content
                for child in list(container.children):
                    child.remove()
                container.mount(tab_cls(self.data))
            except Exception:
                continue
        tc.active = active
        self.notify(f"Refreshed (next GW: {self.data.fpl.next_gw})", timeout=3)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """When a row in any FPL-related table is selected, open player detail."""
        table = event.data_table
        if table.id not in ("gk_dt", "def_dt", "mid_dt", "fwd_dt", "diff_dt", "xi_dt", "bench_dt"):
            return
        # the first cell is web_name; look up that row in projections
        try:
            row = table.get_row(event.row_key)
        except Exception:
            return
        web_name = str(row[0])
        match = self.data.proj[self.data.proj["web_name"] == web_name]
        if match.empty:
            return
        self.push_screen(PlayerDetailScreen(match.iloc[0], self.data.fixtures_table))


def run_tui() -> None:
    print("Loading data and running simulations (this takes ~10s)...")
    data = load_everything()
    app = PLWinnerApp(data)
    app.run()

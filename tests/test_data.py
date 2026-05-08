import pandas as pd

from src.data import (
    SeasonState,
    compute_standings,
    season_code,
    season_label,
    split_current_season,
)


def test_season_code():
    assert season_code(2024) == "2425"
    assert season_code(2025) == "2526"
    assert season_code(1999) == "9900"


def test_season_label():
    assert season_label(2024) == "2024-25"
    assert season_label(2025) == "2025-26"
    assert season_label(1999) == "1999-00"


def _toy_season() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Date": pd.Timestamp("2025-08-15"), "HomeTeam": "A", "AwayTeam": "B", "FTHG": 2, "FTAG": 1, "FTR": "H", "Season": "2025-26"},
            {"Date": pd.Timestamp("2025-08-22"), "HomeTeam": "B", "AwayTeam": "C", "FTHG": 0, "FTAG": 0, "FTR": "D", "Season": "2025-26"},
            {"Date": pd.Timestamp("2025-08-29"), "HomeTeam": "C", "AwayTeam": "A", "FTHG": 3, "FTAG": 2, "FTR": "H", "Season": "2025-26"},
        ]
    )


def test_compute_standings_three_teams():
    df = _toy_season()
    teams = ("A", "B", "C")
    table = compute_standings(df, teams)
    by = {row.Team: row for row in table.itertuples()}
    assert by["A"].Pts == 3 and by["A"].W == 1 and by["A"].L == 1
    assert by["B"].Pts == 1 and by["B"].D == 1 and by["B"].L == 1
    assert by["C"].Pts == 4 and by["C"].W == 1 and by["C"].D == 1
    # GD sanity
    assert by["A"].GF == 4 and by["A"].GA == 4 and by["A"].GD == 0


def test_split_current_season_remaining_pairs():
    df = _toy_season()
    state = split_current_season(df)
    assert isinstance(state, SeasonState)
    assert set(state.teams) == {"A", "B", "C"}
    # 3 teams round-robin = 6 ordered fixtures, 3 played, so 3 remain
    assert len(state.played) == 3
    assert len(state.remaining) == 3
    played = set(zip(df.HomeTeam, df.AwayTeam))
    rem = set(zip(state.remaining.HomeTeam, state.remaining.AwayTeam))
    assert played.isdisjoint(rem)


def test_standings_sorted_by_points_then_gd_then_gf():
    df = pd.DataFrame(
        [
            {"Date": pd.Timestamp("2025-08-15"), "HomeTeam": "X", "AwayTeam": "Y", "FTHG": 1, "FTAG": 0, "FTR": "H", "Season": "2025-26"},
            {"Date": pd.Timestamp("2025-08-22"), "HomeTeam": "Y", "AwayTeam": "X", "FTHG": 1, "FTAG": 0, "FTR": "H", "Season": "2025-26"},
            {"Date": pd.Timestamp("2025-08-29"), "HomeTeam": "X", "AwayTeam": "Z", "FTHG": 5, "FTAG": 0, "FTR": "H", "Season": "2025-26"},
            {"Date": pd.Timestamp("2025-09-05"), "HomeTeam": "Y", "AwayTeam": "Z", "FTHG": 1, "FTAG": 0, "FTR": "H", "Season": "2025-26"},
        ]
    )
    teams = ("X", "Y", "Z")
    t = compute_standings(df, teams)
    # both X and Y have 6 pts but X has GD +5 vs Y +1
    assert list(t["Team"][:2]) == ["X", "Y"]
    assert t.iloc[2]["Team"] == "Z"

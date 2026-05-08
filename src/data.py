"""Load Premier League match data from football-data.co.uk."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import permutations
from pathlib import Path

import pandas as pd

from .paths import data_dir

DATA_URL = "https://www.football-data.co.uk/mmz4281/{code}/{league}.csv"
COLUMNS = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"]


def _cache_dir() -> Path:
    return data_dir()


# Backwards-compat alias used elsewhere in the codebase
CACHE_DIR = _cache_dir()

# League codes used by football-data.co.uk
LEAGUES = {
    "E0": "English Premier League",
    "E1": "English Championship",
    "SP1": "Spanish La Liga",
    "D1": "German Bundesliga",
    "I1": "Italian Serie A",
    "F1": "French Ligue 1",
    "N1": "Dutch Eredivisie",
    "P1": "Portuguese Primeira Liga",
}


def season_code(start_year: int) -> str:
    """2024 -> '2425' (the 2024-25 season)."""
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def season_label(start_year: int) -> str:
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def _cache_path(start_year: int, league: str = "E0") -> Path:
    d = _cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{league}_{season_code(start_year)}.csv"


def download_season(start_year: int, force: bool = False, league: str = "E0") -> Path:
    """Fetch a season CSV from football-data.co.uk with retries; cache to disk.

    Returns an empty file path (and writes a header-only CSV) when the season
    has not been published yet (HTTP 404), so callers can keep going.
    """
    from .http_utils import FetchError, fetch_text

    path = _cache_path(start_year, league=league)
    if path.exists() and not force:
        return path
    url = DATA_URL.format(code=season_code(start_year), league=league)
    try:
        body = fetch_text(url, encoding="utf-8-sig")
    except FetchError as e:
        # 404 typically means the season isn't published yet
        if "404" in str(e):
            _cache_dir().mkdir(parents=True, exist_ok=True)
            path.write_text(",".join(COLUMNS) + "\n")
            return path
        raise
    _cache_dir().mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def load_season(start_year: int, force: bool = False, league: str = "E0") -> pd.DataFrame:
    """Load a single season's match results. Returns an empty frame (with the
    expected columns) if the season hasn't been published yet."""
    path = download_season(start_year, force=force, league=league)
    try:
        df = pd.read_csv(path, usecols=lambda c: c in COLUMNS)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=[*COLUMNS, "Season"])
    if df.empty:
        return df.assign(Season=season_label(start_year))
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["Date", "HomeTeam", "AwayTeam"]).reset_index(drop=True)
    df["Season"] = season_label(start_year)
    return df


def load_seasons(start_years: Iterable[int], force: bool = False, league: str = "E0") -> pd.DataFrame:
    """Concatenate multiple seasons. Skips seasons not yet published."""
    frames = []
    for y in start_years:
        f = load_season(y, force=force, league=league)
        if not f.empty:
            frames.append(f)
    if not frames:
        return pd.DataFrame(columns=[*COLUMNS, "Season"])
    return pd.concat(frames, ignore_index=True)


def load_season_full(start_year: int, force: bool = False, league: str = "E0") -> pd.DataFrame:
    """Load the full season CSV including bookmaker odds columns."""
    path = download_season(start_year, force=force, league=league)
    df = pd.read_csv(path)
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["Date", "HomeTeam", "AwayTeam"]).reset_index(drop=True)
    df["Season"] = season_label(start_year)
    return df


@dataclass(frozen=True)
class SeasonState:
    """Snapshot of an in-progress season: matches played + fixtures still to play."""

    played: pd.DataFrame
    remaining: pd.DataFrame
    teams: tuple[str, ...]

    @property
    def standings(self) -> pd.DataFrame:
        return compute_standings(self.played, self.teams)


def split_current_season(season_df: pd.DataFrame) -> SeasonState:
    """Split a season frame into played matches and the remaining round-robin fixtures."""
    teams = tuple(sorted(set(season_df["HomeTeam"]) | set(season_df["AwayTeam"])))
    played_pairs = {
        (row.HomeTeam, row.AwayTeam) for row in season_df.itertuples(index=False)
    }
    remaining = [
        {"HomeTeam": h, "AwayTeam": a}
        for h, a in permutations(teams, 2)
        if (h, a) not in played_pairs
    ]
    return SeasonState(
        played=season_df.reset_index(drop=True),
        remaining=pd.DataFrame(remaining, columns=["HomeTeam", "AwayTeam"]),
        teams=teams,
    )


def compute_standings(played: pd.DataFrame, teams: tuple[str, ...]) -> pd.DataFrame:
    """Build a points table from played matches."""
    rows = {t: {"P": 0, "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0, "Pts": 0} for t in teams}
    for m in played.itertuples(index=False):
        h, a, hg, ag = m.HomeTeam, m.AwayTeam, int(m.FTHG), int(m.FTAG)
        rows[h]["P"] += 1
        rows[a]["P"] += 1
        rows[h]["GF"] += hg
        rows[h]["GA"] += ag
        rows[a]["GF"] += ag
        rows[a]["GA"] += hg
        if hg > ag:
            rows[h]["W"] += 1
            rows[a]["L"] += 1
            rows[h]["Pts"] += 3
        elif hg < ag:
            rows[a]["W"] += 1
            rows[h]["L"] += 1
            rows[a]["Pts"] += 3
        else:
            rows[h]["D"] += 1
            rows[a]["D"] += 1
            rows[h]["Pts"] += 1
            rows[a]["Pts"] += 1
    table = pd.DataFrame.from_dict(rows, orient="index")
    table.index.name = "Team"
    table["GD"] = table["GF"] - table["GA"]
    table = table.sort_values(["Pts", "GD", "GF"], ascending=False)
    return table.reset_index()

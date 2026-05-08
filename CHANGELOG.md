# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] — 2026-05-08

The "people can actually use it" release.

### Added
- **Packaging** — proper `pyproject.toml`, single `pl-winner` console script
  with subcommands (`predict`, `fpl`, `value`, `tune`, `track`, `league`,
  `fixtures`, `backtest`, `tui`, `web`).
- **Robust HTTP layer** (`pl_winner.http_utils`) — exponential backoff on
  429/5xx, TTL-aware on-disk cache, friendly `FetchError`. All FPL and
  football-data.co.uk fetches go through it.
- **Configurable data dir** — honor `PL_WINNER_DATA_DIR` env var so containers
  and sandboxes can pin caches to a writable mount.
- **Docker** — multi-stage `Dockerfile`, `docker-compose.yml` exposing port
  8501, healthcheck on Streamlit's `/_stcore/health`.
- **CI** — `.github/workflows/ci.yml` runs pytest + ruff on Python 3.10/3.11/3.12
  and a CLI smoke job.
- **Release workflow** — `.github/workflows/release.yml` builds + publishes
  to PyPI via Trusted Publishing on `v*` tag push.
- **FPL features** — set-piece bonuses (penalty / freekick / corner takers),
  continuous availability discount, news-based suspension detection, ILP-based
  squad optimizer (PuLP CBC), Free Hit / Wildcard advisor, mini-league
  simulator, differential picks, chip strategy advisor, predictions tracker
  (SQLite).
- **Modeling** — Elo + Dixon-Coles hybrid (kept for experiments), bootstrap
  CIs on Brier / log-loss, multi-bookmaker comparison, half-life cross-validation.
- **UIs** — 8-tab Textual TUI with player-detail modal & live refresh,
  9-page Streamlit web UI with Plotly charts.
- **Docs** — README rewrite with quickstart, badges, formulas, honest framing.
  CONTRIBUTING.md, MIT LICENSE, SECURITY.md.

### Changed
- Off-season / future-season handling: `load_season(year)` now returns an
  empty DataFrame instead of crashing when the CSV isn't published yet.
- FPL caches now have TTLs (bootstrap 6h, player history 24h, entry picks 30min).

### Honest findings
- **The model doesn't beat Bet365 closing line** (Brier 0.187 vs 0.183);
  the gap is statistically significant by bootstrap CI. Useful as a probability
  estimator and FPL fixture-difficulty signal, not as a money-printer against
  sharp markets.
- **The Elo + Dixon-Coles hybrid does not improve calibration** vs DC alone on
  our 1620-prediction sample. Elo signal is mostly redundant once goal counts
  are modeled.

## [0.1.0] — 2026-05-08

Initial implementation: Dixon-Coles, Monte Carlo simulator, basic FPL projections,
Textual TUI, Streamlit web UI.

[Unreleased]: https://github.com/t-rhex/pl-winner/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/t-rhex/pl-winner/releases/tag/v0.2.0
[0.1.0]: https://github.com/t-rhex/pl-winner/releases/tag/v0.1.0

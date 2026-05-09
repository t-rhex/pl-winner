# pl-winner

[![CI](https://github.com/t-rhex/pl-winner/actions/workflows/ci.yml/badge.svg)](https://github.com/t-rhex/pl-winner/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pl-winner.svg)](https://pypi.org/project/pl-winner/)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> Premier League title-race predictor and Fantasy Premier League recommender.
> Dixon-Coles + Monte Carlo for match outcomes. PuLP ILP for FPL squad selection.
> Terminal UI, web UI, and a single `pl-winner` CLI.

```
$ pl-winner predict --runs 10000
...
Predicted champion: Arsenal  (P = 87.1%)

$ pl-winner fpl
=== ILP-optimal 15-man squad (£100m, max 3 per club) ===
  cost £86.1m   squad pts 209.3   XI pts 163.5   captain Cherki   vice Doku
```

## Quickstart

### 1. Install

```bash
pip install pl-winner            # core CLI + TUI
pip install 'pl-winner[web]'     # + Streamlit web UI
```

…or from source:

```bash
git clone https://github.com/t-rhex/pl-winner && cd pl-winner
python -m venv .venv && source .venv/bin/activate
pip install -e '.[web]'
```

### 2. Run

```bash
pl-winner predict                    # title race + simulation projections
pl-winner fpl                        # top picks, captains, ILP squad, chips
pl-winner tui                        # interactive Textual UI (8 tabs)
pl-winner web                        # Streamlit web UI on :8501
```

### 3. Or run with Docker

```bash
docker compose up
# → http://localhost:8501
```

## What you get

| Command | Output |
|---|---|
| `pl-winner predict` | Title / top-4 / relegation probabilities for every team |
| `pl-winner fixtures` | Every remaining fixture with model H/D/A probs |
| `pl-winner backtest` | Walk-forward title hit-rate + match log-loss vs Bet365 |
| `pl-winner fpl` | Top 8 per position, captains, ILP-optimal 15, differentials, chip advice |
| `pl-winner value` | Brier / log-loss with bootstrap CIs, ROI of edges, break-even odds |
| `pl-winner league --league-id 314` | Mini-league finish-position probabilities |
| `pl-winner track record/score/report` | SQLite log of predictions scored against actuals |
| `pl-winner tune` | Cross-validate the half-life parameter |
| `pl-winner tui` | Interactive 8-tab terminal UI |
| `pl-winner web` | Streamlit web app with the same data + Plotly charts |

```bash
pl-winner --help                     # full subcommand list
pl-winner fpl --help                 # per-subcommand options
```

## How it works

### Match outcomes — Dixon-Coles

Each team has an attack rating $\alpha_i$ and a defense rating $\delta_i$. Expected goals are

$$\lambda_{home} = e^{\alpha_h + \delta_a + h}, \qquad \mu_{away} = e^{\alpha_a + \delta_h}$$

A correlation term $\tau(\cdot, \rho)$ corrects 0-0 / 1-0 / 0-1 / 1-1 dependence that pure independent Poissons miss. Fit by weighted MLE with exponential time decay (default half-life 180 days, cross-validated optimum 270 days).

### Title race — Monte Carlo

For each remaining fixture build the joint score pmf, sample 10k full seasons, count how often each club finishes 1st / top-4 / bottom-3. Vectorized, ~50ms per 1k seasons.

### FPL squads — ILP

Maximize $\sum_i \text{proj}_i \cdot x_i$ subject to:
- £100m budget
- 2 GK / 5 DEF / 5 MID / 3 FWD
- ≤ 3 per club
- All players available (injury / suspension filtered)

Solved with PuLP / CBC. The same ILP in `Free Hit` mode (single-GW) and Wildcard mode (re-pick over remaining GWs) underpins the chip advisor.

### Honest framing

The model is **well-calibrated** (reliability table ticks the diagonal) but **doesn't beat Bet365's closing line** on Brier or log-loss — we verified this with bootstrap CIs and the diff is statistically significant. Useful as a probability estimator and FPL fixture-difficulty signal; *don't* treat the break-even odds as a money printer against sharp markets.

## Configuration

| Env var | Purpose | Default |
|---|---|---|
| `PL_WINNER_DATA_DIR` | Where caches and SQLite live | `<repo>/data` |
| `STREAMLIT_SERVER_PORT` | Web UI port | `8501` |

Caches honor TTLs (FPL bootstrap: 6h; player history: 24h; match CSVs: forever — pass `--refresh`).

## Layout

```
src/                 # pl_winner package
  cli.py             # `pl-winner` entry, subparsers
  commands/          # one module per subcommand
  data.py            # match data (E0/E1/SP1/D1/I1/F1/N1/P1)
  model.py           # Dixon-Coles
  simulate.py        # Monte Carlo
  fpl.py             # FPL API client + projections
  fpl_optimizer.py   # PuLP ILP (squad / Free Hit / Wildcard / transfers)
  chips.py           # Triple Captain / Bench Boost
  league.py          # mini-league simulator
  value.py           # implied probabilities, EV, break-even
  calibration.py     # Brier, log-loss, bootstrap CIs, reliability
  tracker.py         # SQLite log
  tune.py            # half-life CV
  elo.py             # Elo + DC hybrid (kept for experiments)
  http_utils.py      # robust HTTP with retries + cache TTL
  paths.py           # data-dir resolution
  tui.py             # Textual TUI
app/
  streamlit_app.py   # web UI
tests/               # pytest suite (~50 tests)
```

## Data sources

- **Match results / odds:** [football-data.co.uk](https://www.football-data.co.uk/) — free CSVs, no API key
- **FPL data:** [official FPL public API](https://fantasy.premierleague.com/api/bootstrap-static/) — no API key
- **Live odds for unplayed matches:** intentionally not scraped (ToS-grey, fragile per-bookmaker)

All requests retry with exponential backoff, cache to disk with TTLs, and degrade gracefully when the API is unavailable or a season hasn't been published.

## Caveats

- Dixon-Coles is symmetric across clubs — doesn't model transfers/managerial changes/fatigue beyond the time-decay weight.
- Promoted clubs have little prior history; ratings stabilize as the season progresses.
- The mini-league simulator uses Normal samples around player projections (σ ≈ √(μ+1)) — adequate for ranking but conservative on tail outcomes.
- 10k Monte Carlo simulations: title-probability SE ≈ 0.5pp at p≈0.5. Bump `--runs` for tighter intervals.
- ILP is "optimal under the projection" — the projection itself has noise, so don't read £0.1m / 0.05-pt differences as meaningful.

## Privacy

`pl-winner` makes **no telemetry calls**. The only network traffic is to
[football-data.co.uk](https://www.football-data.co.uk/) for match CSVs and
[fantasy.premierleague.com/api](https://fantasy.premierleague.com/api/bootstrap-static/)
for FPL data. Caches stay on your machine. Streamlit usage stats are disabled.

See [SECURITY.md](SECURITY.md) for the full posture and how to report
vulnerabilities.

## Releases

Three workflows automate the entire release flow — no API tokens stored
anywhere (uses [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)).

| Workflow | Trigger | What it does |
|---|---|---|
| `ci.yml` | push, PR | tests + ruff + smoke on Python 3.10/3.11/3.12 |
| `testpypi.yml` | push to main | builds a `.devN` wheel and uploads to TestPyPI; catches build regressions before users see them |
| `cut-release.yml` | manual (Actions tab) | bumps version + CHANGELOG, commits, tags, pushes |
| `release.yml` | tag `v*` push | builds, twine-checks, smoke-installs, publishes to PyPI, creates a GitHub Release |

### Cut a new release (one click)

[Run the **Cut release** workflow](https://github.com/t-rhex/pl-winner/actions/workflows/cut-release.yml)
with a bump type (`patch` / `minor` / `major` / explicit `0.4.2`):

```
Actions → Cut release → Run workflow → bump: patch → Run
```

This handles the full chain: version bump → CHANGELOG roll → commit → tag →
which triggers `release.yml` → which publishes to PyPI and drafts a GitHub
release. End-to-end, ~3 minutes.

### Or release locally

```bash
make release-check          # build + twine check locally
python tools/bump_version.py patch
git commit -am "Release v$(grep '^version' pyproject.toml | cut -d'"' -f2)"
git tag "v$(grep '^version' pyproject.toml | cut -d'"' -f2)"
git push origin HEAD --tags
```

See [CHANGELOG.md](CHANGELOG.md) for release notes.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). PRs welcome for modeling, FPL features,
tests. Run `make test lint` before opening a PR.

## License

MIT — see [LICENSE](LICENSE).

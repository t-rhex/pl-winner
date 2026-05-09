# Contributing

Thanks for your interest in `pl-winner`. The project is small and pragmatic — same rules apply to contributions.

## Dev setup

```bash
git clone https://github.com/t-rhex/pl-winner
cd pl-winner
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,web]"
```

This installs the package editable plus development tools (`pytest`, `ruff`) and the optional Streamlit web UI.

## Day-to-day

```bash
pytest                         # ~2s, all tests
ruff check src tests           # lint
ruff format src tests          # auto-format

pl-winner predict              # quick sanity check
pl-winner -v predict           # verbose logging
```

## Project layout

```
src/                # the pl_winner package (mapped via pyproject.toml)
  data.py           # league CSVs, standings, fixture splits
  model.py          # Dixon-Coles fit
  simulate.py       # Monte Carlo
  fpl.py            # FPL API client + projections
  fpl_optimizer.py  # PuLP ILP for squad / chip selection
  chips.py          # chip strategy advisor
  league.py         # mini-league simulator
  value.py          # implied probabilities, EV, break-even
  calibration.py    # Brier, log-loss, bootstrap CIs, reliability
  tracker.py        # SQLite log of predictions vs actuals
  tune.py           # half-life cross-validation
  http_utils.py     # robust HTTP with retries, on-disk cache w/ TTL
  paths.py          # configurable data dir (PL_WINNER_DATA_DIR)
  tui.py            # Textual app
  cli.py            # `pl-winner` entry
  commands/         # one module per subcommand (predict, fpl, value, ...)

app/streamlit_app.py  # Streamlit web UI
scripts/              # legacy compat shims (prefer `pl-winner` cmd)
tests/                # pytest suite
```

## What's worth a PR

- Modeling improvements (alternative score models, multi-league hyperparameters)
- Better FPL projections (lineup leaks, set-piece taker accuracy)
- Mini-league features (chip detection, transfer history)
- Visualization (TUI / Streamlit polish, real charts in Plotly)
- Tests! Coverage is decent but not exhaustive.

## What's probably not

- Live odds scraping for specific bookmakers (fragile, ToS-grey)
- Heavy ML rewrites (transformer for outcome prediction etc.) — Dixon-Coles is hard to beat at this data scale
- Mobile apps (the Streamlit UI works on phones)

## Testing

Tests should be deterministic. Use `seed=` everywhere. Tests should not hit the network — if you need fixture data, add it under `tests/fixtures/` or mock the `http_utils.fetch_json` function.

```bash
pytest tests/test_model.py -v
pytest -k "not network"
```

## Style

- 100-char line limit (configured in `pyproject.toml`)
- Ruff enforced in CI
- Type hints encouraged; not yet strictly enforced
- Prefer small focused modules; ~400 lines is the upper bound

## Releasing

Two paths:

**One-click (preferred):** GitHub Actions → "Cut release" → pick a bump type
(`patch`/`minor`/`major` or an explicit `X.Y.Z`) → Run. The workflow runs full
CI on the bumped version, commits, tags, pushes — which triggers `release.yml`
to publish to PyPI and create a GitHub Release.

**Local:**

```bash
python tools/bump_version.py patch         # bumps pyproject.toml + CHANGELOG + __init__ + USER_AGENT
make release-check                         # ensures wheel + sdist build clean
git commit -am "Release v$(grep '^version' pyproject.toml | cut -d'"' -f2)"
git tag "v$(grep '^version' pyproject.toml | cut -d'"' -f2)"
git push origin HEAD --tags
```

The `release.yml` workflow takes it from there. **Never publish manually with
`twine upload`** — that requires a stored API token and bypasses the OIDC trust
chain.

## Reporting bugs

Open an issue with: Python version, platform, what you ran, what happened, what you expected. A minimal repro is gold.

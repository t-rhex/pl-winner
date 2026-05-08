# Security Policy

## Telemetry

`pl-winner` makes **no telemetry calls**. The only outbound HTTP requests are to:

- `football-data.co.uk` — historical match CSVs
- `fantasy.premierleague.com/api/` — live FPL squad / player / fixture data

All requests are made by you, on your machine, when you run a command. Nothing is sent
to any author / hosting endpoint. Caches live on disk under `$PL_WINNER_DATA_DIR`
(default `<repo>/data`) and never leave your machine.

The Streamlit web UI launches with `--browser.gatherUsageStats false`.

## Reporting a vulnerability

If you find a security issue, please **don't open a public GitHub issue**. Instead:

1. Open a GitHub Security Advisory: https://github.com/t-rhex/pl-winner/security/advisories/new
2. Or email the maintainer directly with subject `[pl-winner security]`

We aim to acknowledge within 72 hours.

## Supported versions

Only the latest minor release receives security fixes. Pin `pl-winner~=0.2` to
get patch releases without breaking changes.

## What's in scope

- Code execution / injection in the package itself
- Cache-poisoning issues in the on-disk cache layer
- Credential leakage (none should exist; we don't accept any)

## What's not in scope

- Vulnerabilities in upstream APIs (football-data.co.uk, FPL) — please report to them
- Bookmaker odds being inaccurate (not a security issue)
- Model predictions being wrong (very much not a security issue)

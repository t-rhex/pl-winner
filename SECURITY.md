# Security Policy

[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/t-rhex/pl-winner/badge)](https://scorecard.dev/viewer/?uri=github.com/t-rhex/pl-winner)

This repository follows industry-standard supply-chain and container security
practices. This document is the canonical reference; the corresponding
configurations live alongside the code they protect.

## Reporting a vulnerability

**Please don't open a public GitHub issue for security reports.** Instead:

1. **Preferred:** open a [GitHub Security Advisory](https://github.com/t-rhex/pl-winner/security/advisories/new)
   — this stays private until coordinated disclosure.
2. Or email the maintainer with subject `[pl-winner security]`.
3. RFC 9116 metadata: [security.txt](.well-known/security.txt)

**Response time targets:**

- Acknowledgement: ≤ 72 hours
- Triage decision: ≤ 7 days
- Patch + coordinated disclosure: ≤ 30 days for HIGH/CRITICAL

We will credit reporters in release notes unless they prefer to remain
anonymous.

## Supported versions

Only the latest minor release receives security fixes. Pin
`pl-winner~=0.2` (or whatever is current) to receive patch releases without
breaking changes.

| Version | Status |
|---|---|
| 0.2.x | ✅ supported |
| < 0.2 | ❌ end-of-life |

## What's in scope

- Code execution / injection in the package itself
- Cache-poisoning issues in the on-disk cache layer
- SSRF or path traversal via FPL / football-data inputs
- Container image vulnerabilities (we publish to PyPI; we don't currently publish container images)
- CI/CD pipeline takeover (e.g. malicious workflow merges)
- Credential leakage from the GitHub repo, releases, or runtime

## What's not in scope

- Vulnerabilities in upstream APIs (football-data.co.uk, FPL) — please report to them
- Bookmaker odds being inaccurate (not a security issue)
- Model predictions being wrong (not a security issue)
- Denial-of-service via abusive query patterns against `/_stcore/health`

## Telemetry

`pl-winner` makes **no telemetry calls**. The only outbound HTTP requests are to:

- `football-data.co.uk` — historical match CSVs
- `fantasy.premierleague.com/api/` — live FPL squad / player / fixture data

Caches stay on your machine (or, in the deployed Streamlit app, on the
attached Fly volume which only the maintainer can access). The Streamlit web
UI launches with `--browser.gatherUsageStats false`.

## Security controls

### Repository

| Control | Implementation |
|---|---|
| Branch protection on `main` | No force-push, no deletion, linear history required, status-check gates |
| Required reviewer / CODEOWNERS | `.github/CODEOWNERS` routes sensitive paths to maintainer |
| Secret scanning + push protection | Enabled at repo settings level |
| Dependabot security updates | Enabled at repo settings level |

### Supply chain (CI/CD)

| Control | Implementation |
|---|---|
| Pinned action SHAs | All `actions/*` references use 40-char commit SHAs (not floating tags) |
| Least-privilege workflow tokens | Workflows declare `permissions: {}` at top, opt-in per job |
| Egress monitoring | `step-security/harden-runner` audits network egress on every job |
| `persist-credentials: false` | Default for `actions/checkout` so post-checkout steps can't leak the token |
| Dependency audit | `pip-audit` on every push + weekly schedule (`security.yml`) |
| Static analysis | `bandit` + GitHub `CodeQL` (`security.yml`, `codeql.yml`) |
| Secret scanning | `gitleaks` on every push + weekly (`security.yml`) |
| SBOM | CycloneDX SBOM generated for every release; uploaded as workflow artifact |
| OpenSSF Scorecard | Weekly run, results published to Security tab + scorecard.dev |
| PyPI publish via Trusted Publishing | OIDC-based; no API tokens stored anywhere |
| Build provenance attestation | `actions/attest-build-provenance` on each release wheel |

### Container

| Control | Implementation |
|---|---|
| Pinned base image digest | `python:3.12-slim@sha256:...` in Dockerfile, kept fresh by Dependabot |
| Multi-stage build | Build tools / wheels stay in builder stage, never reach runtime layer |
| Non-root runtime user | UID/GID 10001 (`app:app`); shell set to `/usr/sbin/nologin` |
| Read-only home | `chmod 0750 /home/app`; cache lives on `/tmp` (tmpfs) and `/data` (volume) |
| Minimal runtime packages | `tini` and `curl` only; `apt` lists removed |
| HEALTHCHECK | Built-in container health check on `/_stcore/health` |
| Streamlit XSRF protection | `STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=true` |
| File watcher off | `STREAMLIT_SERVER_FILE_WATCHER_TYPE=none` (defense-in-depth, no inotify churn) |

### Application

| Control | Implementation |
|---|---|
| Input validation at boundaries | FPL entry/league IDs cast to `int` before use; URL templates not user-controllable |
| No SQL execution from input | SQLite tracker uses parameterized statements only |
| HTTPS-only | `force_https = true` in `fly.toml`; HSTS handled by Fly's edge |
| No persistent user data | Read-only data viz; no auth, no PII |
| HTTP request retries | Bounded (`DEFAULT_RETRIES = 3`) with exponential backoff to avoid amplification |

### Known gaps (honest disclosure)

- **CSP / X-Frame-Options / X-Content-Type-Options** are not set. Streamlit
  uses inline scripts and dynamic WebSocket frames; a strict CSP would break
  the app. Operators who need them should put a CDN / WAF (Cloudflare,
  Caddy) in front of Streamlit.
- **No rate limiting** at the application layer. Fly has DDoS protection at
  the edge; if abuse becomes a problem, add a reverse proxy.
- **No commit signature requirement.** GitHub does verify commits made via
  the web UI; signed-commit enforcement for CLI commits is out of scope for a
  single-developer repo.
- **No SLSA Level 3.** We have Level 1 (build provenance attestations);
  Level 3 requires hermetic builds and isolated provenance generation, which
  isn't enforced for transitive Python deps.

## Incident response

If a security issue is disclosed publicly before a fix is available:

1. Maintainer acknowledges within 24 hours.
2. Affected versions are tagged in [CHANGELOG.md](CHANGELOG.md) under a
   `Security` heading.
3. A patch release is cut via `cut-release.yml`.
4. PyPI versions affected are marked yanked if necessary.
5. A GitHub Security Advisory is published with CVE if assigned.

# Deploying `pl-winner`

The Streamlit web UI runs on [Fly.io](https://fly.io) and is auto-deployed
from `main` whenever CI passes. Custom domain: `pl.andrewadhikari.com`.

This document covers the **one-time setup**. After that, `git push` deploys.

---

## One-time setup

### 0. Prereqs

- A Fly.io account (free signup; credit card required as of 2024).
- `flyctl` CLI installed locally:
  ```bash
  brew install flyctl     # or: curl -L https://fly.io/install.sh | sh
  fly auth login
  ```

### 1. Create the Fly app

From the repo root (where `fly.toml` lives):

```bash
fly apps create pl-winner --org personal      # or your org slug
fly volumes create pl_winner_data \
    --size 1 --region iad --app pl-winner     # 1 GB persistent cache, $0.15/mo
```

> **Region tip:** `iad` is US East. See the full list at
> https://fly.io/docs/reference/regions/ — pick one close to most of your users
> and update `primary_region` in `fly.toml` to match.

### 2. First deploy (manual — you're proving it works)

```bash
fly deploy --remote-only        # builds in Fly's builder, not your laptop
fly status --app pl-winner      # should show 1 machine, "started"
fly logs --app pl-winner        # tail logs to confirm Streamlit started
```

Visit https://pl-winner.fly.dev — should serve the app.

### 3. Custom domain

Point `pl.andrewadhikari.com` at the Fly app:

```bash
# 1. Tell Fly to expect that hostname (provisions a Let's Encrypt cert)
fly certs add pl.andrewadhikari.com --app pl-winner

# 2. Get the DNS records you need to add
fly certs show pl.andrewadhikari.com --app pl-winner
```

`fly certs show` prints the exact DNS records to add. For a subdomain it's
typically:

| Type | Name | Value |
|---|---|---|
| `CNAME` | `pl` | `pl-winner.fly.dev` |
| `TXT` | `_acme-challenge.pl` | `<value from fly certs show>` |

Add those records at your DNS provider (Cloudflare, Route53, etc.). Wait
1–5 minutes for propagation. Verify:

```bash
dig pl.andrewadhikari.com +short
fly certs show pl.andrewadhikari.com --app pl-winner   # status should flip to "Issued"
```

Once the cert issues, https://pl.andrewadhikari.com is live.

### 4. Auto-deploy on every commit

Generate a deploy token (no expiry → paste once and forget):

```bash
fly tokens create deploy --app pl-winner --expiry 8760h    # 1 year
```

Copy the token, then in GitHub:

```
Settings → Secrets and variables → Actions → New repository secret
Name:  FLY_API_TOKEN
Value: <paste the token>
```

Also create the `production` environment so the deploy workflow finds it:

```bash
gh api -X PUT repos/t-rhex/pl-winner/environments/production
```

That's it. Push to `main` → CI runs → deploy.yml fires → live in ~3 minutes.

---

## Day-to-day operations

```bash
fly status     --app pl-winner    # is it up? where? how many machines?
fly logs       --app pl-winner    # tail
fly ssh console --app pl-winner   # exec into the running container
fly scale memory 2048 --app pl-winner   # bump RAM if you see OOMs
fly scale count 0   --app pl-winner    # turn it off (saves the volume cost)
fly scale count 1   --app pl-winner    # turn it back on
fly destroy        pl-winner       # delete it forever (also kills the volume!)
```

The app is configured to **scale to zero** after ~30s of inactivity
(`auto_stop_machines = "stop"` in `fly.toml`). First request after idle pays a
cold-start (~10–15s for Streamlit + initial data load). Subsequent requests
are instant.

If you don't want cold starts, set `min_machines_running = 1` in `fly.toml`
and redeploy. That keeps one VM warm 24/7.

---

## Cost expectations (rough)

For the default config (1 GB RAM, scale-to-zero, 1 GB volume):

| Item | Rate | If used 8 hrs/day | If used always |
|---|---|---|---|
| `shared-cpu-1x@1gb` machine | $0.0000022/s | ~$2/mo | ~$5.7/mo |
| Volume (1 GB) | $0.15/GB-mo | $0.15/mo | $0.15/mo |
| Bandwidth (first 100 GB free) | $0.02/GB extra | ~$0 | ~$0 |
| Custom domain TLS | free (Let's Encrypt) | $0 | $0 |
| **Total** | | **~$2/mo** | **~$6/mo** |

Source: https://fly.io/docs/about/pricing/. Trustworthy as of 2026; check before scaling up.

---

## Rollback

If a bad deploy lands:

```bash
fly releases --app pl-winner       # find the previous good release ID
fly releases revert <id> --app pl-winner
```

Or just push a revert commit to `main` — CI + deploy will roll forward to it.

---

## Why Fly?

- We already have a working Dockerfile.
- Free tier lapsed but pay-as-you-go is genuinely cheap for hobby traffic.
- Custom-domain TLS in one command.
- Multi-region if needed (`fly scale count 2 --region iad,fra`).
- No build pipeline lock-in — image is portable.

Alternatives worth knowing:

- **Streamlit Community Cloud** — zero ops, but locked to `*.streamlit.app` subdomains
  unless you proxy.
- **Hugging Face Spaces** — free, supports custom domains, Streamlit-native.
- **Railway / Render** — slightly pricier, similar ergonomics.
- **VPS + Caddy + Docker** — most control, most ops. ~$5/mo on Hetzner.
